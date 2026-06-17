"""임베딩 완료 후 RAG 검증용 테스트 케이스.

실행 (임베딩 완료 후):
    conda activate dart-rag
    cd C:\\Users\\Admin\\Desktop\\VAR
    python -m valuation_engine.tests.rag_validation_cases

각 케이스에 대해:
  1. retrieve() 호출
  2. 기대 결과 (예상 청크 ID 또는 키워드) 와 비교
  3. PASS / FAIL 표시
  4. 실패 시 실제 검색 결과 출력

산업 5종 표본 기반 (건설/IT/제약/금융/음식).
"""
from __future__ import annotations

import sys
from pathlib import Path

_VAR_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_VAR_ROOT))

from embedding.retrieval import retrieve


# ─────────────────────────────────────────────────────────────
# 케이스 정의 — 5개 회사 × 평균 3 쿼리
# ─────────────────────────────────────────────────────────────
CASES = [
    # 건설 — 현대건설
    {
        "name": "현대건설 사업부문",
        "query": "주요 사업 부문 매출 구성 도급 주택 플랜트",
        "ticker": "000720", "year": 2025,
        "section_main": None, "top_k": 5,
        "expect_keywords": ["부문", "도급", "플랜트"],
        "expect_section_contains": "사업",
    },
    {
        "name": "현대건설 신용평가",
        "query": "신용평가 등급 회사채 AA",
        "ticker": "000720", "year": 2025,
        "section_main": None, "top_k": 5,
        "expect_keywords": ["AA-", "한국기업평가", "한국신용평가"],
        "expect_section_contains": "회사의 개요",
    },
    {
        "name": "현대건설 발행주식 총수",
        "query": "보통주 발행주식 총수 자기주식",
        "ticker": "000720", "year": 2025,
        "section_main": None, "top_k": 5,
        "expect_keywords": ["보통주", "발행", "주식"],
        "expect_section_contains": "주식",
    },

    # IT/SaaS — 더존비즈온
    {
        "name": "더존비즈온 사업부문",
        "query": "ERP SaaS 클라우드 사업 부문",
        "ticker": "012510", "year": 2025,
        "section_main": None, "top_k": 5,
        "expect_keywords": ["ERP", "클라우드"],
        "expect_section_contains": "사업",
    },
    {
        "name": "더존비즈온 신용평가",
        "query": "신용평가 등급 NICE",
        "ticker": "012510", "year": 2025,
        "section_main": None, "top_k": 5,
        "expect_keywords": ["NICE", "AA"],
        "expect_section_contains": "회사의 개요",
    },

    # 제약 — 한올바이오파마
    {
        "name": "한올바이오파마 사업부문",
        "query": "신약 R&D 임상 파이프라인",
        "ticker": "009420", "year": 2025,
        "section_main": None, "top_k": 5,
        "expect_keywords": ["임상", "신약"],
        "expect_section_contains": "사업",
    },
    {
        "name": "한올바이오파마 신용평가 부재 확인",
        "query": "신용평가 해당사항 없음",
        "ticker": "009420", "year": 2025,
        "section_main": None, "top_k": 3,
        "expect_keywords": ["해당사항"],
        "expect_section_contains": "회사의 개요",
        "expect_no_match": True,    # 신용평가 미보유 — fallback 동작 검증용
    },

    # 금융 — 유진투자증권
    {
        "name": "유진투자증권 사업부문",
        "query": "투자은행 자기매매 위탁매매 자산관리",
        "ticker": "001200", "year": 2025,
        "section_main": None, "top_k": 5,
        "expect_keywords": ["IB", "위탁", "자산관리"],
        "expect_section_contains": "사업",
    },

    # 음식 — 삼양식품
    {
        "name": "삼양식품 사업부문",
        "query": "면스낵 매출 비중 불닭",
        "ticker": "003230", "year": 2025,
        "section_main": None, "top_k": 5,
        "expect_keywords": ["면", "스낵", "비중"],
        "expect_section_contains": "사업",
    },
    {
        "name": "삼양식품 신용평가",
        "query": "신용평가 등급 A0 A+ 회사채",
        "ticker": "003230", "year": 2025,
        "section_main": None, "top_k": 5,
        "expect_keywords": ["A+", "한국기업평가"],
        "expect_section_contains": "회사의 개요",
    },
]


# ─────────────────────────────────────────────────────────────
# 검증 함수
# ─────────────────────────────────────────────────────────────
def run_case(case: dict) -> dict:
    """단일 케이스 실행 + 검증."""
    results = retrieve(
        query=case["query"],
        ticker=case["ticker"],
        year=case.get("year"),
        section_main=case.get("section_main"),
        top_k=case.get("top_k", 5),
    )

    expect_keywords  = case.get("expect_keywords", [])
    expect_section   = case.get("expect_section_contains", "")
    expect_no_match  = case.get("expect_no_match", False)

    # 평가
    if not results:
        return {
            "name":    case["name"],
            "status":  "FAIL — 결과 없음" if not expect_no_match else "PASS — 의도된 빈 결과",
            "results_count": 0,
        }

    # 상위 청크 텍스트 통합 → 키워드 포함 여부
    combined_text = " ".join(r.get("text", "")[:500] for r in results[:3])
    combined_sections = " ".join(
        r.get("metadata", {}).get("section_path_str", "") for r in results[:3])

    keyword_hits = [kw for kw in expect_keywords if kw in combined_text]
    section_hit = expect_section in combined_sections if expect_section else True

    keyword_hit_ratio = len(keyword_hits) / max(len(expect_keywords), 1)

    if expect_no_match:
        # 의도적으로 빈 결과 기대 — 그래도 검색되면 일종의 fallback 시그널
        status = "PARTIAL — 검색은 됐지만 의미 확인 필요"
    elif keyword_hit_ratio >= 0.5 and section_hit:
        status = "PASS"
    elif keyword_hit_ratio > 0 or section_hit:
        status = f"PARTIAL ({len(keyword_hits)}/{len(expect_keywords)} 키워드, section={section_hit})"
    else:
        status = "FAIL"

    return {
        "name":            case["name"],
        "status":          status,
        "results_count":   len(results),
        "keyword_hits":    keyword_hits,
        "keyword_ratio":   keyword_hit_ratio,
        "section_hit":     section_hit,
        "top_similarity":  results[0].get("similarity", 0) if results else 0,
        "top_section":     results[0].get("metadata", {}).get("section_path_str", ""),
    }


def main():
    print("=" * 70)
    print("  RAG 검증 — 5개 산업 × 평균 3 케이스")
    print("=" * 70)

    pass_count = 0
    partial_count = 0
    fail_count = 0
    fail_details = []

    for case in CASES:
        result = run_case(case)
        status = result["status"]
        emoji = "✓" if status.startswith("PASS") else (
            "△" if status.startswith("PARTIAL") else "✗")
        print(f"\n{emoji} [{case['ticker']}] {case['name']}")
        print(f"   상태: {status}")
        print(f"   결과 {result['results_count']}개, "
              f"top_sim={result.get('top_similarity', 0):.3f}")
        print(f"   top_section: {result.get('top_section', '')[:80]}")
        if result.get("keyword_hits"):
            print(f"   매칭 키워드: {result['keyword_hits']}")

        if status.startswith("PASS"):
            pass_count += 1
        elif status.startswith("PARTIAL"):
            partial_count += 1
        else:
            fail_count += 1
            fail_details.append(result)

    print("\n" + "=" * 70)
    print(f"  PASS: {pass_count}  /  PARTIAL: {partial_count}  /  FAIL: {fail_count}  "
          f"(총 {len(CASES)})")
    print("=" * 70)

    if fail_count == 0:
        print("\n✓ 전체 통과 — RAG 정상 작동")
        return 0
    else:
        print(f"\n⚠ {fail_count}개 FAIL — 임베딩·청크·키워드 점검 필요")
        return 1


if __name__ == "__main__":
    sys.exit(main())
