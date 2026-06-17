"""
밸류에이션·챗봇 전용 관리자 메타 엔드포인트.
=================================================
GET /api/valuation-admin/meta

평가에 사용된 '데이터 기준일(As-of)·출처·규모'를 실데이터로 집계해 반환.
 - 밸류: valuation.db(VAR 직결) — valuation_runs / rf_rates / kofia_bond_yields /
         market_snapshot / mongo_docs(model_version·data_sources)
 - 기업개요: filmn9.db — 섹션별 보유 종목수 + 주가 기준일
 - 챗봇: 정적 힌트(프론트가 8800/health 로 청크수·GPU 실시간 보강)

DB 경로는 valuation.py 와 동일하게 VALUATION_DB_PATH 로 재정의 가능
(현재 VAR/data/valuation.db 직결 → 재평가 시 자동 최신화).
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
_VDB = Path(os.getenv("VALUATION_DB_PATH", str(_ROOT / "data" / "valuation.db")))
_FDB = Path(os.getenv("FILMN9_DB_PATH", str(_ROOT / "data" / "filmn9.db")))


def _q1(db: Path, sql: str, default=None):
    if not db.exists():
        return default
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5.0)
        r = con.execute(sql).fetchone()
        con.close()
        return r[0] if r and r[0] is not None else default
    except Exception:
        return default


def _qrow(db: Path, sql: str):
    if not db.exists():
        return None
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5.0)
        con.row_factory = sqlite3.Row
        r = con.execute(sql).fetchone()
        con.close()
        return dict(r) if r else None
    except Exception:
        return None


@router.get("/valuation-admin/meta")
def valuation_admin_meta():
    # ── 밸류 (valuation.db) ──────────────────────────────────────────
    eval_latest = _q1(_VDB, "SELECT MAX(eval_date) FROM valuation_runs")
    eval_bulk = _q1(
        _VDB,
        "SELECT eval_date FROM valuation_runs GROUP BY eval_date "
        "ORDER BY COUNT(*) DESC LIMIT 1",
    )
    n_eval = _q1(_VDB, "SELECT COUNT(DISTINCT stock_code) FROM valuation_runs", 0)

    rf = _qrow(_VDB, "SELECT rate_date, rf, source, detail FROM rf_rates "
                     "ORDER BY rate_date DESC LIMIT 1")
    rf_out = None
    if rf:
        det = {}
        try:
            det = json.loads(rf.get("detail") or "{}")
        except Exception:
            pass
        rf_out = {
            "date": rf.get("rate_date"),
            "pct": round((rf.get("rf") or 0) * 100, 3),
            "name": det.get("stat_name") or "국고채(10년)",
            "source": rf.get("source"),
        }

    kofia = {
        "date": _q1(_VDB, "SELECT MAX(yield_date) FROM kofia_bond_yields"),
        "n": _q1(_VDB, "SELECT COUNT(*) FROM kofia_bond_yields", 0),
    }
    market = {
        "date": _q1(_VDB, "SELECT MAX(snap_date) FROM market_snapshot"),
        "n": _q1(_VDB, "SELECT COUNT(*) FROM market_snapshot", 0),
    }

    # model_version + 종목별 data_sources (mongo doc 1건 파싱)
    model_version, doc_sources = "v8", []
    doc = _q1(_VDB, "SELECT doc FROM mongo_docs WHERE collection='valuation_results' ORDER BY rowid DESC LIMIT 1")
    if doc:
        try:
            dd = json.loads(doc)
            model_version = dd.get("model_version", "v8")
            doc_sources = [
                (x[0] if isinstance(x, (list, tuple)) else x)
                for x in (dd.get("data_sources") or [])
            ]
        except Exception:
            pass

    # ── 기업개요 (filmn9.db) ─────────────────────────────────────────
    def fc(tbl, col="stock_code"):
        return _q1(_FDB, f"SELECT COUNT(DISTINCT {col}) FROM {tbl}", 0)

    company = {
        "company_info": fc("company_info"),
        "financials": fc("financials"),
        "financial_detail": fc("financial_detail"),
        "shareholders": fc("shareholders"),
        "executives": fc("executives"),
        "ohlcv": fc("ohlcv"),
    }
    ohlcv_date = _q1(_FDB, "SELECT MAX(date) FROM ohlcv")

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "valuation": {
            "eval_date_latest": eval_latest,
            "eval_date_bulk": eval_bulk,
            "n_evaluated": n_eval,
            "model_version": model_version,
            "rf": rf_out,
            "kofia": kofia,
            "market": market,
            "data_sources": doc_sources,
            "methodology": "DCF(FCFF) + EPV(Greenwald) + 멀티플(4종) + 시나리오(Bear/Base/Bull)",
            "db_path": str(_VDB),
            "db_exists": _VDB.exists(),
        },
        "company": company,
        "ohlcv_date": ohlcv_date,
        "chatbot_hint": {
            "reports": "2025 사업보고서 + 2026 1분기보고서 (DART)",
            "embed_model": "BGE-M3 (1024차원, FP16)",
            "reranker": "bge-reranker-v2-m3 (cross-encoder)",
            "llm": "gpt-5.4-mini (reasoning=high)",
            "retrieval": "하이브리드(BM25 + 벡터) + 재랭킹 + 재무제표 라우팅(FINSTMT)",
            "coverage": 2597,
        },
    }
