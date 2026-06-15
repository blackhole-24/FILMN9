"""사업보고서 청크에서 RAG + ChatGPT 4o-mini 로 최신 신용등급 추출.

설계서·README §Phase3-11: "Kd = 사업보고서 RAG로 추출한 신용등급 × KOFIA 5년물 수익률"

결정사항:
  - 엄격 매칭: KOFIA 정확 표기
    * 회사채(장기): AAA, AA+, AA0, AA-, A+, A0, A-, BBB+, BBB0, BBB-
    * CP(단기):    A1, A2+, A2, A2-, A3+, A3, A3-, B+, B, B-, C, D
  - 여러 평가사 존재 시: 가장 최근 평가일 기준
  - 우선순위: 회사채(장기) 등급 > CP(단기) 등급
    * 회사채 등급 있으면 그 등급으로 Kd 산정
    * 회사채 등급 없고 CP만 있으면 CP→회사채 표준 매핑 후 Kd 산정
    * 둘 다 없으면 RuntimeError (임의값 절대 금지)
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .compute_equity import _find_chunks_file, _load_chunks
from .kd_loader import VALID_RATINGS
from .cp_yield_data import VALID_CP_RATINGS
from .cp_to_bond_converter import (
    CP_TO_BOND_RATING_MAP as CP_TO_BOND_MAPPING,
    convert_cp_to_bond_5y,
)


_RATING_KEYWORDS = [
    "신용등급", "회사채 등급", "기업어음", "단기신용등급",
    "한국기업평가", "한국신용평가", "NICE신용평가",
    "한기평", "한신평", "나이스신용평가",
    "장기신용등급", "회사채신용등급", "CP",
]


_RAG_SYSTEM_PROMPT = """당신은 한국 사업보고서의 신용등급 정보를 정확히 추출하는 분석가입니다.

규칙 (엄수):
1. 본문에 명시된 신용등급만 추출. 추정 절대 금지.
2. **회사채(장기) 등급**과 **CP(기업어음, 단기) 등급**을 별도로 식별:
   - 회사채 장기 등급 허용 표기: AAA, AA+, AA0, AA-, A+, A0, A-, BBB+, BBB0, BBB-
     * "AA"  → "AA0",  "A" → "A0",  "BBB" → "BBB0"
     * "AA(안정적)" → "AA0"  (괄호 안 전망은 제거)
   - CP(단기) 등급 허용 표기: A1, A2+, A2, A2-, A3+, A3, A3-, B+, B, B-, C, D
     * CP는 보통 "기업어음" 또는 "단기 신용등급" 섹션에 표기됨
3. 여러 평가사 등급이 있으면 **가장 최근 평가일** 기준 1개 선택 (회사채·CP 각각).
   동일 일자에 평가사 간 등급이 다르면 confidence="low".
4. 본문에 해당 등급 명시가 없으면 그 필드는 null.

JSON 스키마 (정확히 이 키 사용):
{
  "bond_rating":        "AA0" | "AA+" | ... | null,
  "bond_rating_agency": "한국기업평가" | "한국신용평가" | "NICE신용평가" | "복수" | null,
  "bond_rating_date":   "2025-06-15" | null,
  "cp_rating":          "A1" | "A2+" | ... | null,
  "cp_rating_agency":   "..." | null,
  "cp_rating_date":     "2025-06-15" | null,
  "source_quote":       "원문 인용 60자 이내 (회사채 우선, 없으면 CP)",
  "confidence":         "high" | "medium" | "low"
}"""


def _filter_rating_chunks(chunks: list[dict], max_chunks: int = 25) -> list[dict]:
    """신용등급 관련 청크 필터링."""
    scored = []
    for c in chunks:
        text = c.get("text", "") or ""
        section = c.get("section_path_str", "") or ""

        score = 0
        if "신용등급" in section or "회사채" in section:
            score += 50
        for kw in _RATING_KEYWORDS:
            if kw in text:
                score += 5
            if kw in section:
                score += 8
        # 표 형태가 등급 정보 핵심
        if score > 0 and c.get("kind") == "table":
            score += 3
        if score > 0:
            scored.append((score, c))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:max_chunks]]


def fetch_credit_rating_via_rag(ticker: str, name: str, year: int,
                                 market: str = "KOSPI",
                                 model: str = "gpt-4o-mini",
                                 verbose: bool = False) -> dict:
    """사업보고서에서 회사채 신용등급 추출.

    Returns:
        {"rating": "AA0", "rating_agency": "한국기업평가",
         "rating_date": "2025-06-15", "source_quote": "...",
         "confidence": "high", "source": "RAG(...) + LLM(gpt-4o-mini)"}

    Raises:
        RuntimeError: 청크 부재 / LLM 응답 부재 / 신용등급 미추출.
    """
    try:
        import openai
    except ImportError as e:
        raise RuntimeError("openai 패키지 필요: pip install openai") from e

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("환경변수 'OPENAI_API_KEY' 가 설정되어 있지 않습니다.")

    # 1) 청크 로드
    chunks_path = _find_chunks_file(ticker, year, market)
    if verbose:
        print(f"   [신용등급 RAG] 청크 파일: {chunks_path.name}")
    all_chunks = _load_chunks(chunks_path)
    if not all_chunks:
        raise RuntimeError(f"청크 파일 비어있음: {chunks_path}")

    # 2) 등급 관련 청크 필터링
    relevant = _filter_rating_chunks(all_chunks)
    if not relevant:
        raise RuntimeError(
            f"{name} 청크 {len(all_chunks)}개 중 신용등급 관련 청크가 없음.\n"
            f"  키워드: {_RATING_KEYWORDS}"
        )
    if verbose:
        print(f"   [신용등급 RAG] 관련 청크 {len(relevant)}개 추출 (전체 {len(all_chunks)})")

    # 3) LLM 컨텍스트
    context_lines = []
    for i, c in enumerate(relevant, 1):
        sec = c.get("section_path_str", "")
        kind = c.get("kind", "")
        context_lines.append(f"[청크 {i}] section={sec} kind={kind}\n{c.get('text','')}")
    context = "\n\n---\n\n".join(context_lines)

    user_prompt = (
        f"회사: {name} ({ticker})\n"
        f"회계연도: FY{year}\n\n"
        f"아래 청크에서 회사채/장기 신용등급을 추출하세요.\n"
        f"여러 평가사 등급이 있으면 가장 최근 평가일 1개를 선택.\n"
        f"===\n{context}\n===\n\n"
        f"JSON으로만 응답:"
    )

    # 4) LLM 호출
    client = openai.OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _RAG_SYSTEM_PROMPT},
            {"role": "user",   "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    raw = response.choices[0].message.content
    if verbose:
        print(f"   [신용등급 RAG] LLM 응답: {raw[:200]}...")

    # 5) 파싱 & 엄격 검증
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"LLM 응답이 JSON 아님: {raw}") from e

    bond_rating = result.get("bond_rating")
    cp_rating   = result.get("cp_rating")

    # 둘 다 비었으면 에러
    if (not bond_rating) and (not cp_rating):
        raise RuntimeError(
            f"[{name}] 신용등급 추출 실패 (회사채·CP 모두 null).\n"
            f"  사업보고서에 신용등급이 명시되어 있는지 확인 필요.\n"
            f"  응답: {raw}"
        )

    # 회사채 등급 우선 — 있으면 그대로 사용
    if bond_rating:
        if bond_rating not in VALID_RATINGS:
            raise RuntimeError(
                f"[{name}] LLM이 반환한 회사채 등급 '{bond_rating}' 이 KOFIA 정확 표기 아님.\n"
                f"  허용 표기: {VALID_RATINGS}\n"
                f"  응답: {raw}"
            )
        return {
            "rating":              bond_rating,
            "rating_type":         "bond",
            "rating_agency":       result.get("bond_rating_agency", ""),
            "rating_date":         result.get("bond_rating_date", ""),
            "bond_rating":         bond_rating,
            "cp_rating":           cp_rating,           # 참고용 (None 일 수도)
            "cp_rating_agency":    result.get("cp_rating_agency", ""),
            "cp_rating_date":      result.get("cp_rating_date", ""),
            "mapping_applied":     None,                # 매핑 안 함
            "source_quote":        result.get("source_quote", ""),
            "confidence":          result.get("confidence", "medium"),
            "source":              f"RAG({chunks_path.name}) + LLM({model})",
        }

    # 회사채 없음 → CP 수익률을 회사채 5년 등가 수익률로 변환
    if cp_rating not in VALID_CP_RATINGS:
        raise RuntimeError(
            f"[{name}] LLM이 반환한 CP 등급 '{cp_rating}' 이 KOFIA 정확 표기 아님.\n"
            f"  허용 표기: {VALID_CP_RATINGS}\n"
            f"  응답: {raw}"
        )

    # CP yield 변환 — KOFIA CP1년 평균 사용 (발행자별 실측 yield 미보유 가정)
    conv = convert_cp_to_bond_5y(cp_rating, cp_yield_observed=None)
    mapped_bond = conv["mapped_bond_rating"]

    if verbose:
        print(f"   [신용등급 RAG] 회사채 등급 부재 → CP 수익률 변환")
        print(f"      CP {cp_rating} 1년 = {conv['kofia_cp_1y']*100:.3f}% "
              f"+ Term-Credit Spread {conv['term_credit_spread']*100:+.3f}%p "
              f"= 회사채5년 {conv['converted_yield']*100:.3f}% (매핑 {mapped_bond})")

    return {
        "rating":              mapped_bond,             # Kd 산정에 사용될 최종 등급
        "rating_type":         "cp_mapped",
        "rating_agency":       result.get("cp_rating_agency", ""),
        "rating_date":         result.get("cp_rating_date", ""),
        "bond_rating":         None,
        "cp_rating":           cp_rating,
        "cp_rating_agency":    result.get("cp_rating_agency", ""),
        "cp_rating_date":      result.get("cp_rating_date", ""),
        "mapping_applied":     f"{cp_rating} → {mapped_bond} (CP 수익률 변환)",
        "cp_conversion":       conv,                    # 분해 산식 전체 보존
        "source_quote":        result.get("source_quote", ""),
        "confidence":          result.get("confidence", "medium"),
        "source":              f"RAG({chunks_path.name}) + LLM({model})",
    }


if __name__ == "__main__":
    # 단일 회사 테스트
    import sys
    if len(sys.argv) < 4:
        print("사용법: python -m valuation_engine.fetch_credit_rating <ticker> <name> <year>")
        sys.exit(1)
    r = fetch_credit_rating_via_rag(
        ticker=sys.argv[1], name=sys.argv[2], year=int(sys.argv[3]),
        verbose=True
    )
    print(json.dumps(r, ensure_ascii=False, indent=2))
