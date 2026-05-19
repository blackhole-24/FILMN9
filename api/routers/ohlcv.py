"""
routers/ohlcv.py
주가 OHLCV 엔드포인트
"""
from fastapi import APIRouter, HTTPException, Query
from pathlib import Path
import json

router = APIRouter()
_ROOT   = Path(__file__).resolve().parent.parent.parent   # FILMN9/
_PARSED = _ROOT / "data" / "parsed"


def _read_ohlcv(code: str) -> dict:
    path = _PARSED / code / "ohlcv.json"
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"{code} ohlcv.json 없음. build_ohlcv.py를 먼저 실행하세요."
        )
    return json.loads(path.read_text(encoding="utf-8"))


@router.get("/ohlcv/{code}")
def get_ohlcv(
    code: str,
    from_date: str = Query(None, description="시작일 YYYY-MM-DD"),
    to_date:   str = Query(None, description="종료일 YYYY-MM-DD"),
):
    """
    OHLCV 데이터 반환. Lightweight Charts 바로 사용 가능한 형식.

    - from_date / to_date 로 기간 필터링 가능 (없으면 전체)
    - 응답: { stock_code, corp_name, count, data: [{date, open, high, low, close, volume}] }
    """
    raw     = _read_ohlcv(code)
    records = raw.get("data", [])

    # 기간 필터링
    if from_date:
        records = [r for r in records if r["date"] >= from_date]
    if to_date:
        records = [r for r in records if r["date"] <= to_date]

    return {
        "stock_code": raw.get("stock_code"),
        "corp_name" : raw.get("corp_name"),
        "from_date" : records[0]["date"]  if records else None,
        "to_date"   : records[-1]["date"] if records else None,
        "count"     : len(records),
        "data"      : records,
    }


@router.get("/ohlcv/{code}/latest")
def get_latest_price(code: str):
    """
    가장 최근 거래일 단일 레코드 반환 (헤더 현재가 표시용).
    """
    raw     = _read_ohlcv(code)
    records = raw.get("data", [])
    if not records:
        raise HTTPException(status_code=404, detail="데이터 없음")
    latest = records[-1]
    prev   = records[-2] if len(records) >= 2 else None

    change     = latest["close"] - prev["close"] if prev else 0
    change_pct = round(change / prev["close"] * 100, 2) if prev else 0.0

    return {
        "stock_code"   : raw.get("stock_code"),
        "corp_name"    : raw.get("corp_name"),
        "date"         : latest["date"],
        "close"        : latest["close"],
        "open"         : latest["open"],
        "high"         : latest["high"],
        "low"          : latest["low"],
        "volume"       : latest["volume"],
        "change"       : change,
        "change_pct"   : change_pct,
        "_generated_at": raw.get("_generated_at"),
        "_source"      : raw.get("_source"),
    }
