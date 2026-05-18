"""Phase 4 — DCF: FCFF 5년 Fade-out + Gordon Growth Terminal Value.

설계서 v4 §2 + 8개 결정사항 반영:
  - 정상화 비율: 모두 3년 평균 (OPM, D&A율, CapEx율, NWC율)
  - 세율:       max(유효세율, 한계세율) — 일단 한계세율
  - CAPEX:      팀원 코드 그대로 (유형자산 Gross)
  - Fade-out:   Y+1=3y_CAGR, Y+2=×0.8, Y+3,4=직전×0.7, Y+5=g
  - TV:         Gordon Growth, FCFF_6 / (WACC − g)
  - 위계 검증:  g < Rf < WACC
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from typing import Optional

_VAR_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_VAR_ROOT))
sys.path.insert(0, str(_VAR_ROOT / "XBRL"))

from xbrl_financials_v4 import get_marginal_tax_rate

from .config import (
    TARGET, FISCAL_YEARS, G_PERPETUAL, DCF_DIR,
    NORMALIZATION_OUTLIER_THRESHOLD,
)
from .fetch_peers_financials import load_all as load_xbrl


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else 0.0


def _check_outliers(values: list[float], name: str) -> list[str]:
    """3년 중 1개가 평균 대비 ±50% 이상 이격이면 경고."""
    warns = []
    avg = _avg(values)
    if avg == 0:
        return warns
    for i, v in enumerate(values):
        if abs(v - avg) / abs(avg) > NORMALIZATION_OUTLIER_THRESHOLD:
            warns.append(f"{name}_FY{FISCAL_YEARS[i]} 평균 대비 {(v-avg)/avg*100:+.0f}% 이격")
    return warns


def compute_dcf(wacc_result: dict, verbose: bool = True) -> dict:
    """타겟(아모레) DCF 산출. wacc_result 는 wacc_engine.compute_wacc() 반환."""
    xbrl = load_xbrl()
    target_by_year = xbrl[TARGET["name"]]["by_year"]

    years = sorted(target_by_year.keys(), key=int)
    fins  = [target_by_year[y]["financials"] for y in years]   # [FY23, FY24, FY25]

    revs  = [f["매출액"]  for f in fins]
    ebits = [f["영업이익"] for f in fins]
    das   = [f["da"]      for f in fins]
    capexs = [abs(f.get("capex") or 0) for f in fins]
    # NWC: 팀원 결과의 nwc_cur["NWC"] 사용
    nwcs   = [f["nwc_cur"]["NWC"] for f in fins]

    # ── 정상화 비율 (3년 평균) ─────────────────────────────────
    opm_series        = [e/r for e,r in zip(ebits, revs) if r]
    da_ratio_series   = [d/r for d,r in zip(das,   revs) if r]
    capex_ratio_series= [c/r for c,r in zip(capexs,revs) if r]
    nwc_ratio_series  = [n/r for n,r in zip(nwcs,  revs) if r]

    OPM         = _avg(opm_series)
    DA_RATIO    = _avg(da_ratio_series)
    CAPEX_RATIO = _avg(capex_ratio_series)
    NWC_RATIO   = _avg(nwc_ratio_series)

    # 검증 플래그
    warnings: list[str] = []
    warnings += _check_outliers(opm_series,         "OPM")
    warnings += _check_outliers(da_ratio_series,    "D&A율")
    warnings += _check_outliers(capex_ratio_series, "CapEx율")

    # ── 세율 (한계세율 — 미래 예측 EBIT 기준으로 매년 갱신) ──
    # 헤드라인용 reference: 최신 실적 EBIT 기준 (verbose / 정상화 / 시나리오용)
    # 실제 FCFF 계산은 아래 루프에서 매년 예측 EBIT 로 t 재산정.
    t_rate, _ = get_marginal_tax_rate(ebits[-1])

    # ── 매출 Fade-out ───────────────────────────────────────────
    g_3yr = (revs[-1] / revs[0]) ** (1.0/(len(revs)-1)) - 1 if revs[0] > 0 else 0.02
    g_perp = G_PERPETUAL
    growth = [g_3yr, g_3yr*0.8, g_3yr*0.8*0.7, g_3yr*0.8*0.7*0.7, g_perp]

    if verbose:
        print(f"\n  3년 CAGR = {g_3yr*100:.2f}%")
        print(f"  Fade-out 성장률: {[f'{g*100:.2f}%' for g in growth]}")
        print(f"  OPM={OPM*100:.2f}%  D&A율={DA_RATIO*100:.2f}%  "
              f"CapEx율={CAPEX_RATIO*100:.2f}%  NWC율={NWC_RATIO*100:.2f}%")
        print(f"  세율 (한계) = {t_rate*100:.1f}%")

    # ── 5년 FCFF 명시예측 ───────────────────────────────────────
    WACC = wacc_result["WACC"]
    Rf   = wacc_result["rf"]

    # 위계 검증 — 일반투자자 친화적 경고
    if not (g_perp < Rf < WACC):
        warnings.append(f"위계 위반: g({g_perp*100:.1f}%) < Rf({Rf*100:.2f}%) < WACC({WACC*100:.2f}%)")

    prev_revenue = revs[-1]
    prev_nwc     = nwcs[-1]
    fcff_table: list[dict] = []
    pv_sum = 0.0

    for t, g_t in enumerate(growth, start=1):
        rev_t   = prev_revenue * (1 + g_t)
        ebit_t  = rev_t * OPM
        da_t    = rev_t * DA_RATIO
        capex_t = rev_t * CAPEX_RATIO
        nwc_t   = rev_t * NWC_RATIO
        dnwc    = nwc_t - prev_nwc

        # Y+5: CapEx > D&A 이면 정상화
        if t == 5 and capex_t > da_t:
            capex_t = da_t
            warnings.append("Y+5 CapEx > D&A → D&A 로 강제 조정")

        # 예측 EBIT 기준 한계세율 (구간을 넘어가면 자동 갱신)
        t_rate_t, tier_t = get_marginal_tax_rate(ebit_t)

        fcff_t = ebit_t * (1 - t_rate_t) + da_t - capex_t - dnwc
        df     = 1 / (1 + WACC)**t
        pv     = fcff_t * df

        fcff_table.append({
            "year": f"Y+{t}",
            "growth":  g_t,
            "revenue": rev_t,
            "ebit":    ebit_t,
            "tax_rate": t_rate_t,
            "tax_tier": tier_t,
            "tax":     -ebit_t * t_rate_t,
            "da":      da_t,
            "capex":   -capex_t,
            "dnwc":    -dnwc,
            "fcff":    fcff_t,
            "discount_factor": df,
            "pv":      pv,
        })
        pv_sum += pv
        prev_revenue, prev_nwc = rev_t, nwc_t

    # ── Terminal Value ─────────────────────────────────────────
    fcff_5 = fcff_table[-1]["fcff"]
    fcff_6 = fcff_5 * (1 + g_perp)
    TV     = fcff_6 / (WACC - g_perp)
    TV_pv  = TV / (1 + WACC)**5

    EV = pv_sum + TV_pv

    # Implied ROIC = NOPAT / 투하자본 (단순 추정: Y+1 NOPAT / (E + Net Debt))
    nopat_y1 = fcff_table[0]["ebit"] * (1 - fcff_table[0]["tax_rate"])
    invested_capital = wacc_result.get("DE_median", 0)  # 단순화: 별도 계산 필요
    implied_roic = nopat_y1 / (EV * 0.9) if EV > 0 else 0   # 보수적 근사

    if verbose:
        fcff_str = [f"{r['fcff']/1e9:.1f}b" for r in fcff_table]; print(f"\n  FCFF: {fcff_str}")
        tax_str  = [f"{r['tax_rate']*100:.1f}%" for r in fcff_table]
        print(f"  연도별 세율: {tax_str}")
        print(f"  TV = FCFF_6/(WACC−g) = ₩{TV/1e12:.3f}조")
        print(f"  PV(TV) = ₩{TV_pv/1e12:.3f}조")
        print(f"  EV = ΣPV(FCFF) + PV(TV) = ₩{EV/1e12:.3f}조")

    result = {
        "as_of_date":  wacc_result["as_of_date"],
        "fiscal_years": [str(y) for y in years],
        "historical": {
            "revenue":     revs,
            "ebit":        ebits,
            "da":          das,
            "capex":       capexs,
            "nwc":         nwcs,
        },
        "normalization": {
            "OPM":         OPM,
            "DA_ratio":    DA_RATIO,
            "CAPEX_ratio": CAPEX_RATIO,
            "NWC_ratio":   NWC_RATIO,
            "tax_rate":    t_rate,
            "g_3yr_CAGR":  g_3yr,
        },
        "fade_out_growth": growth,
        "g_perpetual":   g_perp,
        "fcff_table":    fcff_table,
        "TV":            TV,
        "TV_pv":         TV_pv,
        "EV":            EV,
        "implied_roic":  implied_roic,
        "warnings":      warnings,
    }

    path = DCF_DIR / f"dcf_result_{wacc_result['as_of_date'].replace('-','')}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    if verbose:
        print(f"\n저장: {path}")
    return result


if __name__ == "__main__":
    from .wacc_engine import compute_wacc
    w = compute_wacc(verbose=False)
    compute_dcf(w, verbose=True)
