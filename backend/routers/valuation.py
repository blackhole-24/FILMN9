"""
backend/routers/valuation.py
============================
밸류에이션 통합 JSON 서빙 (신규 — EPV·Reverse DCF·안전마진 UI 대응).

설계 (2026-06, 통합 합의)
-------------------------
  · 밸류에이션 엔진(valuation_engine)이 종목 평가 후 결과를 단일 '통합 JSON'으로
    SQLite(data/valuation.db) + 파일(valuation_<code>_<date>.json)에 저장한다.
  · 본 라우터는 그 통합 JSON을 '있는 그대로' 반환한다(패스스루).
    프론트(Next.js 밸류 탭)가 summary · valuation_diagnostics · scenarios ·
    wacc_breakdown · multiples · peer_beta 등을 직접 렌더한다.
  · 옛 '6분리 파일(dcf/fcff/wacc/multiples/peer_beta/uncertainty)' 변환 로직은
    폐기 — 밸류 탭 디자인이 EPV 중심 신규 UI(로컬 static/index.html)로 확정됨.

데이터 위치 (환경변수로 재정의 가능)
------------------------------------
  · VALUATION_DB_PATH   기본: <repo>/data/valuation.db   (SQLite, 우선)
  · VALUATION_JSON_DIR  기본: <repo>/data/valuation_json (파일 폴백)
        파일명 규칙: valuation_<stockcode>_<YYYYMMDD>.json

읽기 구조 (valuation.db)
------------------------
  valuation_runs(stock_code, eval_date, mongo_doc_id, ...)  ← 최신 평가일 인덱스
  mongo_docs(collection='valuation_results', doc_id, doc)   ← 통합 결과 JSON 본문

응답
----
  · 데이터 있음 → 통합 JSON + {"is_mock": false, "_meta": {...}}
  · 없음        → {"is_mock": true, ...}  → 프론트가 '미평가 안내' 표시 (NO-MOCK)
"""
from __future__ import annotations

import glob
import json
import math
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter

router = APIRouter()

_ROOT = Path(__file__).resolve().parent.parent.parent  # FILMN9/
_DB_PATH = Path(os.getenv("VALUATION_DB_PATH", str(_ROOT / "data" / "valuation.db")))
_JSON_DIR = Path(os.getenv("VALUATION_JSON_DIR", str(_ROOT / "data" / "valuation_json")))


# ─── 헬퍼 ──────────────────────────────────────────────────────────────────────
def _norm_code(s: str) -> str:
    """6자리 숫자면 zfill, 아니면(회사명) 그대로."""
    s = str(s).strip()
    return s.zfill(6) if s.isdigit() else s


def _sanitize(obj: Any) -> Any:
    """NaN/Inf → None (표준 JSON 안전). 엔진이 1차 정화하지만 방어적으로 재처리."""
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    return obj


def _db_latest_doc(code: str, raw: str) -> Optional[dict]:
    """valuation.db 에서 최신 평가일의 통합 결과 doc 반환 (DB 우선).

    종목코드 정확 일치 우선, 미스 시 회사명 폴백(사용자가 코드 대신 이름 입력 대비).
    테이블 부재·손상 등은 None 으로 흡수(파일 폴백으로 진행).
    """
    if not _DB_PATH.exists():
        return None
    try:
        conn = sqlite3.connect(str(_DB_PATH), timeout=10.0)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error:
        return None
    try:
        row = conn.execute(
            "SELECT mongo_doc_id FROM valuation_runs WHERE stock_code=? "
            "ORDER BY eval_date DESC LIMIT 1", (code,)).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT mongo_doc_id FROM valuation_runs WHERE corp_name=? "
                "ORDER BY eval_date DESC LIMIT 1", (raw,)).fetchone()
        if row is None or not row["mongo_doc_id"]:
            return None
        doc_row = conn.execute(
            "SELECT doc FROM mongo_docs WHERE collection='valuation_results' "
            "AND doc_id=?", (row["mongo_doc_id"],)).fetchone()
        if doc_row is None or not doc_row["doc"]:
            return None
        return json.loads(doc_row["doc"])
    except (sqlite3.Error, json.JSONDecodeError):
        return None
    finally:
        conn.close()


def _file_latest_doc(code: str) -> Optional[dict]:
    """파일 폴백 — valuation_<code>_<date>.json 중 최신(파일명 정렬)."""
    if not _JSON_DIR.exists():
        return None
    files = sorted(glob.glob(str(_JSON_DIR / f"valuation_{code}_*.json")))
    if not files:
        return None
    try:
        with open(files[-1], encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


# ─── 엔드포인트 ────────────────────────────────────────────────────────────────
@router.get("/valuation/{stock_code}")
def get_valuation(stock_code: str):
    """종목 밸류에이션 통합 JSON 반환.

    - data/valuation.db(우선) → JSON 파일(폴백) 순으로 최신 결과 탐색
    - 통합 JSON 을 그대로 반환(프론트가 직접 렌더) + is_mock=false
    - 결과 없으면 is_mock=true → 프론트가 '미평가 안내' (가짜 숫자 미표시, NO-MOCK)
    """
    code = _norm_code(stock_code)
    raw = str(stock_code).strip()
    doc = _db_latest_doc(code, raw) or _file_latest_doc(code)

    if doc is None:
        return {
            "is_mock": True,
            "stock_code": code,
            "_meta": {
                "message": "평가 결과 없음 — 미평가 종목(백그라운드 평가 대기 또는 대상 외)",
                "db_path": str(_DB_PATH),
                "db_exists": _DB_PATH.exists(),
                "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
        }

    doc = _sanitize(doc)
    doc["is_mock"] = False
    doc.setdefault("stock_code", code)
    doc["_meta"] = {
        "source": "valuation.db" if _DB_PATH.exists() else "json_file",
        "loaded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    return doc
