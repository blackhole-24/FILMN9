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
import statistics
import sys
from datetime import date
from pathlib import Path
from typing import Optional

_VAR_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_VAR_ROOT))
sys.path.insert(0, str(_VAR_ROOT / "XBRL"))

from xbrl_financials_v4 import get_marginal_tax_rate

from .config import (
    TARGET, PEERS, FISCAL_YEARS, G_PERPETUAL, DCF_DIR,
    NORMALIZATION_OUTLIER_THRESHOLD, MAX_EXPLICIT_GROWTH,
    TERMINAL_ROIC_MODE, MID_YEAR_CONVENTION, MOAT_ROIC_WACC_MARGIN,
)
from .fetch_peers_financials import load_all as load_xbrl
from .extract_balance_sheet import extract_for_company


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else 0.0


def _winsorized_median(xs: list, k: int = 1) -> Optional[float]:
    """양 끝에서 k개씩 winsorize 후 median. B2(다중 성장률 후보 robust 결합)용.

    xs: 유효 후보 리스트. n <= 2k 면 그냥 median.  표본 0이면 None.
    """
    s = sorted([x for x in xs if x is not None])
    n = len(s)
    if n == 0:
        return None
    if n <= 2 * k:
        return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2
    s = [s[k]] * k + s[k : n - k] + [s[n - k - 1]] * k
    n2 = len(s)
    return s[n2 // 2] if n2 % 2 else (s[n2 // 2 - 1] + s[n2 // 2]) / 2


def _classify_opm_pattern(opm_series: list) -> tuple[str, dict]:
    """8년 OPM 시계열을 cyclical / evolution / stable 로 분류 (B1+ OPM 윈도우 자동 분기용).

    - cyclical:  변동성 크고 양방향 진동(사이클성) → 평탄화 가치 큼 → 8년 윈도우 권장
    - evolution: 변동성 크지만 단방향 drift(사업모델 진화) → 옛 데이터 오염 위험 → 3년 권장
    - stable:    변동성 작음 → 윈도우 길이 무관 → 3년 기본 (변경 무의미)

    Returns: (pattern, metrics_dict)
    """
    n = len(opm_series)
    if n < 6:
        return "stable", {"reason": "데이터 부족(<6년)"}

    overall_range = max(opm_series) - min(opm_series)
    if overall_range < 0.05:        # 5%p 이내 변동
        return "stable", {"range_pp": overall_range * 100, "reason": "변동성 ≤5%p"}

    # 전반/후반 절반의 평균 비교 → drift 방향성
    mid = n // 2
    early = opm_series[:mid]
    late = opm_series[mid:]
    early_mean = sum(early) / len(early)
    late_mean = sum(late) / len(late)
    drift = late_mean - early_mean

    # 연속차분의 부호 변화 — 단방향성 측정
    diffs = [opm_series[i+1] - opm_series[i] for i in range(n - 1)]
    sign_changes = sum(1 for i in range(1, len(diffs))
                       if diffs[i] * diffs[i-1] < 0)
    change_ratio = (sign_changes / (len(diffs) - 1)) if len(diffs) > 1 else 0.0

    metrics = {
        "range_pp": overall_range * 100,
        "early_mean_pct": early_mean * 100,
        "late_mean_pct": late_mean * 100,
        "drift_pp": drift * 100,
        "sign_changes": sign_changes,
        "change_ratio": change_ratio,
    }
    # 단방향성 강함 (부호변화율 ≤25%) + 절대 drift ≥3%p → evolution
    # 양방향 진동(부호변화 잦음) → cyclical
    if change_ratio <= 0.25 and abs(drift) > 0.03:
        return "evolution", {
            **metrics,
            "reason": f"단방향 drift {drift*100:+.1f}%p (부호변화 {sign_changes}/{len(diffs)-1})",
        }
    return "cyclical", {
        **metrics,
        "reason": f"양방향 진동 (range {overall_range*100:.1f}%p, 부호변화 {sign_changes}/{len(diffs)-1})",
    }


def _check_outliers(values: list[float], name: str,
                    years: list | None = None) -> list[str]:
    """정상화 표본 중 1개가 평균 대비 ±50% 이상 이격이면 경고.

    years: 실제 데이터 연도 리스트 (values 와 같은 순서). 라벨 정확도용 —
           FISCAL_YEARS 전역 대신 실제 by_year 연도를 써야 데이터 결손 시
           라벨이 어긋나지 않음.
    """
    warns = []
    avg = _avg(values)
    if avg == 0:
        return warns
    for i, v in enumerate(values):
        if abs(v - avg) / abs(avg) > NORMALIZATION_OUTLIER_THRESHOLD:
            yr = years[i] if years and i < len(years) else "?"
            warns.append(f"{name}_FY{yr} 평균 대비 {(v-avg)/avg*100:+.0f}% 이격")
    return warns


def _company_roic_latest(by_year: dict, ticker: str, name: str) -> Optional[float]:
    """회사 최근연도 영업 ROIC = NOPAT / 영업투하자본(지배자본+IBD−NOA). (IC≤0·적자 시 None)"""
    y = max(by_year.keys(), key=int)
    fin = by_year[y]["financials"]
    ebit = fin.get("영업이익") or 0
    if not ebit:
        return None
    ibd = fin.get("ibd") or 0
    noa_raw = fin.get("noa") or 0
    bs = extract_for_company(ticker, name, int(y))
    eq = (bs.get("equity_parent") if bs else 0) or 0
    ic = eq + ibd - noa_raw          # 영업투하자본 (비영업자산 제외)
    if ic <= 0:
        return None
    t_r, _ = get_marginal_tax_rate(ebit)
    return ebit * (1 - t_r) / ic


def _target_roic_series(by_year: dict, years: list, ebits: list,
                        ticker: str, name: str) -> list[float]:
    """타깃 연도별 ROIC 시계열 — 경쟁우위 '지속성(신호 A)' 판정용."""
    out = []
    for i, y in enumerate(years):
        fin = by_year[y]["financials"]
        ebit = ebits[i]
        if not ebit:
            continue
        ibd = fin.get("ibd") or 0
        noa_raw = fin.get("noa") or 0
        bs = extract_for_company(ticker, name, int(y))
        eq = (bs.get("equity_parent") if bs else 0) or 0
        ic = eq + ibd - noa_raw       # 영업투하자본 (비영업자산 제외)
        if ic > 0:
            t_r, _ = get_marginal_tax_rate(ebit)
            out.append(ebit * (1 - t_r) / ic)
    return out


def _peer_opm_roic_median(xbrl: dict) -> tuple[Optional[float], Optional[float]]:
    """피어 중위 OPM(3년 평균) + 중위 ROIC(최근) — 산업 마진 수렴(#3)·경쟁우위(신호 B)용.

    피어 = 동종산업으로 선정되므로 피어 중위값은 산업평균의 실용적 대용치.
    """
    opms, roics = [], []
    for p in PEERS:
        comp = xbrl.get(p["name"])
        if not comp:
            continue
        by = comp["by_year"]
        series = []
        for y in by:
            fin = by[y]["financials"]
            rev = fin.get("매출액")
            if rev:
                series.append((fin.get("영업이익") or 0) / rev)
        if series:
            opms.append(sum(series) / len(series))
        r = _company_roic_latest(by, p["ticker"], p["name"])
        if r is not None:
            roics.append(r)
    return (statistics.median(opms) if opms else None,
            statistics.median(roics) if roics else None)


def compute_dcf(wacc_result: dict, ttm_data: Optional[dict] = None,
                verbose: bool = True, save: bool = True) -> dict:
    """타겟 DCF 산출. wacc_result 는 wacc_engine.compute_wacc() 반환.

    ttm_data: quarterly_financials.compute_ttm() 결과 (선택). 주어지면 '손익'(매출·OPM)을
              TTM(최근 4개 분기)으로 최신화 — 자본항목(CapEx·NWC·D&A)은 연간 유지(하이브리드).
    save:     결과 JSON 파일 저장 여부. 적정주가 구간(WACC_low/high 재할인) 산출 시
              base DCF JSON 을 덮어쓰지 않도록 False 로 호출.
    """
    # eval_date 명시 — load_all 이 인자 없으면 today 로 조회해, 과거 평가일 재평가 시
    #   저장된 통합 인덱스(all_financials_<T>_<eval_date>.json)를 못 찾던 버그 방지.
    #   (fetch_all 은 eval_date 로 저장하는데 load 는 today 기본 → 날짜 불일치)
    xbrl = load_xbrl(wacc_result.get("as_of_date"))
    target_by_year = xbrl[TARGET["name"]]["by_year"]

    # ── Phase 0(2026-05-28) DCF 부적합 라우팅 — 금융업·지주회사 ───────────
    #   금융업은 FCFF 공식이 정상 작동 안 함(이자수익이 영업), 지주회사는 자체 영업 없음.
    #   계산을 진행해도 결과가 신뢰 불가 → 즉시 빈 결과 반환, UI 에서 DCF 비표시.
    try:
        from .industry_classifier import is_dcf_unsuitable
        _unsuit, _unsuit_reason = is_dcf_unsuitable(
            TARGET["ticker"], name=TARGET.get("name"))
    except Exception:
        _unsuit, _unsuit_reason = False, None
    if _unsuit:
        if verbose:
            print(f"\n[DCF 부적합] {_unsuit_reason} → DCF 가치 산출 스킵, 멀티플만 사용")
        result = {
            "as_of_date":            wacc_result["as_of_date"],
            "fiscal_years":          [],
            "historical":            {"revenue": [], "ebit": [], "da": [],
                                       "capex": [], "nwc": []},
            "normalization":         {},
            "fade_out_growth":       [],
            "g_perpetual":           0,
            "fcff_table":            [],
            "TV":                    0,
            "TV_pv":                 0,
            "terminal_value_meta":   {},
            "EV":                    0,
            "implied_roic":          0,
            "invested_capital":      0,
            "eva_spread":            0,
            "nopat_normalized":      0,
            "sgr":                   None,
            "warnings":              [_unsuit_reason],
            "dcf_valid":             False,
            "dcf_invalid_reason":    _unsuit_reason,
            "dcf_unsuitable":        True,
            "dcf_unsuitable_reason": _unsuit_reason,
            "dcf_confidence":        "invalid",
            "dcf_confidence_score":  0,
            "dcf_max_opm_deviation": 0,
            "dcf_outlier_count":     0,
            "dcf_grade":             "E",
            "dcf_tv_weight":         None,
            "dcf_show_point_estimate": False,
            "dcf_grade_conditional": True,
            "dcf_grade_reason":      _unsuit_reason,
        }
        if save:
            path = DCF_DIR / f"dcf_result_{wacc_result['as_of_date'].replace('-','')}.json"
            with path.open("w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        return result

    # ── 산업 분류 (C1) — TTM·정상화 윈도우 적용 전에 미리 확정 ──
    try:
        from .industry_classifier import classify_ticker, industry_window_prior
        _ic = classify_ticker(TARGET["ticker"], name=TARGET.get("name"))
        industry_category = _ic["category"]
        industry_name = _ic["industry"]
        industry_prior = industry_window_prior(industry_category)
    except Exception:
        industry_category = "unknown"
        industry_name = ""
        industry_prior = {"window_yrs": 3, "reason": "분류 실패 — 보수적 3년"}

    years_all = sorted(target_by_year.keys(), key=int)
    # DCF 시계열 무결성 — 매출 결측(None/0) 연도 제외. 보통 해당 연도 보고서 추출이
    #   실패하면 매출·영업이익·da·nwc 가 함께 결측이므로, 연도 단위로 빼야 모든 파생
    #   시계열(revs·ebits·das·capexs·nwcs)의 인덱스가 정합한다. (예: 일부 종목의 특정
    #   연도 매출 미추출 → revs[i]-revs[i-1]·CAGR 등에서 None 산술 크래시를 원천 차단)
    years = [y for y in years_all
             if (target_by_year[y]["financials"].get("매출액") or 0) > 0]
    fins  = [target_by_year[y]["financials"] for y in years]    # 매출 유효 연도만
    if len(fins) < 2:
        raise RuntimeError(
            f"DCF 매출 시계열 부족: 유효 연도 {len(fins)}개(<2) — "
            f"DART XBRL 매출 추출 점검 필요(데이터 불완전 종목)")

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
    # 비율 시계열과 동일 필터(매출>0)를 거친 실제 연도 — 이격 경고 라벨용
    valid_years       = [y for y, r in zip(years, revs) if r]

    # ── 손익 TTM 반영 (하이브리드: 손익만 최신화, 자본비율은 연간 유지) ──
    #   최신연도 OPM → TTM OPM 으로 대체, DCF 예측 시작 매출(revenue_0) → TTM 매출.
    #   자본비율(CapEx율·NWC율·D&A율)은 연간 기준 그대로 → 분모 일관성 유지.
    revenue_0 = revs[-1]
    _ttm_note = None
    _ttm_opm_source = "annual"
    if ttm_data and ttm_data.get("ttm_revenue") and ttm_data.get("ttm_opm") is not None:
        _ttm_rev = ttm_data["ttm_revenue"]
        _ttm_opm = ttm_data["ttm_opm"]
        # C2: cyclical 산업 + 8Q 가중평균 가용 → 8Q OPM 우선 (정점/바닥 평탄화)
        #     매출은 4Q TTM 유지(신선도) — 8Q는 24개월이라 베이스로 부적합.
        if industry_category == "cyclical" and ttm_data.get("ttm8w_opm") is not None:
            _ttm_opm_4q = _ttm_opm
            _ttm_opm = ttm_data["ttm8w_opm"]
            _ttm_opm_source = f"8Q_weighted (4Q={_ttm_opm_4q*100:.2f}% → 8Q={_ttm_opm*100:.2f}%)"
        else:
            _ttm_opm_source = "4Q_TTM"
        opm_series = opm_series[:-1] + [_ttm_opm]   # 최신연도 OPM → TTM (4Q 또는 8Q)
        revenue_0 = _ttm_rev                          # 예측 시작 매출 = TTM(4Q)
        _ttm_note = (f"손익 TTM 반영({ttm_data.get('as_of_period')}, OPM={_ttm_opm_source}): "
                     f"매출 {_ttm_rev/1e12:.2f}조·OPM {_ttm_opm*100:.2f}% (자본항목 연간 유지)")

    OPM         = _avg(opm_series)
    DA_RATIO    = _avg(da_ratio_series)
    CAPEX_RATIO = _avg(capex_ratio_series)
    # NWC율은 재고 평가액 변동(예: 비철금속 LME 가격 급등)으로 연도별 출렁임이 커
    #   단순평균이 특정 연도 이상치(재고 급증)에 끌려 ΔNWC 를 과대추정한다. 성장률·
    #   피어와 동일하게 winsorized_median(k=1, 표본≥3)으로 robust 화한다.
    #   예) 고려아연 NWC율 [27.0%, 37.9%, 28.6%]: 단순평균 31.2% → winsor 28.6%.
    NWC_RATIO   = _avg(nwc_ratio_series)
    if len(nwc_ratio_series) >= 3:
        _nwc_w = _winsorized_median(nwc_ratio_series, k=1)
        if _nwc_w is not None:
            NWC_RATIO = _nwc_w

    # 검증 플래그 (B1+/C1/C2 등 윈도우 분기에서 warnings.append 사용 — 미리 초기화)
    warnings: list[str] = []

    # ── B1+ : OPM 정상화 윈도우 자동 선택 (3년 vs 8년) ───────────────────
    #   추천 1 — 이미 수집된 8년 매출·영업이익을 활용해 explicit OPM 정상화 윈도우를
    #   자동 분기:
    #     · cyclical(사이클성·양방향 진동) → 8년 평균 사용 (정점/바닥 외삽 차단)
    #     · evolution(단방향 drift·사업모델 진화) → 3년 유지 (옛 모습 오염 방지)
    #     · stable / 데이터 부족 → 3년 유지 (변경 무의미)
    #   부산물: 8년 OPM 평균은 B1 terminal target 결합(min)에도 동일 객체 재사용 → 효율.
    OPM_3yr_avg = OPM                          # 원본 3년 평균 보존
    opm_8yr_series_raw: list[float] = []
    opm_8yr_avg: Optional[float] = None
    opm_pattern: str = "stable"
    opm_pattern_meta: dict = {"reason": "미산출"}
    opm_window_used: str = "3yr"
    try:
        _meta = target_by_year[years[-1]].get("meta", {}) or {}
        _cc = _meta.get("corp_code")
        if _cc:
            from .extended_history import get_income_series
            _income_series = get_income_series(_cc, int(years[-1]), n_years=8)
            opm_8yr_series_raw = [
                (e / r) for (_y, r, e) in _income_series
                if r and e is not None and r > 0
            ]
            # 8년 평균은 ≥4년 가용 시 산출 (B1 terminal target 결합용, min_years 4 일관)
            if len(opm_8yr_series_raw) >= 4:
                opm_8yr_avg = sum(opm_8yr_series_raw) / len(opm_8yr_series_raw)
            # 패턴 분류는 ≥6년 가용 시 산출 (B1+ explicit 윈도우 분기용)
            if len(opm_8yr_series_raw) >= 6:
                opm_pattern, opm_pattern_meta = _classify_opm_pattern(opm_8yr_series_raw)
                # 산업 prior + OPM 패턴 결합 (C1):
                #   · 산업 cyclical AND OPM cyclical (양측 동의) → 8년 (확실한 사이클)
                #   · 산업 cyclical AND OPM evolution → 3년 (회사 진화가 산업 압도)
                #   · 산업 mature/growth → 3년 (산업 prior 우선)
                #   · 산업 unknown → OPM 패턴 단독 판단 (기존 B1+ 로직)
                industry_says_cyclical = (industry_category == "cyclical")
                opm_says_cyclical = (opm_pattern == "cyclical")
                opm_says_evolution = (opm_pattern == "evolution")
                gap_significant = abs(opm_8yr_avg - OPM_3yr_avg) > 0.005

                if industry_says_cyclical and opm_says_cyclical and gap_significant:
                    OPM = opm_8yr_avg
                    opm_window_used = "8yr_cyclical_both"
                    warnings.append(
                        f"OPM 윈도우 8년(C1+B1+): 산업·OPM 양측 cyclical 합의 "
                        f"({OPM_3yr_avg*100:.1f}%→{opm_8yr_avg*100:.1f}%)")
                elif industry_says_cyclical and opm_says_evolution:
                    # 산업은 cyclical인데 OPM이 진화형 → 회사 고유 진화 인정
                    opm_window_used = "3yr_evolution_over_industry"
                    warnings.append(
                        f"OPM 윈도우 3년(C1+B1+): 산업={industry_category}이나 "
                        f"OPM 단방향 진화 — 회사 고유 진화 우선")
                elif opm_says_cyclical and gap_significant and industry_category != "mature":
                    # 산업 unknown/growth + OPM cyclical → 8년 (보수적)
                    OPM = opm_8yr_avg
                    opm_window_used = "8yr_cyclical_opm_only"
                    warnings.append(
                        f"OPM 윈도우 8년(B1+): OPM 패턴 cyclical, 산업={industry_category} "
                        f"({OPM_3yr_avg*100:.1f}%→{opm_8yr_avg*100:.1f}%)")
                elif opm_says_evolution:
                    opm_window_used = "3yr_evolution"
                else:
                    opm_window_used = "3yr_stable"
    except Exception as _e:
        if verbose:
            print(f"  [B1+ OPM 윈도우] 산출 스킵: {str(_e)[:80]}")

    # TTM 노트 + 이격 경고 (warnings 리스트는 위에서 미리 초기화 — B1+/C1 사용 후 추가)
    if _ttm_note:
        warnings.append(_ttm_note)
    # Phase(정교화): OPM 이상치 경고를 별도 보관 — 신뢰도 등급의 opm_outliers 는
    #   정상 정보성 메시지("OPM 수렴/윈도우")가 아닌 '진짜 이격 이상치'만 세야 한다.
    _opm_outlier_warns = _check_outliers(opm_series, "OPM", valid_years)
    warnings += _opm_outlier_warns
    warnings += _check_outliers(da_ratio_series,    "D&A율",  valid_years)
    warnings += _check_outliers(capex_ratio_series, "CapEx율", valid_years)

    # ── 세율 (한계세율 — 미래 예측 EBIT 기준으로 매년 갱신) ──
    # 헤드라인용 reference: 최신 실적 EBIT 기준 (verbose / 정상화 / 시나리오용)
    # 실제 FCFF 계산은 아래 루프에서 매년 예측 EBIT 로 t 재산정.
    t_rate, _ = get_marginal_tax_rate(ebits[-1])

    # ── 매출 Fade-out + 지속가능성장률(SGR) 기반 성장률 상한 ─────────
    # Damodaran fundamental growth: g = ROIC × 재투자율(Reinvestment Rate)
    #   ROIC          = NOPAT / Invested Capital            (과거 실적 — 순환참조 없음)
    #   재투자율       = (CapEx − D&A + ΔNWC) / NOPAT        (3년 평균)
    #   → 경기바닥 기점 3년 CAGR 폭등(예: SK하이닉스 72%)을 펀더멘털이 정당화하는
    #     성장 수준으로 제한. 임의 상수가 아니라 기업별로 내생 도출되는 값.
    # ── B2: 다중 성장률 후보 + winsorized median (단일 CAGR 의 시작점 민감성 완화) ──
    #   후보군: ① 3년 CAGR(own) ② 최근 YoY(own) ③ 5년 CAGR(own, 확장 fetch)
    #          ④ 피어 매출성장 중위 ⑤ 명목 GDP 상한
    #   ※ 시장함의 성장률(implied_growth)은 주가에서 역산한 값이라 자기참조 위험 → 제외.
    #   winsorized median(k=1): 양 끝 극값 trim → 한 점 폭주 방지(반도체 슈퍼사이클 등).
    g_candidates: list[tuple[str, float]] = []
    # H2: 순수 연간 CAGR — 분자·분모 모두 '연간' 매출(revs[-1]/revs[0]). revenue_0 는
    #   TTM 으로 대체됐을 수 있어(손익 TTM 반영), 분자에 쓰면 TTM/연간 시점 혼합 →
    #   CAGR 왜곡. 연간 시계열만으로 산출해 혼합 제거.
    g_3yr_own = (
        (revs[-1] / revs[0]) ** (1.0 / (len(revs) - 1)) - 1
        if (len(revs) >= 2 and revs[0] and revs[-1] and revs[0] > 0 and revs[-1] > 0)
        else None
    )
    if g_3yr_own is not None and abs(g_3yr_own) < 5.0:
        g_candidates.append(("own_3yr_cagr", g_3yr_own))
    # ② 8년 매출 CAGR (구 YoY 대체 — 일반투자자 보호: 단기 1년 노이즈 대신 장기 추세).
    #   B1+ OPM 윈도우용으로 이미 가져온 8년 손익 시계열(_income_series, 매출 포함)을
    #   재사용 → 추가 수집 비용 0. 사이클 1바퀴 이상을 평탄화해 '바닥기점 단기 급등'을
    #   영구성장으로 외삽하는 과대평가를 방지(보수적). evolution 기업은 보통 낮게 나와
    #   보수 방향이라 안전. (단기-중기-장기 = 3yr·5yr·8yr 시간축 균형, own 비중 유지)
    _inc8 = locals().get("_income_series")   # B1+ 블록 try 성공 시에만 정의 → 안전 접근
    if _inc8:
        _rev8 = [r for (_y, r, _e) in _inc8 if r and r > 0]
        if len(_rev8) >= 4 and _rev8[0] > 0:
            _g8 = (_rev8[-1] / _rev8[0]) ** (1.0 / (len(_rev8) - 1)) - 1
            if abs(_g8) < 5.0:
                g_candidates.append(("own_8yr_cagr", _g8))
    # ③ 5년 CAGR — 확장 fetch (타깃 한정, 캐시)
    try:
        _meta = target_by_year[years[-1]].get("meta", {}) or {}
        _cc = _meta.get("corp_code")
        if _cc:
            from .extended_history import get_revenue_series
            _ext = get_revenue_series(_cc, int(years[-1]), n_years=5)
            _rev0, _rev_last = (_ext[0][1], _ext[-1][1])
            if _rev0 and _rev_last and _rev0 > 0 and len(_ext) >= 2:
                _g5 = (_rev_last / _rev0) ** (1.0/(len(_ext)-1)) - 1
                if abs(_g5) < 5.0:
                    g_candidates.append(("own_5yr_cagr", _g5))
    except Exception as _e:
        if verbose:
            print(f"  [B2] 5년 CAGR 스킵: {str(_e)[:80]}")
    # ④ 피어 매출성장 중위
    try:
        _peer_growths = []
        for _p in PEERS:
            _by = xbrl.get(_p["name"], {}).get("by_year", {})
            _ys = sorted(_by.keys(), key=int)
            if len(_ys) >= 2:
                _r0 = _by[_ys[0]]["financials"].get("매출액")
                _rN = _by[_ys[-1]]["financials"].get("매출액")
                if _r0 and _rN and _r0 > 0:
                    _g = (_rN/_r0) ** (1.0/(len(_ys)-1)) - 1
                    if abs(_g) < 5.0:
                        _peer_growths.append(_g)
        if _peer_growths:
            import statistics as _st
            _pg_med = _st.median(_peer_growths)
            g_candidates.append(("peer_median_cagr", _pg_med))
    except Exception:
        pass
    # ⑤ 명목 GDP 상한 (후보 목록엔 남겨 로그·참고용, 단 출발점 산정엔 미사용)
    g_candidates.append(("gdp_cap", G_PERPETUAL))

    # [현실화] 성장 출발점은 회사 '자기(own)' 매출성장 중심 — GDP·피어로 끌어내리지
    #   않는다. (GDP 는 g_perp·SGR 상한으로만, 피어는 own 전부 실패 시 폴백). 일회성
    #   급등 무한 외삽은 아래 SGR·절대상한(g_cap)이 차단하므로 출발점은 회사 실적 존중.
    _own_g = [v for n, v in g_candidates if n.startswith("own_")]
    if _own_g:
        g_3yr_raw = _winsorized_median(_own_g, k=1)
    else:
        _peer_g = [v for n, v in g_candidates if n == "peer_median_cagr"]
        g_3yr_raw = _peer_g[0] if _peer_g else G_PERPETUAL
    if g_3yr_raw is None:
        g_3yr_raw = 0.02   # 최후 폴백
    # 역성장(매출 감소) 무한 외삽 방지 — 하한 0%(정체). 영원한 감소는 비현실적이며
    #   FCFF·EV 음수로 DCF 를 붕괴시킨다(상한은 아래 SGR·절대상한이 담당).
    g_3yr_raw = max(g_3yr_raw, 0.0)
    if verbose:
        print(f"  [B2 성장률 후보] " + ", ".join(f"{n}={v*100:+.1f}%" for n, v in g_candidates))
        print(f"  [B2] winsorized median(k=1) = {g_3yr_raw*100:+.2f}%")

    # (a) Invested Capital(영업투하자본) + NOPAT (최근 실적 기준) — implied_roic 공유
    #   Damodaran 영업 IC = 지배자본 + IBD − 비영업자산(NOA).
    #   NOA(현금·투자자산·관계기업 등)를 제외해야 '영업'에 투입된 자본만 남아
    #   ROIC 가 영업수익성을 정확히 측정한다. (NOA 는 현금 포함 순액이므로 cash 도 함께 제외됨)
    bs = extract_for_company(TARGET["ticker"], TARGET["name"], year=int(years[-1]))
    equity_parent = (bs.get("equity_parent") if bs else 0) or 0
    latest_fin = target_by_year[years[-1]]["financials"]
    ibd = latest_fin.get("ibd", 0) or 0
    noa_raw = latest_fin.get("noa") or 0          # 비영업순자산 (현금 포함)
    cash = 0
    for item in latest_fin.get("noa_items", []) or []:
        if item.get("tag") == "CashAndCashEquivalents":
            cash = item.get("val", 0) or 0
            break
    invested_capital = equity_parent + ibd - noa_raw      # 영업투하자본 (비영업자산 제외)

    # ── 정상화 현재 NOPAT (단일 소스) — EPV·SGR·implied_roic 공유 ──────
    #   가정 최소화: 예측(Y+1)·단일연도 EBIT 이 아니라
    #     '정상화 OPM(3년평균) × 현재(TTM)매출 × (1−t)'.
    #   Greenwald EPV(정상화 수익력) 철학과 일치하며, ROIC 도 이 한 값에서 도출 →
    #   EPV·SGR·EVA(moat)·TV-ROIC 가 모두 동일 NOPAT/ROIC 를 쓰게 통일.
    nopat_norm   = OPM * revenue_0 * (1 - t_rate)
    roic_current = (nopat_norm / invested_capital) if invested_capital > 0 else 0.0

    # (b) 재투자율 (3년 평균) — 흑자 연도만 표본
    reinvest_samples = []
    for i in range(1, len(revs)):
        nopat_i = ebits[i] * (1 - t_rate)
        if nopat_i > 0:
            reinvest_samples.append((capexs[i] - das[i] + (nwcs[i] - nwcs[i-1])) / nopat_i)
    reinvest_rate = _avg(reinvest_samples) if reinvest_samples else None

    # (c) SGR = ROIC × 재투자율  (ROIC = 정상화 현재 ROIC, 단일 소스)
    sgr = None
    if invested_capital > 0 and nopat_norm > 0 and reinvest_rate is not None:
        sgr = roic_current * reinvest_rate

    # (d) 성장률 상한 적용 — SGR 우선, 산출 불가(적자·IC≤0) 시 절대상한 폴백
    if sgr is not None and sgr > 0:
        g_cap = sgr
        cap_basis = f"지속가능성장률(ROIC×재투자율) {sgr*100:.1f}%"
    else:
        # SGR ≤ 0 (재투자 회수 국면: CapEx<D&A) 또는 산출불가(적자·IC≤0) → 절대상한 폴백
        g_cap = MAX_EXPLICIT_GROWTH
        cap_basis = f"절대상한 {MAX_EXPLICIT_GROWTH*100:.0f}% (SGR≤0·재투자회수 또는 적자)"
    g_3yr = min(g_3yr_raw, g_cap)
    if g_3yr_raw > g_cap:
        warnings.append(
            f"매출 3년 CAGR {g_3yr_raw*100:.1f}% → {cap_basis} 로 상한 적용 "
            f"(경기회복 일회성 급등 외삽 방지)")
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

    prev_revenue = revenue_0          # TTM 또는 최신연간 (예측 시작 매출)
    # ΔNWC 일관화 (README 결정 #4): 초기 NWC 도 정상화 비율 기반으로 둬서
    #   ΔNWC_t = (rev_t − rev_{t-1}) × NWC율 로 전 구간 일관 산출.
    #   (과거: prev_nwc=실제 최근 NWC → 첫해만 정상화값과 단절되어 FCFF 점프 발생)
    prev_nwc     = revenue_0 * NWC_RATIO
    fcff_table: list[dict] = []
    pv_sum = 0.0

    n_yr = len(growth)

    # ── B1: 영구 OPM 수렴 — 비-moat 기업은 자기 OPM → 피어 중위 OPM 으로 5년 선형 수렴 ──
    #   기존: 영구 OPM = 현재 정상화 OPM 동결 → 고마진 사이클 정점이 영구 외삽되는 위험.
    #   변경: moat(지속성+피어우위+ROIC>WACC) 강함 → 유지 / 그 외 → 피어 중위로 수렴.
    #   주의: nopat_norm·ROIC 는 '현재' 정상화 값을 유지(EPV·SGR 정합), 예측 OPM 만 수렴.
    peer_opm_median, peer_roic_median = _peer_opm_roic_median(xbrl)
    roic_series = _target_roic_series(target_by_year, years, ebits,
                                      TARGET["ticker"], TARGET["name"])
    implied_roic = float(roic_current)
    # Phase 4 (M): moat 신호 B(피어우위) 공정 비교 — 타깃도 피어와 동일하게 '실제 최근
    #   EBIT 기반 ROIC'(_company_roic_latest)로 비교. implied_roic 은 정상화 OPM 기반
    #   (nopat_norm)이라 피어(실제 EBIT)와 분자 정의가 달라 비교가 불공정했다.
    target_roic_latest = _company_roic_latest(target_by_year, TARGET["ticker"], TARGET["name"])
    # Phase 4 (H1): moat 지속성 — 데이터가 FISCAL_YEARS(3년)뿐이라 표본 ≥4 는 불가하다
    #   (8년 ROIC 시계열은 연도별 IC 추출 8회 비용 → 별도 과제). 대신 ① 가용 전부(≥2)가
    #   WACC 초과 AND ② 평균 ROIC 가 WACC 를 명확히(×1.15) 초과 — 경계 초과로 인한
    #   거짓 moat 를 줄여 TV 과대평가 방지.
    _roic_avg = (sum(roic_series) / len(roic_series)) if roic_series else 0.0
    sig_persistence = (len(roic_series) >= 2 and all(r > WACC for r in roic_series)
                       and _roic_avg > WACC * MOAT_ROIC_WACC_MARGIN)
    sig_peer_adv = (peer_roic_median is not None and target_roic_latest is not None
                    and target_roic_latest > peer_roic_median)
    moat = (TERMINAL_ROIC_MODE == "auto" and sig_persistence and sig_peer_adv
            and target_roic_latest is not None and target_roic_latest > WACC)

    # 자기 long-run OPM (8년 평균) — 위 B1+ 블록에서 이미 산출 → 재사용 (중복 fetch 방지)
    opm_long_run_own = opm_8yr_avg

    # 보수적 결합 — min(자기 8년 평균, 피어 중위). 가용한 후보만 사용.
    _opm_target_candidates: list[tuple[str, float]] = []
    if opm_long_run_own is not None and 0 < opm_long_run_own < 0.5:
        _opm_target_candidates.append(("own_8yr_avg", opm_long_run_own))
    if peer_opm_median is not None and 0 < peer_opm_median < 0.5:
        _opm_target_candidates.append(("peer_median", peer_opm_median))

    if (not moat) and _opm_target_candidates:
        _peer_floor = min(v for _, v in _opm_target_candidates)
        # [현실화] 비-moat 라도 피어 중위로 '완전' 수렴(과소평가)하지 않는다. 구조적
        #   고마진(예: 삼성전기 MLCC·기판)을 절반 인정 → 자체 OPM 과 피어의 중간으로 수렴.
        #   자체 ≤ 피어(저마진)면 자체 유지(상향 없음 → 보수 유지). moat 강하면 위 else 로 자체 100%.
        if OPM > _peer_floor:
            # 고마진(자체 > 피어): 자체 OPM 절반 인정(완화) — 구조적 고마진 과소평가 방지.
            opm_terminal_target = (OPM + _peer_floor) / 2
            opm_target_source = "own_peer_mid"
        else:
            # 저마진·적자(자체 ≤ 피어): 피어로 수렴(끌어올림). 적자 OPM 을 자체 유지하면
            #   영원한 적자 외삽 → NOPAT·EV 음수 → DCF 붕괴(예: 펄어비스). 피어 앵커가
            #   '정상화 시 업계 평균 수익성 회복' 을 가정 → 적자 기업도 평가 가능.
            opm_terminal_target = _peer_floor
            opm_target_source = "peer_anchor"
        if abs(OPM - opm_terminal_target) > 1e-6:
            opm_sched = [OPM + (opm_terminal_target - OPM) * (i / (n_yr - 1)) for i in range(n_yr)]
            b1_applied = True
            _cand_str = ", ".join(f"{n}={v*100:.1f}%" for n, v in _opm_target_candidates)
            warnings.append(
                f"OPM 수렴(B1): {OPM*100:.1f}%→{opm_terminal_target*100:.1f}%({opm_target_source}) "
                f"{n_yr}년 선형, 자체·피어 중간(고마진 절반 인정), 후보={{{_cand_str}}}, moat=False")
        else:
            opm_sched = [OPM] * n_yr
            b1_applied = False
    else:
        opm_terminal_target = OPM
        opm_sched = [OPM] * n_yr
        b1_applied = False
        opm_target_source = "moat_keep" if moat else "no_anchor"

    # ── B3: CapEx 유지보수/성장 분리 — 증분자본집약도 사용 가능 시 ──
    #   capex_t = D&A_t (유지보수) + ΔRev_t × 증분자본집약도 (성장 CapEx)
    #   ΔRev 가 fade 되면 성장 CapEx 도 자연 감소 → A4 의 휴리스틱 수렴 불필요.
    incr_samples = []
    for i in range(1, len(revs)):
        dr = revs[i] - revs[i-1]
        if dr > 0:
            gc = abs(capexs[i]) - das[i]
            if gc > 0:
                incr_samples.append(gc / dr)
    incr_intensity = (sum(incr_samples) / len(incr_samples)) if incr_samples else None
    use_b3_capex = (incr_intensity is not None and 0.0 < incr_intensity < 1.0)
    if use_b3_capex:
        warnings.append(
            f"CapEx 분해(B3): 유지보수≈D&A + 성장 ΔRev×{incr_intensity*100:.1f}% "
            f"(증분자본집약도 표본 {len(incr_samples)}개)")
        capex_ratio_sched = None   # B3 우선 → A4 미사용
    else:
        # ── A4 폴백: CapEx 점진 수렴 (CapEx율>D&A율 일 때만 의미) ──
        if CAPEX_RATIO > DA_RATIO and n_yr >= 2:
            capex_ratio_sched = [
                DA_RATIO + (CAPEX_RATIO - DA_RATIO) * max(0.0, 1 - i / (n_yr - 1))
                for i in range(n_yr)
            ]
            warnings.append(
                f"CapEx율 {CAPEX_RATIO*100:.1f}%→D&A율 {DA_RATIO*100:.1f}% 로 {n_yr}년 점진 수렴 "
                f"(A4 폴백 — B3 입력 부족)")
        else:
            capex_ratio_sched = [CAPEX_RATIO] * n_yr

    for t, g_t in enumerate(growth, start=1):
        rev_t   = prev_revenue * (1 + g_t)
        ebit_t  = rev_t * opm_sched[t - 1]               # B1: 연도별 OPM (수렴 또는 유지)
        da_t    = rev_t * DA_RATIO
        if use_b3_capex:
            capex_t = da_t + max(0.0, rev_t - prev_revenue) * incr_intensity   # B3: 유지보수 + 성장
        else:
            capex_t = rev_t * capex_ratio_sched[t - 1]                          # A4 폴백
        nwc_t   = rev_t * NWC_RATIO
        dnwc    = nwc_t - prev_nwc

        # 예측 EBIT 기준 한계세율 (구간을 넘어가면 자동 갱신)
        t_rate_t, tier_t = get_marginal_tax_rate(ebit_t)

        fcff_t = ebit_t * (1 - t_rate_t) + da_t - capex_t - dnwc
        # Mid-year convention — 현금흐름 연중 균등발생 가정 (t−0.5)
        t_disc = (t - 0.5) if MID_YEAR_CONVENTION else t
        df     = 1 / (1 + WACC)**t_disc
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

    # ── Implied ROIC — EVA-style 진단 (TV의 ROIC 수렴 옵션에 사용 → TV 전 계산) ──
    # 정확 IC = 지배지분 자본 + IBD − Cash  (Damodaran/Stewart EVA® 표준)
    # invested_capital / equity_parent / ibd / cash 는 위 SGR 블록에서 이미 산출 (재사용).
    # implied_roic = 정상화 현재 ROIC (위 단일 소스 재사용) — 예측연도(Y+1) 가정 제거.
    #   EVA spread·moat 판정·TV ROIC 가 모두 이 한 값을 공유 → 진단 간 정합성 확보.
    implied_roic = float(roic_current)
    eva_spread = implied_roic - WACC    # 양수 → 가치 창출, 음수 → 파괴

    # ── ROIC_terminal 결정 (Damodaran '경쟁우위 차등') ──────────────
    #   (peer/moat 신호는 위 B1 블록에서 이미 산출 — 여기선 결과만 사용)
    if TERMINAL_ROIC_MODE == "auto":
        roic_terminal = implied_roic if moat else WACC
        roic_mode_detail = (f"auto[지속성={sig_persistence}, 피어우위={sig_peer_adv}]"
                            f" → {'sustain(초과수익 유지)' if moat else 'converge(WACC 수렴)'}")
    elif TERMINAL_ROIC_MODE == "sustain":
        roic_terminal = max(implied_roic, WACC)
        roic_mode_detail = "sustain"
    else:
        roic_terminal = WACC
        roic_mode_detail = "converge_to_wacc"

    # ── Terminal Value — 재투자=g/ROIC 일관 + mid-year ─────────────────
    #   B1: 비-moat 기업은 영구 OPM 을 피어 중위로 수렴(opm_terminal_target).
    #       moat 기업은 정상화 OPM 유지(고마진 우량기업 과소평가 방지).
    opm_terminal   = opm_terminal_target
    rev_5          = fcff_table[-1]["revenue"]
    # Phase 4 (L): 영구세율 — Y+5 단일연도 세율은 그 해 예측 EBIT 가 과표구간 경계
    #   근처면 영구가치 전체가 한 해 값에 고정돼 경계효과. 명시 5년 한계세율 평균으로
    #   평활(TV 는 장기 영속이므로 단일연도보다 기간 평균이 robust).
    t_5            = sum(r["tax_rate"] for r in fcff_table) / len(fcff_table)
    nopat_terminal = rev_5 * (1 + g_perp) * opm_terminal * (1 - t_5)
    #   (#1) 영구성장 2% 를 지원하는 재투자(g/ROIC)만 차감
    reinvest_terminal = (g_perp / roic_terminal) if roic_terminal > 0 else 0.0
    fcff_terminal  = nopat_terminal * (1 - reinvest_terminal)
    TV = fcff_terminal / (WACC - g_perp) if WACC > g_perp else 0.0
    #   (#3) Mid-year — TV 도 마지막 명시연도와 동일 (n−0.5) 시점으로 할인
    n_explicit = len(growth)
    tv_disc = (n_explicit - 0.5) if MID_YEAR_CONVENTION else n_explicit
    TV_pv   = TV / (1 + WACC)**tv_disc

    EV = pv_sum + TV_pv

    if verbose:
        fcff_str = [f"{r['fcff']/1e9:.1f}b" for r in fcff_table]; print(f"\n  FCFF: {fcff_str}")
        tax_str  = [f"{r['tax_rate']*100:.1f}%" for r in fcff_table]
        print(f"  연도별 세율: {tax_str}")
        _pr_med = f"{peer_roic_median*100:.1f}%" if peer_roic_median is not None else "N/A"
        _po_med = f"{peer_opm_median*100:.1f}%" if peer_opm_median is not None else "N/A"
        print(f"  [경쟁우위] 타깃 ROIC={implied_roic*100:.1f}% vs 피어중위 {_pr_med} | "
              f"ROIC 시계열={[f'{r*100:.0f}%' for r in roic_series]} | {roic_mode_detail}")
        print(f"  [terminal OPM] {opm_terminal*100:.1f}% (정상화 유지 — 산업수렴 철회; 피어중위 {_po_med} 참고)")
        print(f"  TV: NOPAT_T {nopat_terminal/1e12:.3f}조 × (1−재투자 {reinvest_terminal*100:.1f}%) "
              f"/ (WACC−g)  [ROIC_T={roic_terminal*100:.2f}%]")
        print(f"  TV = ₩{TV/1e12:.3f}조   PV(TV) = ₩{TV_pv/1e12:.3f}조"
              f"   (mid-year={MID_YEAR_CONVENTION})")
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
            "g_3yr_CAGR":  g_3yr,          # 상한 적용 후 (실제 예측에 사용)
            "g_3yr_CAGR_raw": g_3yr_raw,   # winsorized median (상한 적용 전)
            "g_cap_applied":  g_3yr_raw > MAX_EXPLICIT_GROWTH,
            # B2: 다중 성장률 후보 (감사·투명성)
            "g_candidates": [{"source": n, "value": v} for n, v in g_candidates],
        },
        "fade_out_growth": growth,
        "g_perpetual":   g_perp,
        "fcff_table":    fcff_table,
        "TV":            TV,
        "TV_pv":         TV_pv,
        "terminal_value_meta": {
            "nopat_terminal":     nopat_terminal,
            "roic_terminal":      roic_terminal,
            "reinvest_rate_terminal": reinvest_terminal,
            "fcff_terminal":      fcff_terminal,
            "roic_mode":          TERMINAL_ROIC_MODE,
            "roic_mode_detail":   roic_mode_detail,
            "opm_terminal":       opm_terminal,
            "peer_opm_median":    peer_opm_median,
            "peer_roic_median":   peer_roic_median,
            "sig_persistence":    sig_persistence,
            "sig_peer_advantage": sig_peer_adv,
            "moat":               moat,                       # B1: moat 판정
            "target_roic_series": roic_series,
            "mid_year_convention": MID_YEAR_CONVENTION,
            # B1: 영구 OPM 수렴 추적 (min(자기 8년, 피어 중위) 보수적 결합)
            "b1_opm_converge":    b1_applied,
            "opm_terminal_target": opm_terminal_target,
            "opm_target_source":  opm_target_source,           # own_8yr_avg / peer_median / moat_keep / no_anchor
            "opm_long_run_own":   opm_long_run_own,             # 자기 8년 평균 (없으면 None)
            "opm_sched":          opm_sched,
            # B1+: explicit OPM 윈도우 자동 분기 (3yr vs 8yr)
            "opm_3yr_avg":        OPM_3yr_avg,                 # 원본 3년 평균 (참고)
            "opm_8yr_avg":        opm_8yr_avg,                 # 8년 평균 (가용 시)
            "opm_window_used":    opm_window_used,
            "opm_pattern":        opm_pattern,
            "opm_pattern_meta":   opm_pattern_meta,
            # C1: 산업 분류 (3분류) + 윈도우 prior
            "industry_category":  industry_category,            # mature / cyclical / growth / unknown
            "industry_name":      industry_name,
            "industry_window_prior": industry_prior,           # {window_yrs, reason}
            # B3: CapEx 분해 추적
            "b3_capex_split":     use_b3_capex,
            "incr_capital_intensity": incr_intensity,
        },
        "EV":            EV,
        "implied_roic":  implied_roic,
        "invested_capital": invested_capital,
        "eva_spread":    eva_spread,
        # ── 현재가 적절성 진단(EPV 등)용 — 정상화 NOPAT(현재 수익력) + SGR ──
        "nopat_normalized": nopat_norm,   # 정상화 영업 NOPAT (TTM 반영) — 단일 소스
        "sgr":           sgr,                                  # 지속가능성장률(ROIC×재투자율), None 가능
        "warnings":      warnings,
    }

    # ── FCFF 음수 / EV 음수 회사 처리 (A안: 투자기 성장주 허용) ──────
    #   기존: FCFF Y+1 ≤ 0 이면 DCF 무효 → 투자기 성장주(증설·운전자본 확대로
    #   Y+1 FCFF 음수, EV 양수)까지 None 처리하는 과도한 보수였다. DCF 이론상
    #   EV = ΣPV(FCFF)+PV(TV) > 0 이면 가치는 유효(예: 삼성바이오 CDMO 증설·
    #   고려아연 제련 증설기). → dcf_valid 는 EV>0 단일 기준으로 완화.
    #   FCFF Y+1 음수는 '투자기' 신호로 별도 기록하고, Terminal 비중(tv_weight)이
    #   자동으로 신뢰도 등급을 낮춰(명시PV↓→TV비중↑) 조건부 표시로 유도한다.
    fcff_y1 = fcff_table[0]["fcff"] if fcff_table else 0
    dcf_valid = EV > 0
    result["dcf_valid"] = dcf_valid
    result["dcf_fcff_y1_negative"] = (fcff_y1 <= 0)
    if not dcf_valid:
        result["dcf_invalid_reason"] = f"EV = {EV/1e8:+.0f}억 (음수)"
        result["warnings"].append(
            f"DCF 결과 표시 안 함 - {result['dcf_invalid_reason']}. 멀티플 기반 참고가만 표시.")
    elif fcff_y1 <= 0:
        result["warnings"].append(
            f"FCFF Y+1 = {fcff_y1/1e8:+.0f}억 (투자기 — 성장 CapEx·운전자본 확대로 일시 음수). "
            f"가치가 명시예측 후반·영구가치에 집중되어 신뢰도 등급(Terminal 비중) 확인 권장.")

    # ── ★ DCF 신뢰도 등급 산정 (OPM 이격 + 경고 수 + FCFF 신호) ─
    opm_outliers   = len(_opm_outlier_warns)   # 진짜 이격 이상치만(정보성 'OPM 수렴/윈도우' 제외)
    total_warnings = len(result["warnings"])
    # 최대 OPM 이격율 — Phase(정교화): 분모폭발 보정. 저마진(|avg OPM|≈0) 종목은
    #   분모가 0에 가까워 상대이격이 폭발 → 과민 감점. 분모에 floor 3%p 를 둬 방지한다.
    max_opm_dev = 0.0
    _opm_avg = _avg(opm_series) if opm_series else 0.0
    if opm_series:
        _denom = max(abs(_opm_avg), 0.03)        # 분모 floor 3%p (저마진 과민 방지)
        max_opm_dev = max(abs(v - _opm_avg) / _denom for v in opm_series)
    # Phase 4 (M): OPM 부호반전(흑↔적 혼재) 감지. + Phase(정교화): 일시 적자(턴어라운드)와
    #   구조적 적자를 구분한다. '평균 흑자 & 흑자연도 과반'이면 일시 부호반전(very_low→low 완화),
    #   평균까지 적자면 구조적(very_low 유지). 정상 cyclical(전부 양수)은 미해당.
    opm_sign_flip = bool(opm_series) and (min(opm_series) < 0 < max(opm_series))
    _opm_pos_ratio = (sum(1 for o in opm_series if o > 0) / len(opm_series)) if opm_series else 0.0
    opm_transient_loss  = opm_sign_flip and (_opm_avg > 0) and (_opm_pos_ratio >= 0.5)
    opm_structural_flip = opm_sign_flip and not opm_transient_loss
    result["dcf_opm_sign_flip"] = opm_sign_flip
    result["dcf_opm_transient"] = opm_transient_loss

    if not dcf_valid:
        confidence = "invalid"
        confidence_score = 0
    elif opm_structural_flip or max_opm_dev > 5.0 or opm_outliers >= 3:
        # 구조적 부호반전(평균 적자) / 이격 500%+ / 3년 모두 outlier → 신뢰도 매우 낮음
        confidence = "very_low"
        confidence_score = 1
    elif opm_transient_loss or max_opm_dev > 2.0 or opm_outliers >= 2:
        # 일시 적자(평균 흑자) / 이격 200%+ / outlier 2년 → 낮음
        confidence = "low"
        confidence_score = 2
    elif max_opm_dev > 1.0 or total_warnings >= 2:
        confidence = "medium"
        confidence_score = 3
    else:
        confidence = "high"
        confidence_score = 4

    result["dcf_confidence"]       = confidence       # "very_low"~"high"
    result["dcf_confidence_score"] = confidence_score # 0~4 (UI 표시용)
    result["dcf_max_opm_deviation"] = max_opm_dev      # 최대 OPM 이격율 (0.0~)
    result["dcf_outlier_count"]    = opm_outliers

    # ── ★ DCF 신뢰도 A~E 등급 (A2) — 점추정 노출 차등용 ──────────────
    #   신뢰도점수(0~4) + Terminal 비중(TV/EV)을 결합해 letter grade 산정.
    #   A/B: 적정가+범위 표시 / C: 범위 강조 / D: 점추정 숨김(범위만) /
    #   E: DCF 부적합(적자·IC≤0·EV≤0 — 점추정 숨김, 사용자 클릭 시 조건부 표시).
    tv_weight = (TV_pv / EV) if (EV and EV > 0) else None
    _ORD = ["E", "D", "C", "B", "A"]               # 낮을수록 나쁨
    _score_grade = {0: "E", 1: "D", 2: "C", 3: "B", 4: "A"}[confidence_score]
    if tv_weight is None:        _tv_cap = "A"
    elif tv_weight > 0.92:       _tv_cap = "D"      # Terminal 의존 극단
    elif tv_weight > 0.85:       _tv_cap = "C"
    elif tv_weight > 0.78:       _tv_cap = "B"
    else:                        _tv_cap = "A"
    grade = min(_score_grade, _tv_cap, key=lambda g: _ORD.index(g))   # 둘 중 나쁜 등급
    _ic_impaired = (invested_capital is None) or (invested_capital <= 0)
    _roic_neg    = (implied_roic is None) or (implied_roic <= 0)
    # Phase(정교화): 자본잠식(IC≤0)·구조적 적자(ROIC≤0 & 평균 OPM≤0)는 E.
    #   ROIC≤0 이라도 평균 흑자(일시 적자/턴어라운드)면 E 대신 D 상한(점추정 숨김)으로 완화.
    if (not dcf_valid) or _ic_impaired or (_roic_neg and _opm_avg <= 0):
        grade = "E"
    elif _roic_neg:
        grade = min(grade, "D", key=lambda g: _ORD.index(g))
    _unprofitable = _roic_neg or _ic_impaired   # reason 표기용
    result["dcf_grade"]                = grade
    result["dcf_tv_weight"]            = tv_weight
    result["dcf_show_point_estimate"]  = grade in ("A", "B", "C")   # D·E 점추정 숨김
    result["dcf_grade_conditional"]    = (grade == "E")             # E 는 클릭 시 조건부 표시
    result["dcf_grade_reason"]         = (
        f"신뢰도 {confidence_score}/4"
        + (f", Terminal비중 {tv_weight*100:.0f}%" if tv_weight is not None else "")
        + (", 적자/투하자본≤0" if _unprofitable else ""))

    if not dcf_valid and verbose:
        print(f"\n[WARN] DCF 가치 숨김: {result['dcf_invalid_reason']}")

    if save:
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
