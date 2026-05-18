"""Phase 3-D — ECOS API 국고채 10년물 SPOT 금리 (Rf).

ECOS 통계표:
  - 코드: 817Y002 (시장금리)
  - 항목코드1: 010210000 (국고채 10년)
  - 주기: D (일별)

설계서 v4 §1.1: "T일 데이터 미공개 시 직전 영업일 값 사용"
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import requests

_VAR_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_VAR_ROOT))

from peer_beta.calendar_utils import parse_date, as_yyyymmdd

from .config import ENV_KEY_ECOS

ECOS_BASE = "https://ecos.bok.or.kr/api"
STAT_CODE = "817Y002"
ITEM_CODE = "010210000"   # 국고채 10년


def _ecos_key() -> str:
    key = os.getenv(ENV_KEY_ECOS)
    if not key:
        raise RuntimeError(f"환경변수 '{ENV_KEY_ECOS}' 가 설정되어 있지 않습니다.")
    return key


def fetch_rf(eval_date: Optional[date] = None,
             max_lookback_days: int = 7,
             verbose: bool = True) -> dict:
    """T 기준 직전 영업일 국고채 10년물 SPOT (%).

    Returns:
        {"rf": 0.0321, "rf_pct": 3.21, "as_of_date": "2026-05-13", "stat_name": "..."}
    """
    eval_d = parse_date(eval_date)

    start = eval_d - timedelta(days=max_lookback_days)
    end   = eval_d

    url = (f"{ECOS_BASE}/StatisticSearch/{_ecos_key()}/json/kr/1/100/"
           f"{STAT_CODE}/D/{as_yyyymmdd(start)}/{as_yyyymmdd(end)}/{ITEM_CODE}")

    r = requests.get(url, timeout=30)
    r.raise_for_status()
    data = r.json()

    if "StatisticSearch" not in data:
        raise RuntimeError(f"ECOS API 응답 오류: {data}")
    rows = data["StatisticSearch"].get("row", [])
    if not rows:
        raise RuntimeError(f"ECOS Rf 데이터 없음 ({start} ~ {end})")

    # 가장 최근 일자
    rows_sorted = sorted(rows, key=lambda x: x["TIME"], reverse=True)
    latest = rows_sorted[0]
    rf_pct = float(latest["DATA_VALUE"])

    result = {
        "rf": rf_pct / 100,
        "rf_pct": rf_pct,
        "as_of_date": latest["TIME"][:4] + "-" + latest["TIME"][4:6] + "-" + latest["TIME"][6:],
        "stat_name": latest.get("ITEM_NAME1", "국고채 10년"),
        "source":    "ECOS API (817Y002 / 010210000)",
    }
    if verbose:
        print(f"  Rf ({result['as_of_date']}) = {rf_pct:.3f}%")
    return result


if __name__ == "__main__":
    fetch_rf(verbose=True)
