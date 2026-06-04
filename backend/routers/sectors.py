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
        con = sqlite3.connect(_DB)
        codes = {r[0] for r in con.execute("SELECT stock_code FROM company_info")}
        con.close()
        return codes
    except Exception:
        return set()   # DB 불가 시 필터 미적용(fail-open)


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
    sectors = [{"sector_name": k, "count": v} for k, v in counts.most_common()]
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
    subset.sort(key=lambda r: r["stock_code"])
    return {
        "sector_name": sector_name,
        "count"      : len(subset),
        "stocks"     : [
            {"stock_code": r["stock_code"], "corp_name": r["corp_name"], "market": r["market"]}
            for r in subset
        ],
    }


@router.get("/featured")
def featured(n: int = 60):
    """메인 슬라이드 캐러셀용 랜덤 추천 종목 풀 (데이터 보유 종목 중). 매 호출마다 다른 종목."""
    rows = _load()
    k = min(n, len(rows))
    sample = random.sample(rows, k) if rows else []
    return {
        "count": k,
        "stocks": [
            {"stock_code": r["stock_code"], "corp_name": r["corp_name"],
             "market": r["market"], "tag": r["wics"]}
            for r in sample
        ],
    }
