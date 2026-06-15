"""
api/routers/overview.py
=======================
종목 통합 응답 엔드포인트 - 2탭 화면 1회 호출에 필요한 모든 데이터 반환.

설계
----
- 화면 진입 시 fetch('/api/overview/{stock_code}') 1번만 호출
- SQLite 5테이블 + MongoDB(histories) 동시 조회
- 응답을 탭1/탭2 구조로 분리하여 프론트 렌더링 단순화

응답 스키마
-----------
{
  "stock_code", "corp_name",
  "header":  {가격 + 밸류에이션 적정가 통합 (두 탭 공통)},
  "tab1":    {history, ohlcv, company, financials, shareholders,
              executives, disclosure, health_ratio},
  "tab2":    {valuation},
  "_sources": {각 섹션의 데이터 출처},
  "_meta":    {generated_at, endpoint}
}

MongoDB Atlas 셋업 전에는 history = null 반환 (서비스 동작 영향 없음).
"""
from __future__ import annotations

import sqlite3
import json
import os
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter()

# ─── 경로 설정 ────────────────────────────────────────────────────────────────
_ROOT        = Path(__file__).resolve().parent.parent.parent
_DB_PATH     = _ROOT / "data" / "filmn9.db"
_HISTORY_DIR = _ROOT / "data" / "parsed_history"   # 파일 기반 히스토리 폴백


# ─── MongoDB 연결 (Atlas 셋업 전이라 lazy) ────────────────────────────────────
_mongo_client = None
_history_col  = None
_mongo_failed = False   # 한 번 실패하면 재시도 X (타임아웃 반복 방지)

def _get_mongo_collection():
    """
    MongoDB Atlas filmn9.histories 컬렉션 lazy 연결.
    .env 의 MONGO_URI 가 비어있거나 연결 실패 시 None 반환 (서비스 동작 영향 없음).
    연결 실패 후 재시도하지 않아 응답 속도 저하 방지.
    """
    global _mongo_client, _history_col, _mongo_failed
    if _mongo_failed:
        return None
    uri = os.getenv("MONGO_URI", "").strip()
    if not uri:
        return None
    if _mongo_client is not None:
        return _history_col
    try:
        from pymongo import MongoClient
        _mongo_client = MongoClient(
            uri,
            serverSelectionTimeoutMS=2000,
            connectTimeoutMS=2000,
            socketTimeoutMS=3000,
        )
        db_name  = os.getenv("MONGO_DB", "filmn9")
        col_name = os.getenv("MONGO_COLLECTION", "histories")
        _history_col = _mongo_client[db_name][col_name]
        _mongo_client.admin.command("ping")
        print(f"[overview] MongoDB 연결 성공: {db_name}.{col_name}")
    except Exception as e:
        print(f"[overview] MongoDB 연결 실패 (이후 재시도 없음): {e}")
        _mongo_client = None
        _history_col  = None
        _mongo_failed = True
        return None
    return _history_col


# ─── SQLite 연결 ──────────────────────────────────────────────────────────────
def _conn():
    from backend.db import connect
    return connect()


# ─── 섹션별 헬퍼 ──────────────────────────────────────────────────────────────

def _build_header(conn, stock_code: str) -> dict | None:
    """헤더용 통합 정보 (가격 + 밸류에이션 적정가). 어제 작업한 디자인 그대로."""
    rows = conn.execute("""
        SELECT date, open, high, low, close, volume FROM ohlcv
        WHERE stock_code = ? ORDER BY date DESC LIMIT 2
    """, (stock_code,)).fetchall()
    if not rows:
        return None

    latest = rows[0]
    prev   = rows[1] if len(rows) > 1 else None
    change     = (latest["close"] - prev["close"]) if prev else 0
    change_pct = round(change / prev["close"] * 100, 2) if prev and prev["close"] else 0.0

    # 밸류에이션 적정가 (있으면)
    val_row = conn.execute("""
        SELECT fair_price_min, fair_price_max, fair_price_avg, upside_pct, analyst_count
        FROM valuations WHERE stock_code = ?
    """, (stock_code,)).fetchone()

    return {
        "current_price"           : latest["close"],
        "change"                  : change,
        "change_pct"              : change_pct,
        "date"                    : latest["date"],
        "open"                    : latest["open"],
        "high"                    : latest["high"],
        "low"                     : latest["low"],
        "volume"                  : latest["volume"],
        # 밸류에이션 배너 (탭2 데이터지만 헤더에 표시)
        "valuation_target_min"    : val_row["fair_price_min"]  if val_row else None,
        "valuation_target_max"    : val_row["fair_price_max"]  if val_row else None,
        "valuation_target_avg"    : val_row["fair_price_avg"]  if val_row else None,
        "valuation_upside_pct"    : val_row["upside_pct"]      if val_row else None,
        "valuation_analyst_count" : val_row["analyst_count"]   if val_row else None,
        "_source"                 : "KRX (pykrx) + 밸류에이션팀",
    }


def _get_company(conn, stock_code: str) -> dict | None:
    row = conn.execute("SELECT * FROM company_info WHERE stock_code = ?", (stock_code,)).fetchone()
    return dict(row) if row else None


def _get_financials_list(conn, stock_code: str) -> list:
    """재무요약 — 프론트 배열 형식 (최근연도 먼저).
    한 연도에 연간(11011)+분기(11013 등)가 공존하므로 정렬을 결정적으로:
    연도 DESC, 같은 연도 내에선 연간 > 3분기 > 반기 > 1분기 순(완전성 우선).
    → 프론트 latest=fins[0]가 흔들리지 않고, YoY는 같은 reprt_code 전년 행과 비교."""
    rows = conn.execute(
        "SELECT * FROM financials WHERE stock_code = ? "
        "ORDER BY fiscal_year DESC, "
        "CASE reprt_code WHEN '11011' THEN 4 WHEN '11014' THEN 3 "
        "WHEN '11012' THEN 2 WHEN '11013' THEN 1 ELSE 0 END DESC",
        (stock_code,)
    ).fetchall()
    return [dict(r) for r in rows]


def _get_ohlcv(conn, stock_code: str) -> dict | None:
    """전체 OHLCV (Lightweight Charts 호환 형식)."""
    rows = conn.execute("""
        SELECT date, open, high, low, close, volume FROM ohlcv
        WHERE stock_code = ? ORDER BY date ASC
    """, (stock_code,)).fetchall()
    if not rows:
        return None
    data = [dict(r) for r in rows]
    return {
        "count"     : len(data),
        "from_date" : data[0]["date"],
        "to_date"   : data[-1]["date"],
        "data"      : data,
    }


def _get_shareholders(conn, stock_code: str) -> list:
    rows = conn.execute("""
        SELECT fiscal_year, rank, name, relation, shares, ratio
        FROM shareholders WHERE stock_code = ?
        ORDER BY fiscal_year DESC, rank ASC
    """, (stock_code,)).fetchall()
    return [dict(r) for r in rows]


def _get_valuation(conn, stock_code: str) -> dict | None:
    """밸류에이션 (JSON 컬럼 복원)."""
    row = conn.execute("SELECT * FROM valuations WHERE stock_code = ?", (stock_code,)).fetchone()
    if not row:
        return None
    d = dict(row)
    # JSON 문자열로 저장된 컬럼들 복원
    json_keys = [
        "forecast_revenue", "forecast_op_income", "forecast_net_income",
        "forecast_eps", "forecast_per", "forecast_pbr", "forecast_roe",
        "data_sources",
    ]
    for k in json_keys:
        if d.get(k):
            try:
                d[k] = json.loads(d[k])
            except Exception:
                pass
    return d


def _get_history_from_file(stock_code: str) -> dict | None:
    """
    data/parsed_history/{code}_*.json 파일 기반 히스토리 조회.
    MongoDB 연결 없이도 히스토리 브리핑 반환 (폴백 전용).
    """
    if not _HISTORY_DIR.exists():
        return None
    # {code}_*.json 패턴으로 파일 탐색
    matches = list(_HISTORY_DIR.glob(f"{stock_code}_*.json"))
    if not matches:
        return None
    try:
        data = json.loads(matches[0].read_text(encoding="utf-8"))
        data["_source"] = "file"   # 출처 표기
        return data
    except Exception as e:
        print(f"[overview] parsed_history 파일 읽기 실패: {e}")
        return None


def _get_history(stock_code: str) -> dict | None:
    """
    히스토리 조회 — MongoDB 우선, 실패 시 parsed_history 파일 폴백.
    MongoDB Atlas filmn9.histories 컬렉션 → data/parsed_history/{code}_*.json 순서.
    """
    # 1순위: MongoDB
    col = _get_mongo_collection()
    if col is not None:
        try:
            result = col.find_one({"stock_code": stock_code}, {"_id": 0})
            if result:
                return result
        except Exception as e:
            print(f"[overview] MongoDB history 조회 실패: {e}")

    # 2순위: 로컬 파일 폴백
    return _get_history_from_file(stock_code)


# ─── 메인 엔드포인트 ──────────────────────────────────────────────────────────

@router.get("/overview/{stock_code}")
def get_overview(stock_code: str):
    """
    종목 전체 데이터 통합 응답 (2탭 화면용).

    화면 1회 호출로 모든 섹션 데이터 확보:
      - 헤더: 가격 + 밸류에이션 적정가 (두 탭 공통)
      - 탭1: 히스토리 / 주가차트 / 재무정보 (대부분)
      - 탭2: 밸류에이션 단독
    """
    with _conn() as conn:
        company = _get_company(conn, stock_code)
        if not company:
            raise HTTPException(status_code=404, detail=f"{stock_code} 종목 없음")

        header       = _build_header(conn, stock_code)
        financials   = _get_financials_list(conn, stock_code)
        shareholders = _get_shareholders(conn, stock_code)
        valuation    = _get_valuation(conn, stock_code)

    # MongoDB 조회 (SQLite 커넥션 닫힌 후)
    history = _get_history(stock_code)

    # 데이터 출처 표기 (4가지 상태 구분)
    mongo_col = _get_mongo_collection()
    if history and history.get("_source") == "file":
        mongo_status = f"로컬 파일 (data/parsed_history/{stock_code}_*.json)"
    elif mongo_col is None:
        mongo_status = "MongoDB 미설정 → 로컬 파일 폴백"
    elif history:
        mongo_status = "MongoDB Atlas (filmn9.histories)"
    else:
        mongo_status = "MongoDB Atlas 연결됨 (해당 종목 미적재)"

    return {
        "stock_code" : stock_code,
        "corp_name"  : company.get("corp_name"),

        "header"     : header,

        # ── 탭1: 기업개요·재무 ──
        "tab1": {
            "history"      : history,            # MongoDB · 기업개요 파트
            "ohlcv"        : None,               # 별도 /api/ohlcv/{code} 호출 (경량화)
            "company"      : company,            # SQLite · 본인
            "financials"   : financials,         # SQLite · 본인 (배열, 최근연도 먼저)
            "shareholders" : shareholders,       # SQLite · 본인
        },

        # ── 탭2: 밸류에이션 단독 ──
        "tab2": {
            "valuation"    : valuation,          # SQLite · 밸류에이션팀
        },

        # ── 데이터 출처 표기 (디버깅·신뢰도용) ──
        "_sources": {
            "company"      : "SQLite (filmn9.db)",
            "financials"   : "SQLite (filmn9.db) ← DART JSONL",
            "ohlcv"        : "SQLite (filmn9.db) ← KRX pykrx",
            "shareholders" : "SQLite (filmn9.db) ← DART JSONL VII",
            "valuation"    : "SQLite (filmn9.db) ← 밸류에이션팀 A2 방식",
            "history"      : mongo_status,
        },

        "_meta": {
            "generated_at" : datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "endpoint"     : f"/api/overview/{stock_code}",
            "tab1_sections": ["history", "ohlcv", "company", "financials",
                              "shareholders", "executives", "disclosure", "health_ratio"],
            "tab2_sections": ["valuation"],
        },
    }
