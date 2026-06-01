"""사업보고서 청크에서 RAG + GPT-4o-mini 로 최신 신용등급 추출.

설계서·README §Phase3-11: "Kd = 사업보고서 RAG로 추출한 신용등급 × KOFIA 5년물 수익률"

설계 원칙 (v2):
  ★ "LLM은 추출만, 선택은 Python이"
    - 보고서마다 등급 이력이 오름차순/내림차순/일부 누락 등 다양하게 정렬됨.
    - LLM이 직접 "가장 최근"을 판단하면 표 정렬에 따라 결과가 흔들림.
    - 해결: LLM에게 발견된 모든 등급·평가사·평가일을 리스트로 추출 시키고,
            Python에서 날짜 내림차순 정렬 → 첫 행 선택.

  결정사항:
    - 엄격 매칭: KOFIA 정확 표기
      * 회사채(장기): AAA, AA+, AA0, AA-, A+, A0, A-, BBB+, BBB0, BBB-
      * CP(단기):    A1, A2+, A2, A2-, A3+, A3, A3-, B+, B, B-, C, D
    - 우선순위: 회사채(장기) 등급 > CP(단기) 등급
      * 회사채 등급 있으면 그 등급으로 Kd 산정
      * 회사채 등급 없고 CP만 있으면 CP→회사채 수익률 변환
      * 둘 다 없으면 RuntimeError (임의값 절대 금지)
"""
from __future__ import annotations

import json
import os
from pathlib import Path

_VAR_ROOT = Path(__file__).resolve().parent.parent
# 사업보고서 단위(ticker+year) RAG 결과 캐시 — 신용등급은 사업보고서 신규 공시 전까지 불변.
#   eval_date 와 무관하므로 매 평가마다 LLM 재호출하지 않도록 캐시 (비용·시간 절감).
_RAG_CACHE_DIR = _VAR_ROOT / "data" / "rag_cache"
_RAG_CACHE_DIR.mkdir(parents=True, exist_ok=True)

from .compute_equity import _find_chunks_file, _load_chunks, safe_json_loads
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

1. **본문에 명시된 모든 신용등급 이력을 빠짐없이 수집**. 추정·생성 절대 금지.
   - 표 정렬 순서가 오름차순/내림차순/혼재이든 무관 — 행 단위로 모두 추출.
   - 표가 여러 청크에 걸쳐 분할되어 있어도 발견된 행 모두 수집.

2. **등급 표기 정규화** (KOFIA 정확 표기로):
   - 회사채(장기) 허용: AAA, AA+, AA0, AA-, A+, A0, A-, BBB+, BBB0, BBB-
     * "AA"  → "AA0",  "A"  → "A0",  "BBB" → "BBB0"
     * "AA(안정적)" / "AA0(긍정적)" → "AA0" (괄호 안 전망/평정 의견 제거)
     * "AA+(긍정적)" → "AA+"
   - CP(단기) 허용: A1, A2+, A2, A2-, A3+, A3, A3-, B+, B, B-, C, D
     * CP는 보통 "기업어음" 또는 "단기 신용등급" 섹션에 표기됨
   - 허용 표기 외 등급은 수집 안 함 (잘못된 추출 방지).

3. **모든 평가일을 ISO 포맷 (YYYY-MM-DD) 으로 정규화**:
   - "2024.06.15"          → "2024-06-15"
   - "2024-06-15"          → "2024-06-15"
   - "2024년 6월 15일"      → "2024-06-15"
   - "2024.6" / "2024년 6월" → "2024-06-01"   (일 없으면 01 채움)
   - "2024년"               → "2024-12-31"   (월·일 없으면 연말로 채움)
   - 본문에 날짜 완전 부재   → null

4. **회사채(장기) 등급과 CP(단기) 등급을 별도 리스트로 분리**.
   - 동일 행에 둘 다 표기되어 있어도 각각의 리스트에 따로 기재.

5. **평가사(agency)** 는 다음 4개 중 하나 또는 null:
   - "한국기업평가" (한기평)
   - "한국신용평가" (한신평)
   - "NICE신용평가" (나이스)
   - "복수" (여러 평가사 합의표시)

6. **source_quote** 는 발견 행 중 대표 행 1개를 원문 그대로 60자 이내 인용.

7. **본문에 등급 자체가 명시되어 있지 않으면 해당 리스트는 빈 배열 [].**

JSON 스키마 (정확히 이 키 사용 — 다른 키 추가 금지):
{
  "bond_ratings_observed": [
    {"rating": "AA0", "agency": "한국신용평가", "date": "2025-06-15"},
    {"rating": "AA-", "agency": "한국신용평가", "date": "2024-06-20"},
    {"rating": "AA0", "agency": "한국기업평가", "date": "2025-07-10"}
  ],
  "cp_ratings_observed": [
    {"rating": "A1", "agency": "한국기업평가", "date": "2025-07-10"}
  ],
  "source_quote": "회사채 신용등급 AA0(안정적) - 한국신용평가 2025.06.15 평정",
  "confidence": "high"
}

빈 결과 예시:
{
  "bond_ratings_observed": [],
  "cp_ratings_observed":   [],
  "source_quote": "",
  "confidence":   "low"
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
        # 신용등급은 표(table) 형태가 핵심 — 텍스트 키워드보다 높게 가중
        if score > 0 and c.get("kind") == "table":
            score += 20
        if score > 0:
            scored.append((score, c))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:max_chunks]]


def _sort_key_date_desc(row: dict) -> tuple:
    """등급 이력 행을 날짜 내림차순 정렬용.

    tuple (has_date, date_str) 반환:
      - 날짜 있는 행: (1, "2025-06-15")  — reverse=True 시 1 이 0 보다 앞으로
      - 날짜 없는 행: (0, "")           — reverse=True 시 뒤로 밀림 (의도)
    """
    d = row.get("date") or ""
    return (1, d) if d else (0, "")


def _pick_latest(observed: list[dict], allowed: tuple[str, ...]) -> tuple[dict | None, list[dict]]:
    """관측된 등급 리스트에서 날짜 내림차순 정렬 후 가장 최근 1개 선택.

    Returns:
        (latest_row_or_None, cleaned_sorted_list)

    Filtering:
      - rating 필드가 allowed 표기에 없으면 제외 (오추출 차단)
      - 빈 dict 또는 rating null 행 제외
      - 날짜가 있으면 유효성 검증 (미래/2000년 이전/형식오류 → 날짜만 무효화)
    """
    cleaned = []
    for r in observed:
        if not isinstance(r, dict):
            continue
        rt = r.get("rating")
        if not rt or rt not in allowed:
            continue
        cleaned.append({
            "rating": rt,
            "agency": r.get("agency") or "",
            "date":   _sanitize_rating_date(r.get("date") or ""),
        })

    # 날짜 내림차순 정렬 — 빈 날짜는 자동으로 뒤로 밀림
    cleaned.sort(key=_sort_key_date_desc, reverse=True)
    return (cleaned[0] if cleaned else None), cleaned


def _sanitize_rating_date(date_str: str) -> str:
    """평정일 유효성 검증 — YYYY-MM-DD, 2000년~오늘 범위. 무효면 빈 문자열.

    LLM 환각·사업보고서 초안 등으로 섞이는 미래/형식오류 날짜를 무효화한다.
    (등급 자체는 유지하되 날짜만 비워 정렬에서 뒤로 밀리게 — 등급 손실 방지.)
    """
    if not date_str:
        return ""
    from datetime import datetime, date as _date
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return ""
    if d > _date.today() or d.year < 2000:
        return ""
    return date_str


_CREDIT_TTL_DAYS = 90   # 신용등급 캐시 수명(일) — 분기 검토·수시 등급조정 반영(영구 캐시 회피)


def _credit_cache_fresh(cached: dict) -> bool:
    """credit 캐시가 TTL 이내인지. fetched_at 없으면(구버전 캐시) stale → 1회 재조회."""
    try:
        from datetime import date as _d
        fa = (cached or {}).get("fetched_at")
        if not fa:
            return False
        y, mo, dd = (int(x) for x in str(fa)[:10].split("-"))
        return (_d.today() - _d(y, mo, dd)).days <= _CREDIT_TTL_DAYS
    except Exception:
        return False


def fetch_credit_rating_via_rag(ticker: str, name: str, year: int,
                                 market: str = "KOSPI",
                                 model: str = "gpt-4o-mini",
                                 verbose: bool = False,
                                 use_cache: bool = True) -> dict:
    """신용등급 RAG — 사업보고서 단위(ticker+year) 캐시 래퍼.

    캐시 hit: 저장된 결과 즉시 반환 (LLM 호출 0). None(무차입/미평정)도 캐시.
    캐시 miss: _impl 호출 후 결과 저장.
    """
    cache_path = _RAG_CACHE_DIR / f"credit_{ticker}_{year}.json"
    if use_cache and cache_path.exists():
        try:
            with cache_path.open("r", encoding="utf-8") as f:
                cached = json.load(f)
            if _credit_cache_fresh(cached):           # C.2: TTL 이내만 hit
                if verbose:
                    r = cached.get("result")
                    print(f"   [신용등급 RAG] 캐시 hit ({ticker}_{year}): "
                          f"{(r or {}).get('rating') if r else 'None(미평정)'}")
                # write-through: 캐시 hit 에도 DB 적재 (DB 초기화 후 캐시만 남은 경우 대비).
                #   읽기(WACC Kd)는 파일 캐시 사용 → 불변. DB 는 이력·쿼리용.
                _persist_credit_to_db(ticker, year, cached.get("result"))
                return cached.get("result")
            elif verbose:
                print(f"   [신용등급 RAG] 캐시 만료(>{_CREDIT_TTL_DAYS}일) → 재조회 ({ticker}_{year})")
        except Exception:
            pass   # 캐시 손상 → 재호출
    result = _fetch_credit_rating_via_rag_impl(ticker, name, year, market, model, verbose)
    try:
        with cache_path.open("w", encoding="utf-8") as f:
            json.dump({"result": result, "ticker": ticker, "year": year,
                       "fetched_at": __import__("datetime").date.today().isoformat()}, f,
                      ensure_ascii=False, indent=2)
    except Exception:
        pass
    # ★ DB 자동 적재 (guarded) — None(미평정)도 빈 detail 로 기록
    _persist_credit_to_db(ticker, year, result)
    return result


def _persist_credit_to_db(ticker: str, year: int, result: dict | None) -> None:
    """write-through: credit_ratings 테이블 적재 (guarded). None(미평정)도 기록.

    읽기(WACC Kd)는 파일 캐시 사용 → 불변. DB 는 신용등급 이력·쿼리용.
    """
    try:
        from valuation_engine import db
        r = result or {}
        db.save_credit_rating(
            ticker, int(year),
            bond_rating=r.get("bond_rating") or r.get("rating"),
            cp_rating=r.get("cp_rating"), kd_applied=r.get("mapping_applied"),
            detail=r, source="rag")
    except Exception:
        pass


def _fetch_credit_rating_via_rag_impl(ticker: str, name: str, year: int,
                                 market: str = "KOSPI",
                                 model: str = "gpt-4o-mini",
                                 verbose: bool = False) -> dict:
    """사업보고서에서 신용등급 추출 (GPT-4o-mini).

    LLM은 모든 등급 이력 추출만 담당. 최신 1개 선택은 Python이 수행.

    Returns: 기존 호출부(wacc_engine.py)와 동일한 인터페이스 유지.
             추가로 bond_ratings_observed / cp_ratings_observed (감사용 전체 이력) 포함.

    Raises:
        RuntimeError: 청크 부재 / LLM 응답 부재 / 회사채·CP 모두 추출 실패.
    """
    try:
        from openai import OpenAI
    except ImportError as e:
        raise RuntimeError("openai 패키지 필요: pip install openai") from e

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("환경변수 'OPENAI_API_KEY' 가 설정되어 있지 않습니다.")

    # 1) 청크 수집 — chroma 의미검색 + jsonl 키워드 매칭을 합집합(union)으로 결합.
    #    배타적 fallback(과거: chroma 성공 시 키워드 skip) 대신 둘을 병합해 recall 향상.
    #    chroma 가 정형 신용등급 표를 놓치는 경우(예: 의미 유사도 밀림) 키워드가 보강.
    MAX_CTX_CHUNKS = 30   # LLM 컨텍스트 cap (토큰/비용 제어)

    # (a) chroma 의미검색
    chroma_relevant: list[dict] = []
    try:
        from embedding.retrieval import retrieve_for_keyword
        chunks = retrieve_for_keyword(
            keywords=list(_RATING_KEYWORDS) + ["회사채 신용등급 평정", "장기 신용등급 부여일", "평가일자"],
            ticker=ticker, year=year, top_k=25,
        )
        for c in chunks or []:
            md = c.get("metadata", {}) or {}
            chroma_relevant.append({
                "text":             c.get("text", ""),
                "section_path_str": md.get("section_path_str", md.get("section_main", "")),
                "kind":             md.get("kind", ""),
                "similarity":       c.get("similarity", 0),
                "source":           "chroma",
            })
        if verbose:
            print(f"   [신용등급 RAG/chroma] 의미검색 {len(chroma_relevant)}개 청크")
    except Exception as e:
        if verbose:
            print(f"   [신용등급 RAG/chroma] 실패 ({e}) — 키워드 매칭만 사용")

    # (b) jsonl 키워드 매칭 — chroma 성공 여부와 무관하게 항상 실행
    keyword_relevant: list[dict] = []
    try:
        chunks_path = _find_chunks_file(ticker, year, market)
        all_chunks = _load_chunks(chunks_path)
        if all_chunks:
            keyword_relevant = _filter_rating_chunks(all_chunks)
            for c in keyword_relevant:
                c["source"] = "keyword"
            if verbose:
                print(f"   [신용등급 RAG/jsonl] 키워드 매칭 {len(keyword_relevant)}개 청크 "
                      f"({chunks_path.name})")
    except FileNotFoundError:
        if verbose:
            print(f"   [신용등급 RAG/jsonl] 청크 파일 없음 (ticker={ticker}, year={year})")
    except Exception as e:
        if verbose:
            print(f"   [신용등급 RAG/jsonl] 실패 ({e})")

    # (c) union — text 기준 중복 제거. 키워드 매칭(정형 표에 정밀) 우선 + chroma 보충.
    relevant: list[dict] = []
    seen: set[str] = set()
    for c in keyword_relevant + chroma_relevant:
        key = (c.get("text", "") or "").strip()[:200]
        if not key or key in seen:
            continue
        seen.add(key)
        relevant.append(c)
        if len(relevant) >= MAX_CTX_CHUNKS:
            break

    # (d) 청크 자체가 전무 → None 반환 (호출자 wacc_engine 의 fallback 으로 일관 처리)
    if not relevant:
        if verbose:
            print(f"   [{name}] 신용등급 관련 청크 없음 (chroma·키워드 모두) — 호출자 fallback")
        return None
    if verbose:
        n_kw = sum(1 for c in relevant if c.get("source") == "keyword")
        n_ch = len(relevant) - n_kw
        print(f"   [신용등급 RAG] union {len(relevant)}개 청크 (키워드 {n_kw} + chroma {n_ch})")

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
        f"아래 청크에서 회사채 / CP 신용등급 이력을 **빠짐없이 모두** 추출하세요.\n"
        f"표 정렬 순서(오름차순/내림차순)는 무관. 발견된 행 단위로 수집.\n"
        f"===\n{context}\n===\n\n"
        f"JSON으로만 응답:"
    )

    # 4) LLM 호출 — GPT-4o-mini (response_format=json_object 강제)
    client = OpenAI(api_key=api_key)
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
        print(f"   [신용등급 RAG] LLM 응답: {raw[:300]}...")

    # 5) 파싱 + 검증 — 잘린 응답 복구 시도. 신용등급은 필수 아님(무차입/미평정 대응)
    #    → 복구 실패 시 None 반환 → 호출자(wacc_engine)가 AA0 fallback 으로 graceful 처리.
    result = safe_json_loads(raw)
    if result is None:
        if verbose:
            print(f"   [신용등급 RAG] LLM JSON 파싱 실패 — None 반환 (호출자 fallback)")
        return None

    bond_observed_raw = result.get("bond_ratings_observed") or []
    cp_observed_raw   = result.get("cp_ratings_observed")   or []

    # 6) ★ Python 측 정렬 + 최신 1개 선택 (표 정렬 순서 무관)
    bond_latest, bond_list = _pick_latest(bond_observed_raw, VALID_RATINGS)
    cp_latest,   cp_list   = _pick_latest(cp_observed_raw,   VALID_CP_RATINGS)

    if verbose:
        if bond_list:
            print(f"   [신용등급 RAG] 회사채 이력 {len(bond_list)}건 발견:")
            for r in bond_list:
                marker = "★" if r is bond_latest else " "
                print(f"      {marker} {r['rating']:5s}  {r['date']:>10s}  {r['agency']}")
        if cp_list:
            print(f"   [신용등급 RAG] CP 이력 {len(cp_list)}건 발견:")
            for r in cp_list:
                marker = "★" if r is cp_latest else " "
                print(f"      {marker} {r['rating']:5s}  {r['date']:>10s}  {r['agency']}")

    # 7) 회사채·CP 둘 다 없으면 None 반환 — 호출자(wacc_engine)가 fallback 처리
    #    (무차입/미평정 회사: NAVER 등 — RuntimeError 대신 graceful)
    if bond_latest is None and cp_latest is None:
        if verbose:
            print(f"  [{name}] 신용등급 미추출 (회사채·CP 모두 빈 결과) — 호출자 fallback")
        return None

    # 8) 우선순위: 회사채 > CP
    if bond_latest is not None:
        return {
            "rating":               bond_latest["rating"],
            "rating_type":          "bond",
            "rating_agency":        bond_latest["agency"],
            "rating_date":          bond_latest["date"],
            "bond_rating":          bond_latest["rating"],
            "cp_rating":            cp_latest["rating"] if cp_latest else None,
            "cp_rating_agency":     cp_latest["agency"] if cp_latest else "",
            "cp_rating_date":       cp_latest["date"]   if cp_latest else "",
            "mapping_applied":      None,
            "bond_ratings_observed": bond_list,      # ★ 감사용 전체 이력
            "cp_ratings_observed":   cp_list,        # ★ 감사용 전체 이력
            "source_quote":         result.get("source_quote", ""),
            "confidence":           result.get("confidence", "medium"),
            "source":               f"RAG (chroma·jsonl) + LLM({model})",
        }

    # 9) 회사채 없음 → CP 수익률을 회사채 5년 등가 수익률로 변환
    cp_rating = cp_latest["rating"]
    conv = convert_cp_to_bond_5y(cp_rating, cp_yield_observed=None)
    mapped_bond = conv["mapped_bond_rating"]

    if verbose:
        print(f"   [신용등급 RAG] 회사채 등급 부재 → CP 등급 매핑 (CP {cp_rating} → 회사채 {mapped_bond})")
        print(f"      → KOFIA 회사채5년 {conv['converted_yield']*100:.3f}%  [{conv['method']}]")
        for w in conv.get("warnings", []):
            print(f"      ⚠ {w}")

    return {
        "rating":                mapped_bond,
        "rating_type":           "cp_mapped",
        "rating_agency":         cp_latest["agency"],
        "rating_date":           cp_latest["date"],
        "bond_rating":           None,
        "cp_rating":             cp_rating,
        "cp_rating_agency":      cp_latest["agency"],
        "cp_rating_date":        cp_latest["date"],
        "mapping_applied":       f"{cp_rating} → {mapped_bond} (CP 수익률 변환)",
        "cp_conversion":         conv,
        "bond_ratings_observed": bond_list,           # 비어있겠지만 일관성 위해 포함
        "cp_ratings_observed":   cp_list,
        "source_quote":          result.get("source_quote", ""),
        # Phase 6: 투기등급(B+~D)을 BBB- 로 클립한 경우 Kd 가 과소→가치 과대 위험 →
        #   confidence 를 'low' 로 자동 강등(경고 텍스트만으론 신뢰도에 미반영됐음).
        "confidence":            ("low" if conv.get("speculative_grade")
                                  else result.get("confidence", "medium")),
        # Phase 1: chunks_path 는 jsonl 매칭(try) 안에서만 정의 — chroma만 성공하고
        #   jsonl 파일 부재(FileNotFoundError) 시 미정의 → NameError 방지 위해
        #   bond return(L422)과 동일한 안전 표현으로 통일.
        "source":                f"RAG (chroma·jsonl) + LLM({model})",
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
