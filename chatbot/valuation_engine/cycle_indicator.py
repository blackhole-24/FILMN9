"""산업 사이클 위치 z-score 산출.

피어 4사 (타겟 포함) 의 5년 OPM 시계열로 산업 평균을 구축하고,
현재 산업 OPM이 장기 평균에서 얼마나 벗어나 있는지를 z-score로 표시.

목적:
  - 사이클 산업 (건설·반도체) 에서 "현재가 호황/정상/침체 중 어느 위치인가" 가시화
  - 정상화 비율 (OPM 평균) 이 사이클 특정 시점에 쏠려있는지 자동 진단
  - 일반투자자에게 "회사 결과를 사이클 맥락에서 해석" 정보 제공

학술 근거:
  - Bondt-Thaler (1985) "Mean Reversion": 산업 평균으로 회귀 가설
  - Fama-French: 산업 사이클 인식의 중요성
"""
from __future__ import annotations

from typing import Optional

import numpy as np


def compute_industry_cycle(xbrl_data: dict, verbose: bool = False) -> dict:
    """피어 OPM 시계열(정상화 표본 기간)의 사이클 z-score 산출.

    OPM = 영업이익 / 매출액 (피어별 매년 산출 → 평균 → 산업 OPM 시계열)

    Returns:
        {
            "z_score":               float,    # 현재 위치의 z-score
            "label":                 str,      # "호황기"/"정상기"/"침체기"
            "current_industry_opm":  float,    # 가장 최근 산업 평균 OPM
            "long_term_mean_opm":    float,    # 5년 산업 평균 OPM 의 평균
            "long_term_std_opm":     float,    # 5년 표준편차
            "industry_opm_series":   list[dict], # [{year, opm}, ...]
            "n_years":               int,      # 표본 연도 수
            "n_peers":               int,      # 피어 회사 수
            "metric":                str,      # "OPM"
            "interpretation":        str,      # 자연어 해석
        }
    """
    # ── 1. 연도별 산업 평균 OPM 산출 ───────────────────────────
    all_years: set = set()
    for company, data in xbrl_data.items():
        all_years.update(str(y) for y in data["by_year"].keys())
    years = sorted(all_years, key=int)

    industry_opm_series = []
    for year in years:
        opms = []
        for company, data in xbrl_data.items():
            by_year = data["by_year"]
            # year가 int 또는 str 둘 다 대응
            if year not in by_year:
                year_alt = int(year) if year.isdigit() else year
                if year_alt not in by_year:
                    continue
                fin = by_year[year_alt]["financials"]
            else:
                fin = by_year[year]["financials"]
            rev = fin.get("매출액") or 0
            ebit = fin.get("영업이익") or 0
            if rev > 0:
                opms.append(ebit / rev)
        if opms:
            industry_opm_series.append({
                "year": year,
                "opm": float(np.mean(opms)),
                "n_companies": len(opms),
            })

    if len(industry_opm_series) < 3:
        return {
            "z_score":              None,
            "label":                "데이터 부족",
            "current_industry_opm": None,
            "long_term_mean_opm":   None,
            "long_term_std_opm":    None,
            "industry_opm_series":  industry_opm_series,
            "n_years":              len(industry_opm_series),
            "n_peers":              len(xbrl_data),
            "metric":               "OPM",
            "interpretation":       f"표본 {len(industry_opm_series)}년만 가용 — 사이클 분석 불가",
        }

    # ── 2. 장기 평균·표준편차 ───────────────────────────────────
    opm_values = [r["opm"] for r in industry_opm_series]
    long_mean = float(np.mean(opm_values))
    long_std  = float(np.std(opm_values, ddof=1)) if len(opm_values) >= 2 else 0.0
    current   = opm_values[-1]

    # ── 3. z-score 산출 ─────────────────────────────────────────
    if long_std > 0:
        z = (current - long_mean) / long_std
    else:
        z = 0.0

    # ── 4. 라벨링 + 해석 ───────────────────────────────────────
    if z > 1.0:
        label = "호황기"
        interpretation = (
            f"현재 산업 OPM ({current*100:.2f}%) 이 장기 평균 ({long_mean*100:.2f}%) 보다 "
            f"{z:.1f}σ 위 → 사이클 호황 위치. "
            f"정상화 비율이 다소 낙관적으로 잡힐 수 있음. 사이클 평균으로 검증 권장."
        )
    elif z < -1.0:
        label = "침체기"
        interpretation = (
            f"현재 산업 OPM ({current*100:.2f}%) 이 장기 평균 ({long_mean*100:.2f}%) 보다 "
            f"{abs(z):.1f}σ 아래 → 사이클 침체 위치. "
            f"정상화 비율이 다소 비관적으로 잡힐 수 있음. 회복 시 결과 상향 가능."
        )
    else:
        label = "정상기"
        interpretation = (
            f"현재 산업 OPM ({current*100:.2f}%) 이 장기 평균 ({long_mean*100:.2f}%) 부근 "
            f"(z = {z:+.1f}σ) → 사이클 정상 위치. 정상화 비율 신뢰도 높음."
        )

    if verbose:
        print(f"\n[산업 사이클] {label} (z = {z:+.2f}σ)")
        print(f"  산업 OPM 시계열:")
        for r in industry_opm_series:
            marker = " ★" if r is industry_opm_series[-1] else ""
            print(f"    FY{r['year']}: {r['opm']*100:+.2f}% (n={r['n_companies']}){marker}")
        print(f"  장기 평균: {long_mean*100:+.2f}%   표준편차: {long_std*100:.2f}%p")
        print(f"  해석: {interpretation}")

    return {
        "z_score":              z,
        "label":                label,
        "current_industry_opm": current,
        "long_term_mean_opm":   long_mean,
        "long_term_std_opm":    long_std,
        "industry_opm_series":  industry_opm_series,
        "n_years":              len(industry_opm_series),
        "n_peers":              len(xbrl_data),
        "metric":               "OPM",
        "interpretation":       interpretation,
    }
