"""
api/routers/ohlcv.py
====================
주가 OHLCV 엔드포인트 (SQLite 백엔드)

엔드포인트
----------
GET /api/ohlcv/{stock_code}                       OHLCV 전체 (기간 필터 가능)
GET /api/ohlcv/{stock_code}/latest                최신 가격 + 등락
"""
from fastapi import APIRouter, HTTPException, Query
from pathlib import Path
import sqlite3

router = APIRouter()
_ROOT    = Path(__file__).resolve().parent.parent.parent
_DB_PATH = _ROOT / "data" / "filmn9.db"


def _conn():
    if not _DB_PATH.exists():
        raise HTTPException(
            status_code=500,
            detail="filmn9.db 없음. db/init_db.py 실행 필요"
        )
    c = sqlite3.connect(_DB_PATH)
    c.row_factory = sqlite3.Row
    return c


@router.get("/ohlcv/{stock_code}")
def get_ohlcv(
    stock_code: str,
    from_date: str = Query(None, description="시작일 YYYY-MM-DD"),
    to_date:   str = Query(None, description="종료일 YYYY-MM-DD"),
):
    """
    OHLCV 데이터 (Lightweight Charts 호환 형식).

    응답: { stock_code, corp_name, from_date, to_date, count,
            data: [{date, open, high, low, close, volume}, ...] }
    """
    with _conn() as conn:
        # 기업명 조회
        ci_row = conn.execute(
            "SELECT corp_name FROM company_info WHERE stock_code = ?",
            (stock_code,)
        ).fetchone()
        corp_name = ci_row["corp_name"] if ci_row else None

        # OHLCV 쿼리 (기간 필터)
        sql    = "SELECT date, open, high, low, close, volume FROM ohlcv WHERE stock_code = ?"
        params = [stock_code]
        if from_date:
            sql += " AND date >= ?"
            params.append(from_date)
        if to_date:
            sql += " AND date <= ?"
            params.append(to_date)
        sql += " ORDER BY date ASC"

        rows = conn.execute(sql, params).fetchall()

    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"{stock_code} OHLCV 없음. build_ohlcv.py + load_to_db.py 먼저 실행하세요."
        )

    data = [dict(r) for r in rows]
    return {
        "stock_code": stock_code,
        "corp_name" : corp_name,
        "from_date" : data[0]["date"],
        "to_date"   : data[-1]["date"],
        "count"     : len(data),
        "data"      : data,
    }


@router.get("/ohlcv/{stock_code}/latest")
def get_latest_price(stock_code: str):
    """
    최신 거래일 + 등락. 헤더 현재가 표시용.
    """
    with _conn() as conn:
        # 기업명
        ci = conn.execute(
            "SELECT corp_name FROM company_info WHERE stock_code = ?",
            (stock_code,)
        ).fetchone()

        # 최근 2거래일
        rows = conn.execute("""
            SELECT date, open, high, low, close, volume
            FROM ohlcv WHERE stock_code = ?
            ORDER BY date DESC LIMIT 2
        """, (stock_code,)).fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail=f"{stock_code} OHLCV 없음")

    latest = rows[0]
    prev   = rows[1] if len(rows) > 1 else None

    change     = (latest["close"] - prev["close"]) if prev else 0
    change_pct = round(change / prev["close"] * 100, 2) if prev and prev["close"] else 0.0

    return {
        "stock_code" : stock_code,
        "corp_name"  : ci["corp_name"] if ci else None,
        "date"       : latest["date"],
        "close"      : latest["close"],
        "open"       : latest["open"],
        "high"       : latest["high"],
        "low"        : latest["low"],
        "volume"     : latest["volume"],
        "change"     : change,
        "change_pct" : change_pct,
        "_source"    : "KRX (pykrx)",
    }
