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
from .extract_balance_sheet import extract_for_company


def compute_equity_value(dcf_result: dict, current_price: float = 0,
                         eval_date=None,
                         verbose: bool = True) -> dict:
    """EV → 주당가치 산출."""
    xbrl   = load_xbrl(t=eval_date)
    equity = load_equity(ticker=TARGET.get("ticker"), eval_date=eval_date)

    target_name = TARGET["name"]
    by_year = xbrl[target_name]["by_year"]
    latest_year = max(by_year.keys(), key=int)
    fin = by_year[latest_year]["financials"]

    # ── IBD (장부가) ─ None 안전 가드 ──────────────────────────
    IBD = fin.get("ibd") or 0

    # ── 현금성자산 (팀원 NOA 항목에서 추출) ──────────────────
    # 팀원 NOA_RULES_FINAL_V3 의 DEFAULT_NOA 에 CashAndCashEquivalents 포함
    cash = 0
    for item in fin.get("noa_items", []) or []:
        if item.get("tag") == "CashAndCashEquivalents":
            cash = item.get("val") or 0
            break

    # ── Phase 3: 연간(연말) net_debt 보존 — 멀티플 시점 정합용 ──────────
    #   본체 적정주가는 아래에서 분기 BS 로 net_debt 를 최신화하지만(최신성),
    #   멀티플 역산은 피어 배수(피어 연말 net_debt 기준)와 시점을 맞춰야
    #   사과-사과 비교가 된다 → 타깃도 연말 net_debt 를 쓰도록 별도 보존.
    annual_ibd = IBD
    annual_cash = cash
    annual_net_debt = annual_ibd - annual_cash

    # ── 최신 분기/반기 BS 로 net_debt 시점 최신화 (분기 반영) ────────────
    # BS 는 시점(as-of) 정보 → 가장 최근 정기보고서(예: 2026.03)의 IBD·현금이
    # 연말(2025.12)보다 신선. IBD·현금을 함께 교체해 equity 다리(현금 상쇄) 정합성 유지.
    bs_as_of = f"{latest_year}.12"
    bs_source = "annual"
    try:
        _meta = by_year[latest_year].get("meta", {}) or {}
        _cc = _meta.get("corp_code")
        if _cc:
            from .quarterly_financials import latest_quarter_bs
            _lq = latest_quarter_bs(_cc, int(latest_year), verbose=verbose)
            if _lq:
                IBD = _lq["ibd"]
                cash = _lq["cash"]
                bs_as_of = _lq["period"]
                bs_source = f"latest_{_lq['reprt_code']}"
                if verbose:
                    print(f"  [net_debt 최신화] 연간({latest_year}.12) → {bs_as_of} "
                          f"({_lq['kind']}): IBD=₩{IBD/1e12:.3f}조  현금=₩{cash/1e12:.3f}조")
    except Exception as _e:
        if verbose:
            print(f"  [net_debt 최신화] 스킵 ({str(_e)[:60]})")

    # ── Net Debt ────────────────────────────────────────────────
    net_debt = IBD - cash

    # ── NOA (팀원 합계 − 현금성자산 이중제거) ────────────────
    # ⚠ 이론적 한계: NOA(비영업자산)는 XBRL 재무상태표 '장부가(book value)' 기준.
    #   Damodaran 표준은 공정가치(시장가)이나 비상장투자·토지 등 공정가 데이터
    #   수집이 불가하여 장부가 사용 (보수적·과소평가 방향). nci_source 처럼
    #   noa_basis="book_value" 로 산출물에 명시해 해석 오류를 방지한다.
    noa_raw   = fin.get("noa") or 0
    noa_clean = noa_raw - cash   # 결정사항 #1: 이중차감 방지 (장부가 기준)

    # ── 비지배지분 (XBRL `ifrs-full:NoncontrollingInterests` 직접 추출) ──
    # 연결재무제표 기준 가치평가의 정합성:
    #   EV (연결 FCFF 기반) − Net Debt = 모든 자기자본 청구권 (지배 + 비지배)
    #   여기서 비지배지분 차감 → 모회사 보통주 주주만의 청구권
    #
    # 추출 우선순위:
    #   1) extract_balance_sheet (XBRL raw 직파싱) — 가장 정확
    #   2) 캐시 JSON 의 minority_interest 필드
    #   3) equity_total − equity_parent 로 산식 추정
    #   4) 위 모두 None → 0 으로 가정 (DCF/멀티플은 표시되되 nci_source="missing" 경고 기록)
    # extract_for_company 가 실제 출처(source)를 함께 반환 → 그대로 기록 (거짓 'xbrl_raw' 방지)
    _nci_data = extract_for_company(TARGET["ticker"], TARGET["name"], int(latest_year))
    minority_interest = _nci_data.get("minority_interest") if _nci_data else None
    nci_source = _nci_data.get("source", "xbrl") if (_nci_data and minority_interest is not None) else None
    if minority_interest is None:
        # 캐시 JSON 직접 조회
        cached_nci = fin.get("minority_interest")
        if cached_nci is not None:
            minority_interest = cached_nci
            nci_source = "cached_field"
        else:
            # equity_total − equity_parent 로 추정
            et = fin.get("equity_total")
            ep = fin.get("equity_parent")
            if et is not None and ep is not None:
                minority_interest = max(0, et - ep)
                nci_source = "derived_total_minus_parent"
            else:
                minority_interest = 0
                nci_source = "missing"
                if verbose:
                    print(f"  [WARN] NCI 추출 불가 — 0 으로 가정. xbrl_raw 미수집 또는 필드 부재.")

    # ── NCI 정합성 cross-check (A3) ─────────────────────────────
    #   채택된 minority_interest 를 '자본총계 − 지배지분'(독립 산식)과 대조.
    #   1% 초과 차이 → 경고(LLM/XBRL 추출 오류 의심). 두 출처가 같은 산식이면
    #   trivially 일치(독립 검증 불가)임을 source 로 함께 표기.
    nci_crosscheck = None
    _et = fin.get("equity_total"); _ep = fin.get("equity_parent")
    if _et is not None and _ep is not None:
        _derived = max(0.0, _et - _ep)
        _base = minority_interest or 0
        if _base > 0:
            _diff = abs(_derived - _base) / _base
        elif _derived == 0:
            _diff = 0.0   # Phase 6: 무NCI 단독법인(0/0) — 정상 일치(ok=True). trivial(독립검증 불가)
        else:
            _diff = 1.0   # _base=0 인데 자본총계−지배 > 0 → 추출 불일치(경고)
        nci_crosscheck = {
            "primary": _base, "primary_source": nci_source,
            "derived_total_minus_parent": _derived,
            "diff_pct": round(_diff * 100, 2) if _diff is not None else None,
            "ok": (_diff is not None and _diff < 0.01),
            "independent": nci_source != "derived_total_minus_parent",
        }
        if _diff is not None and _diff >= 0.01 and verbose:
            print(f"  [NCI cross-check] 채택 ₩{_base/1e12:.3f}조 vs "
                  f"자본총계−지배 ₩{_derived/1e12:.3f}조 (Δ{_diff*100:.1f}%) ⚠ 불일치")

    # ── EV from DCF ─ None 안전 ────────────────────────────────
    EV = dcf_result.get("EV") or 0

    # ── Equity Value ───────────────────────────────────────────
    equity_value = EV - net_debt + noa_clean - minority_interest

    # ── 주당가치 ────────────────────────────────────────────────
    common_float = equity["companies"][target_name]["common_float"]
    fair_price = equity_value / common_float if common_float > 0 else 0

    # Phase 1: 음수 equity_value 가드 — EV < (NetDebt + 비지배지분) 이면 보통주
    #   잔여청구권이 음수. 주주 유한책임상 음수 주가는 무의미하다. dcf_valid=True
    #   (FCFF Y+1 양수)여도 순부채 과대 시 발생(예: 현대차) → fair_price 무효화하고
    #   멀티플 평가로 유도. dcf_unsuitable/dcf_valid=False 와는 독립 신호.
    equity_value_valid = (common_float > 0 and equity_value > 0)
    equity_invalid_reason = None
    if not equity_value_valid:
        # Phase 9: 일반투자자 평이화 — '주주 몫이 마이너스'를 직관적으로.
        equity_invalid_reason = (
            f"주주 몫(자기자본 가치)이 마이너스 (₩{equity_value/1e12:.2f}조) — "
            f"기업가치보다 갚을 빚(순부채)이 커서 DCF 주가 산출 불가. 비교평가(멀티플) 참고"
            if common_float > 0 else "유통주식수 정보 없음")

    # ── 상승여력 ───────────────────────────────────────────────
    if current_price == 0:
        current_price = equity["companies"][target_name]["close_price"]
    upside_pct = (fair_price / current_price - 1) * 100 if current_price > 0 else 0

    if verbose:
        print(f"\n  IBD       = ₩{IBD/1e12:.3f}조")
        print(f"  현금성    = ₩{cash/1e12:.3f}조")
        print(f"  Net Debt  = IBD − 현금성 = ₩{net_debt/1e12:.3f}조")
        print(f"  NOA (원본) = ₩{noa_raw/1e12:.3f}조  →  NOA(현금성 제외) = ₩{noa_clean/1e12:.3f}조")
        print(f"  비지배지분 = ₩{minority_interest/1e12:.3f}조 (출처: {nci_source})")
        print(f"  Equity Value = EV − Net Debt + NOA − 비지배 = ₩{equity_value/1e12:.3f}조")
        print(f"  유통주식수    = {common_float:,}")
        if equity_value_valid:
            print(f"\n  ★ 적정주가 = ₩{fair_price:,.0f}/주")
            print(f"  현재 주가  = ₩{current_price:,.0f}/주")
            print(f"  상승여력   = {upside_pct:+.1f}%")
        else:
            print(f"\n  ★ 적정주가 = - (무효: {equity_invalid_reason})")
            print(f"  현재 주가  = ₩{current_price:,.0f}/주  → 멀티플 평가 참고")

    # DCF 유효성 flag 전파 (dcf_engine 에서 음수 FCFF/EV 처리)
    dcf_valid = dcf_result.get("dcf_valid", True)

    return {
        "as_of_date":         dcf_result["as_of_date"],
        "IBD":                IBD,
        "cash_equivalents":   cash,
        "net_debt":           net_debt,
        "net_debt_annual":    annual_net_debt,   # Phase 3: 연말 기준 (멀티플 역산 시점 정합)
        "annual_ibd":         annual_ibd,
        "annual_cash":        annual_cash,
        "net_debt_as_of":     bs_as_of,    # BS 시점 (분기 반영 시 2026.03 등)
        "net_debt_source":    bs_source,   # annual / latest_<reprt_code>

        "noa_raw":            noa_raw,
        "noa_clean":          noa_clean,
        "noa_basis":          "book_value",   # 장부가 기준 (공정가 데이터 미수집 — 보수적)
        "minority_interest":  minority_interest,
        "nci_source":         nci_source,
        "nci_crosscheck":     nci_crosscheck,   # A3: 자본총계−지배지분 대조
        "EV":                 EV,
        "equity_value":       equity_value,
        "common_float":       common_float,
        "fair_price":         fair_price if (dcf_valid and equity_value_valid) else None,
        "current_price":      current_price,
        "upside_pct":         upside_pct if (dcf_valid and equity_value_valid) else None,
        "dcf_valid":          dcf_valid,
        "equity_value_valid": equity_value_valid,                  # Phase 1: 음수 equity 가드
        "equity_invalid_reason": equity_invalid_reason,
        "dcf_invalid_reason": dcf_result.get("dcf_invalid_reason"),
    }
