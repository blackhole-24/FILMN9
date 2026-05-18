"""Phase 6 — 멀티플 4종 역산 (EV/EBITDA, EV/Sales, PER, PBR).

설계서 v4 §4 + 결정사항 #5: 모두 중위값(Median).

피어 3사 (LG생활건강, 한국콜마, 에이피알) 중위값 × 타겟 지표 = 역산가.
타겟 자체는 피어에 포함 안 함 (자기 회피).

피어 25~75 백분위 밖이면 이격 경고.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

_VAR_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_VAR_ROOT))

from .config import TARGET, PEERS
from .fetch_peers_financials import load_all as load_xbrl
from .compute_equity import load_latest as load_equity


def _ibd_for(by_year: dict) -> float:
    latest_year = max(by_year.keys(), key=int)
    return by_year[latest_year]["financials"]["ibd"]


def _ebitda_for(by_year: dict) -> float:
    latest_year = max(by_year.keys(), key=int)
    return by_year[latest_year]["financials"]["ebitda"]


def _revenue_for(by_year: dict) -> float:
    latest_year = max(by_year.keys(), key=int)
    return by_year[latest_year]["financials"]["매출액"]


def _ni_controlling_for(by_year: dict) -> float:
    latest_year = max(by_year.keys(), key=int)
    return by_year[latest_year]["financials"].get("지배순이익") or 0


def _book_value_for(by_year: dict) -> float:
    """지배주주지분(자본총계 - 비지배). 팀원 코드 미제공 → 단순 추정."""
    # POC: NI / ROE 식 가능하나 데이터 없음. 일단 0.
    # TODO: 팀원 코드에 equity_controlling 추가 후 사용
    return 0


def compute_multiples(equity_value_result: dict, verbose: bool = True) -> dict:
    """피어 4종 멀티플 중위값 × 타겟 지표 = 역산가."""
    xbrl    = load_xbrl()
    equity  = load_equity()

    # ── 피어별 멀티플 산출 ──────────────────────────────────────
    peer_multiples = []
    for p in PEERS:
        name = p["name"]
        by_year = xbrl[name]["by_year"]
        E   = equity["companies"][name]["E_market_cap"]
        ibd = _ibd_for(by_year)
        # Net Debt 단순: IBD - 현금성 (NOA에서 추출)
        cash = 0
        for it in by_year[max(by_year.keys(), key=int)]["financials"].get("noa_items", []):
            if it.get("tag") == "CashAndCashEquivalents":
                cash = it.get("val", 0); break
        net_debt = ibd - cash
        EV_peer  = E + net_debt

        ebitda = _ebitda_for(by_year)
        revenue= _revenue_for(by_year)
        ni     = _ni_controlling_for(by_year)
        common_float = equity["companies"][name]["common_float"]
        eps  = ni / common_float if common_float else 0
        per  = (equity["companies"][name]["close_price"] / eps) if eps > 0 else None
        peer_multiples.append({
            "name": name,
            "EV":   EV_peer,
            "EV_EBITDA": EV_peer / ebitda if ebitda > 0 else None,
            "EV_Sales":  EV_peer / revenue if revenue > 0 else None,
            "PER":       per,
            "PBR":       None,    # 자본총계 미수집
        })

    # ── 중위값 + 백분위 ────────────────────────────────────────
    def stats(key):
        vals = [m[key] for m in peer_multiples if m[key] is not None]
        if not vals:
            return None, None, None
        return float(np.median(vals)), float(np.percentile(vals, 25)), float(np.percentile(vals, 75))

    ev_ebitda_med, ev_ebitda_p25, ev_ebitda_p75 = stats("EV_EBITDA")
    ev_sales_med,  ev_sales_p25,  ev_sales_p75  = stats("EV_Sales")
    per_med,       per_p25,       per_p75       = stats("PER")

    # ── 타겟 지표 ──────────────────────────────────────────────
    target_by_year = xbrl[TARGET["name"]]["by_year"]
    t_ebitda  = _ebitda_for(target_by_year)
    t_revenue = _revenue_for(target_by_year)
    t_ni      = _ni_controlling_for(target_by_year)
    t_float   = equity["companies"][TARGET["name"]]["common_float"]
    t_eps     = t_ni / t_float if t_float else 0

    net_debt = equity_value_result["net_debt"]
    noa      = equity_value_result["noa_clean"]
    minority = equity_value_result["minority_interest"]

    # ── 역산 (피어 중위값 × 타겟) → Equity Value → Price ───────
    def back_solve(mult_med: float | None, target_metric: float, mult_type: str) -> dict | None:
        if mult_med is None:
            return None
        if mult_type.startswith("EV"):
            EV = mult_med * target_metric
            eq = EV - net_debt + noa - minority
            price = eq / t_float if t_float else 0
        elif mult_type == "PER":
            price = mult_med * t_eps
        else:
            price = 0
        return {"multiple_median": mult_med, "implied_price": price}

    results = {
        "EV/EBITDA": back_solve(ev_ebitda_med, t_ebitda,  "EV/EBITDA"),
        "EV/Sales":  back_solve(ev_sales_med,  t_revenue, "EV/Sales"),
        "PER":       back_solve(per_med,       t_eps,     "PER"),
    }

    # 평균 가격 (역산 4종 중 산정 가능한 것만)
    prices = [r["implied_price"] for r in results.values() if r and r["implied_price"] > 0]
    avg_price = sum(prices) / len(prices) if prices else 0

    out = {
        "as_of_date": equity_value_result["as_of_date"],
        "peers":      peer_multiples,
        "medians":    {
            "EV_EBITDA": {"median": ev_ebitda_med, "p25": ev_ebitda_p25, "p75": ev_ebitda_p75},
            "EV_Sales":  {"median": ev_sales_med,  "p25": ev_sales_p25,  "p75": ev_sales_p75},
            "PER":       {"median": per_med,       "p25": per_p25,       "p75": per_p75},
        },
        "target_metrics": {
            "ebitda":  t_ebitda,
            "revenue": t_revenue,
            "eps":     t_eps,
        },
        "results":     results,
        "avg_implied_price": avg_price,
    }

    if verbose:
        print(f"\n  피어 멀티플 중위값:")
        print(f"    EV/EBITDA = {ev_ebitda_med:.2f}× (P25 {ev_ebitda_p25:.2f}× ~ P75 {ev_ebitda_p75:.2f}×)" if ev_ebitda_med else "    EV/EBITDA = N/A")
        print(f"    EV/Sales  = {ev_sales_med:.2f}×" if ev_sales_med else "    EV/Sales = N/A")
        print(f"    PER       = {per_med:.2f}×" if per_med else "    PER = N/A")
        print(f"\n  역산 주당가치:")
        for name, r in results.items():
            if r:
                print(f"    {name:10s} ₩{r['implied_price']:,.0f}")
        if avg_price:
            print(f"  ─────────────")
            print(f"    평균       ₩{avg_price:,.0f}")

    return out
