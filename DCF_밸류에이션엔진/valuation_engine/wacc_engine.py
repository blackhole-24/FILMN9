"""Phase 3-E — WACC 산출.

흐름:
  1. 피어별 Hamada Unlever  βU_i = βL_i / [1 + (1-t_i)·D_i/E_i]
  2. 피어 βU, D/E 중위값 (Median, 설계서 v4 §1.9, §1.10)
  3. 타겟 Hamada Relever    βL_target = βU_med × [1 + (1-t_target)·D/E_med]
  4. Ke = Rf + βL_target × ERP + SRP + CRP
  5. Kd_after_tax = Kd × (1 − t_target)
  6. WACC = E/(D+E)·Ke + D/(D+E)·Kd_after_tax  (가중치 = 타겟 목표자본구조 = 중위값)

8개 결정사항 반영:
  - 피어 βU·D/E 집계: 중위값
  - SRP: 시총 자동 매칭
  - 세율: max(유효세율, 한계세율) 보수적
  - Kd: 사업보고서 RAG 신용등급 × KOFIA 5년 무보증 회사채 (동적)
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from typing import Optional

import numpy as np

_VAR_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_VAR_ROOT))
sys.path.insert(0, str(_VAR_ROOT / "XBRL"))

from peer_beta.run_beta import run as run_beta
from xbrl_financials_v4 import get_marginal_tax_rate  # 팀원 함수 그대로

from .config import (
    ALL_COMPANIES, PEERS, TARGET, ERP, CRP, FISCAL_YEARS,
    WACC_DIR, match_srp,
)
from .compute_equity import load_latest as load_equity
from .fetch_peers_financials import load_all as load_xbrl
from .ecos_client import fetch_rf
from .kd_loader import get_kd_by_rating
from .fetch_credit_rating import fetch_credit_rating_via_rag
from .cycle_indicator import compute_industry_cycle


# ── WACC 신뢰구간 산출용 상수 ──────────────────────────────────────
ERP_LOW  = 0.07   # 한공회 가이던스 하단
ERP_HIGH = 0.09   # 한공회 가이던스 상단


def _tax_rate_for_company(by_year: dict) -> tuple[float, str]:
    """한계세율(marginal tax rate) 반환 — (세율, 과표구간 라벨).

    설계 의도는 max(유효세율, 한계세율)이나 현재는 한계세율만 사용한다
    (유효세율 추출 미구현 — 향후 max 결합 예정). 한계세율 ≥ 유효세율이
    일반적이므로 세후 자본비용을 과소평가하지 않는 보수적 방향이다.

    [세율 축 정합 — Phase 2] WACC 는 '현재 시점' 자본비용이라 최신연도 1개
    한계세율을 쓰고, DCF FCFF·시나리오는 '미래 예측'이라 연도별 EBIT 한계세율을
    쓴다(uncertainty_engine 도 동일 정합). 이는 불일치가 아니라 시점·목적이
    다른 의도된 차이다.
    """
    # Phase 1: 빈 by_year 가드 — XBRL 시계열 부재 시 list(...)[0] IndexError 방지.
    #   영업이익 0(최저 한계세율 구간)으로 폴백 (실데이터 부재 — 보수적 처리).
    if not by_year:
        return get_marginal_tax_rate(0)
    keys = list(by_year.keys())
    latest_year = max(keys, key=int) if isinstance(keys[0], str) else max(keys)
    fin = by_year[latest_year]["financials"]
    ebit_won = fin.get("영업이익") or 0
    t_marginal, tier = get_marginal_tax_rate(ebit_won)
    # TODO: 유효세율 추가 시 max(t_marginal, t_effective)
    return t_marginal, tier


# ── 피어 βU 집계 상수 (사용자 제안: median → 이상치제외+유사도가중평균+Damodaran혼합) ──
_BETA_SHRINK_K      = 2.0    # Vasicek shrinkage: 피어가중 w = n/(n+K). 표본 클수록 피어↑
_BETA_OUTLIER_MAD_K = 3.0    # MAD 이상치 임계 (표본 ≥4): |βU−med| > K·MAD 제외
_BETA_DMD_RATIO_HI  = 2.5    # 표본 3사: Damodaran βU 대비 상한 배수 초과 시 이상치
_BETA_DMD_RATIO_LO  = 0.4    # 표본 3사: Damodaran βU 대비 하한 배수 미만 시 이상치
_BETA_GAP_FULL      = 0.6    # gap-aware 혼합: |피어βU−Damodaran| 이 값 이상이면 Damodaran 가중 0
                             #   (Damodaran 가이드라인 0.3 의 2배 — 산업매핑 부정확/정의차 왜곡 회피)
_BETA_DE_EXTREME    = 3.0    # D/E 극단 가드(선행): D/E>300% 피어는 과부채로 Hamada unlever 가
                             #   βU 를 과소 왜곡(예: 대창 D/E 445%→βU 0.18) → 제외(Damodaran 비의존)


def _reject_beta_outliers(peers: list, dmd_bu: Optional[float]) -> tuple:
    """βU 이상치 피어 제외. βU=영업위험이므로 같은 산업 피어는 수렴해야 정상 —
    크게 벗어난 피어는 표본부족·일시변동 노이즈로 보고 제외한다.
      · 표본 ≥4: MAD 기반(robust). |βU−median| > K·MAD 제외.
      · 표본 3 + Damodaran 가용: 산업 βU 대비 과도 이탈(배수)만 보수적 제외.
      · 표본 <3: 제외 안 함(표본 보호). 제외 후 2사 미만이면 원복.
    반환: (kept, excluded)
    """
    excluded = []
    # (0) D/E 극단 가드 (선행, Damodaran 비의존): 과부채(D/E>임계) 피어는 Hamada unlever
    #     가 βU 를 과소 왜곡한다(대창 D/E 445%→βU 0.18). 최소 2사 보장 시에만 제외.
    de_ok = [p for p in peers if abs(p.get("D_over_E") or 0.0) <= _BETA_DE_EXTREME]
    if 2 <= len(de_ok) < len(peers):
        excluded += [p for p in peers if p not in de_ok]
        peers = de_ok
    n = len(peers)
    if n < 3:
        return peers, excluded
    bus = [p["beta_U"] for p in peers]
    med = float(np.median(bus))
    if n >= 4:
        mad = float(np.median([abs(b - med) for b in bus]))
        if mad <= 0:
            return peers, excluded
        kept = [p for p in peers if abs(p["beta_U"] - med) <= _BETA_OUTLIER_MAD_K * mad]
    elif dmd_bu and dmd_bu > 0:
        kept = [p for p in peers
                if _BETA_DMD_RATIO_LO <= (p["beta_U"] / dmd_bu) <= _BETA_DMD_RATIO_HI]
    else:
        return peers, excluded
    if len(kept) < 2:
        return peers, excluded     # 과도 제외 방지(최소 표본 보장)
    excluded += [p for p in peers if p not in kept]
    return kept, excluded


def _blend_peer_bu(valid_peers: list, dmd_bu: Optional[float]) -> dict:
    """피어 βU 집계: (1) 이상치 제외 → (2) 사업유사도 가중평균 → (3) Damodaran 혼합.
      · 유사도(score) 전원 가용 시 가중평균(βU=영업위험 → 영업 유사 피어 가중↑),
        하나라도 없으면 median 폴백(이상치 robust).
      · Damodaran 산업 βU 가용 시 Vasicek shrinkage 로 혼합:
        βU_final = w·βU_peer + (1−w)·βU_dmd,  w = n/(n+K) (표본 클수록 피어↑).
    """
    kept, excluded = _reject_beta_outliers(valid_peers, dmd_bu)
    sims = [p.get("sim") for p in kept]
    if sims and all(s is not None and s > 0 for s in sims):
        _wsum = sum(sims)
        bU_peer = sum(p["sim"] * p["beta_U"] for p in kept) / _wsum
        agg = "similarity_weighted"
    else:
        bU_peer = float(np.median([p["beta_U"] for p in kept]))
        agg = "median_fallback"
    n = len(kept)
    if dmd_bu and dmd_bu > 0:
        # Vasicek shrinkage(표본 클수록 피어↑) × gap-aware(피어와 Damodaran 이 멀수록
        #   Damodaran 신뢰↓ → 가중↓). βU=영업위험이므로 영업 유사 피어가 더 적합하고,
        #   Damodaran 산업매핑 부정확·산업정의 차이를 gap 으로 감지해 왜곡을 막는다.
        gap = abs(bU_peer - dmd_bu)
        w_dmd_base = _BETA_SHRINK_K / (n + _BETA_SHRINK_K)
        gap_factor = max(0.0, 1.0 - gap / _BETA_GAP_FULL)
        w_dmd = w_dmd_base * gap_factor
        w = 1.0 - w_dmd
        bU_final = w * bU_peer + w_dmd * dmd_bu
        blend = "damodaran_blended" if w_dmd > 0.01 else "peer_only(gap_large)"
    else:
        w = 1.0
        bU_final = bU_peer
        blend = "peer_only"
    return {
        "bU_final": bU_final, "bU_peer": bU_peer, "weight_peer": w,
        "n_kept": n, "excluded": [p["name"] for p in excluded],
        "agg_method": agg, "blend_method": blend,
    }


def compute_wacc(eval_date: Optional[date] = None,
                 beta_result: Optional[dict] = None,
                 verbose: bool = True) -> dict:
    """WACC 통합 산출. peer_beta + XBRL + Equity + ECOS 결합.

    실데이터만 사용 - 신용등급은 사업보고서 RAG 추출 (OpenAI 필수).
    추출 실패 시 RuntimeError (임의값 절대 사용 안 함).

    Args:
        beta_result: 이미 호출된 run_beta 결과. 명시 시 중복 호출 방지 (성능).
    """
    eval_d = date.today() if eval_date is None else eval_date
    if isinstance(eval_d, str):
        from datetime import datetime as _dt
        eval_d = _dt.fromisoformat(eval_d).date()

    if verbose:
        print(f"[T={eval_d}] WACC 산출 시작\n")

    # ── 1. 입력 데이터 로드 ─ ticker+eval_date 명시 (stale 방지) ─
    # ★ beta_result 가 인자로 주어지면 중복 호출 방지 (성능 — run_valuation 에서 사용)
    if beta_result is None:
        beta_result = run_beta(eval_date=eval_d, save_json=False, save_csv=False, verbose=False)
    xbrl        = load_xbrl(t=eval_d)
    equity_data = load_equity(ticker=TARGET.get("ticker"), eval_date=eval_d)

    # ── 2. 피어별 Hamada Unlever ───────────────────────────────
    peers_only = PEERS  # 타겟(아모레) 제외
    peer_betas: list[dict] = []

    for p in peers_only:
        name = p["name"]
        bL_adj = beta_result["peers"][name]["beta_adjusted"]

        # D (IBD) = 팀원 XBRL
        ibd = xbrl[name]["by_year"][str(max(xbrl[name]["by_year"].keys()))]["financials"]["ibd"]
        # E = compute_equity
        E   = equity_data["companies"][name]["E_market_cap"]
        de  = ibd / E if E > 0 else 0.0
        # t_i = 한계세율 (피어 i의 EBIT 기준)
        t_i, tier = _tax_rate_for_company(xbrl[name]["by_year"])

        bU = bL_adj / (1 + (1 - t_i) * de)

        peer_betas.append({
            "name": name,
            "beta_L_adj": bL_adj,
            "D": ibd, "E": E,
            "D_over_E": de,
            "tax_rate": t_i, "tax_tier": tier,
            "beta_U": bU,
            "sim": p.get("score"),     # 사업유사도 [0,1] — βU 가중평균용 (없으면 median 폴백)
        })
        if verbose:
            print(f"  [{name}]  βL={bL_adj:.4f}  D/E={de*100:.1f}%  t={t_i*100:.1f}%  → βU={bU:.4f}")

    # ── 3. βU 집계 (이상치 제외 → 유사도 가중평균 → Damodaran 혼합) ──────────
    #   기존: 단순 피어 βU 중위값 → 표본 3사면 가운데 1사가 좌우하고 이상치·표본부족에
    #   취약. 개선(사용자 제안): (a) βU 이상치 피어 제외(MAD≥4표본 / Damodaran 대비
    #   배수, 표본 3) (b) 사업유사도 가중평균(βU=영업위험 → 영업 유사 피어 가중↑;
    #   score 없으면 median) (c) Damodaran 산업 βU 와 Vasicek shrinkage 혼합
    #   (w=n/(n+K), 표본 클수록 피어↑). de_median 은 cap 산정용이라 robust median 유지.
    _valid = [p for p in peer_betas
              if np.isfinite(p["beta_U"]) and np.isfinite(p["D_over_E"])]
    if not _valid:
        raise RuntimeError(
            "WACC: 유효한 피어 βU 없음 (전 피어 회귀 표본 부족/NaN). "
            "피어 상장기간·주가 데이터 확인 필요.")
    if verbose and len(_valid) < len(peer_betas):
        print(f"  [WACC] NaN/inf 피어 {len(peer_betas) - len(_valid)}사 제외 "
              f"→ {len(_valid)}사로 집계")
    de_median = float(np.median([p["D_over_E"] for p in _valid]))

    # (Damodaran 산업 βU 조회 — 이상치 기준·혼합 앵커로 사용)
    dmd_bu = None
    _dmd_meta = {}
    try:
        from .industry_classifier import classify_ticker
        from .damodaran_betas import lookup_industry_beta
        _ic = classify_ticker(TARGET["ticker"], name=TARGET.get("name"))
        _ind = _ic.get("industry", "")
        _dmd = lookup_industry_beta(_ind, verbose=False) if _ind else None
        if _dmd and _dmd.get("unlevered_beta") is not None:
            dmd_bu = float(_dmd["unlevered_beta"])
            _dmd_meta = {
                "damodaran_sector": _dmd.get("damodaran_sector"),
                "mapping_keyword": _dmd.get("mapping_keyword"),
            }
    except Exception as _e:
        if verbose:
            print(f"  [C3 Damodaran 조회] 스킵: {str(_e)[:100]}")

    # 집계: 이상치 제외 → 유사도 가중평균 → Damodaran 혼합
    _blend = _blend_peer_bu(_valid, dmd_bu)
    bU_peer_raw = _blend["bU_peer"]
    bU_median   = _blend["bU_final"]      # ← relever 에 쓰는 최종 βU (변수명 하위호환)
    if verbose:
        _exc = f" [이상치제외: {', '.join(_blend['excluded'])}]" if _blend["excluded"] else ""
        print(f"\n  피어 βU: {_blend['agg_method']} {bU_peer_raw:.4f}{_exc}")
        print(f"  → {_blend['blend_method']} (피어가중 {_blend['weight_peer']*100:.0f}%): "
              f"βU_final = {bU_median:.4f}"
              + (f" / Damodaran {dmd_bu:.4f}" if dmd_bu else ""))
        print(f"  D/E 중위(cap용) = {de_median*100:.2f}%")

    # Damodaran 교차검증 기록 (혼합 결과 포함; 기존 키 peer_median_bU 호환 유지)
    damodaran_check = {"available": dmd_bu is not None}
    if dmd_bu is not None:
        gap = bU_peer_raw - dmd_bu
        damodaran_check.update({
            **_dmd_meta,
            "damodaran_bU": dmd_bu,
            "peer_median_bU": bU_peer_raw,    # (호환) 이상치제외+유사도가중 후 peer βU
            "blended_bU": bU_median,
            "weight_peer": _blend["weight_peer"],
            "n_peers_kept": _blend["n_kept"],
            "excluded_peers": _blend["excluded"],
            "agg_method": _blend["agg_method"],
            "gap": gap,
            "warn_gt_0p3": abs(gap) > 0.30,
        })
        if verbose:
            tag = "⚠ GAP" if abs(gap) > 0.30 else "OK"
            print(f"  [C3 Damodaran βU] 산업 {_dmd_meta.get('damodaran_sector')}: "
                  f"피어 {bU_peer_raw:.3f} vs Damodaran {dmd_bu:.3f} (Δ{gap:+.3f}) {tag}")

    # ── 3.5 타겟 본인 자본구조 + 산업 캡 (C안) ───────────────────────
    #   교과서 Hamada: βU 중위값을 '타겟 본인' D/E 로 relever (회사 고유 재무위험 반영).
    #   단, 일시적 과부채(distress 역설: 부채비중↑→WACC↓ 모순) 방지를 위해
    #   산업(피어) 분포로 캡:  cap = clamp(2.5 × 피어중위 D/E, 100%, 200%).
    #     사용 D/E = min(본인 시장가 D/E, cap);  본인값 산출 불가 시 피어 중위 폴백.
    #   relever 와 가중치(We/Wd)에 '동일한 사용 D/E' 적용(내부 정합).
    _t_xbrl_by_year = xbrl[TARGET["name"]]["by_year"]
    _t_latest = str(max(_t_xbrl_by_year.keys()))
    target_ibd = _t_xbrl_by_year[_t_latest]["financials"].get("ibd") or 0.0
    # ── 타깃 IBD 시점 최신화 (net_debt 와 동일 빈티지: 최신 분기/반기 BS) ──
    #   D/E 정합성 — equity_value 의 net_debt 와 같은 IBD(2026.03 등)를 사용.
    #   피어 IBD 는 산업 베타·de_median 용이라 연간 유지(분기 수렴 효과 미미).
    _ibd_as_of = f"{_t_latest}.12"
    try:
        _meta = _t_xbrl_by_year[_t_latest].get("meta", {}) or {}
        _cc = _meta.get("corp_code")
        if _cc:
            from .quarterly_financials import latest_quarter_bs
            _lq = latest_quarter_bs(_cc, int(_t_latest), verbose=False)
            if _lq:
                target_ibd = _lq["ibd"]
                _ibd_as_of = _lq["period"]
                if verbose:
                    print(f"  [WACC IBD 최신화] 연간({_t_latest}.12) → {_ibd_as_of}: "
                          f"IBD=₩{target_ibd/1e12:.3f}조")
    except Exception:
        pass
    target_E = equity_data["companies"][TARGET["name"]]["E_market_cap"]
    de_cap = min(max(2.5 * de_median, 1.0), 2.0)
    if target_E and target_E > 0:
        de_own = target_ibd / target_E
        de_used = min(de_own, de_cap)
        de_basis = "own_capped" if de_own > de_cap else "own"
    else:
        de_own = None
        de_used = de_median
        de_basis = "peer_median_fallback"
    # ── 캡 발동(고지) 판정 — 본인 D/E 가 산업 캡을 초과해 조정된 경우 ──
    #   개인투자자 고지용: 적정주가는 '정상화 자본구조 가정' 하의 값이며,
    #   실제 재무위험(과부채)은 별도로 봐야 함을 명시 (오도 방지).
    leverage_cap_applied = (de_basis == "own_capped")
    leverage_disclosure = None
    if leverage_cap_applied:
        leverage_disclosure = (
            f"본 종목은 실제 시장가 D/E({de_own*100:.0f}%)가 피어 기반 상한"
            f"({de_cap*100:.0f}%)을 초과하여, WACC 계산에 조정 D/E({de_used*100:.0f}%)를 "
            f"적용했습니다. 이는 과도한 레버리지가 WACC를 기계적으로 낮추는 왜곡(distress 역설)을 "
            f"줄이기 위한 보정이며, 산출된 적정가치는 재무구조 정상화 가정을 포함합니다. "
            f"실제 과부채에 따른 재무위험은 별도 위험요인으로 확인하시기 바랍니다."
        )
    if verbose:
        _ob = f"{de_own*100:.1f}%" if de_own is not None else "N/A"
        print(f"  타겟 자본구조(C안): 본인 D/E={_ob}  캡={de_cap*100:.0f}%  "
              f"→ 사용 D/E={de_used*100:.1f}% [{de_basis}]"
              + ("  ⚠ CAP 발동(고지 대상)" if leverage_cap_applied else ""))

    # ── 4. 타겟 한계세율 ────────────────────────────────────────
    target_xbrl = xbrl[TARGET["name"]]["by_year"]
    t_target, tier_target = _tax_rate_for_company(target_xbrl)
    if verbose:
        print(f"  타겟 한계세율: {t_target*100:.1f}% ({tier_target})")

    # ── 5. Hamada Relever (타겟 본인 사용 D/E 로) ──────────────────
    bL_target = bU_median * (1 + (1 - t_target) * de_used)
    if verbose:
        print(f"  타겟 βL = βU × [1+(1−t)·D/E] = {bL_target:.4f}  (D/E={de_used*100:.1f}%)")

    # ── 6. Rf, SRP, Ke ─────────────────────────────────────────
    rf_data = fetch_rf(eval_d, verbose=False)
    Rf = rf_data["rf"]

    # SRP: 타겟 시총 자동 매칭 (한공회 3분위)
    # 시점 정책: 평가일 현재 시총 사용 (설계서 §1.3 '직전 사업연도말'과 의도적 차이).
    #   일반투자자 서비스 특성상 실시간 시총이 목적적합하다는 판단. SRP 3분위 구간이
    #   넓어(Mid 6,848억~333조) 시점 차이의 SRP 영향은 경계 종목을 제외하면 미미.
    target_E = equity_data["companies"][TARGET["name"]]["E_market_cap"]
    SRP, srp_tier = match_srp(target_E)

    Ke = Rf + bL_target * ERP + SRP + CRP

    if verbose:
        print(f"\n  Rf = {Rf*100:.3f}%  (국고채 10년, {rf_data['as_of_date']})")
        print(f"  ERP = {ERP*100:.1f}%  SRP = {SRP*100:+.2f}% ({srp_tier})  CRP = {CRP*100:.1f}%")
        print(f"  Ke = Rf + βL·ERP + SRP + CRP = {Ke*100:.3f}%")

    # ── 7. Kd ─ 사업보고서 RAG 신용등급 × KOFIA 5년 무보증 회사채 ─
    # KOFIA 채권시가평가수익률 자동 수집 (hidden API) — eval_date 기준 CSV 보장.
    #   실패해도 기존 CSV fallback (graceful) — 평가 전체를 중단시키지 않음.
    try:
        from .kofia_fetcher import fetch_and_save
        fetch_and_save(eval_date=eval_d, verbose=verbose)
    except Exception as e:
        if verbose:
            print(f"  [KOFIA 자동수집 실패 → 기존 CSV 사용] {str(e)[:100]}")
    # 추출 실패 시 fallback — 무차입 우량주 (NAVER 등) 대응
    if verbose:
        print(f"\n  [Kd 산정] 사업보고서 RAG 신용등급 추출 중...")
    rating_info = fetch_credit_rating_via_rag(
        ticker=TARGET["ticker"],
        name=TARGET["name"],
        year=max(FISCAL_YEARS),
        market=TARGET["market"],
        verbose=verbose,
    )
    rating_fallback_used = False
    if rating_info is None or not rating_info.get("rating"):
        # Fallback: 신용등급이 사업보고서에 없는 무차입/우량 IT 회사 대응
        # KOSPI 대형주 중위 등급 AA0 을 보수적 프록시로 사용 (D 비중이 작을수록 영향 미미)
        rating_fallback_used = True
        rating_info = {
            "rating":          "AA0",
            "rating_type":     "fallback",
            "rating_agency":   "system_default",
            "rating_date":     None,
            "confidence":      "low",
            "fallback_reason": "사업보고서에 회사채·CP 신용등급 명시 없음 (무차입 또는 미평정)",
        }
        if verbose:
            print(f"  [WARN] 신용등급 RAG 빈 응답 — AA0 fallback 적용 (D 비중이 작을수록 영향 미미)")
    # KOFIA 회사채 5년 표에 없는 등급(투기등급 BB+ 이하 등) → BBB- 보수적 클립
    # (RuntimeError 로 평가 전체가 중단되지 않도록 graceful 처리)
    try:
        kd_info = get_kd_by_rating(rating_info["rating"])
    except KeyError:
        original = rating_info.get("rating")
        rating_info["rating_original"] = original
        rating_info["rating"] = "BBB-"      # KOFIA 표 최저 등급 (보수적)
        rating_info["rating_clipped"] = True
        rating_fallback_used = True
        if verbose:
            print(f"  [WARN] 등급 '{original}' KOFIA 5년 표 외 → BBB- 보수적 클립")
        kd_info = get_kd_by_rating("BBB-")
    Kd = kd_info["kd"]
    Kd_after_tax = Kd * (1 - t_target)

    if verbose:
        rtype = rating_info.get("rating_type", "")   # "bond" / "cp_mapped" / "fallback"
        if rtype == "cp_mapped" and rating_info.get("cp_conversion"):
            # CP 폴백 — 수익률 변환 분해 표시
            conv = rating_info["cp_conversion"]
            print(f"  신용등급(CP 폴백) = CP {conv['cp_rating']} → 회사채 "
                  f"{conv['mapped_bond_rating']} "
                  f"({rating_info['rating_agency']}, {rating_info['rating_date']}, "
                  f"conf={rating_info['confidence']})")
            print(f"  Kd 산정: CP {conv['cp_rating']} → 회사채 {conv['mapped_bond_rating']} "
                  f"→ KOFIA 회사채5년 {conv['converted_yield']*100:.3f}%")
            print(f"    [{conv['method']}]")
            for w in conv.get("warnings", []):
                print(f"    ⚠ {w}")
            print(f"  Kd = {Kd*100:.3f}%  (KOFIA 회사채 {conv['kofia_bond_as_of']})")
        else:
            # 회사채(bond) / 미평정 폴백(fallback) — cp_conversion 없음
            label = "회사채" if rtype == "bond" else f"폴백/{rtype}"
            print(f"  신용등급({label}) = {rating_info['rating']} "
                  f"({rating_info.get('rating_agency','')}, "
                  f"conf={rating_info.get('confidence','')})")
            print(f"  Kd = KOFIA {kd_info.get('bond_type','회사채')} "
                  f"{kd_info.get('guarantee','무보증')} {kd_info.get('maturity','5년')} "
                  f"= {Kd*100:.3f}%  (KOFIA {kd_info.get('kofia_as_of','')})")
        if not kd_info["filename_has_date"]:
            print(f"  ⚠ KOFIA 파일명에 날짜가 없어 mtime을 as_of 로 사용. "
                  f"권장: 채권시가평가기준수익률_YYYYMMDD.csv 로 저장.")
        print(f"  Kd_after_tax = Kd × (1 − t_target) = {Kd_after_tax*100:.3f}%")

    # ── 8. WACC + 신뢰구간 (가중치도 타겟 본인 사용 D/E 로) ──────────
    We = 1.0 / (1.0 + de_used)
    Wd = de_used / (1.0 + de_used)

    WACC = We * Ke + Wd * Kd_after_tax

    # ▼ WACC 신뢰구간 — βU 분산 + ERP 범위 분리 후 보수적 결합 (H-10 정합화)
    # 학술 근거: Fernandez (IESE 2019) "WACC: A Confusion"
    #            - 두 불확실성 동시 변동시 신뢰구간 과대평가
    #            - 분리 산출 후 RSS (Root Sum of Squares) 결합 권장
    peer_bU_values = [p["beta_U"] for p in peer_betas]
    bU_std = float(np.std(peer_bU_values, ddof=1)) if len(peer_bU_values) >= 2 else 0.0

    # (a) βU 만 ± 1σ 변동 (ERP 고정 = Base)
    bL_bu_low  = (bU_median - bU_std) * (1 + (1 - t_target) * de_used)
    bL_bu_high = (bU_median + bU_std) * (1 + (1 - t_target) * de_used)
    WACC_bu_low  = We * (Rf + bL_bu_low * ERP + SRP + CRP)  + Wd * Kd_after_tax
    WACC_bu_high = We * (Rf + bL_bu_high * ERP + SRP + CRP) + Wd * Kd_after_tax

    # (b) ERP 만 변동 (βU 고정 = Base)
    WACC_erp_low  = We * (Rf + bL_target * ERP_LOW  + SRP + CRP) + Wd * Kd_after_tax
    WACC_erp_high = We * (Rf + bL_target * ERP_HIGH + SRP + CRP) + Wd * Kd_after_tax

    # (c) 보수적 결합 — RSS (Fernandez 권장)
    #    Δ_total = √(Δ_βU² + Δ_ERP²)
    delta_bu_low  = WACC - WACC_bu_low
    delta_bu_high = WACC_bu_high - WACC
    delta_erp_low  = WACC - WACC_erp_low
    delta_erp_high = WACC_erp_high - WACC

    import math as _m
    delta_low  = _m.sqrt(delta_bu_low**2  + delta_erp_low**2)
    delta_high = _m.sqrt(delta_bu_high**2 + delta_erp_high**2)
    WACC_low   = max(0.0, WACC - delta_low)
    WACC_high  = WACC + delta_high

    if verbose:
        print(f"  E 비중 = {We*100:.1f}%  D 비중 = {Wd*100:.1f}%")
        print(f"\n  ★ WACC = {WACC*100:.3f}%")
        print(f"  신뢰구간 (Fernandez RSS 결합): "
              f"{WACC_low*100:.2f}% ~ {WACC*100:.2f}% ~ {WACC_high*100:.2f}%")
        print(f"    βU σ 단독 변동: {WACC_bu_low*100:.2f}% ~ {WACC_bu_high*100:.2f}%")
        print(f"    ERP 단독 변동:  {WACC_erp_low*100:.2f}% ~ {WACC_erp_high*100:.2f}%")

    # ── 9. 산업 사이클 z-score ─────────────────────────────────
    cycle_info = compute_industry_cycle(xbrl, verbose=verbose)

    result = {
        "as_of_date": eval_d.isoformat(),
        "rf": Rf, "rf_pct": Rf*100,
        "rf_source": rf_data,
        "ERP": ERP, "CRP": CRP, "SRP": SRP, "SRP_tier": srp_tier,
        "peers_hamada": peer_betas,
        "beta_U_median":   bU_median,
        "DE_median":       de_median,
        # C안: 실제 사용 D/E = 타겟 본인(시장가) D/E, 단 산업 캡 적용
        "DE_target_pct":   de_used * 100,          # 실제 relever·가중치에 쓰인 D/E
        "DE_own_pct":      (de_own * 100) if de_own is not None else None,  # 타겟 본인 D/E
        "DE_peer_median_pct": de_median * 100,     # 피어 중위 D/E(참고)
        "DE_cap_pct":      de_cap * 100,           # 산업 캡 상한
        "DE_basis":        de_basis,               # own / own_capped / peer_median_fallback
        # 캡 발동 고지 (개인투자자 오도 방지)
        "leverage_cap_applied": leverage_cap_applied,
        "leverage_disclosure":  leverage_disclosure,
        "beta_L_target":   bL_target,
        "damodaran_check": damodaran_check,   # C3: 산업 βU 교차검증 보조 메타
        "t_target":        t_target, "t_target_tier": tier_target,
        "Ke":              Ke, "Ke_pct": Ke*100,
        "Kd":              Kd, "Kd_pct": Kd*100,
        "Kd_after_tax":    Kd_after_tax,
        "credit_rating":   rating_info,
        "kd_source":       kd_info,
        "kd_fallback":     rating_fallback_used,
        "We":              We, "Wd": Wd,
        "WACC":            WACC, "WACC_pct": WACC*100,
        # WACC 신뢰구간 (βU σ + ERP 7~9% 결합)
        "WACC_low":        WACC_low,
        "WACC_high":       WACC_high,
        "WACC_range_meta": {
            "bU_median":      bU_median,
            "bU_std":         bU_std,
            "ERP_low":        ERP_LOW,
            "ERP_high":       ERP_HIGH,
            # 분리 변동값 (학술 검증용 — 어느 변수 영향이 큰지)
            "WACC_bu_low":    WACC_bu_low,
            "WACC_bu_high":   WACC_bu_high,
            "WACC_erp_low":   WACC_erp_low,
            "WACC_erp_high":  WACC_erp_high,
            "method":         "βU σ + ERP 분리 후 RSS 결합 (√(Δ_βU² + Δ_ERP²))",
            "academic_ref":   "Fernandez (IESE 2019) 'WACC: A Confusion'",
        },
        # 산업 사이클 z-score
        "cycle_indicator": cycle_info,
    }

    path = WACC_DIR / f"wacc_result_{eval_d.strftime('%Y%m%d')}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    if verbose:
        print(f"\n저장: {path}")
    return result


if __name__ == "__main__":
    compute_wacc(verbose=True)
