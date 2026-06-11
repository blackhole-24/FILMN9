CREATE TABLE company_customers (
            stock_code     TEXT PRIMARY KEY,
            customer_type  TEXT,    -- B2B / B2C / MIXED
            customers      TEXT,    -- 기업명 / '일반 소비자(개인)' / 병기
            channels       TEXT,    -- 판매채널(빈도순) + 지역
            source_grade   TEXT,    -- B(매출처) / C(소비자) / M(혼합)
            source_text    TEXT,
            loaded_at      TEXT
        );

CREATE TABLE company_info (
    stock_code      TEXT PRIMARY KEY,
    corp_name       TEXT NOT NULL,
    market          TEXT,                   -- KOSPI / KOSDAQ / KONEX
    sector          TEXT,                   -- DART induty_code
    listing_date    TEXT,                   -- "2006-06-01" 또는 "2006년 06월 01일"
    ceo             TEXT,
    employees       INTEGER,
    homepage        TEXT,
    address         TEXT,
    phone           TEXT,
    fiscal_month    INTEGER,                -- 1-12
    source          TEXT,                   -- "DART company.json"
    generated_at    TEXT,                   -- JSON 생성 시각
    loaded_at       TEXT                    -- DB 적재 시각
, legal_name TEXT);

CREATE TABLE credit_ratings (
    stock_code      TEXT NOT NULL,
    rating_year     INTEGER NOT NULL,
    agency          TEXT NOT NULL,              -- "KIS" / "KR" / "NICE"
    rating          TEXT NOT NULL,              -- "AAA","AA+","AA","AA-","A+",...
    rating_score    INTEGER,                    -- AAA=22, AA+=21, ..., D=1 (정렬용)
    outlook         TEXT,                       -- "Stable" / "Positive" / "Negative"
    rating_date     TEXT,                       -- YYYY-MM-DD
    source          TEXT,                       -- "수동 입력 / 신평사 공시"
    loaded_at       TEXT,
    PRIMARY KEY (stock_code, rating_year, agency)
);

CREATE TABLE dart_halt_events (
            stock_code  TEXT NOT NULL,
            rcept_dt    TEXT NOT NULL,      -- 공시 접수일 YYYYMMDD
            state       TEXT NOT NULL,      -- HALT / RESUMED
            report_nm   TEXT,
            rcept_no    TEXT,
            PRIMARY KEY (stock_code, rcept_no)
        );

CREATE TABLE disclosures (
    stock_code      TEXT NOT NULL,
    rcept_no        TEXT NOT NULL,              -- 접수번호 (DART PK)
    report_nm       TEXT,                       -- 보고서명
    flr_nm          TEXT,                       -- 제출인
    rcept_dt        TEXT,                       -- 접수일자 YYYY-MM-DD
    rm              TEXT,                       -- 비고
    url             TEXT,                       -- DART 원문 링크
    source          TEXT,                       -- "DART list.json"
    loaded_at       TEXT,
    PRIMARY KEY (stock_code, rcept_no)
);

CREATE TABLE executives (
    stock_code      TEXT NOT NULL,
    fiscal_year     INTEGER NOT NULL,
    rank            INTEGER NOT NULL,           -- 표시 순서
    name            TEXT,                       -- 성명
    position        TEXT,                       -- 직위 (대표이사 / 사외이사 등)
    role            TEXT,                       -- 등기/미등기, 상근/비상근
    birth_year      TEXT,                       -- 출생년도 YYYY
    career          TEXT,                       -- 주요경력 (요약)
    shares          INTEGER,                    -- 보유주식수
    appointed_at    TEXT,                       -- 선임일자 YYYY-MM-DD
    term_end        TEXT,                       -- 임기만료일 YYYY-MM-DD
    source          TEXT,                       -- "DART exctvSttus"
    loaded_at       TEXT,
    PRIMARY KEY (stock_code, fiscal_year, rank)
);

CREATE TABLE financial_detail (
    stock_code      TEXT NOT NULL,
    fiscal_year     INTEGER NOT NULL,
    statement_type  TEXT NOT NULL,              -- "BS" / "IS"
    account_id      TEXT NOT NULL,              -- DART account_id (예: ifrs-full_Revenue)
    account_nm      TEXT,                       -- 한글 계정명
    amount          REAL,                       -- 금액 (백만원)
    unit            TEXT DEFAULT '백만원',
    statement_scope TEXT,                       -- "연결" / "별도"
    display_order   INTEGER,                    -- 표시 순서
    source          TEXT,                       -- "DART fnlttSinglAcntAll"
    loaded_at       TEXT,
    PRIMARY KEY (stock_code, fiscal_year, statement_type, account_id, statement_scope)
);

CREATE TABLE financials (
    stock_code      TEXT NOT NULL,
    fiscal_year     INTEGER NOT NULL,
    revenue         REAL,                   -- 매출액 (백만원)
    op_income       REAL,                   -- 영업이익
    net_income      REAL,                   -- 당기순이익
    assets          REAL,                   -- 자산총계
    liabilities     REAL,                   -- 부채총계
    equity          REAL,                   -- 자본총계
    debt_ratio      REAL,                   -- 부채비율 (%)
    cashflow_op     REAL,                   -- 영업활동현금흐름
    cashflow_inv    REAL,                   -- 투자활동현금흐름
    cashflow_fin    REAL,                   -- 재무활동현금흐름
    unit            TEXT DEFAULT '백만원',
    source          TEXT,                   -- "JSONL 파싱 (연결재무제표)"
    generated_at    TEXT,
    loaded_at       TEXT,
    PRIMARY KEY (stock_code, fiscal_year)
);

CREATE TABLE ohlcv (
    stock_code      TEXT NOT NULL,
    date            TEXT NOT NULL,           -- "YYYY-MM-DD"
    open            INTEGER,
    high            INTEGER,
    low             INTEGER,
    close           INTEGER,
    volume          INTEGER,
    PRIMARY KEY (stock_code, date)
);

CREATE TABLE peer_competitors (
            stock_code      TEXT NOT NULL,
            rank            INTEGER NOT NULL,
            competitor_code TEXT NOT NULL,
            competitor_name TEXT NOT NULL,
            wics            TEXT,
            basis           TEXT, similarity REAL,        -- 선정 근거
            PRIMARY KEY (stock_code, competitor_code)
        );

CREATE TABLE shareholders (
    stock_code              TEXT NOT NULL,
    fiscal_year             INTEGER NOT NULL,
    rank                    INTEGER NOT NULL,
    name                    TEXT,             -- "아모레퍼시픽홀딩스"
    relation                TEXT,             -- "최대주주" / "특수관계인" / "기타"
    shares                  INTEGER,          -- 보유주식수
    ratio                   REAL,             -- 50.15 (%)
    source                  TEXT,             -- "JSONL VII. 주주에 관한 사항"
    loaded_at               TEXT,
    PRIMARY KEY (stock_code, fiscal_year, rank)
);

CREATE TABLE stock_status (
            stock_code      TEXT PRIMARY KEY,
            status          TEXT NOT NULL,    -- NORMAL/ADMIN/HALT/DELISTED
            label           TEXT,             -- 화면 표기용 한글
            reason          TEXT,             -- 사유
            ref_date        TEXT,             -- 상폐일/지정일
            last_trade_date TEXT,             -- 마지막 거래일(our ohlcv)
            source          TEXT,
            checked_at      TEXT
        );

CREATE TABLE ticker_suffix (
        stock_code TEXT PRIMARY KEY, suffix TEXT, market TEXT);

CREATE TABLE valuation_summary (
    stock_code            TEXT PRIMARY KEY,
    corp_name             TEXT,
    market                TEXT,
    industry              TEXT,
    dcf_grade             TEXT,
    dcf_confidence        TEXT,
    peer_confidence_grade TEXT,
    fair_price            REAL,
    current_price         REAL,
    upside_pct            REAL,
    wacc                  REAL,
    as_of_date            TEXT,
    model_version         TEXT,
    source_file           TEXT,
    loaded_at             TEXT
);

CREATE TABLE valuations (
    stock_code              TEXT PRIMARY KEY,

    -- 적정주가 컨센서스 (한경)
    fair_price_avg          REAL,             -- 적정주가 평균
    fair_price_min          REAL,
    fair_price_max          REAL,
    upside_pct              REAL,             -- 현재가 대비 상승여력 (%)
    analyst_count           INTEGER,          -- 컨센서스 참여 N명
    opinion_majority        TEXT,             -- "Buy" / "Hold" / "Sell"

    -- DCF 결과
    dcf_value               REAL,
    wacc                    REAL,             -- 9.2 (%)
    perpetual_growth        REAL,             -- 2.0 (%)
    roic                    REAL,             -- 12.5 (%)
    roic_vs_wacc            REAL,             -- ROIC - WACC

    -- 상대가치
    relative_per_value      REAL,             -- PER × EPS
    relative_pbr_value      REAL,             -- PBR × BPS

    -- 미래 추정 (네이버 컨센서스)
    forecast_revenue        TEXT,             -- JSON dict: {"2026":5250,"2027":6100,...}
    forecast_op_income      TEXT,             -- JSON dict
    forecast_net_income     TEXT,             -- JSON dict
    forecast_eps            TEXT,             -- JSON dict
    forecast_per            TEXT,             -- JSON dict
    forecast_pbr            TEXT,             -- JSON dict
    forecast_roe            TEXT,             -- JSON dict

    -- 데이터 품질
    data_quality            TEXT,             -- "green" / "yellow" / "red"
    data_sources            TEXT,             -- JSON array: ["hankyung","naver"]

    -- 메타정보
    generated_at            TEXT,
    loaded_at               TEXT
);

CREATE TABLE wics_keywords (
            wics_name   TEXT NOT NULL,
            keyword     TEXT NOT NULL,
            keyword_norm TEXT NOT NULL,   -- 공백·대소문자 정규화
            PRIMARY KEY (wics_name, keyword)
        );
