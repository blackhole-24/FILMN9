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
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

_VAR_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_VAR_ROOT))

from peer_beta.run_beta import run as run_beta
from .config import RESULTS_DIR, TARGET, PEERS
from .fetch_peers_financials import fetch_all
from .compute_equity import compute_all as compute_equity_all
from .wacc_engine import compute_wacc
from .dcf_engine import compute_dcf
from .equity_value import compute_equity_value
from .multiples_engine import compute_multiples
from .uncertainty_engine import run_scenarios


def run(eval_date: Optional[date] = None, verbose: bool = True) -> dict:
    """전 단계 순차 실행."""
    eval_d = eval_date or date.today()
    if isinstance(eval_d, str):
        eval_d = datetime.fromisoformat(eval_d).date()

    if verbose:
        print("=" * 70)
        print(f"기업가치 평가 — {TARGET['name']} (T={eval_d})")
        print("=" * 70)

    # ── Phase 1-A: 피어 베타 ────────────────────────────────────
    if verbose:
        print("\n[Phase 1-A] 피어 베타 회귀 (winsorize)...")
    beta = run_beta(eval_date=eval_d, save_json=True, save_csv=False, verbose=False)
    if verbose:
        for name, r in beta["peers"].items():
            print(f"   {name:10s} β_adj={r['beta_adjusted']:.4f}  R²={r['r_squared']:.3f}")

    # ── Phase 1-B: XBRL 재무 ────────────────────────────────────
    if verbose:
        print("\n[Phase 1-B] 팀원 XBRL — 4사 × 3년 재무 추출 (캐시 적중 시 빠름)...")
    fetch_all(verbose=False, skip_existing=True)

    # ── Phase 2-A: 시가총액 E ───────────────────────────────────
    if verbose:
        print("\n[Phase 2-A] 보통주 시가총액 E 산출...")
    compute_equity_all(eval_date=eval_d, verbose=False)

    # ── Phase 3: WACC ───────────────────────────────────────────
    if verbose:
        print("\n[Phase 3] Hamada Unlever/Relever + Rf + WACC...")
    wacc = compute_wacc(eval_date=eval_d, verbose=verbose)

    # ── Phase 4: DCF ────────────────────────────────────────────
    if verbose:
        print("\n[Phase 4] DCF — FCFF 5년 Fade-out + TV...")
    dcf = compute_dcf(wacc, verbose=verbose)

    # ── Phase 5: Equity Value ───────────────────────────────────
    if verbose:
        print("\n[Phase 5] EV → Equity Value → 주당가치...")
    eqv = compute_equity_value(dcf, verbose=verbose)

    # ── Phase 6: 멀티플 ─────────────────────────────────────────
    if verbose:
        print("\n[Phase 6] 멀티플 4종 역산...")
    multi = compute_multiples(eqv, verbose=verbose)

    # ── Phase 7: 시나리오/민감도/토네이도 ─────────────────────
    if verbose:
        print("\n[Phase 7] Bear/Base/Bull + 민감도 + 토네이도...")
    unc = run_scenarios(dcf, wacc, eqv, verbose=verbose)

    # ── 통합 결과 (Streamlit 포맷) ──────────────────────────────
    output = _build_streamlit_payload(eval_d, beta, wacc, dcf, eqv, multi, unc)

    # ── 저장 ────────────────────────────────────────────────────
    path = RESULTS_DIR / f"valuation_{eval_d.strftime('%Y%m%d')}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)

    if verbose:
        print("\n" + "=" * 70)
        print(f"완료 — {path}")
        print(f"  적정주가: ₩{eqv['fair_price']:,.0f}/주")
        print(f"  현재 주가: ₩{eqv['current_price']:,.0f}/주")
        print(f"  상승여력: {eqv['upside_pct']:+.1f}%")
        print(f"  WACC: {wacc['WACC']*100:.2f}%")
        print("=" * 70)
        print("\n다음: streamlit run valuation_engine/streamlit_app.py")

    return output


def _build_streamlit_payload(eval_d, beta, wacc, dcf, eqv, multi, unc) -> dict:
    """Streamlit MOCKUP 스키마에 맞춰 통합."""
    return {
        "as_of_date": eval_d.isoformat(),
        "company": {"name": TARGET["name"], "ticker": TARGET["ticker"],
                    "market": TARGET["market"]},
        "summary": {
            "equity_value_won": eqv["equity_value"],
            "fair_price":       eqv["fair_price"],
            "current_price":    eqv["current_price"],
            "upside_pct":       eqv["upside_pct"],
            "wacc":             wacc["WACC"],
            "implied_roic":     dcf.get("implied_roic", 0),
            "beta_L_target":    wacc["beta_L_target"],
            "DE_target_pct":    wacc["DE_target_pct"],
            "net_debt_won":     eqv["net_debt"],
            "noa_won":          eqv["noa_clean"],
            "rf":               wacc["rf"],
            "ke":               wacc["Ke"],
            "kd_aftertax":      wacc["Kd_after_tax"],
        },
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
            "df":      [r["discount_factor"] for r in dcf["fcff_table"]] + [dcf["fcff_table"][-1]["discount_factor"]],
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
        "peer_capital_detail": _build_capital_detail(eqv, wacc),
        "ibd_breakdown":       _build_ibd_breakdown(),
        "validation": _build_validation(wacc, dcf),
        "data_sources": [
            ("국고채 10년 (Rf)",     wacc["rf_source"]["as_of_date"], "ECOS API"),
            ("주가·시가총액",        eval_d.isoformat(), "KRX OpenAPI"),
            ("재무제표 (FCFF용)",    "FY2023~FY2025", "DART OpenAPI (팀원 XBRL)"),
            ("피어 자본구조 D",      "FY2025", "DART OpenAPI (팀원 XBRL)"),
            ("피어 자본구조 E",      eval_d.isoformat(), "KRX × DART"),
            ("회사채 (Kd)",          wacc["kd_source"]["kofia_as_of"],
             f"KOFIA {wacc['kd_source']['bond_type']} {wacc['kd_source']['guarantee']} "
             f"{wacc['kd_source']['maturity']} × 신용등급 {wacc['credit_rating']['rating']}"),
            ("SRP 테이블",           "2025-06-10", "한공회 가이던스"),
        ],
    }


def _build_capital_detail(eqv, wacc):
    """피어 4사 자본구조 상세 — E 산출 매칭 + D + D/E."""
    from .compute_equity import load_latest as _load_equity
    from .fetch_peers_financials import load_all as _load_xbrl
    equity_data = _load_equity()
    xbrl_data   = _load_xbrl()

    # WACC 결과에서 피어 D/E 찾기 (피어 3사만)
    peer_de_lookup = {p["name"]: p for p in wacc["peers_hamada"]}

    out = []
    for name, info in equity_data["companies"].items():
        # IBD
        by_year = xbrl_data[name]["by_year"]
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


def _build_ibd_breakdown():
    """4사 IBD 6컴포넌트 분해 — 팀원 ibd_detail 그대로 (단위: 백만원)."""
    from .fetch_peers_financials import load_all as _load_xbrl
    xbrl_data = _load_xbrl()
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
