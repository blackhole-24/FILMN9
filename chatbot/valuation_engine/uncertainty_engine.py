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

from .config import TORNADO_RANGES, MAX_EXPLICIT_GROWTH, MID_YEAR_CONVENTION


# Phase 2: 본체 DCF 와 동일한 연도별 한계세율 — 시나리오/토네이도가 스칼라
#   세율을 쓰면 성장으로 과표구간(예: 3000억 초과)을 넘나드는 종목에서 Base 가
#   본체 fair_price 와 미세 괴리. dcf_engine 과 같은 get_marginal_tax_rate 를
#   연도별 EBIT 에 적용해 정합. 모듈 1회 로드(토네이도 20+회 호출 대비).
_GMT = None


def _get_marginal_tax_fn():
    """xbrl_financials_v4.get_marginal_tax_rate lazy 로드. 실패 시 None(스칼라 폴백)."""
    global _GMT
    if _GMT is None:
        try:
            _xbrl = str(_VAR_ROOT / "XBRL")
            if _xbrl not in sys.path:
                sys.path.insert(0, _xbrl)
            from xbrl_financials_v4 import get_marginal_tax_rate
            _GMT = get_marginal_tax_rate
        except Exception:
            _GMT = False
    return _GMT or None


def _run_dcf_with(opm: float, capex_ratio: float, nwc_ratio: float,
                  g_y1: float, wacc: float, g_perp: float,
                  da_ratio: float, tax_rate: float,
                  revenue_0: float, nwc_0: float,
                  roic_terminal: float = None,
                  terminal_opm: float = None,
                  opm_sched: list = None,
                  incr_intensity: float = None) -> float:
    """단순화 DCF — 정상화 비율을 받아 5년 FCFF + Gordon TV → EV.

    roic_terminal: 본체 DCF 가 정한 terminal ROIC(moat 종목의 implied_roic).
                   None 이면 WACC 로 수렴(비-moat). → Base 시나리오를 본체와 정합.
    terminal_opm:  영구가치 NOPAT 에만 적용할 OPM(전구간 opm 과 별개로 민감도 분석용).
                   None 이면 opm 사용 (A1: 영구 OPM 민감도).
    opm_sched:     B1+ 연도별 OPM 스케줄(5개). 제공 시 explicit 기간에서 opm 스칼라 대신
                   년차별 opm_sched[t-1] 사용. terminal_opm 미지정 시 opm_sched[-1] 채택.
    incr_intensity: B3 증분자본집약도. 제공+합리범위(0<x<1.0)면 capex_t = da_t + max(0,ΔRev)
                   × incr_intensity 로 분해. 없으면 A4 linear 수렴 schedule 사용.
    """
    fade = [g_y1, g_y1*0.8, g_y1*0.8*0.7, g_y1*0.8*0.7*0.7, g_perp]
    n_yr = len(fade)
    use_b3 = (incr_intensity is not None and 0.0 < incr_intensity < 1.0)
    use_opm_sched = (opm_sched is not None and len(opm_sched) >= n_yr)

    # A4 linear capex schedule — B3 미사용 시 폴백
    if not use_b3:
        if capex_ratio > da_ratio and n_yr >= 2:
            capex_sched = [da_ratio + (capex_ratio - da_ratio) * max(0.0, 1 - i / (n_yr - 1))
                           for i in range(n_yr)]
        else:
            capex_sched = [capex_ratio] * n_yr

    prev_rev = revenue_0
    # 주의(Phase 7): 시그니처의 nwc_0 인자는 미사용 — 초기 NWC 를 revenue_0×nwc_ratio 로
    #   재계산해 본체 DCF(dcf_engine 와 동일)와 ΔNWC 시작점을 일치시킨다. 호출부 호환
    #   유지를 위해 인자는 남겨둠(제거 시 5개 호출부 동반 수정 필요, 무해).
    prev_nwc = revenue_0 * nwc_ratio
    pv_sum = 0.0
    rev_5 = revenue_0

    # Phase 2: 연도별 한계세율 함수 (본체 DCF 정합). None 이면 스칼라 tax_rate 폴백.
    _gmt = _get_marginal_tax_fn()
    t5_rate = tax_rate   # TV 용 — 마지막 explicit 연도 세율로 갱신

    for t, g_t in enumerate(fade, start=1):
        rev_t   = prev_rev * (1 + g_t)
        # B1+: opm_sched 우선, 없으면 scalar opm
        _opm_t  = opm_sched[t - 1] if use_opm_sched else opm
        ebit_t  = rev_t * _opm_t
        da_t    = rev_t * da_ratio
        # B3: 증분자본집약도 분리, 없으면 A4 linear
        if use_b3:
            capex_t = da_t + max(0.0, rev_t - prev_rev) * incr_intensity
        else:
            capex_t = rev_t * capex_sched[t - 1]
        nwc_t   = rev_t * nwc_ratio
        dnwc    = nwc_t - prev_nwc
        # Phase 2: 본체 DCF 와 동일하게 연도별 한계세율 — 흑자 EBIT 에만 적용,
        #   적자/함수부재 시 스칼라 tax_rate 폴백 (Bear 적자 시나리오 보호).
        if _gmt is not None and ebit_t > 0:
            t_rate_t, _ = _gmt(ebit_t)
        else:
            t_rate_t = tax_rate
        fcff_t  = ebit_t * (1 - t_rate_t) + da_t - capex_t - dnwc
        t_disc  = (t - 0.5) if MID_YEAR_CONVENTION else t
        pv_sum += fcff_t / (1 + wacc) ** t_disc

        if t == n_yr:
            rev_5 = rev_t
            t5_rate = t_rate_t

        prev_rev, prev_nwc = rev_t, nwc_t

    # ── Terminal Value — 본체 DCF 와 동일 산식 ──
    _roic_t = roic_terminal if (roic_terminal and roic_terminal > 0) else wacc
    # terminal_opm 명시 우선 → 없으면 opm_sched 마지막 값 → 없으면 scalar opm
    if terminal_opm is not None:
        _topm = terminal_opm
    elif use_opm_sched:
        _topm = opm_sched[-1]
    else:
        _topm = opm
    # Phase 2: TV 세율도 본체와 동일하게 마지막 explicit 연도 세율(t5_rate) 사용.
    nopat_terminal    = rev_5 * (1 + g_perp) * _topm * (1 - t5_rate)
    reinvest_terminal = (g_perp / _roic_t) if _roic_t > 0 else 0.0
    fcff_terminal     = nopat_terminal * (1 - reinvest_terminal)
    TV = fcff_terminal / (wacc - g_perp) if wacc > g_perp else 0.0
    tv_disc = (n_yr - 0.5) if MID_YEAR_CONVENTION else n_yr
    return pv_sum + TV / (1 + wacc) ** tv_disc


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

    # ── 본체 DCF 의 terminal ROIC + Tier B/B+ 메타 재사용 (Base ≠ 적정주가 불일치 제거) ──
    #   moat 종목(roic_terminal ≠ WACC)은 본체 implied_roic 를 고정 전달,
    #   비-moat(roic_terminal ≈ WACC)는 None → 시나리오 WACC 로 수렴.
    #   opm_sched_main (B1+) / incr_int_main (B3) — Base·민감도·일부 토네이도에 전달해
    #   본체와 일관 (Bear/Bull/OPM·CapEx 토네이도는 스칼라 perturbation 유지 — 의도된 가변).
    _tv_meta = dcf_result.get("terminal_value_meta", {}) or {}
    _roic_main = _tv_meta.get("roic_terminal")
    roic_pass = (_roic_main if (_roic_main is not None
                 and abs(_roic_main - base_wacc) > 1e-6) else None)
    opm_sched_main = _tv_meta.get("opm_sched")           # B1+ 5년 OPM 스케줄 (없으면 None)
    incr_int_main = _tv_meta.get("incr_capital_intensity") if _tv_meta.get("b3_capex_split") else None

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
            # 성장률 상한 적용 (dcf_engine 과 일관) — 경기바닥 기점 급등 외삽 방지
            g_y1   = min(min(yoy_growth), MAX_EXPLICIT_GROWTH) if yoy_growth else g_3yr
            capex_s= max(capex_ratio_series)
            nwc_s  = max(nwc_ratio_series)
        elif label == "Bull":
            opm_s  = max(opm_series)
            g_y1   = min(max(yoy_growth), MAX_EXPLICIT_GROWTH) if yoy_growth else g_3yr
            capex_s= min(capex_ratio_series)
            nwc_s  = min(nwc_ratio_series)
        else:  # Base
            opm_s  = sum(opm_series)/len(opm_series)
            g_y1   = g_3yr
            capex_s= sum(capex_ratio_series)/len(capex_ratio_series)
            nwc_s  = sum(nwc_ratio_series)/len(nwc_ratio_series)

        # Base만 본체 OPM/CapEx 스케줄 사용 → fair_price와 정확 일치
        # Bear/Bull은 의도적으로 scalar OPM/CapEx perturbation 유지
        if label == "Base":
            EV = _run_dcf_with(opm_s, capex_s, nwc_s, g_y1, base_wacc, base_g,
                               da_ratio, tax_rate, revenue_0, nwc_0,
                               roic_terminal=roic_pass,
                               opm_sched=opm_sched_main,
                               incr_intensity=incr_int_main)
        else:
            EV = _run_dcf_with(opm_s, capex_s, nwc_s, g_y1, base_wacc, base_g,
                               da_ratio, tax_rate, revenue_0, nwc_0,
                               roic_terminal=roic_pass)
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
            # 민감도는 OPM/CapEx 본체 일치 — WACC×g만 변동
            EV = _run_dcf_with(opm_base, capex_base, nwc_base, g_y1_base,
                               w, g, da_ratio, tax_rate, revenue_0, nwc_0,
                               roic_terminal=roic_pass,
                               opm_sched=opm_sched_main,
                               incr_intensity=incr_int_main)
            price = _price_from_ev(EV, net_debt, noa, minority, float_sh)
            row.append(price)
        sens_matrix.append(row)

    # ── (3) 토네이도 ───────────────────────────────────────────
    base_price = scenarios["Base"]["price"]

    # _eval: opm/capex 토네이도는 scalar perturbation(opm_sched·incr_intensity 미전달).
    #        다른 항목(g_y1·NWC·WACC·g_perp·영구OPM)은 본체 OPM/CapEx 스케줄 유지.
    def _eval(opm=opm_base, capex=capex_base, nwc=nwc_base,
              g_y1=g_y1_base, wacc=base_wacc, g_perp=base_g, terminal_opm=None,
              use_main_sched=True):
        kwargs = dict(roic_terminal=roic_pass, terminal_opm=terminal_opm)
        if use_main_sched:
            kwargs["opm_sched"] = opm_sched_main
            kwargs["incr_intensity"] = incr_int_main
        EV = _run_dcf_with(opm, capex, nwc, g_y1, wacc, g_perp,
                           da_ratio, tax_rate, revenue_0, nwc_0, **kwargs)
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
            # OPM scalar perturb — opm_sched 무시 (Bear/Bull과 같은 정신)
            neg_v = _eval(opm=opm_base - delta, use_main_sched=False)
            pos_v = _eval(opm=opm_base + delta, use_main_sched=False)
        elif key == "capex":
            # CapEx scalar perturb — incr_intensity 무시
            neg_v = _eval(capex=capex_base + delta, use_main_sched=False)
            pos_v = _eval(capex=capex_base - delta, use_main_sched=False)
        elif key == "nwc":
            neg_v = _eval(nwc=nwc_base + delta);   pos_v = _eval(nwc=nwc_base - delta)
        elif key == "wacc":
            neg_v = _eval(wacc=base_wacc + delta); pos_v = _eval(wacc=base_wacc - delta)
        else:  # gperp
            neg_v = _eval(g_perp=base_g - delta);  pos_v = _eval(g_perp=base_g + delta)

        tornado.append({
            "name": name,
            "neg": neg_v - base_price,
            "pos": pos_v - base_price,
        })

    # ── (3-A1) Terminal-specific 민감도 — 영구 OPM ±2%p (Terminal NOPAT 에만 적용) ──
    _topm_d = TORNADO_RANGES.get("opm", 0.02)
    _t_neg = _eval(terminal_opm=opm_base - _topm_d)
    _t_pos = _eval(terminal_opm=opm_base + _topm_d)
    tornado.append({
        "name": f"영구 OPM ±{_topm_d*100:.0f}%p (TV 한정)",
        "neg":  _t_neg - base_price,
        "pos":  _t_pos - base_price,
    })

    # ── (3-A1) ROIC_terminal 3시나리오 — WACC 수렴 / 피어중위 / 현재 유지 ──
    _impl_roic = dcf_result.get("implied_roic")
    _peer_roic = _tv_meta.get("peer_roic_median")
    terminal_roic_scenarios = []
    for _lbl, _rv in [("WACC 수렴", base_wacc),
                       ("피어 중위", _peer_roic),
                       ("현재 유지", _impl_roic)]:
        if _rv is not None and _rv > 0:
            _EV = _run_dcf_with(opm_base, capex_base, nwc_base, g_y1_base,
                                base_wacc, base_g, da_ratio, tax_rate,
                                revenue_0, nwc_0, roic_terminal=_rv,
                                opm_sched=opm_sched_main,
                                incr_intensity=incr_int_main)
            terminal_roic_scenarios.append({
                "label": _lbl, "roic": _rv,
                "price": _price_from_ev(_EV, net_debt, noa, minority, float_sh),
            })

    # ── (3-A1) TV 비중 (TV_pv / EV) — Terminal 의존도 노출 ──
    _tv_pv = dcf_result.get("TV_pv"); _ev_main = dcf_result.get("EV")
    tv_weight = (_tv_pv / _ev_main) if (_tv_pv and _ev_main and _ev_main > 0) else None

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
        "terminal_roic_scenarios": terminal_roic_scenarios,   # A1
        "tv_weight": tv_weight,                                # A1
        "base_price": base_price,
    }
