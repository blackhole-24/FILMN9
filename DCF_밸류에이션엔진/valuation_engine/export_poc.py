"""통합 평가 JSON → KPMG PoC 6종 분리 JSON 어댑터.

입력 : valuation_engine/results/valuation_<ticker>_<YYYYMMDD>.json (통합)
출력 : <out_root>/<ticker>/{fcff,wacc,dcf,multiples,uncertainty,peer_beta}_result.json

팀원 인수인계서(02_..._개발인수인계서.txt) §4 스키마에 맞춰 변환.
단위: dcf 시계열은 이미 billion, summary 의 *_won 은 원 → billion 환산.
필수 5필드(화면 깨짐 방지)는 반드시 채움:
  dcf.fair_value_per_share, dcf.current_price,
  dcf.scenarios.{bear,base,bull}.fair_value, wacc.components.wacc_pct,
  uncertainty.sensitivity_matrix.values (3×3)

실행:
  python -m valuation_engine.export_poc --ticker 009150           # 최신 통합 JSON 자동 탐색
  python -m valuation_engine.export_poc --json <path> --out-root results
  python -m valuation_engine.export_poc --all                     # 데모 3종목 일괄
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Optional

_MODULE_DIR = Path(__file__).resolve().parent
_RESULTS_DIR = _MODULE_DIR / "results"

DEMO_TICKERS = ["090430", "009150", "035420"]   # 아모레·삼성전기·NAVER
G_TERMINAL_PCT = 2.0


# ── 파싱 헬퍼 ──────────────────────────────────────────────────
def _round(x, n=2):
    return round(float(x), n) if x is not None else None


def _to_billion(won):
    return round(float(won) / 1e9, 1) if won is not None else None


def _parse_mult(s):
    """'25.50×' → 25.50 / '—' → None."""
    if not isinstance(s, str):
        return s
    m = re.search(r"-?\d+\.?\d*", s.replace(",", ""))
    return float(m.group()) if m else None


def _parse_range(s):
    """'18.79× ~ 51.11×' → (18.79, 51.11)."""
    if not isinstance(s, str):
        return None, None
    nums = re.findall(r"-?\d+\.?\d*", s.replace(",", ""))
    if len(nums) >= 2:
        return float(nums[0]), float(nums[1])
    return None, None


def _wb_value(wacc_breakdown, label):
    """wacc_breakdown([label,value,source]) 에서 label 행의 value 반환."""
    for row in wacc_breakdown or []:
        if len(row) >= 2 and row[0] == label:
            return row[1]
    return None


def _wb_source(wacc_breakdown, label):
    for row in wacc_breakdown or []:
        if len(row) >= 3 and row[0] == label:
            return row[2]
    return None


def _pct_str(s):
    """'4.55%' → 4.55."""
    if not isinstance(s, str):
        return s
    m = re.search(r"-?\d+\.?\d*", s)
    return float(m.group()) if m else None


# ── 6종 변환 ───────────────────────────────────────────────────
def build_fcff(integ: dict) -> dict:
    dcf = integ["dcf"]
    rev = dcf["revenue"]
    ebit = dcf["ebit"]
    opm = [round(e / r * 100, 1) if r else None for e, r in zip(ebit, rev)]
    # 세율(헤드라인): tax/ebit 중 유효한 첫 값
    tax_rate = None
    for t, e in zip(dcf["tax"], ebit):
        if t is not None and e:
            tax_rate = round(abs(t) / e * 100, 1)
            break
    return {
        "stock_code": integ["company"]["ticker"],
        "as_of_date": integ["as_of_date"],
        "currency": "KRW",
        "unit": "billion",
        "fiscal_years": dcf["labels"],
        "revenue_growth_pct": [_round(g * 100, 1) for g in dcf["growth"]],
        "revenue": rev,
        "ebit": ebit,
        "opm_pct": opm,
        "tax": dcf["tax"],
        "tax_rate_pct": tax_rate,
        "da": dcf["da"],
        "capex_net": dcf["capex"],
        "delta_nwc": dcf["dnwc"],
        "fcff": dcf["fcff"],
        "discount_factor": [_round(d, 3) for d in dcf["df"]],
        "pv": dcf["pv"],
        "ev_total_billion": dcf["ev_total"],
        "model_version": integ.get("model_version", "v4"),
    }


def build_wacc(integ: dict) -> dict:
    s = integ["summary"]
    wb = integ.get("wacc_breakdown", [])
    de_pct = s.get("DE_target_pct") or 0.0
    de = de_pct / 100.0
    we = 1.0 / (1.0 + de) if (1.0 + de) else 1.0
    wd = de / (1.0 + de) if (1.0 + de) else 0.0

    # 신용등급 — wacc_breakdown Kd source 의 끝부분 (예: "... × AA-")
    kd_src = _wb_source(wb, "Kd") or ""
    m = re.search(r"×\s*([A-D]{1,3}[+\-0]?)", kd_src)
    credit_rating = m.group(1) if m else None

    return {
        "stock_code": integ["company"]["ticker"],
        "as_of_date": integ["as_of_date"],
        "components": {
            "rf_pct": _round((s.get("rf") or 0) * 100),
            "erp_pct": _pct_str(_wb_value(wb, "ERP")) or 8.0,
            "beta_levered_target": _round(s.get("beta_L_target"), 3),
            "srp_pct": _pct_str(_wb_value(wb, "SRP")),
            "crp_pct": _pct_str(_wb_value(wb, "CRP")) or 0.0,
            "ke_pct": _round((s.get("ke") or 0) * 100),
            "credit_rating": credit_rating,
            "kd_pct": _pct_str(_wb_value(wb, "Kd")),
            "tax_rate_pct": _pct_str(_wb_value(wb, "한계세율 t")),
            "kd_after_tax_pct": _round((s.get("kd_aftertax") or 0) * 100),
            "weight_equity_pct": _round(we * 100, 1),
            "weight_debt_pct": _round(wd * 100, 1),
            "wacc_pct": _round((s.get("wacc") or 0) * 100),
        },
        "peer_capital_structure": [
            {
                "name": p.get("회사"),
                "beta_l": p.get("βL"),
                "de_pct": p.get("D/E%"),
                "tax_pct": p.get("t%"),
                "beta_u": p.get("βU"),
            }
            for p in integ.get("peers_hamada", []) if p.get("회사") != "중위값"
        ],
        "peer_median": next(
            ({"beta_l": p.get("βL"), "de_pct": p.get("D/E%"), "beta_u": p.get("βU")}
             for p in integ.get("peers_hamada", []) if p.get("회사") == "중위값"),
            {},
        ),
        "target_beta_u_method": "peer_median",
        "hamada_formula": "βL = βU × [1 + (1-t)·D/E]",
        "sources": {
            "rf": "ECOS API", "kd": "KOFIA",
            "srp": "한공회 가이던스 2025-06-10",
            "credit_rating": "사업보고서 RAG (chroma+키워드 union)",
        },
    }


def build_dcf(integ: dict) -> dict:
    s = integ["summary"]
    sc = integ.get("scenarios", {})
    val = integ.get("validation", [])
    val_text = " ".join(str(v) for row in val for v in (row if isinstance(row, list) else [row]))

    def _scen(key_kr):
        d = sc.get(key_kr, {})
        return {
            "fair_value": _round(d.get("price"), 0) if d.get("price") is not None else None,
            "upside_pct": _round(d.get("upside_pct"), 1),
            "ev_ebitda": _round(d.get("ev_ebitda"), 1),
        }

    bear, base, bull = _scen("Bear"), _scen("Base"), _scen("Bull")
    bear["assumption_set"] = {"growth": "min", "opm": "min", "capex": "max", "nwc": "max"}
    base["assumption_set"] = {"growth": "mean", "opm": "mean", "capex": "mean", "nwc": "mean"}
    bull["assumption_set"] = {"growth": "max", "opm": "max", "capex": "min", "nwc": "min"}

    roic = s.get("implied_roic")
    wacc = s.get("wacc")
    return {
        "stock_code": integ["company"]["ticker"],
        "as_of_date": integ["as_of_date"],
        "currency": "KRW",
        "dcf_valid": s.get("dcf_valid"),
        "dcf_invalid_reason": s.get("dcf_invalid_reason"),
        "fair_value_per_share": _round(s.get("fair_price"), 0) if s.get("fair_price") is not None else None,
        "current_price": _round(s.get("current_price"), 0),
        "upside_pct": _round(s.get("upside_pct"), 1),
        "equity_value_billion": _to_billion(s.get("equity_value_won")),
        "ev_billion": integ["dcf"].get("ev_total"),
        "net_debt_billion": _to_billion(s.get("net_debt_won")),
        "noa_billion": _to_billion(s.get("noa_won")),
        "minority_interest_billion": _to_billion(s.get("minority_interest")),
        "implied_roic_pct": _round((roic or 0) * 100, 1),
        "wacc_pct": _round((wacc or 0) * 100),
        "roic_minus_wacc_pct": _round((s.get("eva_spread") or 0) * 100, 2),
        "dcf_confidence": s.get("dcf_confidence"),
        "scenarios": {"bear": bear, "base": base, "bull": bull},
        "g_terminal_pct": G_TERMINAL_PCT,
        "validation": {
            "g_lt_rf_lt_wacc": "위계" in val_text and "PASS" in val_text,
            "roic_gt_wacc": (roic or 0) > (wacc or 0),
            "capex_normalized": "CapEx" in val_text and "조정" in val_text,
        },
    }


def build_multiples(integ: dict) -> dict:
    out_rows = []
    implied_prices = []
    upsides = []
    for m in integ.get("multiples", []):
        p25, p75 = _parse_range(m.get("피어 25~75 백분위"))
        implied = m.get("역산가")
        vs = m.get("vs 현재")
        if isinstance(implied, (int, float)):
            implied_prices.append(implied)
        if isinstance(vs, (int, float)):
            upsides.append(vs)
        out_rows.append({
            "metric": m.get("멀티플"),
            "peer_median": _parse_mult(m.get("피어 중위")),
            "peer_p25": p25,
            "peer_p75": p75,
            "target_value": m.get("대상"),
            "implied_per_share": implied,
            "vs_current_pct": vs,
            "in_range": m.get("판정") == "정합",
        })
    return {
        "stock_code": integ["company"]["ticker"],
        "as_of_date": integ["as_of_date"],
        "multiples": out_rows,
        "average_implied_per_share": round(sum(implied_prices) / len(implied_prices)) if implied_prices else None,
        "average_upside_pct": _round(sum(upsides) / len(upsides), 1) if upsides else None,
    }


def build_uncertainty(integ: dict) -> dict:
    sens = integ.get("sensitivity", {})
    return {
        "stock_code": integ["company"]["ticker"],
        "as_of_date": integ["as_of_date"],
        "sensitivity_matrix": {
            "rows": sens.get("wacc_axis", []),
            "cols": sens.get("g_axis", []),
            "values": [[round(v) for v in row] for row in sens.get("matrix", [])],
            "unit": "KRW per share",
        },
        "tornado": [
            {"variable": t.get("name"), "neg": t.get("neg"), "pos": t.get("pos")}
            for t in integ.get("tornado", [])
        ],
    }


def build_peer_beta(integ: dict) -> dict:
    return {
        "stock_code": integ["company"]["ticker"],
        "as_of_date": integ["as_of_date"],
        "method": "OLS + Blume(α=2/3) + winsorize(±3σ)",
        "window": "KRX 2년 주간",
        "peer_betas": [
            {
                "name": b.get("회사"),
                "n_weeks": b.get("n"),
                "beta_raw": b.get("β_raw"),
                "beta_adj": b.get("β_adj"),
                "r_squared": b.get("R²"),
                "warnings": [w.strip() for w in (b.get("warn") or "").split(",") if w.strip()],
            }
            for b in integ.get("peer_beta", [])
        ],
    }


# ── 검증 (§6) ─────────────────────────────────────────────────
def validate(fcff, wacc, dcf, mult, unc, beta) -> list[str]:
    warns = []
    fc = fcff["fcff"][:5]
    if not all(isinstance(x, (int, float)) and x > 0 for x in fc):
        if dcf.get("dcf_valid"):
            warns.append(f"fcff[0..4] 음수 포함: {fc} (dcf_valid=True 인데 음수 — 확인)")
    fv = [dcf["scenarios"][k]["fair_value"] for k in ("bear", "base", "bull")]
    if all(x is not None for x in fv) and not (fv[0] <= fv[1] <= fv[2]):
        warns.append(f"시나리오 fair_value 단조증가 위반: {fv}")
    w = wacc["components"]["wacc_pct"]
    if w is None or not (3 <= w <= 20):
        warns.append(f"wacc_pct 범위 이탈: {w}")
    if any(m["in_range"] is None for m in mult["multiples"]):
        warns.append("multiples in_range 미정의 항목 존재")
    for b in beta["peer_betas"]:
        if b["r_squared"] is not None and b["r_squared"] < 0.10:
            warns.append(f"peer_beta R²<0.10: {b['name']} {b['r_squared']}")
    sm = unc["sensitivity_matrix"]["values"]
    if len(sm) != 3 or any(len(r) != 3 for r in sm):
        warns.append("sensitivity_matrix 3×3 아님")
    elif any(v <= 0 for r in sm for v in r):
        warns.append("sensitivity_matrix 음수/0 포함")
    if len(unc["tornado"]) < 4:
        warns.append(f"tornado 항목 4개 미만: {len(unc['tornado'])}")
    return warns


def export_one(integrated_json_path: Path, out_root: Path, verbose: bool = True) -> dict:
    with integrated_json_path.open(encoding="utf-8") as f:
        integ = json.load(f)
    ticker = integ["company"]["ticker"]
    out_dir = out_root / ticker
    out_dir.mkdir(parents=True, exist_ok=True)

    parts = {
        "fcff_result.json": build_fcff(integ),
        "wacc_result.json": build_wacc(integ),
        "dcf_result.json": build_dcf(integ),
        "multiples_result.json": build_multiples(integ),
        "uncertainty_result.json": build_uncertainty(integ),
        "peer_beta_result.json": build_peer_beta(integ),
    }
    for fname, obj in parts.items():
        with (out_dir / fname).open("w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)

    warns = validate(parts["fcff_result.json"], parts["wacc_result.json"],
                     parts["dcf_result.json"], parts["multiples_result.json"],
                     parts["uncertainty_result.json"], parts["peer_beta_result.json"])
    if verbose:
        print(f"[OK] {ticker} → {out_dir}  (6종 생성)")
        for w in warns:
            print(f"     ⚠ {w}")
    return {"ticker": ticker, "out_dir": str(out_dir), "warnings": warns}


def _find_latest_integrated(ticker: str) -> Optional[Path]:
    cands = sorted(_RESULTS_DIR.glob(f"valuation_{ticker}_*.json"))
    return cands[-1] if cands else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", help="종목코드 — 최신 통합 JSON 자동 탐색")
    ap.add_argument("--json", help="통합 JSON 경로 직접 지정")
    ap.add_argument("--out-root", default=str(_MODULE_DIR / "results" / "poc"))
    ap.add_argument("--all", action="store_true", help="데모 3종목 일괄")
    args = ap.parse_args()

    out_root = Path(args.out_root)
    targets: list[Path] = []
    if args.json:
        targets.append(Path(args.json))
    elif args.all:
        for tk in DEMO_TICKERS:
            p = _find_latest_integrated(tk)
            if p:
                targets.append(p)
            else:
                print(f"[WARN] {tk} 통합 JSON 없음 — 평가 먼저 실행 필요")
    elif args.ticker:
        p = _find_latest_integrated(args.ticker)
        if not p:
            print(f"[ERROR] {args.ticker} 통합 JSON 없음")
            return 1
        targets.append(p)
    else:
        ap.error("--ticker, --json, --all 중 하나 필요")

    for p in targets:
        export_one(p, out_root)
    print(f"\n출력 루트: {out_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
