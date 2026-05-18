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
    >>> result["converted_yield"]    # 0.04848  (3.40% + 1.448%p)
    >>> result["decomposition"]      # 모든 중간 산식 표시
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

    # 1) CP rating → Bond rating (한국 신평사 표준)
    bond_rating = CP_TO_BOND_RATING_MAP[cp_rating]

    # 2) KOFIA 회사채 5년 yield (매핑된 장기 등급)
    bond_info = get_kd_by_rating(bond_rating)
    kofia_bond_5y = bond_info["kd"]

    # 3) KOFIA CP 1년 yield (원래 CP 등급) — CSV 우선, 없으면 하드코드 fallback
    cp_info = get_cp_yield(cp_rating, cp_maturity)
    kofia_cp_1y = cp_info["yield"]

    # 4) Term-Credit Spread = 회사채5년 − CP1년 (만기 + 신용체계 보정 합산)
    spread = kofia_bond_5y - kofia_cp_1y

    # 5) 입력 yield + spread
    if cp_yield_observed is not None:
        cp_input  = cp_yield_observed
        cp_source = "관측값 (발행자별)"
    else:
        cp_input  = kofia_cp_1y
        cp_source = "KOFIA 평균"

    converted = cp_input + spread

    return {
        "cp_rating":          cp_rating,
        "cp_maturity":        cp_maturity,
        "cp_yield_input":     cp_input,
        "cp_yield_source":    cp_source,
        "mapped_bond_rating": bond_rating,
        "kofia_bond_5y":      kofia_bond_5y,
        "kofia_bond_as_of":   bond_info["kofia_as_of"],
        "kofia_cp_1y":        kofia_cp_1y,
        "kofia_cp_as_of":     cp_info["as_of"],
        "kofia_cp_source":    cp_info["source_detail"],
        "kofia_cp_data_origin": cp_info["source"],   # "CSV" 또는 "hardcoded fallback"
        "term_credit_spread": spread,
        "converted_yield":    converted,
        "method": "CP1년 + (KOFIA 회사채5년_매핑등급 − KOFIA CP1년_원등급)",
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
