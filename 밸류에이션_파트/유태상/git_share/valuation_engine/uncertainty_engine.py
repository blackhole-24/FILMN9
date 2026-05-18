"""Phase 7 — 불확실성 표현 (Bear/Base/Bull + 민감도 + 토네이도).

설계서 v4 §3:
  1) Bear/Base/Bull 3시나리오
     - 매출 성장률, OPM, CapEx율, NWC율을 과거 3년의 최저/평균/최고 조합
     - WACC, g, D&A율, 세율은 Base 고정
  2) 민감도 매트릭스: WACC ±1%p × g ±0.5%p → 주당가치 3×3
  3) 토네이도: 변수별 단독 ±변동의 주당가치 영향도
"""
from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

_VAR_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_VAR_ROOT))

from .config import TORNADO_RANGES


def _run_dcf_with(opm: float, capex_ratio: float, nwc_ratio: float,
                  g_y1: float, wacc: float, g_perp: float,
                  da_ratio: float, tax_rate: float,
                  revenue_0: float, nwc_0: float) -> float:
    """단순화 DCF — 정상화 비율을 받아 5년 FCFF + TV → EV."""
    fade = [g_y1, g_y1*0.8, g_y1*0.8*0.7, g_y1*0.8*0.7*0.7, g_perp]
    prev_rev = revenue_0
    prev_nwc = nwc_0
    pv_sum = 0.0
    for t, g_t in enumerate(fade, start=1):
        rev_t   = prev_rev * (1 + g_t)
        ebit_t  = rev_t * opm
        da_t    = rev_t * da_ratio
        capex_t = rev_t * capex_ratio
        if t == 5 and capex_t > da_t:
            capex_t = da_t
        nwc_t   = rev_t * nwc_ratio
        dnwc    = nwc_t - prev_nwc
        fcff_t  = ebit_t * (1 - tax_rate) + da_t - capex_t - dnwc
        pv_sum += fcff_t / (1 + wacc) ** t
        prev_rev, prev_nwc = rev_t, nwc_t
    # TV
    fcff_5 = ebit_t * (1 - tax_rate) + da_t - capex_t - (nwc_t - (prev_nwc - dnwc))
    fcff_6 = fcff_5 * (1 + g_perp)
    TV = fcff_6 / (wacc - g_perp) if wacc > g_perp else 0
    return pv_sum + TV / (1 + wacc) ** 5


def _price_from_ev(EV: float, net_debt: float, noa: float,
                   minority: float, float_shares: float) -> float:
    eq = EV - net_debt + noa - minority
    return eq / float_shares if float_shares else 0


def run_scenarios(dcf_result: dict, wacc_result: dict,
                  equity_value_result: dict, verbose: bool = True) -> dict:
    """Bear / Base / Bull + 민감도 매트릭스 + 토네이도."""
    hist = dcf_result["historical"]
    norm = dcf_result["normalization"]

    revs   = hist["revenue"]
    ebits  = hist["ebit"]
    capexs = hist["capex"]
    nwcs   = hist["nwc"]

    # 3년 비율 시계열
    opm_series        = [e/r for e,r in zip(ebits,  revs) if r]
    capex_ratio_series= [c/r for c,r in zip(capexs, revs) if r]
    nwc_ratio_series  = [n/r for n,r in zip(nwcs,   revs) if r]
    yoy_growth = [(revs[i]/revs[i-1] - 1) for i in range(1, len(revs)) if revs[i-1]]

    base_wacc = wacc_result["WACC"]
    base_g    = dcf_result["g_perpetual"]
    da_ratio  = norm["DA_ratio"]
    tax_rate  = norm["tax_rate"]
    g_3yr     = norm["g_3yr_CAGR"]
    revenue_0 = revs[-1]
    nwc_0     = nwcs[-1]

    net_debt = equity_value_result["net_debt"]
    noa      = equity_value_result["noa_clean"]
    minority = equity_value_result["minority_interest"]
    float_sh = equity_value_result["common_float"]

    # ── (1) Bear / Base / Bull ─────────────────────────────────
    scenarios = {}
    for label, picker in [
        ("Bear", lambda s: min(s)),
        ("Base", lambda s: sum(s)/len(s)),
        ("Bull", lambda s: max(s)),
    ]:
        # Bear: OPM↓·성장↓·CapEx↑·NWC↑  /  Bull: 반대
        if label == "Bear":
            opm_s  = min(opm_series)
            g_y1   = min(yoy_growth) if yoy_growth else g_3yr
            capex_s= max(capex_ratio_series)
            nwc_s  = max(nwc_ratio_series)
        elif label == "Bull":
            opm_s  = max(opm_series)
            g_y1   = max(yoy_growth) if yoy_growth else g_3yr
            capex_s= min(capex_ratio_series)
            nwc_s  = min(nwc_ratio_series)
        else:  # Base
            opm_s  = sum(opm_series)/len(opm_series)
            g_y1   = g_3yr
            capex_s= sum(capex_ratio_series)/len(capex_ratio_series)
            nwc_s  = sum(nwc_ratio_series)/len(nwc_ratio_series)

        EV = _run_dcf_with(opm_s, capex_s, nwc_s, g_y1, base_wacc, base_g,
                           da_ratio, tax_rate, revenue_0, nwc_0)
        price = _price_from_ev(EV, net_debt, noa, minority, float_sh)
        scenarios[label] = {
            "OPM": opm_s, "growth_y1": g_y1, "capex_ratio": capex_s, "nwc_ratio": nwc_s,
            "EV": EV, "price": price,
        }

    # ── (2) 민감도 매트릭스 ─────────────────────────────────────
    opm_base   = norm["OPM"]
    capex_base = norm["CAPEX_ratio"]
    nwc_base   = norm["NWC_ratio"]
    g_y1_base  = g_3yr

    sens_matrix = []
    wacc_axis = [base_wacc - 0.01, base_wacc, base_wacc + 0.01]
    g_axis    = [base_g - 0.005, base_g, base_g + 0.005]
    for w in wacc_axis:
        row = []
        for g in g_axis:
            EV = _run_dcf_with(opm_base, capex_base, nwc_base, g_y1_base,
                               w, g, da_ratio, tax_rate, revenue_0, nwc_0)
            price = _price_from_ev(EV, net_debt, noa, minority, float_sh)
            row.append(price)
        sens_matrix.append(row)

    # ── (3) 토네이도 ───────────────────────────────────────────
    base_price = scenarios["Base"]["price"]

    def _eval(opm=opm_base, capex=capex_base, nwc=nwc_base,
              g_y1=g_y1_base, wacc=base_wacc, g_perp=base_g):
        EV = _run_dcf_with(opm, capex, nwc, g_y1, wacc, g_perp,
                           da_ratio, tax_rate, revenue_0, nwc_0)
        return _price_from_ev(EV, net_debt, noa, minority, float_sh)

    tornado = []
    for name, key, delta in [
        ("매출 성장률 Y+1 ±2%p", "g_y1",  TORNADO_RANGES["revenue_growth_y1"]),
        ("OPM ±2%p",            "opm",   TORNADO_RANGES["opm"]),
        ("CapEx율 ±2%p",        "capex", TORNADO_RANGES["capex_ratio"]),
        ("NWC율 ±2%p",          "nwc",   TORNADO_RANGES["nwc_ratio"]),
        ("WACC ±1%p",           "wacc",  TORNADO_RANGES["wacc"]),
        ("g (영구성장) ±0.5%p",  "gperp", TORNADO_RANGES["g_perpetual"]),
    ]:
        if key == "g_y1":
            neg_v = _eval(g_y1=g_y1_base - delta); pos_v = _eval(g_y1=g_y1_base + delta)
        elif key == "opm":
            neg_v = _eval(opm=opm_base - delta);   pos_v = _eval(opm=opm_base + delta)
        elif key == "capex":
            neg_v = _eval(capex=capex_base + delta); pos_v = _eval(capex=capex_base - delta)  # 부호 반대
        elif key == "nwc":
            neg_v = _eval(nwc=nwc_base + delta);   pos_v = _eval(nwc=nwc_base - delta)        # 부호 반대
        elif key == "wacc":
            neg_v = _eval(wacc=base_wacc + delta); pos_v = _eval(wacc=base_wacc - delta)      # WACC↑면 가격↓
        else:  # gperp
            neg_v = _eval(g_perp=base_g - delta);  pos_v = _eval(g_perp=base_g + delta)

        tornado.append({
            "name": name,
            "neg": neg_v - base_price,
            "pos": pos_v - base_price,
        })

    if verbose:
        print(f"\n  Bear:  ₩{scenarios['Bear']['price']:,.0f}")
        print(f"  Base:  ₩{scenarios['Base']['price']:,.0f}")
        print(f"  Bull:  ₩{scenarios['Bull']['price']:,.0f}")
        print(f"\n  민감도 매트릭스 (단위: 원):")
        for r in sens_matrix:
            print(f"    {[f'{v/1000:.0f}k' for v in r]}")
        print(f"\n  토네이도 (Base 대비, 단위: 원):")
        for t in tornado:
            print(f"    {t['name']:24s}: {t['neg']/1000:+.0f}k ~ {t['pos']/1000:+.0f}k")

    return {
        "as_of_date": dcf_result["as_of_date"],
        "scenarios":  scenarios,
        "sensitivity": {
            "wacc_axis": wacc_axis,
            "g_axis":    g_axis,
            "matrix":    sens_matrix,
        },
        "tornado": tornado,
        "base_price": base_price,
    }
