-- ============================================================================
--  FINSIGHT  filmn9.db (SQLite) → PostgreSQL/Supabase 변환 DDL  (16 테이블)
--  작성: 2026-06-10 야간 자율작업 (초안 — 실적재 전 검토 필요)
--  변환 규칙:
--    TEXT     → TEXT
--    INTEGER  → INTEGER  (단, 거래량/대용량은 BIGINT)
--    REAL     → DOUBLE PRECISION  (금액 정밀도 필요 시 NUMERIC 고려)
--    "INSERT OR REPLACE" → "INSERT ... ON CONFLICT (pk) DO UPDATE"  (코드에서 처리)
--    AUTOINCREMENT 없음(전부 자연키) · SQLite 'PRAGMA' 류 제거
--  주의: ohlcv 1,067만행은 COPY 로 적재(INSERT 금지). 무료티어(500MB) 한도 확인.
-- ============================================================================

-- 1) 마스터 허브 -------------------------------------------------------------
CREATE TABLE company_info (
    stock_code   TEXT PRIMARY KEY,
    corp_name    TEXT NOT NULL,
    market       TEXT,
    sector       TEXT,
    listing_date TEXT,
    ceo          TEXT,
    employees    INTEGER,
    homepage     TEXT,
    address      TEXT,
    phone        TEXT,
    fiscal_month INTEGER,
    source       TEXT,
    generated_at TEXT,
    loaded_at    TEXT,
    legal_name   TEXT
);

-- 2) 재무 ------------------------------------------------------------------
CREATE TABLE financials (
    stock_code   TEXT NOT NULL,
    fiscal_year  INTEGER NOT NULL,
    revenue      DOUBLE PRECISION,
    op_income    DOUBLE PRECISION,
    net_income   DOUBLE PRECISION,
    assets       DOUBLE PRECISION,
    liabilities  DOUBLE PRECISION,
    equity       DOUBLE PRECISION,
    debt_ratio   DOUBLE PRECISION,
    cashflow_op  DOUBLE PRECISION,
    cashflow_inv DOUBLE PRECISION,
    cashflow_fin DOUBLE PRECISION,
    unit         TEXT DEFAULT '백만원',
    source       TEXT,
    generated_at TEXT,
    loaded_at    TEXT,
    PRIMARY KEY (stock_code, fiscal_year)
);

CREATE TABLE financial_detail (
    stock_code      TEXT NOT NULL,
    fiscal_year     INTEGER NOT NULL,
    statement_type  TEXT NOT NULL,
    account_id      TEXT NOT NULL,
    account_nm      TEXT,
    amount          DOUBLE PRECISION,
    unit            TEXT DEFAULT '백만원',
    statement_scope TEXT NOT NULL,
    display_order   INTEGER,
    source          TEXT,
    loaded_at       TEXT,
    PRIMARY KEY (stock_code, fiscal_year, statement_type, account_id, statement_scope)
);

-- 3) 주가 (대용량 1,067만행 — COPY 적재) -------------------------------------
CREATE TABLE ohlcv (
    stock_code TEXT NOT NULL,
    date       TEXT NOT NULL,
    open       INTEGER,
    high       INTEGER,
    low        INTEGER,
    close      INTEGER,
    volume     BIGINT,            -- SQLite INTEGER → 거래량 대용량이라 BIGINT
    PRIMARY KEY (stock_code, date)
);

-- 4) 지배구조 ---------------------------------------------------------------
CREATE TABLE shareholders (
    stock_code  TEXT NOT NULL,
    fiscal_year INTEGER NOT NULL,
    rank        INTEGER NOT NULL,
    name        TEXT,
    relation    TEXT,
    shares      BIGINT,
    ratio       DOUBLE PRECISION,
    source      TEXT,
    loaded_at   TEXT,
    PRIMARY KEY (stock_code, fiscal_year, rank)
);

CREATE TABLE executives (
    stock_code   TEXT NOT NULL,
    fiscal_year  INTEGER NOT NULL,
    rank         INTEGER NOT NULL,
    name         TEXT,
    position     TEXT,
    role         TEXT,
    birth_year   TEXT,
    career       TEXT,
    shares       BIGINT,
    appointed_at TEXT,
    term_end     TEXT,
    source       TEXT,
    loaded_at    TEXT,
    PRIMARY KEY (stock_code, fiscal_year, rank)
);

-- 5) 공시 / 상태 ------------------------------------------------------------
CREATE TABLE disclosures (
    stock_code TEXT NOT NULL,
    rcept_no   TEXT NOT NULL,
    report_nm  TEXT,
    flr_nm     TEXT,
    rcept_dt   TEXT,
    rm         TEXT,
    url        TEXT,
    source     TEXT,
    loaded_at  TEXT,
    PRIMARY KEY (stock_code, rcept_no)
);

CREATE TABLE dart_halt_events (
    stock_code TEXT NOT NULL,
    rcept_dt   TEXT NOT NULL,
    state      TEXT NOT NULL,
    report_nm  TEXT,
    rcept_no   TEXT,
    PRIMARY KEY (stock_code, rcept_no)
);

CREATE TABLE stock_status (
    stock_code      TEXT PRIMARY KEY,
    status          TEXT NOT NULL,
    label           TEXT,
    reason          TEXT,
    ref_date        TEXT,
    last_trade_date TEXT,
    source          TEXT,
    checked_at      TEXT
);

-- 6) 밸류 / 신용 / 경쟁사 ---------------------------------------------------
CREATE TABLE valuation_summary (
    stock_code            TEXT PRIMARY KEY,
    corp_name             TEXT,
    market                TEXT,
    industry              TEXT,
    dcf_grade             TEXT,
    dcf_confidence        TEXT,
    peer_confidence_grade TEXT,
    fair_price            DOUBLE PRECISION,
    current_price         DOUBLE PRECISION,
    upside_pct            DOUBLE PRECISION,
    wacc                  DOUBLE PRECISION,
    as_of_date            TEXT,
    model_version         TEXT,
    source_file           TEXT,
    loaded_at             TEXT
);

CREATE TABLE valuations (
    stock_code          TEXT PRIMARY KEY,
    fair_price_avg      DOUBLE PRECISION,
    fair_price_min      DOUBLE PRECISION,
    fair_price_max      DOUBLE PRECISION,
    upside_pct          DOUBLE PRECISION,
    analyst_count       INTEGER,
    opinion_majority    TEXT,
    dcf_value           DOUBLE PRECISION,
    wacc                DOUBLE PRECISION,
    perpetual_growth    DOUBLE PRECISION,
    roic                DOUBLE PRECISION,
    roic_vs_wacc        DOUBLE PRECISION,
    relative_per_value  DOUBLE PRECISION,
    relative_pbr_value  DOUBLE PRECISION,
    forecast_revenue    JSONB,   -- SQLite TEXT(JSON 문자열) → Postgres JSONB 권장
    forecast_op_income  JSONB,
    forecast_net_income JSONB,
    forecast_eps        JSONB,
    forecast_per        JSONB,
    forecast_pbr        JSONB,
    forecast_roe        JSONB,
    data_quality        TEXT,
    data_sources        JSONB,
    generated_at        TEXT,
    loaded_at           TEXT
);

CREATE TABLE credit_ratings (
    stock_code   TEXT NOT NULL,
    rating_year  INTEGER NOT NULL,
    agency       TEXT NOT NULL,
    rating       TEXT NOT NULL,
    rating_score INTEGER,
    outlook      TEXT,
    rating_date  TEXT,
    source       TEXT,
    loaded_at    TEXT,
    PRIMARY KEY (stock_code, rating_year, agency)
);

CREATE TABLE peer_competitors (
    stock_code      TEXT NOT NULL,
    rank            INTEGER NOT NULL,
    competitor_code TEXT NOT NULL,
    competitor_name TEXT NOT NULL,
    wics            TEXT,
    basis           TEXT,
    similarity      DOUBLE PRECISION,
    PRIMARY KEY (stock_code, competitor_code)
);

-- 7) 보조 / 룩업 ------------------------------------------------------------
CREATE TABLE company_customers (
    stock_code    TEXT PRIMARY KEY,
    customer_type TEXT,
    customers     TEXT,
    channels      TEXT,
    source_grade  TEXT,
    source_text   TEXT,
    loaded_at     TEXT
);

CREATE TABLE ticker_suffix (
    stock_code TEXT PRIMARY KEY,
    suffix     TEXT,
    market     TEXT
);

CREATE TABLE wics_keywords (
    wics_name    TEXT NOT NULL,
    keyword      TEXT NOT NULL,
    keyword_norm TEXT NOT NULL,
    PRIMARY KEY (wics_name, keyword)
);

-- ============================================================================
--  보조 인덱스 (조회 성능 — 화면 쿼리 패턴 기준)
-- ============================================================================
CREATE INDEX idx_financials_sc       ON financials(stock_code);
CREATE INDEX idx_findetail_sc_fy     ON financial_detail(stock_code, fiscal_year);
CREATE INDEX idx_ohlcv_sc_date       ON ohlcv(stock_code, date DESC);
CREATE INDEX idx_shareholders_sc     ON shareholders(stock_code);
CREATE INDEX idx_executives_sc       ON executives(stock_code);
CREATE INDEX idx_disclosures_sc      ON disclosures(stock_code, rcept_dt DESC);
CREATE INDEX idx_peer_sc             ON peer_competitors(stock_code);
CREATE INDEX idx_company_sector      ON company_info(sector);

-- ============================================================================
--  적재 순서(FK 무결성 — 현재 스키마는 명시적 FK 없으나 논리적 순서 권장)
--   1. company_info  →  2. 나머지 1:N/1:1 자식  →  3. peer_competitors
--  대용량 ohlcv 는 \copy ohlcv FROM 'ohlcv.csv' CSV HEADER; 로 적재.
-- ============================================================================
