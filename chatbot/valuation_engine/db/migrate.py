"""기존 캐시 파일 → DB 일괄 적재 (원본 파일 보존, 멱등 upsert).

대상(식별자 명확·가치 높은 데이터):
  · data/xbrl/*.json, valuation_engine/data/xbrl*/*.json → financials
  · data/rag_cache/credit_*.json                         → credit_ratings
  · valuation_engine/data/ecos/rf_*.json                 → rf_rates
  · 채권시가평가기준수익률_*.csv                          → kofia_bond_yields
  · data/report_registry.json                            → report_registry
  · peer_beta/results/peer_beta_*.json                   → beta_results
  · valuation_engine/results/valuation_*.json            → valuation_runs + diagnostics + Mongo
  · (companies 마스터는 financials meta 로 기본 구성)

제외(의도적):
  · KOSPI/KOSDAQ/*.jsonl(사업보고서 청크) — 이미 Mongo-import 가능한 JSONL 이며
    대용량. '파일 폴백' 코퍼스로 유지하고, 신규 보고서만 Mongo report_chunks 에 적재.
  · wacc/dcf/equity 의 레거시 per-run 결과 — 타깃 식별자 불명확 + 신규 평가가 재생성.

실행:
    python -m valuation_engine.db.migrate            # 전체
    python -m valuation_engine.db.migrate --only financials,credit
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import re
from pathlib import Path

from . import mongo_json, store
from .. import db as api  # 상위 패키지 통합 API (save_*)

_VAR_ROOT = Path(__file__).resolve().parent.parent.parent


def _load(path: str) -> dict | list | None:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────
def migrate_financials(verbose=True) -> dict:
    pats = [
        str(_VAR_ROOT / "data" / "xbrl" / "*.json"),
        str(_VAR_ROOT / "valuation_engine" / "data" / "xbrl" / "*.json"),
        str(_VAR_ROOT / "valuation_engine" / "data" / "xbrl_balance" / "*.json"),
    ]
    ok = fail = 0
    for pat in pats:
        for fp in glob.glob(pat):
            d = _load(fp)
            if not isinstance(d, dict):
                fail += 1
                continue
            meta = d.get("meta", {}) or {}
            sc = meta.get("stock_code")
            yr = meta.get("year")
            if not sc or not yr:
                m = re.search(r"(\d{6})_.+_(\d{4})", Path(fp).stem)
                if m:
                    sc, yr = sc or m.group(1), yr or int(m.group(2))
            if not (sc and yr and "financials" in d):
                fail += 1
                continue
            try:
                api.save_financials(sc, int(yr), d)
                ok += 1
            except Exception:
                fail += 1
    if verbose:
        print(f"  financials: {ok} 적재 / {fail} 스킵")
    return {"ok": ok, "fail": fail}


def migrate_companies(verbose=True) -> dict:
    """financials meta 로 companies 마스터 기본 구성 (stock_code/corp_name/corp_code)."""
    seen: dict[str, dict] = {}
    for fp in glob.glob(str(_VAR_ROOT / "data" / "xbrl" / "*.json")):
        d = _load(fp)
        meta = (d or {}).get("meta", {}) if isinstance(d, dict) else {}
        sc = meta.get("stock_code")
        if sc and sc not in seen:
            seen[sc] = {"corp_name": meta.get("corp_name"),
                        "corp_code": meta.get("corp_code")}
    for sc, f in seen.items():
        api.save_company(sc, **f)
    if verbose:
        print(f"  companies: {len(seen)} 적재")
    return {"ok": len(seen)}


def migrate_credit(verbose=True) -> dict:
    ok = fail = 0
    for fp in glob.glob(str(_VAR_ROOT / "data" / "rag_cache" / "credit_*.json")):
        d = _load(fp)
        if not isinstance(d, dict):
            fail += 1
            continue
        res = d.get("result", {}) or {}
        sc = d.get("ticker")
        yr = d.get("year")
        if not (sc and yr):
            m = re.search(r"credit_(\d{6})_(\d{4})", Path(fp).stem)
            if m:
                sc, yr = m.group(1), int(m.group(2))
        if not (sc and yr):
            fail += 1
            continue
        try:
            api.save_credit_rating(
                sc, int(yr),
                bond_rating=res.get("bond_rating") or res.get("rating"),
                cp_rating=res.get("cp_rating"),
                kd_applied=res.get("mapping_applied"),
                detail=res, source="rag_cache")
            ok += 1
        except Exception:
            fail += 1
    if verbose:
        print(f"  credit_ratings: {ok} 적재 / {fail} 스킵")
    return {"ok": ok, "fail": fail}


def migrate_rf(verbose=True) -> dict:
    ok = 0
    for fp in glob.glob(str(_VAR_ROOT / "valuation_engine" / "data" / "ecos" / "rf_*.json")):
        d = _load(fp)
        if not isinstance(d, dict):
            continue
        rd = d.get("as_of_date")
        rf = d.get("rf")
        if rd and rf is not None:
            api.save_rf(rd, rf, source=d.get("source", "ECOS"), detail=d)
            ok += 1
    if verbose:
        print(f"  rf_rates: {ok} 적재")
    return {"ok": ok}


def migrate_kofia(verbose=True) -> dict:
    ok = 0
    for fp in glob.glob(str(_VAR_ROOT / "채권시가평가기준수익률_*.csv")):
        m = re.search(r"(\d{8})", Path(fp).stem)
        ydate = m.group(1) if m else Path(fp).stem
        try:
            with open(fp, encoding="utf-8-sig") as f:
                rows = list(csv.reader(f))
        except Exception:
            continue
        if not rows:
            continue
        header = rows[0]
        # 만기 컬럼 = 4번째 이후 (종류/종류명/신용등급/고시기관 다음)
        mat_cols = list(range(4, len(header)))
        batch = []
        for r in rows[1:]:
            if len(r) < 5:
                continue
            kind_name = r[1].strip() if len(r) > 1 else ""
            rating = (r[2].strip() if len(r) > 2 else "") or kind_name
            if rating in ("", "-"):
                rating = kind_name
            for ci in mat_cols:
                if ci >= len(r):
                    continue
                val = r[ci].strip().replace(",", "")
                if not val or val == "-":
                    continue
                try:
                    y = float(val)
                except ValueError:
                    continue
                batch.append({"yield_date": ydate, "rating": f"{kind_name}|{rating}",
                              "maturity": header[ci].strip(), "yield_pct": y})
        # 중복 PK 는 마지막 값 우선 (upsert)
        ok += api.store.upsert_many("kofia_bond_yields", batch) if batch else 0
    if verbose:
        print(f"  kofia_bond_yields: {ok} 적재")
    return {"ok": ok}


def migrate_registry(verbose=True) -> dict:
    d = _load(str(_VAR_ROOT / "data" / "report_registry.json"))
    ok = 0
    if isinstance(d, dict):
        for sc, node in d.items():
            cc = node.get("corp_code", "")
            for period, rec in (node.get("reports", {}) or {}).items():
                api.save_registry_entry(sc, period, {**rec, "corp_code": cc})
                ok += 1
    if verbose:
        print(f"  report_registry: {ok} 적재")
    return {"ok": ok}


def migrate_shares(verbose=True) -> dict:
    """data/rag_cache/shares_*.json → shares 테이블 (멱등 upsert; 파일이 원본)."""
    ok = fail = 0
    for fp in glob.glob(str(_VAR_ROOT / "data" / "rag_cache" / "shares_*.json")):
        d = _load(fp)
        if not isinstance(d, dict):
            fail += 1
            continue
        m = re.search(r"shares_(\d{6})_(\d{4})", Path(fp).stem)
        if not m or d.get("common_float") is None:
            fail += 1
            continue
        try:
            api.save_shares(m.group(1), int(m.group(2)), d)
            ok += 1
        except Exception:
            fail += 1
    if verbose:
        print(f"  shares: {ok} 적재 / {fail} 스킵")
    return {"ok": ok, "fail": fail}


def migrate_beta(verbose=True) -> dict:
    ok = 0
    for fp in glob.glob(str(_VAR_ROOT / "peer_beta" / "results" / "peer_beta_*.json")):
        d = _load(fp)
        if not isinstance(d, dict):
            continue
        eval_date = d.get("eval_date")
        roles = {p.get("ticker"): p.get("role")
                 for p in d.get("peers_input", []) if isinstance(p, dict)}
        batch = []
        for name, pr in (d.get("peers", {}) or {}).items():
            if not isinstance(pr, dict):
                continue
            sc = pr.get("ticker")
            if not (sc and eval_date):
                continue
            batch.append({
                "stock_code": str(sc).zfill(6), "eval_date": eval_date,
                "role": roles.get(sc), "beta_raw": pr.get("beta_raw"),
                "beta_adjusted": pr.get("beta_adjusted"),
                "r_squared": pr.get("r_squared"),
                "n_obs": pr.get("n_weeks_used"), "detail": pr})
        ok += api.store.upsert_many("beta_results", batch) if batch else 0
    if verbose:
        print(f"  beta_results: {ok} 적재")
    return {"ok": ok}


def migrate_results(verbose=True) -> dict:
    ok = fail = 0
    for fp in glob.glob(str(_VAR_ROOT / "valuation_engine" / "results" / "valuation_*.json")):
        d = _load(fp)
        if not isinstance(d, dict) or not d.get("company"):
            fail += 1
            continue
        try:
            api.save_valuation_result(d, result_path=fp)
            ok += 1
        except Exception as e:
            if verbose:
                print(f"    [skip] {Path(fp).name}: {str(e)[:80]}")
            fail += 1
    if verbose:
        print(f"  valuation_runs+results(Mongo): {ok} 적재 / {fail} 스킵")
    return {"ok": ok, "fail": fail}


_STEPS = {
    "financials": migrate_financials,
    "companies":  migrate_companies,
    "credit":     migrate_credit,
    "rf":         migrate_rf,
    "kofia":      migrate_kofia,
    "registry":   migrate_registry,
    "shares":     migrate_shares,
    "beta":       migrate_beta,
    "results":    migrate_results,
}


def run(only: list[str] | None = None, verbose=True) -> dict:
    steps = only or list(_STEPS.keys())
    print("=" * 60)
    print("  기존 캐시 → DB 마이그레이션 (원본 보존)")
    print("=" * 60)
    out = {}
    for name in steps:
        fn = _STEPS.get(name)
        if not fn:
            print(f"  [무시] 알 수 없는 단계: {name}")
            continue
        out[name] = fn(verbose=verbose)
    print("-" * 60)
    print("  최종 DB 테이블 행 수:")
    for t, n in store.table_counts().items():
        if n:
            print(f"    {t:22s} {n:>7d}")
    print("  Mongo-JSON:")
    for c, n in mongo_json.counts().items():
        print(f"    {c:22s} {n:>7d}")
    print("=" * 60)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", type=str, default=None,
                    help="콤마구분 단계 (financials,companies,credit,rf,kofia,registry,beta,results)")
    args = ap.parse_args()
    only = [s.strip() for s in args.only.split(",")] if args.only else None
    run(only=only)
