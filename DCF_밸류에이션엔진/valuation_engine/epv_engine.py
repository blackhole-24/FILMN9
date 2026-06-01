"""현재가 적절성 진단 (Reverse Valuation) — 미래 예측 없이 WACC·현재수익력만 사용.

5종 지표 (전부 기존 DCF/Equity 산출값 재활용, 새 가정·예측 0):
  ① EPV (Earnings Power Value, Greenwald): 성장 0 기준가치 = NOPAT / WACC (+비영업−순부채−비지배)
  ② Growth Premium: 시가총액 / EPV − 1  (주가 중 '성장 기대분' 비율)
  ③ Implied Growth (Damodaran Reverse DCF): 현재 EV 를 정당화하는 영구성장률 역산
  ④ Expectations Gap (Mauboussin): 시장 함의 성장(g_implied) − 펀더멘털 SGR
  ⑤ Margin of Safety (Graham): 1 − 현재가 / EPV주당  (보수적 가치 대비 하방 쿠션)

이론 근거:
  Greenwald(2001) Value Investing — EPV
  Damodaran — Reverse DCF / implied growth (g ≤ 명목 GDP)
  Mauboussin & Rappaport(2001/2021) Expectations Investing — Expectations Gap
  Graham — Margin of Safety
"""
from __future__ import annotations

from typing import Optional

# Damodaran 제약: 영구성장률은 명목 GDP 를 초과할 수 없음. 한국 장기 명목성장 ~3%.
KOREA_NOMINAL_GDP_GROWTH = 0.03


def compute_diagnostics(dcf: dict, wacc: dict, eqv: dict,
                        verbose: bool = True) -> dict:
    """DCF·WACC·Equity 결과 → 현재가 적절성 진단 5종.

    Args:
        dcf:  compute_dcf 결과 (nopat_normalized, sgr 포함)
        wacc: compute_wacc 결과 (WACC)
        eqv:  compute_equity_value 결과 (net_debt, noa_clean, minority_interest,
              common_float, current_price)
    """
    W          = wacc.get("WACC") or 0.0
    nopat      = dcf.get("nopat_normalized") or 0.0
    sgr        = dcf.get("sgr")               # None 가능
    net_debt   = eqv.get("net_debt") or 0.0
    noa        = eqv.get("noa_clean") or 0.0
    minority   = eqv.get("minority_interest") or 0.0
    float_sh   = eqv.get("common_float") or 0
    cur_price  = eqv.get("current_price") or 0.0

    out: dict = {
        "as_of_date": dcf.get("as_of_date"),
        "inputs": {"nopat_normalized": nopat, "wacc": W, "sgr": sgr,
                   "net_debt": net_debt, "noa": noa, "current_price": cur_price},
        "notes": [],
    }
    if W <= 0 or nopat <= 0 or float_sh <= 0:
        out["valid"] = False
        out["notes"].append("EPV 산출 불가 (WACC·NOPAT·유통주식 결측 또는 비양수)")
        return out
    out["valid"] = True

    # ── ① EPV (성장 0 기준가치) ──────────────────────────────────
    epv_op    = nopat / W                                  # 영업 EPV
    epv_eq    = epv_op - net_debt + noa - minority          # 자기자본 EPV
    epv_price = epv_eq / float_sh if float_sh else None
    mcap      = cur_price * float_sh                        # 현재 시가총액
    ev_market = mcap + net_debt - noa                       # 현재 영업 EV (시장)

    # ── ② Growth Premium (주가 중 성장 기대분) ──────────────────
    growth_premium = (mcap / epv_eq - 1) if epv_eq > 0 else None

    # ── ③ Implied Growth (현재 EV 정당화 영구성장률) ────────────
    #   EV = NOPAT·(1+g)/(W−g)  →  g = (EV·W − NOPAT)/(EV + NOPAT)
    #   가드: 시장 영업 EV(ev_market)가 양수일 때만 역산(비양수면 역산식이
    #   비논리적 값을 냄). ev,nopat>0 이면 수학적으로 항상 g<W 보장.
    g_implied = None
    if ev_market > 0 and (ev_market + nopat) != 0:
        g_implied = (ev_market * W - nopat) / (ev_market + nopat)

    # ── ④ Expectations Gap (시장 기대 − 펀더멘털 지속가능성장) ──
    expectations_gap = None
    if g_implied is not None and sgr is not None:
        expectations_gap = g_implied - sgr

    # ── ⑤ Margin of Safety (보수적 가치 대비) ───────────────────
    margin_of_safety = (1 - cur_price / epv_price) if (epv_price and epv_price > 0) else None

    # ── 일반투자자용 해석 라벨 ──────────────────────────────────
    def _verdict_g(g):
        if g is None: return "산출불가"
        if g < 0: return "시장 쇠퇴 가정(저평가 신호 가능)"
        if g <= KOREA_NOMINAL_GDP_GROWTH: return "보수적(현실적)"
        if g <= KOREA_NOMINAL_GDP_GROWTH * 2: return "다소 낙관적"
        if g < W: return "매우 낙관적"
        return "비현실적(g≥WACC)"

    out.update({
        "epv_operating":     epv_op,
        "epv_equity":        epv_eq,
        "epv_price":         epv_price,
        "market_cap":        mcap,
        "ev_market":         ev_market,
        "growth_premium":    growth_premium,           # 소수 (0.5 = +50%)
        "implied_growth":    g_implied,                 # 소수 (영구성장률)
        "implied_growth_verdict": _verdict_g(g_implied),
        "gdp_growth_ref":    KOREA_NOMINAL_GDP_GROWTH,
        "expectations_gap":  expectations_gap,          # 소수 (양수=시장 과열)
        "margin_of_safety":  margin_of_safety,          # 소수 (음수=하방쿠션 없음)
    })

    # 종합 한줄 진단 (일반투자자 메시지)
    if epv_price and cur_price:
        if cur_price > epv_price:
            premium_pct = (cur_price / epv_price - 1) * 100
            out["headline"] = (
                f"현재가 ₩{cur_price:,.0f}는 '성장 0' 기준가치(EPV ₩{epv_price:,.0f})보다 "
                f"{premium_pct:.0f}% 높음 — 주가의 상당부분이 성장 기대분. "
                f"정당화에 필요한 영구성장 {(_pct(g_implied))} → {out['implied_growth_verdict']}.")
        else:
            disc_pct = (1 - cur_price / epv_price) * 100
            out["headline"] = (
                f"현재가 ₩{cur_price:,.0f}는 '성장 0' 기준가치(EPV ₩{epv_price:,.0f})보다 "
                f"{disc_pct:.0f}% 낮음 — 성장 없이도 안전마진 존재(저평가 가능).")

    if verbose:
        print(f"\n  ── 현재가 적절성 진단 (Reverse Valuation) ──")
        print(f"  ① EPV(성장0): ₩{epv_price:,.0f}/주  (영업 {epv_op/1e12:.2f}조)")
        print(f"  ② 성장프리미엄: {_pct(growth_premium)}  (시총/EPV)")
        print(f"  ③ 시장함의 성장률: {_pct(g_implied)}  [{out['implied_growth_verdict']}, GDP {KOREA_NOMINAL_GDP_GROWTH*100:.0f}% 대비]")
        print(f"  ④ 기대격차(시장−펀더멘털): {_pct(expectations_gap)}  (SGR {_pct(sgr)})")
        print(f"  ⑤ 안전마진: {_pct(margin_of_safety)}")
    return out


def _pct(x) -> str:
    return f"{x*100:+.1f}%" if isinstance(x, (int, float)) else "N/A"
