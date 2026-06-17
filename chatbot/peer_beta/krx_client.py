"""KRX OpenAPI 클라이언트 (data-dbg.krx.co.kr).

엔드포인트 (명세서 Spec 5/6/7 기준):
  - 주식 (KOSPI):  /svc/apis/sto/stk_bydd_trd?basDd=YYYYMMDD
  - 지수 (KOSPI):  /svc/apis/idx/kospi_dd_trd?basDd=YYYYMMDD
  - 지수 (KOSDAQ): /svc/apis/idx/kosdaq_dd_trd?basDd=YYYYMMDD
  - 주식 (KOSDAQ): 명세서 미확인. 일반적으로 /svc/apis/sto/ksq_bydd_trd 로 알려져 있음.
                  POC 4사는 모두 KOSPI 이므로 호출되지 않으나, 호출 시 응답 구조는
                  KOSPI 주식과 동일하다고 가정 (동일 파서 사용).
헤더: AUTH_KEY: <발급키>

KRX 응답 표준 (Spec 5):
  주식  : OutBlock_1[*] = {BAS_DD, ISU_CD, ISU_NM, MKT_NM, SECT_TP_NM,
                          TDD_CLSPRC, CMPPREVDD_PRC, FLUC_RT,
                          TDD_OPNPRC, TDD_HGPRC, TDD_LWPRC,
                          ACC_TRDVOL, ACC_TRDVAL, MKTCAP, LIST_SHRS}
  지수  : OutBlock_1[*] = {BAS_DD, IDX_CLSS, IDX_NM, CLSPRC_IDX, ...}

주의: ISU_CD 는 보통 12자리 표준코드 (예: "KR7090430005").
      단축코드(6자리) 매칭을 위해 [3:9] 슬라이싱을 수행합니다.
      ISU_SRT_CD(단축코드)가 동봉되면 그것을 우선 사용합니다.

휴장일/거래정지: OutBlock_1 가 비거나, 가격 필드가 "-" 로 채워질 수 있습니다.

캐시 정책:
  - 일자별로 data/raw/<category>_<market>_<YYYYMMDD>.json 로 저장
  - 정상 응답(OutBlock_1 비어있지 않음)만 캐시 → 영구 재사용
  - 빈 응답(휴장/거래미마감)은 캐시하지 않음 → 다음 실행에서 재시도
  - 다음 주 실행 시(예: 5/8 -> 5/15) 새 일자만 API 호출, 기존 일자는 디스크 캐시 HIT

응답 구조가 다를 경우 _parse_stock_row / _parse_index_row 두 함수만 수정하면 됩니다.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Optional

import requests

from .calendar_utils import as_yyyymmdd, previous_business_day_candidates
from .config import ENV_KEY_KRX, RAW_DIR


BASE_URL = "https://data-dbg.krx.co.kr/svc/apis"

ENDPOINTS = {
    ("stock", "KOSPI"):  f"{BASE_URL}/sto/stk_bydd_trd",
    ("stock", "KOSDAQ"): f"{BASE_URL}/sto/ksq_bydd_trd",
    ("index", "KOSPI"):  f"{BASE_URL}/idx/kospi_dd_trd",
    ("index", "KOSDAQ"): f"{BASE_URL}/idx/kosdaq_dd_trd",
    # 종목기본정보 (Spec 7/8) — 상장일·증권구분·주식종류·액면가
    ("isu_base", "KOSPI"):  f"{BASE_URL}/sto/stk_isu_base_info",
    ("isu_base", "KOSDAQ"): f"{BASE_URL}/sto/ksq_isu_base_info",
}

TIMEOUT = 30
RETRY = 2
SLEEP_BETWEEN_RETRY = 1.0


# ---- 캐시 통계 ------------------------------------------------------------
class _CacheStats:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.hits        = 0
        self.misses      = 0
        self.empty_skips = 0

    def to_dict(self) -> dict:
        return {"hits": self.hits, "misses": self.misses, "empty_skips": self.empty_skips}


CACHE_STATS = _CacheStats()


def reset_cache_stats() -> None:
    CACHE_STATS.reset()


def get_cache_stats() -> dict:
    return CACHE_STATS.to_dict()


# ---- 인증 -----------------------------------------------------------------
def _get_auth_key() -> str:
    key = os.getenv(ENV_KEY_KRX)
    if not key:
        raise RuntimeError(f"환경변수 '{ENV_KEY_KRX}' 가 설정되어 있지 않습니다. .env 확인 필요.")
    return key


def _headers() -> dict:
    return {"AUTH_KEY": _get_auth_key()}


# ---- 응답 행 추출 ---------------------------------------------------------
def _rows(data: dict) -> list[dict]:
    return data.get("OutBlock_1") or data.get("OutBlock") or []


# ---- 캐시 + API 호출 ------------------------------------------------------
def _cache_path(category: str, market: str, day: date) -> Path:
    return RAW_DIR / f"{category}_{market}_{as_yyyymmdd(day)}.json"


def _fetch_day_raw(category: str, market: str, day: date, *,
                   force: bool = False) -> dict:
    """하루치 raw JSON을 받아 캐시.

    - 정상 응답: 디스크에 영구 저장 → 재호출 시 HIT
    - 빈 응답  : 저장하지 않음 → 다음 실행에서 재시도
    """
    cache = _cache_path(category, market, day)
    if cache.exists() and not force:
        with cache.open("r", encoding="utf-8") as f:
            data = json.load(f)
        CACHE_STATS.hits += 1
        return data

    url = ENDPOINTS[(category, market)]
    params = {"basDd": as_yyyymmdd(day)}

    last_exc: Optional[Exception] = None
    for attempt in range(RETRY + 1):
        try:
            r = requests.get(url, headers=_headers(), params=params, timeout=TIMEOUT)
            r.raise_for_status()
            data = r.json()
            break
        except Exception as e:
            last_exc = e
            if attempt < RETRY:
                time.sleep(SLEEP_BETWEEN_RETRY)
            else:
                # ★ Graceful — 전체 중단 대신 빈 응답 반환 + warning
                #    (휴장일·API 장애·권한 문제 등 모두 빈 응답으로 처리해 다른 일자는 진행)
                import warnings
                warnings.warn(
                    f"KRX 호출 실패 ({category}/{market}/{day}): {str(e)[:120]} - "
                    f"빈 응답으로 진행"
                )
                return {"OutBlock_1": []}

    CACHE_STATS.misses += 1

    if len(_rows(data)) == 0:
        CACHE_STATS.empty_skips += 1
        return data

    cache.parent.mkdir(parents=True, exist_ok=True)
    with cache.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return data


# ---- 응답 파서 ------------------------------------------------------------
def _to_short_code(raw_code: str) -> str:
    """KR7090430005 -> 090430. 이미 단축이면 그대로 (zfill 6)."""
    s = str(raw_code).strip()
    if len(s) == 12 and s.upper().startswith("KR"):
        return s[3:9]
    return s.zfill(6)


def _parse_stock_row(row: dict) -> Optional[dict]:
    def _get(*keys):
        for k in keys:
            if k in row and row[k] not in ("", None):
                return row[k]
        return None

    raw_code  = _get("ISU_SRT_CD", "ISU_CD")
    close_raw = _get("TDD_CLSPRC", "CLSPRC")
    if raw_code is None or close_raw is None:
        return None

    if isinstance(close_raw, str):
        close_clean = close_raw.replace(",", "").strip()
        if close_clean in ("", "-"):
            return None
    else:
        close_clean = close_raw
    try:
        close = float(close_clean)
    except (TypeError, ValueError):
        return None

    return {
        "date":   _get("BAS_DD", "TRD_DD"),
        "code":   _to_short_code(raw_code),
        "name":   _get("ISU_NM", "ISU_ABBRV"),
        "market": _get("MKT_NM"),
        "close":  close,
    }


def _parse_index_row(row: dict) -> Optional[dict]:
    def _get(*keys):
        for k in keys:
            if k in row and row[k] not in ("", None):
                return row[k]
        return None

    name      = _get("IDX_NM", "INDX_NM")
    close_raw = _get("CLSPRC_IDX", "CLSPRC")
    if name is None or close_raw is None:
        return None

    if isinstance(close_raw, str):
        close_clean = close_raw.replace(",", "").strip()
        if close_clean in ("", "-"):
            return None
    else:
        close_clean = close_raw
    try:
        close = float(close_clean)
    except (TypeError, ValueError):
        return None

    return {
        "date":        _get("BAS_DD", "TRD_DD"),
        "index_class": _get("IDX_CLSS"),
        "index_name":  name,
        "close":       close,
    }


# ---- 고수준 API -----------------------------------------------------------
@dataclass
class ClosePoint:
    asked_date: date
    actual_date: date
    code_or_name: str
    close: float
    market: str

    def to_dict(self) -> dict:
        return {
            "asked_date":  self.asked_date.isoformat(),
            "actual_date": self.actual_date.isoformat(),
            "key":         self.code_or_name,
            "close":       self.close,
            "market":      self.market,
        }


def fetch_stock_close(ticker: str, market: str, day: date,
                      *, max_lookback: int = 5) -> Optional[ClosePoint]:
    target_code = _to_short_code(ticker)
    for cand in previous_business_day_candidates(day, max_lookback):
        data = _fetch_day_raw("stock", market, cand)
        rows = _rows(data)
        for raw in rows:
            parsed = _parse_stock_row(raw)
            if parsed is None:
                continue
            if parsed["code"] == target_code:
                return ClosePoint(asked_date=day, actual_date=cand,
                                  code_or_name=parsed["code"], close=parsed["close"],
                                  market=market)
    return None


def fetch_index_close(market: str, day: date,
                      index_name_hint: Optional[str] = None,
                      *, max_lookback: int = 5) -> Optional[ClosePoint]:
    preferred = "코스피" if market == "KOSPI" else "코스닥"
    target_names = {index_name_hint, preferred} if index_name_hint else {preferred, "코스피", "코스닥"}
    for cand in previous_business_day_candidates(day, max_lookback):
        data = _fetch_day_raw("index", market, cand)
        rows = _rows(data)
        best: Optional[dict] = None
        for raw in rows:
            parsed = _parse_index_row(raw)
            if parsed is None:
                continue
            if parsed["index_name"] == preferred:
                best = parsed
                break
            if parsed["index_name"] in target_names and best is None:
                best = parsed
        if best is not None:
            return ClosePoint(asked_date=day, actual_date=cand,
                              code_or_name=best["index_name"], close=best["close"],
                              market=market)
    return None


def fetch_stock_weekly(ticker: str, market: str,
                       fridays: Iterable[date]) -> list[ClosePoint]:
    out: list[ClosePoint] = []
    seen_actual: set[date] = set()
    for fri in fridays:
        cp = fetch_stock_close(ticker, market, fri)
        if cp is None:
            continue
        if cp.actual_date in seen_actual:
            continue
        seen_actual.add(cp.actual_date)
        out.append(cp)
    return out


def fetch_index_weekly(market: str,
                       fridays: Iterable[date]) -> list[ClosePoint]:
    out: list[ClosePoint] = []
    seen_actual: set[date] = set()
    for fri in fridays:
        cp = fetch_index_close(market, fri)
        if cp is None:
            continue
        if cp.actual_date in seen_actual:
            continue
        seen_actual.add(cp.actual_date)
        out.append(cp)
    return out


def fetch_isu_base_info(market: str, day: date,
                        *, max_lookback: int = 7) -> list[dict]:
    """종목기본정보 (Spec 7/8) 전종목 — 상장일·증권구분·주식종류·액면가.

    Returns: [{ticker, name, list_dd, secugrp, stkcert_tp, parval, list_shrs, market}, ...]
             빈 응답(휴장/권한)이면 [] (graceful).
    응답 필드: ISU_CD, ISU_SRT_CD, ISU_NM, LIST_DD, MKT_TP_NM,
               SECUGRP_NM(증권구분), KIND_STKCERT_TP_NM(주식종류), PARVAL, LIST_SHRS
    """
    for cand in previous_business_day_candidates(day, max_lookback):
        data = _fetch_day_raw("isu_base", market, cand)
        rows = _rows(data)
        if not rows:
            continue
        out = []
        for raw in rows:
            code = raw.get("ISU_SRT_CD") or raw.get("ISU_CD") or ""
            code = _to_short_code(code)
            if not code:
                continue
            out.append({
                "ticker":     code,
                "name":       raw.get("ISU_NM", ""),
                "list_dd":    raw.get("LIST_DD", ""),
                "secugrp":    raw.get("SECUGRP_NM", ""),       # 증권구분 (주권/ETF/리츠 등)
                "stkcert_tp": raw.get("KIND_STKCERT_TP_NM", ""),  # 주식종류 (보통주/우선주)
                "parval":     raw.get("PARVAL", ""),
                "list_shrs":  raw.get("LIST_SHRS", ""),
                "market":     market,
            })
        if out:
            return out
    return []
