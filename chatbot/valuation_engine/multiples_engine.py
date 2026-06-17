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
from .extract_balance_sheet import (
    get_basic_eps, get_bps, extract_for_company,
)


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


def _book_value_for(by_year: dict, ticker: str, corp_name: str) -> float:
    """지배지분 자본 (XBRL `EquityAttributableToOwnersOfParent`) − 우선주 자본금.

    BPS 산출용. extract_balance_sheet 모듈에서 직접 추출.
    """
    latest_year = int(max(by_year.keys(), key=int))
    data = extract_for_company(ticker, corp_name, year=latest_year)
    if not data:
        return 0
    equity_parent     = data.get("equity_parent",     0) or 0
    preferred_capital = data.get("preferred_capital", 0) or 0
    return equity_parent - preferred_capital   # 보통주 청구권만


def _ttm_revenue_ebitda(corp_code, by_year) -> tuple:
    """Phase 3+: 멀티플용 TTM 매출·EBITDA (비교표시 누적, 최신 분기 자동 반영).

    EV/Sales·EV/EBITDA 분모를 직전 연간 대신 TTM(최근 12개월)으로 — 분자(현재 시총
    +분기 net_debt)와 시점을 맞춘다. 반기·3Q·차기 사보 공시 시 자동으로 최신 TTM.
    EBITDA = TTM영업이익 + 연간 D&A율 × TTM매출 (D&A는 안정적이라 연간율 근사).
    실패 시 연간값 폴백(graceful). Returns: (revenue, ebitda, method).
    """
    yr = max(by_year.keys(), key=int)
    fin = by_year[yr]["financials"]
    annual_rev    = fin.get("매출액") or 0
    annual_ebitda = fin.get("ebitda") or 0
    annual_da     = fin.get("da") or 0
    if not corp_code:
        return annual_rev, annual_ebitda, "annual"
    try:
        from .report_detector import list_periodic_reports
        from .quarterly_financials import compute_ttm_comparative, _MM_TO_Q
        reps = list_periodic_reports(corp_code)
        if reps:
            period = reps[0]["period"]                      # 최신 'YYYY.MM'
            ly, lq = int(period[:4]), _MM_TO_Q.get(period[5:7])
            if lq:
                ttm = compute_ttm_comparative(corp_code, ly, lq)
                if ttm and ttm.get("ttm_revenue") and ttm.get("ttm_ebit") is not None:
                    da_ratio = (annual_da / annual_rev) if annual_rev else 0.0
                    ttm_ebitda = ttm["ttm_ebit"] + da_ratio * ttm["ttm_revenue"]
                    return ttm["ttm_revenue"], ttm_ebitda, ttm["method"]
    except Exception:
        pass
    return annual_rev, annual_ebitda, "annual_fallback"


def _bps_quarterly(corp_code, ticker, name, common_float, by_year) -> "float|None":
    """Phase 3+: 분기 BPS — (분기 지배지분 자본 − 우선주자본금) / 보통주 유통주식.

    BPS 는 자본 잔액(stock)이라 PBR 분자(현재가)와 시점을 맞추려면 최신(분기말)이
    정합. net_debt 용으로 이미 조회한 분기 BS(latest_quarter_bs)에서 지배지분 자본을
    함께 추출하므로 추가 API 0. 분기 지배지분 부재 시 연간 get_bps 폴백(graceful).
    우선주자본금은 연 단위 거의 불변이라 연간값 사용.
    """
    if not common_float:
        return get_bps(ticker, name, common_float)
    try:
        yr = max(by_year.keys(), key=int)
        if corp_code:
            from .quarterly_financials import latest_quarter_bs
            _lq = latest_quarter_bs(corp_code, int(yr), verbose=False)
            if _lq and _lq.get("equity_parent"):
                from .extract_balance_sheet import extract_for_company
                _bs = extract_for_company(ticker, name, int(yr))
                pref = (_bs.get("preferred_capital") if _bs else 0) or 0
                return (_lq["equity_parent"] - pref) / common_float
    except Exception:
        pass
    return get_bps(ticker, name, common_float)   # 연간 폴백


def compute_multiples(equity_value_result: dict, eval_date=None,
                      verbose: bool = True) -> dict:
    """피어 4종 멀티플 중위값 × 타겟 지표 = 역산가.

    Phase 3+ 시점 정합 (두 층위를 구분):
      ① 회사 간 대칭: 피어·타깃에 동일 기준(같은 시점·정의) 적용 — 상대비교 보존.
      ② 비율 내 시점 정합: EV 분자(시총=현재 + net_debt=분기 + NCI)와 분모를 같은
         시점으로. EV/Sales·EV/EBITDA 분모를 연간→TTM(최근12개월)으로, PBR BPS 를
         분기말 자본(stock)으로 최신화해 ②도 확보.
      · 예외: PER EPS 는 지배주주 가중평균주식 정확성을 위해 연간 Basic 유지(②는 근사).
    """
    xbrl    = load_xbrl(t=eval_date)
    equity  = load_equity(ticker=TARGET.get("ticker"), eval_date=eval_date)

    # ── 피어별 멀티플 산출 ──────────────────────────────────────
    peer_multiples = []
    for p in PEERS:
        name = p["name"]
        ticker = p["ticker"]
        by_year = xbrl[name]["by_year"]
        E   = equity["companies"][name]["E_market_cap"] or 0
        ibd = _ibd_for(by_year) or 0
        # Net Debt: IBD − 현금성 (NOA items 에서 추출) — None 가드
        cash = 0
        for it in by_year[max(by_year.keys(), key=int)]["financials"].get("noa_items", []) or []:
            if it.get("tag") == "CashAndCashEquivalents":
                cash = it.get("val") or 0; break
        # Phase 3: 피어도 분기 net_debt 로 최신화 — 피어 시총(현재)·타깃(분기)과
        #   시점 정합 + 최신성. 실패 시 연간 폴백(graceful). latest_quarter_bs 는
        #   프로세스 메모리 캐시라 같은 평가 내 중복 조회 없음.
        _pyr = max(by_year.keys(), key=int)
        _pcc = (by_year[_pyr].get("meta", {}) or {}).get("corp_code")
        try:
            if _pcc:
                from .quarterly_financials import latest_quarter_bs
                _plq = latest_quarter_bs(_pcc, int(_pyr), verbose=False)
                if _plq:
                    ibd = _plq["ibd"]
                    cash = _plq["cash"]
        except Exception:
            pass
        net_debt = ibd - cash
        # Phase 3+: 표준 EV = 시총 + net_debt + 비지배지분(NCI). 연결 EBITDA(NCI 포함
        #   자회사 창출)와 분자-분모 정합. 타깃 역산도 minority 차감 → 양쪽 NCI 일관.
        peer_nci = by_year[_pyr]["financials"].get("minority_interest") or 0
        EV_peer  = E + net_debt + peer_nci

        # Phase 3+: 피어 EBITDA·매출도 TTM(비교표시 누적) — EV(현재·분기)와 시점 정합.
        #   헬퍼 반환 순서 = (revenue, ebitda, method).
        revenue, ebitda, _ = _ttm_revenue_ebitda(_pcc, by_year)
        common_float = equity["companies"][name]["common_float"]
        close_price  = equity["companies"][name]["close_price"]

        # PER — XBRL Basic EPS 직접 사용 (가중평균 유통주식 자동 반영)
        eps_basic = get_basic_eps(ticker, name)
        per = (close_price / eps_basic) if (eps_basic and eps_basic > 0) else None

        # PBR — Phase 3+: 분기 BPS(지배지분 자본 stock 최신화) → 현재가와 시점 정합.
        bps = _bps_quarterly(_pcc, ticker, name, common_float, by_year)
        pbr = (close_price / bps) if (bps and bps > 0) else None

        peer_multiples.append({
            "name": name,
            "EV":   EV_peer,
            "EV_EBITDA": EV_peer / ebitda if ebitda > 0 else None,
            "EV_Sales":  EV_peer / revenue if revenue > 0 else None,
            "PER":       per,
            "PBR":       pbr,
            "eps_basic": eps_basic,
            "bps":       bps,
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
    pbr_med,       pbr_p25,       pbr_p75       = stats("PBR")

    # ── 타겟 지표 ──────────────────────────────────────────────
    target_by_year = xbrl[TARGET["name"]]["by_year"]
    t_ticker  = TARGET["ticker"]
    t_name    = TARGET["name"]
    # Phase 3+: 타깃 EBITDA·매출도 TTM(비교표시 누적) — 피어 배수와 동일 시점 기준.
    _t_cc = (target_by_year[max(target_by_year.keys(), key=int)].get("meta", {}) or {}).get("corp_code")
    t_revenue, t_ebitda, _t_ttm_method = _ttm_revenue_ebitda(_t_cc, target_by_year)
    t_float   = equity["companies"][t_name]["common_float"]
    t_price   = equity["companies"][t_name]["close_price"]

    # PER 분모: XBRL Basic EPS 직접 사용 (지배주주 가중평균주식 자동 반영 — 연간 유지)
    t_eps_basic = get_basic_eps(t_ticker, t_name)
    # PBR 분모: Phase 3+ 분기 BPS(지배지분 자본 stock 최신화) → 현재가와 시점 정합.
    t_bps       = _bps_quarterly(_t_cc, t_ticker, t_name, t_float, target_by_year)

    # Phase 3: 멀티플 equity bridge 는 '현재 주주 청구권' → 최신(분기) net_debt 사용.
    #   피어 EV 도 아래 피어 루프에서 분기 net_debt 로 맞춰, 시점 정합(피어 시총=현재,
    #   net_debt=분기)과 최신성을 동시에 달성한다. (연간 통일은 최신성을 희생.)
    net_debt = equity_value_result["net_debt"]
    noa      = equity_value_result["noa_clean"]
    minority = equity_value_result["minority_interest"]

    # ── 역산 (피어 중위값 × 타겟) → Equity Value → Price ───────
    def back_solve(mult_med: float | None, target_metric: float | None,
                   mult_type: str) -> dict | None:
        # Phase 1: 음수 차단 — ① 타깃 지표 ≤0(적자 EPS·음수 BPS),
        #   ② 피어 중위 멀티플 ≤0(다수 피어 적자로 PER 중위 음수) 모두 무의미.
        if (mult_med is None or target_metric is None
                or target_metric <= 0 or mult_med <= 0):
            return None
        if mult_type.startswith("EV"):
            EV = mult_med * target_metric
            eq = EV - net_debt + noa - minority
            price = eq / t_float if t_float else 0
        elif mult_type == "PER":
            price = mult_med * target_metric    # target_metric = EPS
        elif mult_type == "PBR":
            price = mult_med * target_metric    # target_metric = BPS
        else:
            price = 0
        # Phase 1: EV 계열은 eq = EV−netdebt+noa−minority 가 음수일 수 있음 →
        #   역산 주가 ≤0 이면 무의미 (보통주 잔여청구권 음수) → None.
        if price <= 0:
            return None
        return {"multiple_median": mult_med, "implied_price": price}

    results = {
        "EV/EBITDA": back_solve(ev_ebitda_med, t_ebitda,     "EV/EBITDA"),
        "EV/Sales":  back_solve(ev_sales_med,  t_revenue,    "EV/Sales"),
        "PER":       back_solve(per_med,       t_eps_basic,  "PER"),
        "PBR":       back_solve(pbr_med,       t_bps,        "PBR"),
    }

    # ── 이격 경고 (타깃 시가 멀티플 vs 피어 P25~P75) ───────────
    # 타깃 현재 시가 기준 멀티플 계산 후 피어 백분위 범위 밖이면 경고
    # Phase 3: 이격 경고도 피어(분기 net_debt)와 시점 일치 — 분기 net_debt 사용
    #   (equity_value_result 의 IBD·cash_equivalents 는 분기 갱신값).
    # Phase 3+: 피어 EV 에 NCI 포함했으므로 타깃 EV 도 NCI 포함(표준 EV 정합).
    target_ev = (equity["companies"][t_name]["E_market_cap"]
                 + (equity_value_result["IBD"] - equity_value_result["cash_equivalents"])
                 + (equity_value_result.get("minority_interest") or 0))
    t_multiples = {
        "EV_EBITDA": target_ev / t_ebitda if t_ebitda > 0 else None,
        "EV_Sales":  target_ev / t_revenue if t_revenue > 0 else None,
        "PER":       t_price / t_eps_basic if (t_eps_basic and t_eps_basic > 0) else None,
        "PBR":       t_price / t_bps if (t_bps and t_bps > 0) else None,
    }
    dispersion_warnings = []
    pct_ranges = {
        "EV_EBITDA": (ev_ebitda_p25, ev_ebitda_p75),
        "EV_Sales":  (ev_sales_p25,  ev_sales_p75),
        "PER":       (per_p25,       per_p75),
        "PBR":       (pbr_p25,       pbr_p75),
    }
    for key, (p25, p75) in pct_ranges.items():
        tm = t_multiples.get(key)
        if tm is None or p25 is None or p75 is None:
            continue
        median_val = {
            "EV_EBITDA": ev_ebitda_med, "EV_Sales": ev_sales_med,
            "PER": per_med, "PBR": pbr_med,
        }[key]
        if tm < p25:
            dispersion_warnings.append({
                "multiple":     key,
                "target_value": float(tm),
                "peer_median":  float(median_val) if median_val else 0.0,
                "peer_p25":     float(p25),
                "peer_p75":     float(p75),
                "zone":         "동종 하위 25% 미만 — 동종 대비 싼 편(상대적 저평가)",
            })
        elif tm > p75:
            dispersion_warnings.append({
                "multiple":     key,
                "target_value": float(tm),
                "peer_median":  float(median_val) if median_val else 0.0,
                "peer_p25":     float(p25),
                "peer_p75":     float(p75),
                "zone":         "동종 상위 25% 초과 — 동종 대비 비싼 편(상대적 고평가)",
            })

    # ── 종합 멀티플 가치 ──────────────────────────────────────────
    # 단순평균 대신 '중위값' 채택 — 적자기업 PER·일회성 PBR 등 이상 멀티플의
    # 영향을 자동 배제(robust). 대표 멀티플은 EV/EBITDA(자본구조·감가상각정책
    # 중립이라 비교가능성 최고 — CFA·Damodaran 공통 권고)로 별도 표기.
    prices = [r["implied_price"] for r in results.values() if r and r["implied_price"] > 0]
    avg_price    = sum(prices) / len(prices) if prices else 0          # 호환 유지
    median_price = float(np.median(prices)) if prices else 0            # ★ 종합 대표가
    ev_ebitda_price = (results["EV/EBITDA"]["implied_price"]
                       if results.get("EV/EBITDA") else None)           # 대표 단일 멀티플

    out = {
        "as_of_date": equity_value_result["as_of_date"],
        "peers":      peer_multiples,
        "medians":    {
            "EV_EBITDA": {"median": ev_ebitda_med, "p25": ev_ebitda_p25, "p75": ev_ebitda_p75},
            "EV_Sales":  {"median": ev_sales_med,  "p25": ev_sales_p25,  "p75": ev_sales_p75},
            "PER":       {"median": per_med,       "p25": per_p25,       "p75": per_p75},
            "PBR":       {"median": pbr_med,       "p25": pbr_p25,       "p75": pbr_p75},
        },
        "target_metrics": {
            "ebitda":     t_ebitda,
            "revenue":    t_revenue,
            "eps_basic":  t_eps_basic,
            "bps":        t_bps,
        },
        "target_current_multiples": t_multiples,
        "results":     results,
        "avg_implied_price":      avg_price,         # [호환] 4종 단순평균
        "median_implied_price":   median_price,      # ★ 종합 대표가 (중위값, robust)
        "ev_ebitda_implied_price": ev_ebitda_price,  # 대표 단일 멀티플 (자본구조 중립)
        "representative_multiple": "EV/EBITDA",
        "dispersion_warnings": dispersion_warnings,
    }

    if verbose:
        print(f"\n  피어 멀티플 중위값 (P25 ~ P75):")
        print(f"    EV/EBITDA = {ev_ebitda_med:.2f}× ({ev_ebitda_p25:.2f} ~ {ev_ebitda_p75:.2f})" if ev_ebitda_med else "    EV/EBITDA = N/A")
        print(f"    EV/Sales  = {ev_sales_med:.2f}× ({ev_sales_p25:.2f} ~ {ev_sales_p75:.2f})" if ev_sales_med else "    EV/Sales  = N/A")
        print(f"    PER       = {per_med:.2f}× ({per_p25:.2f} ~ {per_p75:.2f})" if per_med else "    PER       = N/A")
        print(f"    PBR       = {pbr_med:.2f}× ({pbr_p25:.2f} ~ {pbr_p75:.2f})" if pbr_med else "    PBR       = N/A")

        print(f"\n  타깃 (현 시가 기준) 멀티플:")
        for key, val in t_multiples.items():
            print(f"    {key:10s} {val:.2f}×" if val is not None else f"    {key:10s} N/A")

        if dispersion_warnings:
            print(f"\n  ⚠ 이격 경고:")
            for w in dispersion_warnings:
                print(f"    - {w}")

        print(f"\n  역산 주당가치:")
        for name, r in results.items():
            if r:
                star = " ★대표(자본구조 중립)" if name == "EV/EBITDA" else ""
                print(f"    {name:10s} ₩{r['implied_price']:,.0f}{star}")
        if median_price:
            print(f"  ─────────────")
            print(f"    종합(중위값) ₩{median_price:,.0f}   [참고 평균 ₩{avg_price:,.0f}]")

    return out
