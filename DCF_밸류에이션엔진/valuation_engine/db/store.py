"""SQLite 정형/수치 데이터 저장소 — 모델 데이터의 단일 접근 계층(쓰기).

설계(사용자 결정):
  · 정형/수치 데이터 → SQLite (data/valuation.db)
  · 텍스트 데이터    → MongoDB-ready JSONL (db/mongo_json.py)
  · 임베딩 벡터      → ChromaDB 유지(여기서 다루지 않음)
  · 읽기는 'DB 우선 + 파일 폴백' (db/__init__.py 의 통합 API)
  · 기존 캐시 파일은 보존(마이그레이션은 복제)

동시성:
  · WAL 모드 + busy_timeout 으로 단일 머신 다중 스레드(api.py 비동기 워커) 안전.
  · 각 호출마다 짧은 연결을 열고 닫음(스레드 안전 단순화).

이 모듈은 '쓰기/스키마/저수준 조회'만 담당. 폴백·도메인 로직은 __init__.py.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import numpy as np
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

_VAR_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = _VAR_ROOT / "data" / "valuation.db"

_INIT_LOCK = threading.Lock()
_INITIALIZED = False

# ─────────────────────────────────────────────────────────────
# 스키마 (14 테이블) — 정형/수치 전용. 상세 dict 는 JSON 텍스트 컬럼.
# ─────────────────────────────────────────────────────────────
_SCHEMA = """
-- companies: 팀원 ticker_universe.csv 컬럼에 맞춤 + 본 모델 확장 컬럼
CREATE TABLE IF NOT EXISTS companies (
    stock_code        TEXT PRIMARY KEY,
    corp_name         TEXT,
    market            TEXT,
    industry          TEXT,
    wics              TEXT,
    is_spac           INTEGER,
    is_preferred      INTEGER,
    has_multi_sector  INTEGER,
    needs_rerun       INTEGER,
    rerun_reasons     TEXT,
    -- 본 모델 확장 (팀원 CSV 에 없음)
    corp_code         TEXT,
    wics_mid          TEXT,
    products          TEXT,
    listing_date      TEXT,
    is_eligible       INTEGER,
    updated_at        TEXT
);

CREATE TABLE IF NOT EXISTS financials (
    stock_code         TEXT,
    fiscal_year        INTEGER,
    corp_name          TEXT,
    fs_basis           TEXT,
    revenue            REAL,
    operating_income   REAL,
    net_income         REAL,
    net_income_parent  REAL,
    da                 REAL,
    ebitda             REAL,
    nwc_cur            REAL,
    nwc_pfy            REAL,
    delta_nwc          REAL,
    capex              REAL,
    ibd                REAL,
    ibd_detail         TEXT,
    noa                REAL,
    noa_items          TEXT,
    marginal_tax_rate  REAL,
    tax_bracket        TEXT,
    nopat              REAL,
    fcff               REAL,
    equity_total       REAL,
    equity_parent      REAL,
    minority_interest  REAL,
    preferred_capital  REAL,
    basic_eps          REAL,
    rcept_no           TEXT,
    rcept_dt           TEXT,
    reprt_code         TEXT,
    unit               TEXT,
    source             TEXT,
    raw_json           TEXT,
    updated_at         TEXT,
    PRIMARY KEY (stock_code, fiscal_year)
);

CREATE TABLE IF NOT EXISTS ttm_financials (
    stock_code    TEXT,
    period        TEXT,
    revenue_ttm   REAL,
    ebit_ttm      REAL,
    opm           REAL,
    prev_q_rev    REAL,
    sanity_yoy    TEXT,
    rcept_no      TEXT,
    raw_json      TEXT,
    updated_at    TEXT,
    PRIMARY KEY (stock_code, period)
);

CREATE TABLE IF NOT EXISTS beta_results (
    stock_code     TEXT,
    eval_date      TEXT,
    role           TEXT,
    beta_raw       REAL,
    beta_adjusted  REAL,
    r_squared      REAL,
    n_obs          INTEGER,
    detail         TEXT,
    updated_at     TEXT,
    PRIMARY KEY (stock_code, eval_date)
);

CREATE TABLE IF NOT EXISTS wacc_results (
    stock_code      TEXT,
    eval_date       TEXT,
    wacc            REAL,
    ke              REAL,
    kd_pretax       REAL,
    kd_aftertax     REAL,
    rf              REAL,
    erp             REAL,
    beta_relevered  REAL,
    weight_e        REAL,
    weight_d        REAL,
    tax_rate        REAL,
    credit_rating   TEXT,
    detail          TEXT,
    updated_at      TEXT,
    PRIMARY KEY (stock_code, eval_date)
);

CREATE TABLE IF NOT EXISTS dcf_results (
    stock_code         TEXT,
    eval_date          TEXT,
    fair_price         REAL,
    ev                 REAL,
    equity_value       REAL,
    nopat_normalized   REAL,
    sgr                REAL,
    terminal_value     REAL,
    scenarios          TEXT,
    sensitivity        TEXT,
    tornado            TEXT,
    detail             TEXT,
    updated_at         TEXT,
    PRIMARY KEY (stock_code, eval_date)
);

CREATE TABLE IF NOT EXISTS equity_results (
    stock_code         TEXT,
    eval_date          TEXT,
    market_cap         REAL,
    common_float       REAL,
    net_debt           REAL,
    noa_clean          REAL,
    minority_interest  REAL,
    current_price      REAL,
    detail             TEXT,
    updated_at         TEXT,
    PRIMARY KEY (stock_code, eval_date)
);

CREATE TABLE IF NOT EXISTS diagnostics_results (
    stock_code        TEXT,
    eval_date         TEXT,
    epv_price         REAL,
    epv_equity        REAL,
    epv_operating     REAL,
    growth_premium    REAL,
    implied_growth    REAL,
    expectations_gap  REAL,
    margin_of_safety  REAL,
    headline          TEXT,
    detail            TEXT,
    updated_at        TEXT,
    PRIMARY KEY (stock_code, eval_date)
);

CREATE TABLE IF NOT EXISTS credit_ratings (
    stock_code    TEXT,
    year          INTEGER,
    bond_rating   TEXT,
    cp_rating     TEXT,
    kd_applied    REAL,
    detail        TEXT,
    source        TEXT,
    updated_at    TEXT,
    PRIMARY KEY (stock_code, year)
);

CREATE TABLE IF NOT EXISTS rf_rates (
    rate_date  TEXT PRIMARY KEY,
    rf         REAL,
    source     TEXT,
    detail     TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS kofia_bond_yields (
    yield_date  TEXT,
    rating      TEXT,
    maturity    TEXT,
    yield_pct   REAL,
    updated_at  TEXT,
    PRIMARY KEY (yield_date, rating, maturity)
);

CREATE TABLE IF NOT EXISTS report_registry (
    stock_code  TEXT,
    period      TEXT,
    corp_code   TEXT,
    reprt_code  TEXT,
    kind        TEXT,
    rcept_no    TEXT,
    rcept_dt    TEXT,
    xbrl_done   INTEGER,
    embed_done  INTEGER,
    updated_at  TEXT,
    PRIMARY KEY (stock_code, period)
);

CREATE TABLE IF NOT EXISTS shares (
    stock_code       TEXT,
    fiscal_year      INTEGER,
    common_issued    INTEGER,
    common_treasury  INTEGER,
    common_float     INTEGER,
    corp_code        TEXT,
    rcept_no         TEXT,
    source           TEXT,
    source_quote     TEXT,
    confidence       TEXT,
    updated_at       TEXT,
    PRIMARY KEY (stock_code, fiscal_year)
);

CREATE TABLE IF NOT EXISTS market_snapshot (
    stock_code  TEXT,
    snap_date   TEXT,
    close       REAL,
    mktcap      REAL,
    shares      REAL,
    list_dd     TEXT,
    market      TEXT,
    updated_at  TEXT,
    PRIMARY KEY (stock_code, snap_date)
);

CREATE TABLE IF NOT EXISTS valuation_runs (
    run_id        TEXT PRIMARY KEY,
    stock_code    TEXT,
    corp_name     TEXT,
    eval_date     TEXT,
    fair_price    REAL,
    current_price REAL,
    upside_pct    REAL,
    wacc          REAL,
    peers         TEXT,
    mongo_doc_id  TEXT,
    result_path   TEXT,
    created_at    TEXT,
    updated_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_financials_sc ON financials(stock_code);
CREATE INDEX IF NOT EXISTS idx_runs_sc        ON valuation_runs(stock_code, eval_date);
CREATE INDEX IF NOT EXISTS idx_credit_sc      ON credit_ratings(stock_code);

-- 통합 결과 doc(텍스트 포함 전체) — JSONL 전체 스캔(O(n)) 제거용 SQLite 백엔드.
--   (collection, doc_id) PK 인덱스로 get_doc 이 O(log n) 조회. UI 응답 속도가
--   종목 수에 무관해진다(기존 mongo_json.get_doc 은 매 조회 JSONL 전수 파싱).
CREATE TABLE IF NOT EXISTS mongo_docs (
    collection  TEXT,
    doc_id      TEXT,
    doc         TEXT,
    updated_at  TEXT,
    PRIMARY KEY (collection, doc_id)
);
"""

# 테이블별 PK 컬럼 (upsert 충돌 키)
_PK = {
    "companies":           ["stock_code"],
    "financials":          ["stock_code", "fiscal_year"],
    "ttm_financials":      ["stock_code", "period"],
    "beta_results":        ["stock_code", "eval_date"],
    "wacc_results":        ["stock_code", "eval_date"],
    "dcf_results":         ["stock_code", "eval_date"],
    "equity_results":      ["stock_code", "eval_date"],
    "diagnostics_results": ["stock_code", "eval_date"],
    "credit_ratings":      ["stock_code", "year"],
    "rf_rates":            ["rate_date"],
    "kofia_bond_yields":   ["yield_date", "rating", "maturity"],
    "report_registry":     ["stock_code", "period"],
    "shares":              ["stock_code", "fiscal_year"],
    "market_snapshot":     ["stock_code", "snap_date"],
    "valuation_runs":      ["run_id"],
    "mongo_docs":          ["collection", "doc_id"],
}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    """초기화 보장 후 새 연결 반환 (WAL + busy_timeout)."""
    _ensure_init()
    conn = sqlite3.connect(str(DB_PATH), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def _ensure_init() -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return
    with _INIT_LOCK:
        if _INITIALIZED:
            return
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH), timeout=30.0)
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()
        _INITIALIZED = True


def _np_default(o: Any) -> Any:
    """json.dumps 내부의 numpy 스칼라/배열 처리 — dict/list 안에 섞인 numpy 대비."""
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(f"not JSON serializable: {type(o)}")


def _encode(v: Any) -> Any:
    """dict/list → JSON 문자열, numpy 스칼라/배열 → python, bool → int.

    numpy.bool_/integer/floating 은 sqlite3 바인딩이 막혀 upsert 가 예외로 죽고,
    run_valuation 의 guarded DB 저장이 통째로 스킵돼 valuation_runs 가 누락되던
    문제를 여기 한 곳에서 정화한다(api._sanitize 와 동일 취지).
    """
    if isinstance(v, np.bool_):
        return int(v)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return float(v)
    if isinstance(v, np.ndarray):
        return json.dumps(v.tolist(), ensure_ascii=False)
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, default=_np_default)
    return v


def upsert(table: str, row: dict, conn: Optional[sqlite3.Connection] = None) -> None:
    """단일 행 upsert (PK 충돌 시 갱신). dict/list 값은 JSON 문자열로 자동 직렬화."""
    rows = [row]
    upsert_many(table, rows, conn=conn)


def upsert_many(table: str, rows: Iterable[dict],
                conn: Optional[sqlite3.Connection] = None) -> int:
    """다건 upsert. 컬럼은 각 행의 키 합집합. updated_at 자동 채움.

    Returns: 처리한 행 수.
    """
    rows = [dict(r) for r in rows]
    if not rows:
        return 0
    if table not in _PK:
        raise ValueError(f"알 수 없는 테이블: {table}")

    own = conn is None
    if own:
        conn = connect()
    try:
        # 컬럼 합집합 (입력 순서 보존)
        cols: list[str] = []
        for r in rows:
            r.setdefault("updated_at", _now())
            for k in r:
                if k not in cols:
                    cols.append(k)
        pk = _PK[table]
        non_pk = [c for c in cols if c not in pk]
        placeholders = ",".join("?" for _ in cols)
        col_list = ",".join(cols)
        if non_pk:
            set_clause = ",".join(f"{c}=excluded.{c}" for c in non_pk)
            conflict = f"ON CONFLICT({','.join(pk)}) DO UPDATE SET {set_clause}"
        else:
            conflict = f"ON CONFLICT({','.join(pk)}) DO NOTHING"
        sql = (f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) {conflict}")
        data = [tuple(_encode(r.get(c)) for c in cols) for r in rows]
        conn.executemany(sql, data)
        if own:
            conn.commit()
        return len(rows)
    finally:
        if own:
            conn.close()


def query(sql: str, params: tuple = ()) -> list[dict]:
    """SELECT → list[dict]. JSON 컬럼은 호출자가 필요 시 json.loads."""
    conn = connect()
    try:
        cur = conn.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def query_one(sql: str, params: tuple = ()) -> Optional[dict]:
    rows = query(sql, params)
    return rows[0] if rows else None


def count(table: str) -> int:
    if table not in _PK:
        raise ValueError(f"알 수 없는 테이블: {table}")
    r = query_one(f"SELECT COUNT(*) AS n FROM {table}")
    return int(r["n"]) if r else 0


def table_counts() -> dict[str, int]:
    """모든 테이블 행 수 — 마이그레이션/프리워밍 검증용."""
    return {t: count(t) for t in _PK}


if __name__ == "__main__":
    _ensure_init()
    print(f"DB 초기화 완료: {DB_PATH}")
    for t, n in table_counts().items():
        print(f"  {t:22s} {n:>6d}")
