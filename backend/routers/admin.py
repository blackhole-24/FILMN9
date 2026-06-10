"""
backend/routers/admin.py
========================
관리자/QA 메타 엔드포인트 — 평가 기준일·모델버전·데이터 출처 일자·규모를
valuation.db / filmn9.db 에서 실데이터로 집계해 반환.

관리자 페이지(/admin)가 이 메타 + 챗봇 8800/health 를 합쳐 표시한다.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter

router = APIRouter()

_ROOT = Path(__file__).resolve().parent.parent.parent
_VAL_DB = Path(os.getenv("VALUATION_DB_PATH", str(_ROOT / "data" / "valuation.db")))
_FILMN9_DB = _ROOT / "data" / "filmn9.db"


def _q1(db: Path, sql: str, params: tuple = ()) -> dict | None:
    if not db.exists():
        return None
    try:
        conn = sqlite3.connect(str(db), timeout=10.0)
        conn.row_factory = sqlite3.Row
        row = conn.execute(sql, params).fetchone()
        conn.close()
        return dict(row) if row else None
    except sqlite3.Error:
        return None


def _g(r: dict | None, k: str, default=None):
    return r.get(k) if r else default


@router.get("/admin/meta")
def admin_meta():
    """평가에 사용된 데이터 기준일·규모·출처 일자 요약 (실데이터)."""
    # ── 밸류에이션 (valuation.db) ──────────────────────────────
    v: dict = {"db_exists": _VAL_DB.exists()}
    cnt = _q1(_VAL_DB, "SELECT COUNT(DISTINCT stock_code) AS n, COUNT(*) AS runs, "
                       "COUNT(DISTINCT eval_date) AS dates, MAX(eval_date) AS latest "
                       "FROM valuation_runs")
    v["n_stocks"] = _g(cnt, "n")
    v["n_runs"] = _g(cnt, "runs")
    v["n_eval_dates"] = _g(cnt, "dates")
    v["latest_eval_date"] = _g(cnt, "latest")
    v["rf"] = _q1(_VAL_DB, "SELECT rate_date, rf, source FROM rf_rates ORDER BY rate_date DESC LIMIT 1")
    v["kofia_latest"] = _g(_q1(_VAL_DB, "SELECT MAX(yield_date) AS d FROM kofia_bond_yields"), "d")
    v["market_snapshot_latest"] = _g(_q1(_VAL_DB, "SELECT MAX(snap_date) AS d FROM market_snapshot"), "d")
    v["xbrl_years"] = [
        _g(_q1(_VAL_DB, "SELECT MIN(fiscal_year) AS y FROM financials"), "y"),
        _g(_q1(_VAL_DB, "SELECT MAX(fiscal_year) AS y FROM financials"), "y"),
    ]
    mv = _q1(_VAL_DB, "SELECT doc FROM mongo_docs WHERE collection='valuation_results' "
                      "ORDER BY updated_at DESC LIMIT 1")
    try:
        v["model_version"] = json.loads(mv["doc"]).get("model_version") if mv else None
    except Exception:
        v["model_version"] = None

    # ── 기업개요 (filmn9.db) ───────────────────────────────────
    co: dict = {"db_exists": _FILMN9_DB.exists()}
    co["company_info"] = _g(_q1(_FILMN9_DB, "SELECT COUNT(*) AS n FROM company_info"), "n")
    co["ohlcv_latest"] = _g(_q1(_FILMN9_DB, "SELECT MAX(date) AS d FROM ohlcv"), "d")
    co["ohlcv_rows"] = _g(_q1(_FILMN9_DB, "SELECT COUNT(*) AS n FROM ohlcv"), "n")
    fy = _q1(_FILMN9_DB, "SELECT MIN(fiscal_year) AS mn, MAX(fiscal_year) AS mx FROM financials")
    co["fiscal_years"] = [_g(fy, "mn"), _g(fy, "mx")]
    co["financial_detail_rows"] = _g(_q1(_FILMN9_DB, "SELECT COUNT(*) AS n FROM financial_detail"), "n")
    co["financial_detail_stocks"] = _g(
        _q1(_FILMN9_DB, "SELECT COUNT(DISTINCT stock_code) AS n FROM financial_detail"), "n")

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "valuation": v,
        "company": co,
        "ports": {"frontend": 3000, "backend": 8090, "chatbot": 8800},
        "policy": {"no_mock": True, "note": "실데이터 100% — 데이터 없으면 가짜 숫자 대신 '미평가/준비중' 표시"},
    }
