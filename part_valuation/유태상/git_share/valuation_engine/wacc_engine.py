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


def _effective_tax_rate(by_year: dict) -> float:
    """3년 평균 유효세율 = 법인세비용/세전이익 (양수만).

    팀원 XBRL 결과에서 직접 추출 가능한 필드가 없으면 0 반환.
    """
    rates = []
    for y, r in by_year.items():
        fin = r["financials"]
        # 팀원 결과에 세전이익/법인세 없으면 nopat 으로 역산
        # POC: 단순화 — 한계세율 사용 (effective ≤ marginal 통상)
        pass
    return 0.0   # POC: 한계세율로 폴백


def _tax_rate_for_company(by_year: dict) -> tuple[float, str]:
    """max(유효, 한계) 보수적. 일단 한계세율 사용 (유효는 추후 보완)."""
    latest_year = max(by_year.keys(), key=int) if isinstance(list(by_year.keys())[0], str) else max(by_year.keys())
    fin = by_year[latest_year]["financials"]
    ebit_won = fin.get("영업이익") or 0
    t_marginal, tier = get_marginal_tax_rate(ebit_won)
    # TODO: 유효세율 추가 시 max(t_marginal, t_effective)
    return t_marginal, tier


def compute_wacc(eval_date: Optional[date] = None,
                 verbose: bool = True) -> dict:
    """WACC 통합 산출. peer_beta + XBRL + Equity + ECOS 결합."""
    eval_d = date.today() if eval_date is None else eval_date
    if isinstance(eval_d, str):
        from datetime import datetime as _dt
        eval_d = _dt.fromisoformat(eval_d).date()

    if verbose:
        print(f"[T={eval_d}] WACC 산출 시작\n")

    # ── 1. 입력 데이터 로드 ─────────────────────────────────────
    beta_result = run_beta(eval_date=eval_d, save_json=False, save_csv=False, verbose=False)
    xbrl        = load_xbrl()
    equity_data = load_equity()

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
        })
        if verbose:
            print(f"  [{name}]  βL={bL_adj:.4f}  D/E={de*100:.1f}%  t={t_i*100:.1f}%  → βU={bU:.4f}")

    # ── 3. 중위값 집계 ──────────────────────────────────────────
    bU_median = float(np.median([p["beta_U"]   for p in peer_betas]))
    de_median = float(np.median([p["D_over_E"] for p in peer_betas]))
    if verbose:
        print(f"\n  중위값(피어): βU = {bU_median:.4f}, D/E = {de_median*100:.2f}%")

    # ── 4. 타겟 한계세율 ────────────────────────────────────────
    target_xbrl = xbrl[TARGET["name"]]["by_year"]
    t_target, tier_target = _tax_rate_for_company(target_xbrl)
    if verbose:
        print(f"  타겟 한계세율: {t_target*100:.1f}% ({tier_target})")

    # ── 5. Hamada Relever ──────────────────────────────────────
    bL_target = bU_median * (1 + (1 - t_target) * de_median)
    if verbose:
        print(f"  타겟 βL = βU × [1+(1−t)·D/E] = {bL_target:.4f}")

    # ── 6. Rf, SRP, Ke ─────────────────────────────────────────
    rf_data = fetch_rf(eval_d, verbose=False)
    Rf = rf_data["rf"]

    # SRP: 타겟 시총 자동 매칭
    target_E = equity_data["companies"][TARGET["name"]]["E_market_cap"]
    SRP, srp_tier = match_srp(target_E)

    Ke = Rf + bL_target * ERP + SRP + CRP

    if verbose:
        print(f"\n  Rf = {Rf*100:.3f}%  (국고채 10년, {rf_data['as_of_date']})")
        print(f"  ERP = {ERP*100:.1f}%  SRP = {SRP*100:+.2f}% ({srp_tier})  CRP = {CRP*100:.1f}%")
        print(f"  Ke = Rf + βL·ERP + SRP + CRP = {Ke*100:.3f}%")

    # ── 7. Kd ─ 사업보고서 RAG 신용등급 × KOFIA 5년 무보증 회사채 ─
    if verbose:
        print(f"\n  [Kd 산정] 사업보고서 RAG 신용등급 추출 중...")
    rating_info = fetch_credit_rating_via_rag(
        ticker=TARGET["ticker"],
        name=TARGET["name"],
        year=max(FISCAL_YEARS),
        market=TARGET["market"],
        verbose=verbose,
    )
    kd_info = get_kd_by_rating(rating_info["rating"])
    Kd = kd_info["kd"]
    Kd_after_tax = Kd * (1 - t_target)

    if verbose:
        rtype = rating_info["rating_type"]   # "bond" or "cp_mapped"
        if rtype == "bond":
            print(f"  신용등급(회사채) = {rating_info['rating']} "
                  f"({rating_info['rating_agency']}, {rating_info['rating_date']}, "
                  f"conf={rating_info['confidence']})")
            print(f"  Kd = KOFIA {kd_info['bond_type']} {kd_info['guarantee']} "
                  f"{kd_info['maturity']} = {Kd*100:.3f}%  "
                  f"(KOFIA {kd_info['kofia_as_of']})")
        else:
            # CP 폴백 — 수익률 변환 분해 표시
            conv = rating_info["cp_conversion"]
            print(f"  신용등급(CP 폴백) = CP {conv['cp_rating']} → 회사채 "
                  f"{conv['mapped_bond_rating']} "
                  f"({rating_info['rating_agency']}, {rating_info['rating_date']}, "
                  f"conf={rating_info['confidence']})")
            print(f"  Kd 산정:")
            print(f"    CP {conv['cp_rating']} {conv['cp_maturity']} = "
                  f"{conv['cp_yield_input']*100:.3f}% [{conv['cp_yield_source']}]")
            print(f"    + Term-Credit Spread = KOFIA 회사채5년({conv['mapped_bond_rating']}) "
                  f"− KOFIA CP1년({conv['cp_rating']}) "
                  f"= {conv['kofia_bond_5y']*100:.3f}% − {conv['kofia_cp_1y']*100:.3f}% "
                  f"= {conv['term_credit_spread']*100:+.3f}%p")
            print(f"    = 회사채5년 등가 {conv['converted_yield']*100:.3f}%")
            print(f"  Kd = {Kd*100:.3f}%  (KOFIA 회사채 {conv['kofia_bond_as_of']}, "
                  f"CP {conv['kofia_cp_as_of']})")
        if not kd_info["filename_has_date"]:
            print(f"  ⚠ KOFIA 파일명에 날짜가 없어 mtime을 as_of 로 사용. "
                  f"권장: 채권시가평가기준수익률_YYYYMMDD.csv 로 저장.")
        print(f"  Kd_after_tax = Kd × (1 − t_target) = {Kd_after_tax*100:.3f}%")

    # ── 8. WACC ────────────────────────────────────────────────
    We = 1.0 / (1.0 + de_median)
    Wd = de_median / (1.0 + de_median)

    WACC = We * Ke + Wd * Kd_after_tax

    if verbose:
        print(f"  E 비중 = {We*100:.1f}%  D 비중 = {Wd*100:.1f}%")
        print(f"\n  ★ WACC = {WACC*100:.3f}%")

    result = {
        "as_of_date": eval_d.isoformat(),
        "rf": Rf, "rf_pct": Rf*100,
        "rf_source": rf_data,
        "ERP": ERP, "CRP": CRP, "SRP": SRP, "SRP_tier": srp_tier,
        "peers_hamada": peer_betas,
        "beta_U_median":   bU_median,
        "DE_median":       de_median,
        "DE_target_pct":   de_median * 100,
        "beta_L_target":   bL_target,
        "t_target":        t_target, "t_target_tier": tier_target,
        "Ke":              Ke, "Ke_pct": Ke*100,
        "Kd":              Kd, "Kd_pct": Kd*100,
        "Kd_after_tax":    Kd_after_tax,
        "credit_rating":   rating_info,
        "kd_source":       kd_info,
        "We":              We, "Wd": Wd,
        "WACC":            WACC, "WACC_pct": WACC*100,
    }

    path = WACC_DIR / f"wacc_result_{eval_d.strftime('%Y%m%d')}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    if verbose:
        print(f"\n저장: {path}")
    return result


if __name__ == "__main__":
    compute_wacc(verbose=True)
