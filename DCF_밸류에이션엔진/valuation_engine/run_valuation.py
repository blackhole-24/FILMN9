"""기업가치 평가 통합 진입점 — Phase 1~7 순차 실행.

사용:
    conda activate dart-rag
    cd C:\\Users\\Admin\\Desktop\\VAR
    python -m valuation_engine.run_valuation
    streamlit run valuation_engine/streamlit_app.py

산출물:
    valuation_engine/results/valuation_<T>.json
    → Streamlit 대시보드가 자동 fetch
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

_VAR_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_VAR_ROOT))

# ★ H-8: Windows cp949 콘솔에서도 한글·이모지 출력 가능
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from peer_beta.run_beta import run as run_beta
from .config import RESULTS_DIR, TARGET, PEERS, ALL_COMPANIES, FISCAL_YEARS, MODEL_VERSION
from .fetch_peers_financials import fetch_all
from .compute_equity import compute_all as compute_equity_all
from .wacc_engine import compute_wacc
from .dcf_engine import compute_dcf
from .equity_value import compute_equity_value
from .multiples_engine import compute_multiples
from .uncertainty_engine import run_scenarios


def run(eval_date: Optional[date] = None,
        verbose: bool = True) -> dict:
    """전 단계 순차 실행 - 실데이터 100% (임의값 금지).

    데이터 부재 시:
      - KOFIA CSV 없음 → RuntimeError
      - 사업보고서 청크 없음 → 신용등급/주식수 RAG 실패 → RuntimeError
      - XBRL 누락 → 해당 회사 제외 (피어 부족 시 RuntimeError)
    """
    eval_d = eval_date or date.today()
    if isinstance(eval_d, str):
        eval_d = datetime.fromisoformat(eval_d).date()

    if verbose:
        print("=" * 70)
        print(f"기업가치 평가 — {TARGET['name']} (T={eval_d})")
        print("=" * 70)

    # ── Phase 0: 사업보고서(연간) 본문 증분 임베딩 ─────────────────
    # 정책(사용자 결정): 정성 정보(사업의 내용)는 연 단위로만 크게 변하므로
    #   사업보고서(reprt_code 11011)만 임베딩한다. 분기/반기 본문은 임베딩하지 않음
    #   (사업유사도 RAG 한계효용 낮음 + ChromaDB 중복 누적 방지).
    #   재무 수치(분기·반기 변동)는 Phase 4-pre 의 TTM 으로 별도 최신화한다.
    # 이미 임베딩된 청크는 skip_existing 으로 즉시 통과 (최초 1회만 비용).
    try:
        if os.getenv("SKIP_REPORT_EMBED") == "1":
            raise RuntimeError("SKIP_REPORT_EMBED=1 — 종가·금리 최신화 모드(기존 임베딩 재사용, 다운로드·청크화 생략)")
        sys.path.insert(0, str(_VAR_ROOT / "XBRL"))
        from .report_detector import detect_new, mark_processed
        from .report_ingest import ingest_report
        from xbrl_financials_v4 import get_corp_code
        _cc = get_corp_code(TARGET["ticker"])
        _cc = _cc.get("corp_code") if isinstance(_cc, dict) else _cc
        _det = detect_new(TARGET["ticker"], _cc)
        # 가용 정기공시 중 '사업보고서(연간, 11011)' 최신본만 임베딩 대상
        _annuals = [r for r in _det.get("available", []) if r.get("reprt_code") == "11011"]
        _latest_annual = _annuals[0] if _annuals else None
        if _latest_annual:
            if verbose:
                print(f"\n[Phase 0] 사업보고서 임베딩 — {_latest_annual['period']} "
                      f"{_latest_annual['kind']} (분기/반기 본문은 임베딩 안 함)")
            _r = ingest_report(TARGET["ticker"], _cc, TARGET["name"],
                               _latest_annual, skip_existing=True, verbose=verbose)
            if _r.get("embedded"):
                mark_processed(TARGET["ticker"], _cc, _latest_annual, embed_done=True)
        elif verbose:
            print("\n[Phase 0] 임베딩 스킵 — 가용 사업보고서(연간) 없음")
    except Exception as e:
        if verbose:
            print(f"[Phase 0] 보고서 임베딩 스킵 (기존 청크 사용): {str(e)[:100]}")

    # ── Phase 1-A/1-B/2-A 병렬 (B-3) ────────────────────────────
    #   세 작업은 데이터 소스가 독립이라 동시 실행해도 결과 불변:
    #     · 1-A 베타  = 주가 회귀 (peers 명시 전달 → config 비의존)
    #     · 1-B XBRL  = 재무제표 (DART)
    #     · 2-A 시총E = 종가(KRX 캐시) + 주식수(RAG) — XBRL 비의존(compute_all 검증)
    #   config 는 호출 전 swap 완료 → 세 작업 모두 읽기전용 접근(race 없음).
    #   각 함수는 내부에서도 회사단위 ThreadPool 병렬(중첩) → 첫 평가(캐시 미스)
    #   시 외부 I/O 대기가 겹쳐 시간 단축. (캐시 적중 시 효과는 작음.)
    from concurrent.futures import ThreadPoolExecutor as _PhaseTPE
    # ★ peers 명시 전달 — config 동적 swap 됐는지에 의존하지 않게
    _peers_for_beta = [
        {"name": TARGET["name"], "ticker": TARGET["ticker"],
         "market": TARGET["market"], "role": "target"},
    ] + [{"name": p["name"], "ticker": p["ticker"],
          "market": p["market"], "role": "peer"} for p in PEERS]
    if verbose:
        print("\n[Phase 1-A/1-B/2-A 병렬] 베타·XBRL·시총E 동시 실행 (독립 I/O)...")
    with _PhaseTPE(max_workers=3, thread_name_prefix="phase_par") as _pex:
        _f_beta = _pex.submit(run_beta, eval_date=eval_d, peers=_peers_for_beta,
                              save_json=True, save_csv=False, verbose=False)
        _f_xbrl = _pex.submit(fetch_all, verbose=False,
                              skip_existing=True, eval_date=eval_d)
        _f_eqty = _pex.submit(compute_equity_all, eval_date=eval_d, verbose=False)
        beta = _f_beta.result()      # 예외 시 여기서 전파 (기존 순차와 동일 동작)
        _f_xbrl.result()
        _f_eqty.result()
    if verbose:
        for name, r in beta["peers"].items():
            print(f"   {name:10s} β_adj={r['beta_adjusted']:.4f}  R²={r['r_squared']:.3f}")

    # ── Phase 3: WACC ───────────────────────────────────────────
    if verbose:
        print("\n[Phase 3] Hamada Unlever/Relever + Rf + WACC...")
    # ★ Phase 1-A 에서 받은 beta 재사용 — run_beta 중복 호출 제거 (C-4)
    wacc = compute_wacc(eval_date=eval_d, beta_result=beta, verbose=verbose)

    # ── Phase 4: DCF ────────────────────────────────────────────
    # ★ 손익 TTM 자동 반영 (B 즉시 ON) — 최신 분기 공시까지 손익 최신화.
    #   감지(report_detector) → 최신 회계기간 → TTM(quarterly_financials) → DCF 전달.
    #   실패해도 graceful (ttm_data=None → 기존 연간 정상화).
    ttm_data = None
    try:
        from .report_detector import detect_new
        from .quarterly_financials import ttm_from_period
        sys.path.insert(0, str(_VAR_ROOT / "XBRL"))
        from xbrl_financials_v4 import get_corp_code
        _cc = get_corp_code(TARGET["ticker"])
        _cc = _cc.get("corp_code") if isinstance(_cc, dict) else _cc
        _det = detect_new(TARGET["ticker"], _cc)
        if _det.get("latest"):
            if verbose:
                print(f"\n[Phase 4-pre] 최신 공시 {_det['latest']['period']} "
                      f"{_det['latest']['kind']} → 손익 TTM 산출")
            ttm_data = ttm_from_period(_cc, _det["latest"]["period"], verbose=verbose)
            # C2: 8분기 가중평균 TTM 추가 (cyclical 종목 호황/바닥 평탄화)
            try:
                from .quarterly_financials import compute_ttm_8q_weighted
                _yr = int(_det["latest"]["period"].split(".")[0])
                _q  = {"03":1,"06":2,"09":3,"12":4}.get(_det["latest"]["period"].split(".")[1])
                if _q and ttm_data is not None:
                    _ttm8 = compute_ttm_8q_weighted(_cc, _yr, _q, verbose=verbose)
                    if _ttm8:
                        ttm_data["ttm8w_opm"] = _ttm8["ttm8w_opm"]
                        ttm_data["ttm8_opm"] = _ttm8["ttm8_opm"]
                        ttm_data["ttm8_n_quarters"] = _ttm8["n_quarters"]
            except Exception as _e:
                if verbose:
                    print(f"  [TTM 8Q 가중] 스킵: {str(_e)[:80]}")
            # ★ TTM 영속화 — 평가 중 산출값을 ttm_financials 테이블에 저장(자동 갱신)
            if ttm_data:
                try:
                    from valuation_engine import db as _db
                    _db.save_ttm(TARGET["ticker"], ttm_data,
                                 rcept_no=_det["latest"].get("rcept_no"))
                except Exception:
                    pass
    except Exception as e:
        if verbose:
            print(f"[Phase 4-pre] TTM 스킵 (기존 연간 사용): {str(e)[:100]}")
    if verbose:
        print("\n[Phase 4] DCF — FCFF 5년 Fade-out + TV...")
    dcf = compute_dcf(wacc, ttm_data=ttm_data, verbose=verbose)

    # ── Phase 5: Equity Value ───────────────────────────────────
    if verbose:
        print("\n[Phase 5] EV → Equity Value → 주당가치...")
    eqv = compute_equity_value(dcf, eval_date=eval_d, verbose=verbose)

    # ── Phase 5.5: 적정주가 구간 — WACC 신뢰구간(WACC_low/high)을 DCF 에 전파 ──
    #   WACC 만 EV 에 영향(net_debt·NOA·NCI·주식수는 WACC 무관) → EV 차분으로 환산.
    #   낮은 WACC → 높은 적정주가, 높은 WACC → 낮은 적정주가.
    try:
        _fp_lo, _fp_hi = _fair_price_range(wacc, dcf, eqv, ttm_data)
        eqv["fair_price_low"]  = _fp_lo
        eqv["fair_price_high"] = _fp_hi
        if verbose and _fp_lo is not None and _fp_hi is not None:
            print(f"  적정주가 구간(WACC {wacc['WACC_high']*100:.2f}~"
                  f"{wacc['WACC_low']*100:.2f}%): "
                  f"KRW {_fp_lo:,.0f} ~ {_fp_hi:,.0f}/주")
    except Exception as _e:
        eqv["fair_price_low"] = eqv["fair_price_high"] = None
        if verbose:
            print(f"  [적정주가 구간 스킵] {str(_e)[:100]}")

    # ── Phase 6: 멀티플 ─────────────────────────────────────────
    if verbose:
        print("\n[Phase 6] 멀티플 4종 역산...")
    multi = compute_multiples(eqv, eval_date=eval_d, verbose=verbose)

    # ── Phase 7: 시나리오/민감도/토네이도 ─────────────────────
    #   dcf_unsuitable(금융·지주)는 historical 이 빈 리스트라 run_scenarios 가
    #   revenue_0 = revs[-1] 에서 IndexError → 평가 전체 중단·결과 미저장.
    #   DCF 자체가 부적합하므로 DCF 기반 시나리오·토네이도는 논리적으로도 무의미
    #   → 스킵하고 빈 구조 전달 (멀티플 기반 가치만 사용). payload 는 scenarios 가
    #   빈 dict 면 루프를 돌지 않아 historical[-1] 접근도 회피된다.
    if dcf.get("dcf_unsuitable"):
        if verbose:
            print("\n[Phase 7] DCF 부적합(금융·지주) → 시나리오·토네이도 스킵 (멀티플만 사용)")
        unc = {"scenarios": {}, "sensitivity": {"matrix": []}, "tornado": []}
    else:
        if verbose:
            print("\n[Phase 7] Bear/Base/Bull + 민감도 + 토네이도...")
        unc = run_scenarios(dcf, wacc, eqv, verbose=verbose)

    # ── Phase 8: 현재가 적절성 진단 (EPV·성장프리미엄·Implied g·기대격차·안전마진) ──
    #   dcf_unsuitable 도 historical 빈 리스트라 진단 무의미 → 스킵.
    diagnostics = {}
    if dcf.get("dcf_unsuitable"):
        if verbose:
            print("\n[Phase 8] DCF 부적합 → Reverse Valuation 진단 스킵")
    else:
        if verbose:
            print("\n[Phase 8] 현재가 적절성 진단 (Reverse Valuation)...")
        try:
            from .epv_engine import compute_diagnostics
            diagnostics = compute_diagnostics(dcf, wacc, eqv, verbose=verbose)
        except Exception as e:
            if verbose:
                print(f"[Phase 8] 진단 스킵: {str(e)[:100]}")

    # ── 통합 결과 (Streamlit 포맷) ──────────────────────────────
    output = _build_streamlit_payload(eval_d, beta, wacc, dcf, eqv, multi, unc, ttm_data)
    output["valuation_diagnostics"] = diagnostics
    output["model_version"] = MODEL_VERSION   # C.2: 캐시 무효화 — 구버전 결과는 자동 재평가

    # ── Phase 1 D-1: 피어셋 신뢰도 첨부 (파일/DB/UI 일관 보존) ──
    #   peer_selector.select_peers_for_target 호출 시 모듈 변수
    #   _LAST_CONFIDENCE 에 100-점 감점 결과가 저장됨. 여기서
    #   output 에 합쳐 두면 결과 JSON · mongo · index.html 모두에
    #   동일한 값이 노출된다.
    try:
        from valuation_engine.peer_selector import get_last_peer_confidence
        _conf = get_last_peer_confidence()
        if _conf:
            output["peer_confidence"] = _conf
            if isinstance(output.get("summary"), dict):
                output["summary"]["peer_confidence_grade"] = _conf.get("grade")
                output["summary"]["peer_confidence_score"] = _conf.get("score")
            if verbose:
                _g, _s = _conf.get("grade"), _conf.get("score")
                print(f"  [피어 신뢰도] 점수 {_s}/100 등급 {_g} → output 첨부")
    except Exception as _e:
        if verbose:
            print(f"  [피어 신뢰도] 첨부 스킵: {str(_e)[:120]}")

    # ── 저장 ────────────────────────────────────────────────────
    # ★ ticker 포함 — 회사별 결과 분리 (UI 가 ticker 로 직접 조회)
    tag = eval_d.strftime("%Y%m%d")
    path = RESULTS_DIR / f"valuation_{TARGET['ticker']}_{tag}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)
    # 호환성 — 가장 최근 결과 alias (UI 가 '최근' 으로 fallback 가능)
    alias = RESULTS_DIR / f"valuation_{tag}.json"
    with alias.open("w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)

    # ★ DB 자동 적재 (파일 보존 + DB 동기화). 신규 평가가 자동으로 DB 에 담김.
    #   실패해도 파일 경로/평가 결과에 영향 없음(guarded).
    try:
        from valuation_engine import db as _db
        _tk = TARGET["ticker"]
        _db.save_beta(eval_d, beta)        # 베타도 DB 자동저장 (타 산출물과 일관)
        _db.save_wacc(_tk, eval_d, wacc)
        _db.save_dcf(_tk, eval_d, dcf)
        _db.save_equity(_tk, eval_d, eqv)
        _db.save_valuation_result(output, result_path=str(path))
        # companies 마스터 자동 적재 (평가 종목 + 피어; migrate 외 평가마다 채움)
        for _co in [TARGET, *PEERS]:
            _ctk = _co.get("ticker")
            if not _ctk:
                continue
            _db.save_company(_ctk,
                             corp_name=_co.get("name"),
                             market=_co.get("market"),
                             corp_code=_co.get("corp_code"))
        # report_registry sync — mark_processed 는 첫 XBRL 수집 때만 적재하므로
        #   캐시 skip(skip_existing) 종목이 DB 에 누락됨 → 매 평가 시 registry 전체
        #   백필(멱등 upsert)로 일관성 회복. 실패해도 파일 registry 가 원본.
        if os.getenv("SKIP_REGISTRY_BACKFILL") != "1":
          try:
            from . import report_detector as _rd
            _reg = _rd.load_registry()
            for _rtk, _node in (_reg or {}).items():
                _cc = _node.get("corp_code")
                for _period, _rec in (_node.get("reports") or {}).items():
                    _db.save_registry_entry(_rtk, _period, {**_rec, "corp_code": _cc})
          except Exception:
            pass
    except Exception as _e:
        if verbose:
            print(f"  [DB] 자동 적재 스킵: {str(_e)[:120]}")

    if verbose:
        print("\n" + "=" * 70)
        print(f"완료 - {path}")
        # dcf_valid=False (FCFF/EV 음수) 시 fair_price/upside_pct 가 None
        _fp = eqv.get("fair_price")
        _cp = eqv.get("current_price") or 0
        _up = eqv.get("upside_pct")
        if _fp is not None:
            print(f"  적정주가: KRW {_fp:,.0f}/주")
            print(f"  현재 주가: KRW {_cp:,.0f}/주")
            if _up is not None:
                print(f"  상승여력: {_up:+.1f}%")
            else:
                print(f"  상승여력: -")
        else:
            print(f"  적정주가: - (DCF 산출 불가, dcf_valid=False)")
            print(f"  현재 주가: KRW {_cp:,.0f}/주")
        print(f"  WACC: {wacc['WACC']*100:.2f}%")
        print("=" * 70)
        print("\n다음: python -m uvicorn valuation_engine.api:app --port 8011")

    return output


def _fair_price_range(wacc: dict, dcf: dict, eqv: dict,
                      ttm_data: Optional[dict]) -> tuple:
    """WACC 신뢰구간(WACC_low/high)을 DCF 에 재할인해 적정주가 구간 산출.

    EV 만 WACC 에 의존(net_debt·NOA·NCI·유통주식수는 무관) → base 대비 EV 차분을
    유통주식수로 나눠 fair_price 에 가산. base 가 dcf_invalid 면 구간도 None.

    Returns: (fair_price_low, fair_price_high)  — 산출 불가 항목은 None.
    """
    cf = eqv.get("common_float") or 0
    fp_base = eqv.get("fair_price")
    if not eqv.get("dcf_valid") or cf <= 0 or fp_base is None:
        return None, None
    ev_base = dcf.get("EV") or 0
    g_perp  = dcf.get("g_perpetual") or 0
    rf      = wacc.get("rf") or 0
    w_lo = wacc.get("WACC_low")    # 낮은 WACC → 높은 가격
    w_hi = wacc.get("WACC_high")   # 높은 WACC → 낮은 가격

    def _price_at(w):
        # 위계(g < Rf < WACC) 위반 시 산출 안 함 (TV 폭주/음수 방지)
        if not w or w <= g_perp or w <= rf:
            return None
        d = compute_dcf({**wacc, "WACC": w}, ttm_data=ttm_data,
                        verbose=False, save=False)
        ev = d.get("EV") or 0
        if ev <= 0:
            return None
        return fp_base + (ev - ev_base) / cf

    fp_high = _price_at(w_lo)
    fp_low  = _price_at(w_hi)
    # 정합 보장 — low ≤ base ≤ high (moat 플립 등 비단조 edge 방어)
    if fp_low is not None and fp_low > fp_base:
        fp_low = fp_base
    if fp_high is not None and fp_high < fp_base:
        fp_high = fp_base
    return fp_low, fp_high


def _build_streamlit_payload(eval_d, beta, wacc, dcf, eqv, multi, unc, ttm_data=None) -> dict:
    """Streamlit MOCKUP 스키마에 맞춰 통합."""
    return {
        "as_of_date": eval_d.isoformat(),
        "company": {"name": TARGET["name"], "ticker": TARGET["ticker"],
                    "market": TARGET["market"]},
        "summary": {
            "equity_value_won": eqv["equity_value"],
            "fair_price":       eqv["fair_price"],
            # 적정주가 구간 (WACC 신뢰구간 전파) — 점추정 오도 완화
            "fair_price_low":   eqv.get("fair_price_low"),
            "fair_price_high":  eqv.get("fair_price_high"),
            "current_price":    eqv["current_price"],
            "upside_pct":       eqv["upside_pct"],
            "wacc":             wacc["WACC"],
            "implied_roic":     dcf.get("implied_roic", 0),
            "beta_L_target":    wacc["beta_L_target"],
            "DE_target_pct":    wacc["DE_target_pct"],
            # 자본구조 고지 (캡 발동 시 적정주가는 '정상화 가정' 하의 값)
            "DE_own_pct":          wacc.get("DE_own_pct"),
            "DE_peer_median_pct":  wacc.get("DE_peer_median_pct"),
            "DE_cap_pct":          wacc.get("DE_cap_pct"),
            "DE_basis":            wacc.get("DE_basis"),
            "leverage_cap_applied": wacc.get("leverage_cap_applied", False),
            "leverage_disclosure":  wacc.get("leverage_disclosure"),
            "net_debt_won":     eqv["net_debt"],
            "noa_won":          eqv["noa_clean"],
            "rf":               wacc["rf"],
            "ke":               wacc["Ke"],
            "kd_aftertax":      wacc["Kd_after_tax"],
            # v3 — FCFF 음수 회사 처리 flag / v7 — 투자기 성장주 신호
            "dcf_valid":          dcf.get("dcf_valid", True),
            "dcf_fcff_y1_negative": dcf.get("dcf_fcff_y1_negative", False),
            "dcf_invalid_reason": dcf.get("dcf_invalid_reason"),
            # v3 — DCF 신뢰도 등급
            "dcf_confidence":     dcf.get("dcf_confidence", "medium"),
            "dcf_confidence_score": dcf.get("dcf_confidence_score", 3),
            "dcf_max_opm_deviation": dcf.get("dcf_max_opm_deviation", 0),
            "dcf_outlier_count":  dcf.get("dcf_outlier_count", 0),
            # A2: DCF 신뢰도 A~E 등급 (점추정 노출 차등)
            "dcf_grade":              dcf.get("dcf_grade", "B"),
            "dcf_tv_weight":          dcf.get("dcf_tv_weight"),
            "dcf_show_point_estimate": dcf.get("dcf_show_point_estimate", True),
            "dcf_grade_conditional":  dcf.get("dcf_grade_conditional", False),
            "dcf_grade_reason":       dcf.get("dcf_grade_reason"),
            # A3: NCI 정합성 cross-check
            "nci_crosscheck":         eqv.get("nci_crosscheck"),
            # A1: Terminal ROIC 시나리오 + TV 비중 (tornado 는 별도 키로 이미 노출)
            "terminal_roic_scenarios": unc.get("terminal_roic_scenarios"),
            "tv_weight":              unc.get("tv_weight"),
            # B1/B2/B3: Tier B 적용 트래킹
            "moat":                   (dcf.get("terminal_value_meta", {}) or {}).get("moat"),
            "b1_opm_converge":        (dcf.get("terminal_value_meta", {}) or {}).get("b1_opm_converge"),
            "opm_terminal_target":    (dcf.get("terminal_value_meta", {}) or {}).get("opm_terminal_target"),
            "opm_target_source":      (dcf.get("terminal_value_meta", {}) or {}).get("opm_target_source"),
            "opm_long_run_own":       (dcf.get("terminal_value_meta", {}) or {}).get("opm_long_run_own"),
            # B1+: OPM 윈도우 자동 분기 (3yr vs 8yr)
            "opm_3yr_avg":            (dcf.get("terminal_value_meta", {}) or {}).get("opm_3yr_avg"),
            "opm_8yr_avg":            (dcf.get("terminal_value_meta", {}) or {}).get("opm_8yr_avg"),
            "opm_window_used":        (dcf.get("terminal_value_meta", {}) or {}).get("opm_window_used"),
            "opm_pattern":            (dcf.get("terminal_value_meta", {}) or {}).get("opm_pattern"),
            # C1: 산업 분류
            "industry_category":      (dcf.get("terminal_value_meta", {}) or {}).get("industry_category"),
            "industry_name":          (dcf.get("terminal_value_meta", {}) or {}).get("industry_name"),
            # C3: Damodaran βU 교차검증
            "damodaran_check":        wacc.get("damodaran_check"),
            # C2: 8Q 가중 TTM OPM
            "ttm8w_opm":              ttm_data.get("ttm8w_opm") if isinstance(ttm_data, dict) else None,
            "b3_capex_split":         (dcf.get("terminal_value_meta", {}) or {}).get("b3_capex_split"),
            "incr_capital_intensity": (dcf.get("terminal_value_meta", {}) or {}).get("incr_capital_intensity"),
            "g_candidates":           (dcf.get("normalization", {}) or {}).get("g_candidates"),
            # v3 — NCI / WACC 신뢰구간 / EVA spread
            "minority_interest":  eqv.get("minority_interest", 0),
            "WACC_low":           wacc.get("WACC_low",  wacc["WACC"]),
            "WACC_high":          wacc.get("WACC_high", wacc["WACC"]),
            "eva_spread":         dcf.get("eva_spread", 0),
            "invested_capital":   dcf.get("invested_capital", 0),
        },
        # v3 — 멀티플 이격 경고
        "multiples_dispersion_warnings": multi.get("dispersion_warnings", []),
        "scenarios": {
            k: {"price": v["price"],
                "upside_pct": (v["price"]/eqv["current_price"] - 1)*100 if eqv["current_price"] else 0,
                "ev_ebitda":  v["EV"] / (dcf["historical"]["ebit"][-1] + dcf["historical"]["da"][-1])
                              if (dcf["historical"]["ebit"][-1] + dcf["historical"]["da"][-1]) else 0}
            for k, v in unc["scenarios"].items()
        },
        "dcf": {
            "labels":  [r["year"] for r in dcf["fcff_table"]] + ["TV"],
            "growth":  [r["growth"]  for r in dcf["fcff_table"]] + [dcf["g_perpetual"]],
            "revenue": [round(r["revenue"]/1e9, 0) for r in dcf["fcff_table"]] + [0],
            "ebit":    [round(r["ebit"]/1e9, 0)    for r in dcf["fcff_table"]] + [0],
            "tax":     [round(r["tax"]/1e9, 0)     for r in dcf["fcff_table"]] + [None],
            "da":      [round(r["da"]/1e9, 0)      for r in dcf["fcff_table"]] + [None],
            "capex":   [round(r["capex"]/1e9, 0)   for r in dcf["fcff_table"]] + [None],
            "dnwc":    [round(r["dnwc"]/1e9, 0)    for r in dcf["fcff_table"]] + [None],
            "fcff":    [round(r["fcff"]/1e9, 0)    for r in dcf["fcff_table"]] + [round(dcf["TV"]/1e9, 0)],
            # dcf_unsuitable(금융·지주)는 fcff_table 이 빈 리스트 → [-1] 접근 시 IndexError.
            #   TV 열의 discount_factor 는 마지막 연차 것을 재사용하나, 빈 테이블이면 None.
            "df":      [r["discount_factor"] for r in dcf["fcff_table"]]
                       + [dcf["fcff_table"][-1]["discount_factor"] if dcf["fcff_table"] else None],
            "pv":      [round(r["pv"]/1e9, 0) for r in dcf["fcff_table"]] + [round(dcf["TV_pv"]/1e9, 0)],
            "ev_total":round(dcf["EV"]/1e9, 0),
        },
        "wacc_breakdown": [
            ("Rf (국고채 10년)",  f"{wacc['rf']*100:.2f}%",  "ECOS API"),
            ("ERP",                f"{wacc['ERP']*100:.1f}%", "한공회 가이던스"),
            ("βL,target (Blume)",  f"{wacc['beta_L_target']:.3f}", "피어 4사 회귀 (winsorize)"),
            ("SRP",                f"{wacc['SRP']*100:+.2f}%", f"한공회 {wacc['SRP_tier']}"),
            ("CRP",                f"{wacc['CRP']*100:.1f}%", "POC 정책"),
            ("Ke",                 f"{wacc['Ke']*100:.2f}%",  "= Rf + βL·ERP + SRP"),
            ("Kd",                 f"{wacc['Kd']*100:.2f}%",
             f"KOFIA 무보증 5년 × {wacc['credit_rating']['rating']}"),
            ("한계세율 t",          f"{wacc['t_target']*100:.1f}%", wacc['t_target_tier']),
            ("Kd × (1−t)",         f"{wacc['Kd_after_tax']*100:.2f}%", "세후 타인자본비용"),
            ("E 비중",              f"{wacc['We']*100:.1f}%", "목표 자본구조"),
            ("D 비중",              f"{wacc['Wd']*100:.1f}%", "목표 자본구조"),
            ("WACC",               f"{wacc['WACC']*100:.2f}%", "가중평균"),
        ],
        "peers_hamada": [
            {"회사": p["name"], "βL": round(p["beta_L_adj"], 3),
             "D/E%": round(p["D_over_E"]*100, 1),
             "t%":   round(p["tax_rate"]*100, 1),
             "βU":   round(p["beta_U"], 3)}
            for p in wacc["peers_hamada"]
        ] + [{"회사":"중위값","βL":None,"D/E%": round(wacc['DE_median']*100, 1),
              "t%": None, "βU": round(wacc['beta_U_median'], 3)}],
        "multiples": [
            {"멀티플": k.replace("_","/"),
             "피어 중위": f"{multi['medians'][k.replace('/','_')]['median']:.2f}×"
                          if multi['medians'][k.replace('/','_')]['median'] else "N/A",
             "대상": "—", "역산가": int(v["implied_price"]),
             "vs 현재": round((v["implied_price"]/eqv["current_price"] - 1)*100, 1)
                        if eqv["current_price"] and v else 0,
             "피어 25~75 백분위": (
                 f"{multi['medians'][k.replace('/','_')]['p25']:.2f}× ~ "
                 f"{multi['medians'][k.replace('/','_')]['p75']:.2f}×"
                 if multi['medians'][k.replace('/','_')]['median'] else "N/A"),
             "판정": "정합"}
            for k, v in multi["results"].items() if v
        ],
        "sensitivity": {
            "wacc_axis": ["WACC −1%p","WACC (Base)","WACC +1%p"],
            "g_axis":    ["g = 1.5%","g = 2.0%","g = 2.5%"],
            "matrix":    unc["sensitivity"]["matrix"],
        },
        "tornado": [
            {"name": t["name"], "neg": round(t["neg"]), "pos": round(t["pos"])}
            for t in unc["tornado"]
        ],
        "peer_beta": [
            {"회사": name, "n": r["n_weeks_used"],
             "β_raw": round(r["beta_raw"], 4),
             "β_adj": round(r["beta_adjusted"], 4),
             "R²":    round(r["r_squared"], 3),
             "warn":  ", ".join(r["warnings"]) if r["warnings"] else "-"}
            for name, r in beta["peers"].items()
        ],
        "peer_capital_detail": _build_capital_detail(eqv, wacc, eval_d),
        "ibd_breakdown":       _build_ibd_breakdown(eval_d),
        "validation": _build_validation(wacc, dcf),
        "data_sources": [
            ("국고채 10년 (Rf)",     wacc["rf_source"]["as_of_date"], "ECOS API"),
            ("주가·시가총액",        eval_d.isoformat(), "KRX OpenAPI"),
            # Phase 7: FY 표기를 config.FISCAL_YEARS 에서 동적 생성 — 회계연도 변경 시
            #   결과 JSON·UI 출처 표기가 실제 데이터와 자동 일치(하드코딩 drift 제거).
            (f"재무제표 (FCFF용)",
             f"FY{FISCAL_YEARS[0]}~FY{FISCAL_YEARS[-1]}", "DART OpenAPI (팀원 XBRL)"),
            ("피어 자본구조 D",      f"FY{FISCAL_YEARS[-1]}", "DART OpenAPI (팀원 XBRL)"),
            ("피어 자본구조 E",      eval_d.isoformat(), "KRX × DART"),
            ("회사채 (Kd)",          wacc["kd_source"]["kofia_as_of"],
             f"KOFIA {wacc['kd_source']['bond_type']} {wacc['kd_source']['guarantee']} "
             f"{wacc['kd_source']['maturity']} × 신용등급 {wacc['credit_rating']['rating']}"),
            ("SRP 테이블",           "2025-06-10", "한공회 가이던스"),
        ],
    }


def _build_capital_detail(eqv, wacc, eval_d=None):
    """피어 4사 자본구조 상세 — E 산출 매칭 + D + D/E.

    ★ ticker·eval_date 명시 로드 — 인자 없이 호출하면 load_latest 가 디스크 최신
      파일(직전 평가 종목)을 fallback 로드해 equity·xbrl 캐시가 어긋나 KeyError 발생.
    """
    from .compute_equity import load_latest as _load_equity
    from .fetch_peers_financials import load_all as _load_xbrl
    equity_data = _load_equity(ticker=TARGET.get("ticker"), eval_date=eval_d)
    xbrl_data   = _load_xbrl(t=eval_d)

    # WACC 결과에서 피어 D/E 찾기 (피어 3사만)
    peer_de_lookup = {p["name"]: p for p in wacc["peers_hamada"]}

    out = []
    for name, info in equity_data["companies"].items():
        # IBD — equity·xbrl 캐시 불일치 시 방어 (근본은 eval_date 명시 로드로 해결)
        comp = xbrl_data.get(name)
        if not comp:
            continue
        by_year = comp["by_year"]
        latest_y = max(by_year.keys(), key=int)
        ibd = by_year[latest_y]["financials"]["ibd"]
        E = info["E_market_cap"]
        de = (ibd / E * 100) if E > 0 else 0.0
        is_target = (name == TARGET["name"])
        out.append({
            "회사":          name,
            "ticker":        info["ticker"],
            "보통주 발행":   info["common_issued"],
            "자기주식":      info["common_treasury"],
            "유통주식":      info["common_float"],
            "종가":          info["close_price"],
            "E (시총)":      E,
            "D (IBD)":       ibd,
            "D/E%":          de,
            "tag":           "TARGET(집계 제외)" if is_target else "PEER",
        })
    return out


def _build_ibd_breakdown(eval_d=None):
    """4사 IBD 6컴포넌트 분해 — 팀원 ibd_detail 그대로 (단위: 백만원)."""
    from .fetch_peers_financials import load_all as _load_xbrl
    xbrl_data = _load_xbrl(t=eval_d)
    out = []
    for name, comp in xbrl_data.items():
        latest_y = max(comp["by_year"].keys(), key=int)
        detail = comp["by_year"][latest_y]["financials"].get("ibd_detail", {}) or {}
        def _mn(v): return int((v or 0) / 1e6)   # 원 → 백만원
        out.append({
            "회사":              name,
            "단기차입금":         _mn(detail.get("단기차입금")),
            "유동성장기차입금":   _mn(detail.get("유동성장기차입금")),
            "유동리스부채":       _mn(detail.get("유동리스부채")),
            "장기차입금":         _mn(detail.get("장기차입금")),
            "비유동리스부채":     _mn(detail.get("비유동리스부채")),
            "비유동사채":         _mn(detail.get("비유동사채")),
            "합계":               _mn(sum((v or 0) for v in detail.values())),
        })
    return out


def _build_validation(wacc, dcf):
    g = dcf["g_perpetual"]
    rf = wacc["rf"]
    w  = wacc["WACC"]
    items = []
    if g < rf < w:
        items.append(("PASS", f"위계 (g<Rf<WACC): {g*100:.1f}% < {rf*100:.2f}% < {w*100:.2f}%", "ok"))
    else:
        items.append(("FAIL", f"위계 위반: g={g*100:.1f}% Rf={rf*100:.2f}% WACC={w*100:.2f}%", "warn"))
    roic = dcf.get("implied_roic", 0)
    if roic > w:
        items.append(("PASS", f"Implied ROIC > WACC: {roic*100:.1f}% > {w*100:.2f}%", "ok"))
    else:
        items.append(("주의", f"Implied ROIC < WACC: {roic*100:.1f}% < {w*100:.2f}% — TV 보수적 검토", "warn"))
    for warn in dcf.get("warnings", []):
        items.append(("주의", warn, "warn"))
    items.append(("정보", "베타: KRX 2년 주간, OLS+Blume(2/3)+winsorize±3σ", "info"))
    items.append(("정보", "피어 βU·D/E·멀티플 모두 중위값 집계", "info"))
    return items


if __name__ == "__main__":
    run(verbose=True)
