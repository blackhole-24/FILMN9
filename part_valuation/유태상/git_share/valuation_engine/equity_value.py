"""Phase 5 — EV → Equity Value → 주당가치.

8개 결정사항 #1: 현금성자산 이중차감 방지
  - Net Debt = IBD − 현금성자산
  - NOA      = 팀원 NOA 합계 − 현금성자산 (중복 제거)
  - Equity Value = EV − Net Debt + NOA − 비지배지분
  - 주당가치     = Equity Value / 보통주 유통주식수

비지배지분, 자본총계 등 팀원 코드에 없는 필드는 0 처리 (별도 추출 필요).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_VAR_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_VAR_ROOT))

from .config import TARGET
from .fetch_peers_financials import load_all as load_xbrl
from .compute_equity import load_latest as load_equity


def compute_equity_value(dcf_result: dict, current_price: float = 0,
                         verbose: bool = True) -> dict:
    """EV → 주당가치 산출."""
    xbrl   = load_xbrl()
    equity = load_equity()

    target_name = TARGET["name"]
    by_year = xbrl[target_name]["by_year"]
    latest_year = max(by_year.keys(), key=int)
    fin = by_year[latest_year]["financials"]

    # ── IBD (장부가) ───────────────────────────────────────────
    IBD = fin["ibd"]

    # ── 현금성자산 (팀원 NOA 항목에서 추출) ──────────────────
    # 팀원 NOA_RULES_FINAL_V3 의 DEFAULT_NOA 에 CashAndCashEquivalents 포함
    cash = 0
    for item in fin.get("noa_items", []):
        if item.get("tag") == "CashAndCashEquivalents":
            cash = item.get("val", 0)
            break

    # ── Net Debt ────────────────────────────────────────────────
    net_debt = IBD - cash

    # ── NOA (팀원 합계 − 현금성자산 이중제거) ────────────────
    noa_raw   = fin.get("noa", 0)
    noa_clean = noa_raw - cash   # 결정사항 #1: 이중차감 방지

    # ── 비지배지분 (팀원 코드 미추출 — POC 단계 0) ────────────
    minority_interest = 0   # TODO: 추가 추출 모듈 작성 시 보완

    # ── EV from DCF ─────────────────────────────────────────────
    EV = dcf_result["EV"]

    # ── Equity Value ───────────────────────────────────────────
    equity_value = EV - net_debt + noa_clean - minority_interest

    # ── 주당가치 ────────────────────────────────────────────────
    common_float = equity["companies"][target_name]["common_float"]
    fair_price = equity_value / common_float if common_float > 0 else 0

    # ── 상승여력 ───────────────────────────────────────────────
    if current_price == 0:
        current_price = equity["companies"][target_name]["close_price"]
    upside_pct = (fair_price / current_price - 1) * 100 if current_price > 0 else 0

    if verbose:
        print(f"\n  IBD       = ₩{IBD/1e12:.3f}조")
        print(f"  현금성    = ₩{cash/1e12:.3f}조")
        print(f"  Net Debt  = IBD − 현금성 = ₩{net_debt/1e12:.3f}조")
        print(f"  NOA (원본) = ₩{noa_raw/1e12:.3f}조  →  NOA(현금성 제외) = ₩{noa_clean/1e12:.3f}조")
        print(f"  비지배지분 = ₩{minority_interest/1e12:.3f}조 (POC: 0)")
        print(f"  Equity Value = EV − Net Debt + NOA − 비지배 = ₩{equity_value/1e12:.3f}조")
        print(f"  유통주식수    = {common_float:,}")
        print(f"\n  ★ 적정주가 = ₩{fair_price:,.0f}/주")
        print(f"  현재 주가  = ₩{current_price:,.0f}/주")
        print(f"  상승여력   = {upside_pct:+.1f}%")

    return {
        "as_of_date":         dcf_result["as_of_date"],
        "IBD":                IBD,
        "cash_equivalents":   cash,
        "net_debt":           net_debt,
        "noa_raw":            noa_raw,
        "noa_clean":          noa_clean,
        "minority_interest":  minority_interest,
        "EV":                 EV,
        "equity_value":       equity_value,
        "common_float":       common_float,
        "fair_price":         fair_price,
        "current_price":      current_price,
        "upside_pct":         upside_pct,
    }
