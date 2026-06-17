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

# ★ 캐시 디렉터리 — eval_date 별 영구 저장 (재호출 비용 0)
import json as _json
ECOS_CACHE_DIR = _VAR_ROOT / "valuation_engine" / "data" / "ecos"
ECOS_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _ecos_key() -> str:
    key = os.getenv(ENV_KEY_ECOS)
    if not key:
        raise RuntimeError(f"환경변수 '{ENV_KEY_ECOS}' 가 설정되어 있지 않습니다.")
    return key


def _cache_path(eval_d: date) -> Path:
    """eval_date 별 캐시 파일 경로 (예: rf_20260520.json)."""
    return ECOS_CACHE_DIR / f"rf_{eval_d.strftime('%Y%m%d')}.json"


def _persist_rf_to_db(result: dict) -> None:
    """write-through: rf_rates 테이블에도 기록. 읽기는 파일/라이브 유지 → 매일 갱신 불변."""
    try:
        from valuation_engine import db
        db.save_rf(result["as_of_date"], result["rf"],
                   source=result.get("source", "ECOS"),
                   detail={"rf_pct": result.get("rf_pct"),
                           "stat_name": result.get("stat_name")})
    except Exception:
        pass


def fetch_rf(eval_date: Optional[date] = None,
             max_lookback_days: int = 7,
             use_cache: bool = True,
             verbose: bool = True) -> dict:
    """T 기준 직전 영업일 국고채 10년물 SPOT (%).

    캐시 정책:
      - rf_<YYYYMMDD>.json 존재 시 즉시 로드 (API skip)
      - 미존재 시 ECOS API 호출 + 결과를 캐시에 저장

    Returns:
        {"rf": 0.0321, "rf_pct": 3.21, "as_of_date": "2026-05-13", "stat_name": "..."}
    """
    eval_d = parse_date(eval_date)
    cpath  = _cache_path(eval_d)

    # ── 1) 캐시 hit ──
    if use_cache and cpath.exists():
        try:
            with cpath.open("r", encoding="utf-8") as f:
                cached = _json.load(f)
            if verbose:
                print(f"  Rf ({cached['as_of_date']}) = {cached['rf_pct']:.3f}%  [cache hit]")
            _persist_rf_to_db(cached)
            return cached
        except Exception:
            pass   # 캐시 깨졌으면 API 호출로 폴백

    # ── 2) API 호출 ──
    start = eval_d - timedelta(days=max_lookback_days)
    end   = eval_d

    url = (f"{ECOS_BASE}/StatisticSearch/{_ecos_key()}/json/kr/1/100/"
           f"{STAT_CODE}/D/{as_yyyymmdd(start)}/{as_yyyymmdd(end)}/{ITEM_CODE}")

    r = requests.get(url, timeout=30)
    r.raise_for_status()
    try:
        data = r.json()
    except ValueError as e:
        raise RuntimeError(f"ECOS API 응답 JSON 파싱 실패: {e}") from e

    # ★ H-7: 스키마 변경 대비 안전한 파싱
    # 정상 응답: {"StatisticSearch": {"list_total_count": N, "row": [...]}}
    # 에러 응답: {"RESULT": {"CODE": "INFO-200", "MESSAGE": "..."}}
    if "RESULT" in data and "CODE" in data.get("RESULT", {}):
        code = data["RESULT"]["CODE"]
        msg = data["RESULT"].get("MESSAGE", "")
        raise RuntimeError(f"ECOS API 에러 응답 [{code}]: {msg}")

    container = data.get("StatisticSearch")
    if not isinstance(container, dict):
        raise RuntimeError(f"ECOS API 응답에 StatisticSearch 없음: {str(data)[:200]}")
    rows = container.get("row")
    if not isinstance(rows, list) or not rows:
        raise RuntimeError(f"ECOS Rf 데이터 없음 ({start} ~ {end})")

    # 필수 필드 검증 — TIME / DATA_VALUE
    rows_valid = [r for r in rows if isinstance(r, dict) and r.get("TIME") and r.get("DATA_VALUE")]
    if not rows_valid:
        raise RuntimeError(f"ECOS Rf 응답에 유효 행 없음 (TIME/DATA_VALUE 누락)")

    rows_sorted = sorted(rows_valid, key=lambda x: str(x.get("TIME", "")), reverse=True)
    latest = rows_sorted[0]
    try:
        rf_pct = float(latest["DATA_VALUE"])
    except (ValueError, TypeError) as e:
        raise RuntimeError(f"ECOS Rf 값 파싱 실패: {latest.get('DATA_VALUE')} ({e})")

    result = {
        "rf": rf_pct / 100,
        "rf_pct": rf_pct,
        "as_of_date": latest["TIME"][:4] + "-" + latest["TIME"][4:6] + "-" + latest["TIME"][6:],
        "stat_name": latest.get("ITEM_NAME1", "국고채 10년"),
        "source":    "ECOS API (817Y002 / 010210000)",
    }

    # ── 3) 캐시 저장 ──
    try:
        with cpath.open("w", encoding="utf-8") as f:
            _json.dump(result, f, ensure_ascii=False, indent=2)
    except Exception as e:
        if verbose:
            print(f"  [WARN] Rf 캐시 저장 실패: {e}")

    if verbose:
        print(f"  Rf ({result['as_of_date']}) = {rf_pct:.3f}%  [API + cached]")
    _persist_rf_to_db(result)
    return result


if __name__ == "__main__":
    fetch_rf(verbose=True)
