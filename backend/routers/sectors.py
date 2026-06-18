"""
api/routers/sectors.py
======================
WICS 섹터 기반 종목 탐색 (산업 분류 탭).

엔드포인트
----------
  GET /api/sectors                       섹터 목록 (종목 수 내림차순)
  GET /api/sectors/{sector_name}/stocks  섹터 내 종목 목록 (stock_code 오름차순)

데이터 소스
----------
  ticker_universe.csv  (SPAC·우선주 제외 → 활성 2,588종목 / 78섹터)
  ※ 실데이터만 사용. 임의 생성(Mock) 없음.
"""
from __future__ import annotations

import csv
import random
import sqlite3
from collections import Counter
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter()

_ROOT = Path(__file__).resolve().parent.parent.parent   # FILMN9/
_CSV  = _ROOT / "ticker_universe.csv"
_DB   = _ROOT / "data" / "filmn9.db"

_cache: list[dict] | None = None


def _truthy(v) -> bool:
    return str(v).strip().lower() in ("true", "1", "y", "yes")


def _valid_codes() -> set[str]:
    """company_info(데이터 보유) 종목코드 집합. 산업분류에 데이터 없는 코드(우선주 등) 제외용."""
    try:
        from backend.db import connect
        con = connect()
        codes = {r["stock_code"] for r in con.execute("SELECT stock_code FROM company_info")}
        con.close()
        return codes
    except Exception:
        return set()   # DB 불가 시 필터 미적용(fail-open)


_LIQ_CACHE = None
_HALT_CACHE = None


def _liquidity() -> dict:
    """종목별 최근 거래대금(close×volume) — 인기/규모(시총 대용) 정렬용. 1회 캐시."""
    global _LIQ_CACHE
    if _LIQ_CACHE is None:
        _LIQ_CACHE = {}
        try:
            from backend.db import connect
            con = connect()
            mx_row = con.execute("SELECT MAX(date) AS d FROM ohlcv").fetchone()
            mx = mx_row["d"] if mx_row else None
            if mx:
                for r in con.execute(
                    "SELECT stock_code, close, volume FROM ohlcv WHERE date = ?", (mx,)
                ).fetchall():
                    c, v = r["close"], r["volume"]
                    if c and v:
                        _LIQ_CACHE[r["stock_code"]] = c * v
            con.close()
        except Exception:
            pass
    return _LIQ_CACHE


def _halted() -> set:
    """거래 불가 종목(거래정지 HALT·상장폐지 DELISTED·관리종목 ADMIN) — 추천에서 제외용. 1회 캐시."""
    global _HALT_CACHE
    if _HALT_CACHE is None:
        _HALT_CACHE = set()
        try:
            from backend.db import connect
            con = connect()
            for r in con.execute(
                "SELECT stock_code FROM stock_status WHERE status IN ('HALT','DELISTED','ADMIN')"
            ).fetchall():
                _HALT_CACHE.add(r["stock_code"])
            con.close()
        except Exception:
            pass
    return _HALT_CACHE


def _load() -> list[dict]:
    """ticker_universe.csv 로드 (SPAC·우선주·섹터없음 제외). 1회 캐시."""
    global _cache
    if _cache is not None:
        return _cache
    valid = _valid_codes()   # company_info 등록 종목만(데이터 없는 우선주 등 제외)
    rows: list[dict] = []
    if _CSV.exists():
        with open(_CSV, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if _truthy(r.get("is_spac")) or _truthy(r.get("is_preferred")):
                    continue
                wics = (r.get("wics") or "").strip()
                if not wics:
                    continue
                code = (r.get("stock_code") or "").strip()
                if valid and code not in valid:   # 데이터 없는 코드(우선주 등) 산업분류서 제외
                    continue
                rows.append({
                    "stock_code": (r.get("stock_code") or "").strip(),
                    "corp_name" : (r.get("corp_name")  or "").strip(),
                    "market"    : (r.get("market")     or "").strip(),
                    "wics"      : wics,
                    "industry"  : (r.get("industry")   or "").strip(),
                })
    _cache = rows
    return _cache


@router.get("/sectors")
def list_sectors():
    """WICS 섹터 목록 + 섹터별 종목 수 (종목 수 내림차순)."""
    rows = _load()
    counts = Counter(r["wics"] for r in rows)
    liq = _liquidity()
    sector_liq: dict = {}
    for r in rows:
        sector_liq[r["wics"]] = sector_liq.get(r["wics"], 0) + liq.get(r["stock_code"], 0)
    # 업종을 총 거래대금(시총 대용) 내림차순으로 정렬
    order = sorted(counts.keys(), key=lambda s: sector_liq.get(s, 0), reverse=True)
    sectors = [{"sector_name": k, "count": counts[k]} for k in order]
    return {
        "total_stocks" : len(rows),
        "total_sectors": len(sectors),
        "sectors"      : sectors,
    }


@router.get("/sectors/{sector_name}/stocks")
def list_stocks_in_sector(sector_name: str):
    """특정 WICS 섹터에 속한 종목 목록 (stock_code 오름차순)."""
    rows   = _load()
    subset = [r for r in rows if r["wics"] == sector_name]
    if not subset:
        raise HTTPException(status_code=404, detail=f"섹터 '{sector_name}' 없음")
    liq = _liquidity()
    subset.sort(key=lambda r: liq.get(r["stock_code"], 0), reverse=True)   # 거래대금(시총 대용) 높은 순
    return {
        "sector_name": sector_name,
        "count"      : len(subset),
        "stocks"     : [
            {"stock_code": r["stock_code"], "corp_name": r["corp_name"], "market": r["market"]}
            for r in subset
        ],
    }


def _valuation_pool() -> list[dict]:
    """밸류에이션·DCF가 충실히 산출된 종목 풀 (valuation_summary 적정가 보유 = 정보 부실 종목 제외).
    캐러셀에 '정보 빠진 종목'이 안 나오게 하기 위함."""
    try:
        from backend.db import connect
        con = connect()
        rows = con.execute(
            "SELECT stock_code, corp_name, market, industry FROM valuation_summary "
            "WHERE fair_price IS NOT NULL AND corp_name IS NOT NULL"
        ).fetchall()
        con.close()
        wics = {r["stock_code"]: r["wics"] for r in _load()}   # 코드→WICS 업종명
        return [{"stock_code": r["stock_code"], "corp_name": r["corp_name"],
                 "market": r["market"] or "", "tag": wics.get(r["stock_code"], "")} for r in rows]
    except Exception:
        return []


@router.get("/featured")
def featured(n: int = 60, source: str = "val"):
    """메인 슬라이드 캐러셀용 랜덤 추천 종목 풀. 매 호출마다 다른 종목.
    source=val(기본): 밸류에이션·DCF 충실 종목만(적정가 보유 1,308종) → 정보 부실 종목 제외.
    source=all: 기존(데이터 보유 전 종목)."""
    pool = _valuation_pool() if source == "val" else []
    if not pool:                       # 밸류 풀 비었으면 폴백(전 종목)
        pool = [{"stock_code": r["stock_code"], "corp_name": r["corp_name"],
                 "market": r["market"], "tag": r["wics"]} for r in _load()]
    halted = _halted()
    pool = [p for p in pool if p["stock_code"] not in halted]              # 거래정지·상폐·관리 제외
    liq = _liquidity()
    pool.sort(key=lambda p: liq.get(p["stock_code"], 0), reverse=True)     # 거래대금(인기) 높은 순
    sample = pool[:min(n, len(pool))]
    return {"count": len(sample), "stocks": sample}
