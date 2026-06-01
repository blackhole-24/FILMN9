"""CP 수익률 → 회사채 I(공모사채) 무보증 5년 수익률 변환.

변환 원리 (금융이론):
    회사채5년 yield = CP1년 yield + Term-Credit Spread
    where  Term-Credit Spread = KOFIA 회사채5년(매핑등급) − KOFIA CP1년(원등급)

이 스프레드는 두 가지 효과를 동시에 반영:
  ① 만기 프리미엄: 1년 → 5년 (장기일수록 yield ↑)
  ② 신용등급 체계 차이: 단기 등급 (A1) → 장기 등급 (AA-) 환산

전제:
  - 동일 발행자에 대해 KOFIA CP1년 평균과 그 발행자의 실제 CP1년 yield 가
    크게 다르지 않다면, 변환 후 회사채5년 등가값도 KOFIA 회사채5년 평균에
    가까워짐. 발행자가 시장평균보다 비싸게 CP를 발행했다면 결과도 그만큼 ↑.

사용:
    >>> result = convert_cp_to_bond_5y("A1", cp_yield_observed=0.0340)
    >>> result["converted_yield"]      # 0.04848  (3.40% + 1.448%p)
    >>> result["term_credit_spread"]   # 0.01448  (1.448%p)
    >>> result["kofia_bond_5y"]        # 0.04429  KOFIA AA+ 회사채5년
"""
from __future__ import annotations

from typing import Optional

from .cp_yield_data import VALID_CP_RATINGS
from .cp_loader import get_cp_yield
from .kd_loader import get_kd_by_rating


# CP → 회사채 신용등급 매핑 (한국 3대 신평사 등급정의서 공통)
# 근거: 한국신용평가/한국기업평가/NICE신용평가 「신용등급 정의서」 장단기 대응표
CP_TO_BOND_RATING_MAP: dict[str, str] = {
    "A1":  "AA-",     # "AA- 이상" 의 보수적 하한값
    "A2+": "A+",
    "A2":  "A0",
    "A2-": "A-",
    "A3+": "BBB+",
    "A3":  "BBB0",
    "A3-": "BBB-",
    "B+":  "BBB-",    # 투자부적격은 KOFIA 표 최저등급으로 폴백
    "B":   "BBB-",
    "B-":  "BBB-",
    "C":   "BBB-",
    "D":   "BBB-",
}


def convert_cp_to_bond_5y(
    cp_rating: str,
    cp_yield_observed: Optional[float] = None,
    cp_maturity: str = "1년",
) -> dict:
    """CP 등급(+ 선택적 실측 yield)을 회사채 I 무보증 5년 등가 yield 로 변환.

    Args:
        cp_rating: KOFIA CP 정확 표기 (A1, A2+, A2, A2-, A3+, ...)
        cp_yield_observed: 발행자가 실제 발행한 CP 수익률 (소수). None이면 KOFIA 평균 사용.
        cp_maturity: 비교 기준 CP 만기. 기본 "1년" (5년 회사채와의 만기 차이를
                     명확히 측정하기 위해 가장 긴 CP 만기 사용).

    Returns:
        {
            "cp_rating":           "A1",
            "cp_maturity":         "1년",
            "cp_yield_input":      0.03150,   # 입력값 (관측 또는 KOFIA 평균)
            "cp_yield_source":     "KOFIA 평균" | "관측값",
            "mapped_bond_rating":  "AA-",
            "kofia_bond_5y":       0.04598,
            "kofia_cp_1y":         0.03150,
            "term_credit_spread":  0.01448,    # = kofia_bond_5y − kofia_cp_1y
            "converted_yield":     0.04598,    # 최종 = cp_yield_input + spread
            "kofia_cp_as_of":      "2026-05-18",
            "method":              "CP1년 + (KOFIA 회사채5년 − KOFIA CP1년)",
        }
    """
    if cp_rating not in VALID_CP_RATINGS:
        raise ValueError(
            f"CP 등급 '{cp_rating}' 이 KOFIA 정확 표기 아님.\n"
            f"  허용: {VALID_CP_RATINGS}"
        )

    # 1) CP rating → Bond rating (한국 신평사 장단기 등급 대응표)
    bond_rating = CP_TO_BOND_RATING_MAP[cp_rating]
    speculative = cp_rating in ("B+", "B", "B-", "C", "D")   # 투기등급 (BBB- 로 클립됨)

    # 2) KOFIA 회사채 5년 yield (매핑된 장기 등급) — 변환의 핵심 기준값
    bond_info = get_kd_by_rating(bond_rating)
    kofia_bond_5y = bond_info["kd"]

    # 3) KOFIA CP 1년 yield (원 CP 등급) — graceful: 하드코드 미수록 등급(A2 등)도
    #    평가가 중단되지 않도록 KeyError 흡수. observed 없으면 결과에 영향 없음(아래 참조).
    kofia_cp_1y = None
    cp_info = None
    try:
        cp_info = get_cp_yield(cp_rating, cp_maturity)
        kofia_cp_1y = cp_info["yield"]
    except Exception:
        pass

    # 4) 변환 — 일반투자자 목적적합성을 위해 '단순·투명' 우선.
    #    · observed(발행자 실제 CP 수익률) 있으면: 매핑 회사채5년 + 발행자 스프레드(observed−KOFIA평균)
    #    · 없으면(현재 기본): CP등급→대응 회사채등급→KOFIA 회사채5년 수익률 '직접' 사용.
    #      (기존 Term-Credit Spread 분해는 observed 부재 시 결과가 이와 수학적으로 동일 →
    #       오해 소지 있는 복잡성 제거하고 설명 가능한 단순 매핑으로 통일.)
    if cp_yield_observed is not None and kofia_cp_1y is not None:
        converted = kofia_bond_5y + (cp_yield_observed - kofia_cp_1y)
        cp_input, cp_source = cp_yield_observed, "관측값 (발행자별)"
        method = "매핑 회사채5년 + 발행자 CP 스프레드(관측−KOFIA평균)"
    else:
        converted = kofia_bond_5y
        cp_input = cp_yield_observed if cp_yield_observed is not None else kofia_cp_1y
        cp_source = "매핑 회사채 직접"
        method = "CP등급 → 대응 회사채등급 → KOFIA 회사채5년 수익률 직접"

    # 5) 신뢰도 경고 (일반투자자 보호) — 임의 가산 없이 '명시'로 처리 (실데이터 정책 유지)
    warnings = []
    if speculative:
        warnings.append(
            f"투기등급 CP({cp_rating})를 KOFIA 표 최저 BBB- 로 클립 — "
            f"실제 Kd 는 더 높을 수 있어 가치가 과대평가될 수 있음 (신뢰도 낮음).")

    return {
        "cp_rating":          cp_rating,
        "cp_maturity":        cp_maturity,
        "cp_yield_input":     cp_input,
        "cp_yield_source":    cp_source,
        "mapped_bond_rating": bond_rating,
        "kofia_bond_5y":      kofia_bond_5y,
        "kofia_bond_as_of":   bond_info["kofia_as_of"],
        "kofia_cp_1y":        kofia_cp_1y,
        "kofia_cp_as_of":     cp_info["as_of"] if cp_info else None,
        "kofia_cp_source":    cp_info["source_detail"] if cp_info else "N/A",
        "kofia_cp_data_origin": cp_info["source"] if cp_info else "unavailable",
        "term_credit_spread": (kofia_bond_5y - kofia_cp_1y) if kofia_cp_1y is not None else None,
        "converted_yield":    converted,
        "speculative_grade":  speculative,
        "warnings":           warnings,
        "method":             method,
    }


if __name__ == "__main__":
    # 데모 — 캡처상의 3개 CP 등급에 대해 변환 시연
    print(f"{'CP':5s} {'→Bond':5s} | {'CP1년':>7s} {'채5년':>7s} {'Spread':>7s} | "
          f"{'CP수익률→채수익률':>16s}")
    print("-" * 70)
    for cp in ("A1", "A2+", "A3+"):
        r = convert_cp_to_bond_5y(cp)
        print(f"{r['cp_rating']:5s} {r['mapped_bond_rating']:5s} | "
              f"{r['kofia_cp_1y']*100:6.3f}% {r['kofia_bond_5y']*100:6.3f}% "
              f"{r['term_credit_spread']*100:+6.3f}%p | "
              f"{r['cp_yield_input']*100:6.3f}% → {r['converted_yield']*100:6.3f}%")
