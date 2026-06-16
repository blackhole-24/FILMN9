"""
api/routers/valuation_summary.py
================================
밸류에이션 요약(산업 대표주) 서빙 — SQLite valuation_summary 테이블.

엔드포인트
----------
  GET /api/valuation-summary             요약 전체 (정렬: sort=upside|grade|wacc|name)
  GET /api/valuation-summary/{code}      단일 종목 요약

데이터 소스
----------
  filmn9.db · valuation_summary   ← load_valuation_summary.py 가 summary.csv 적재
  ※ 엔진 v8 산출 실데이터. 폴더/테이블 없으면 빈 결과(NO-MOCK).
  ※ 경로(/valuation-summary)는 기존 /valuation/{code} 와 충돌 방지를 위해 분리.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter()

_ROOT = Path(__file__).resolve().parent.parent.parent
_DB   = _ROOT / "data" / "filmn9.db"
# 엔진 v8 합본(통합) JSON — index.html 대시보드가 그대로 소비하는 포맷
_FULL_DIR = _ROOT / "data" / "valuation_inbox" / "repr20_export" / "data"
# 전 종목(2,224+) 통합 JSON 원본 — repr20에 없으면 여기서 찾음. 파일명 valuation_{code}_{YYYYMMDD}.json
_ENGINE_RESULTS = _ROOT / "DCF_밸류에이션엔진" / "valuation_engine" / "results"

_COLS = ("stock_code, corp_name, market, industry, dcf_grade, dcf_confidence, "
         "peer_confidence_grade, fair_price, current_price, upside_pct, wacc, "
         "as_of_date, model_version, source_file, loaded_at")

# DCF 등급 정렬 우선순위 (A 최상)
_GRADE_RANK = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}
# DCF 신뢰도 정렬 우선순위 (엔진 산출값 high~invalid) — dcf_grade(A~E) 없는 6파일 대응
_CONF_RANK = {"high": 0, "medium": 1, "low": 2, "very_low": 3, "invalid": 4}


def _conn():
    from backend.db import connect
    return connect()


def _enrich(d: dict) -> dict:
    """WACC %편의 + 현재가를 ohlcv 최신 종가로 교체 후 상승여력 재계산.

    valuation_summary.current_price 는 산출시점(예 6/1) 스냅샷이라 실제 현재가와
    괴리(일부 극단값). ohlcv 최신 종가(=realtime과 일치 검증됨)로 덮어쓰고
    upside_pct 를 재계산한다(NO-MOCK: 근거 있는 실제 최신가 사용).
    """
    w = d.get("wacc")
    d["wacc_pct"] = round(w * 100, 2) if isinstance(w, (int, float)) else None
    live = d.pop("live_price", None)
    if live:
        d["current_price"] = live
        fp = d.get("fair_price")
        d["upside_pct"] = round((fp - live) / live * 100, 1) if fp else None
    return d


def _fetch_all() -> list[dict]:
    try:
        with _conn() as con:
            rows = con.execute(
                f"SELECT {_COLS}, "
                "(SELECT close FROM ohlcv o WHERE o.stock_code = valuation_summary.stock_code "
                " ORDER BY date DESC LIMIT 1) AS live_price "
                "FROM valuation_summary").fetchall()
    except Exception:
        return []   # 테이블 없음 → 빈 결과
    return [_enrich(dict(r)) for r in rows]


@router.get("/valuation-summary")
def list_summary(sort: str = "upside"):
    """산업 대표주 밸류에이션 요약 목록.

    sort: upside(상승여력 내림차순·기본) | grade(DCF등급) | wacc(낮은순) | name
    """
    data = _fetch_all()
    if not data:
        return {
            "count": 0, "stocks": [],
            "_note": "valuation_summary 테이블/데이터 없음 — `python load_valuation_summary.py` 실행 필요",
        }

    if sort in ("grade", "confidence"):
        data.sort(key=lambda r: (_CONF_RANK.get(r.get("dcf_confidence"), 9), r.get("corp_name") or ""))
    elif sort == "wacc":
        data.sort(key=lambda r: (r.get("wacc") is None, r.get("wacc") or 0))
    elif sort == "name":
        data.sort(key=lambda r: r.get("corp_name") or "")
    else:  # upside (기본) — 상승여력 높은 순, 무효(NULL)는 맨 뒤
        data.sort(key=lambda r: (r.get("upside_pct") is None, -(r.get("upside_pct") or 0)))

    as_of = max((r.get("as_of_date") or "") for r in data) if data else ""
    model = (data[0].get("model_version") if data else "") or ""
    valid = sum(1 for r in data if r.get("fair_price") is not None)
    return {
        "count"        : len(data),
        "valid_count"  : valid,        # 적정가 산출된 종목 수
        "as_of"        : as_of,
        "model_version": model,
        "source"       : "filmn9.db · valuation_summary (엔진 v8)",
        "stocks"       : data,
    }


@router.get("/valuation-summary/{code}")
def get_one(code: str):
    """단일 종목 요약."""
    try:
        with _conn() as con:
            row = con.execute(
                f"SELECT {_COLS} FROM valuation_summary WHERE stock_code = ?", (code,)
            ).fetchone()
    except sqlite3.OperationalError:
        raise HTTPException(status_code=404, detail="valuation_summary 테이블 없음")
    if not row:
        raise HTTPException(status_code=404, detail=f"{code} 밸류 요약 없음")
    return _enrich(dict(row))


@router.get("/valuation-full/{code}")
def get_full(code: str):
    """엔진 v8 합본(통합) 평가 JSON 그대로 반환 — index.html 대시보드 렌더용.

    data/valuation_inbox/repr20_export/data/{code}_*.json (산업 대표 20종).
    없으면 404 → 프론트가 "데이터 준비중" 표시.
    """
    code = code.strip()
    # 1) repr20_export (산업 대표 20종) 우선
    matches = sorted(_FULL_DIR.glob(f"{code}_*.json")) if _FULL_DIR.exists() else []
    # 2) 없으면 전 종목 엔진 통합 JSON (valuation_{code}_{YYYYMMDD}.json) — 최신 날짜 우선
    if not matches and _ENGINE_RESULTS.exists():
        matches = sorted(_ENGINE_RESULTS.glob(f"valuation_{code}_*.json"), reverse=True)
    if not matches:
        raise HTTPException(status_code=404, detail=f"{code} 평가 데이터 없음 (밸류에이션 미산출 종목)")
    try:
        return json.loads(matches[0].read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"JSON 로드 실패: {e}")
