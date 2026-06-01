"""
db/init_db.py
=============
FILMN9 PoC - SQLite 6테이블 초기화 스크립트

목적
----
- 5종 JSON 산출물(company_info, financials, ohlcv, history, valuation)을
  통합 적재할 SQLite 단일 파일 데이터베이스 초기화
- 모든 테이블에 stock_code (한국 6자리 종목코드)를 식별자로 통일
- 재실행 안전 (CREATE TABLE IF NOT EXISTS)

산출
----
C:/Users/Admin/FILMN9/data/filmn9.db
- 테이블 6개
- 인덱스 자동 생성 (PK + 검색용)

사용법
------
cd C:/Users/Admin/FILMN9
python db/init_db.py            # DB 초기화 (재실행 안전)
python db/init_db.py --reset    # 기존 DB 파일 삭제 후 재생성
python db/init_db.py --verify   # 스키마만 검증 출력

테이블 구성 (5개 — histories는 MongoDB에서 관리)
-----------
1) company_info    기업 기본정보       (재무정보 파트)
2) financials      재무 3년치          (재무정보 파트)
3) ohlcv           일봉 가격           (재무정보 파트)
4) valuations      밸류에이션          (밸류에이션팀 — A2 방식)
5) shareholders    주주 구성           (재무정보 파트 — step3b)

DB 분리 정책
-----------
- 정형 데이터 5종     → SQLite (이 파일)
- 히스토리 브리핑     → MongoDB Atlas (filmn9.histories collection)
- 휘주님 LLM 산출물은 중첩 JSON 구조라 MongoDB가 자연스러움
- FastAPI에서 두 DB 동시 조회 (sqlite3 + pymongo)

참고
----
- 식별자 명칭: stock_code (한국 6자리 종목코드, 문자열)
  예: "090430", "005930", "031210" (앞자리 0 유지 필수)
- JSON 배열·딕셔너리 필드는 TEXT 컬럼에 json.dumps() 결과 저장 후
  조회 시 json.loads() 로 복원
- LLM 모델 기본 gpt-5-mini, 결과 품질 부족 시 상위 모델 사용 가능
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# ─── 경로 설정 ────────────────────────────────────────────────────────────────
ROOT     = Path(__file__).resolve().parent.parent   # C:/Users/Admin/FILMN9
DATA_DIR = ROOT / "data"
DB_PATH  = DATA_DIR / "filmn9.db"


# ─── 스키마 정의 ──────────────────────────────────────────────────────────────
SCHEMA_SQL = """
-- ===================================================================
-- 1. company_info  : 기업 기본정보
-- ===================================================================
CREATE TABLE IF NOT EXISTS company_info (
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
);

CREATE INDEX IF NOT EXISTS idx_company_market  ON company_info(market);
CREATE INDEX IF NOT EXISTS idx_company_sector  ON company_info(sector);
CREATE INDEX IF NOT EXISTS idx_company_name    ON company_info(corp_name);


-- ===================================================================
-- 2. financials   : 재무 3년치 (Long 형식: 한 종목 × 한 연도 = 한 행)
-- ===================================================================
CREATE TABLE IF NOT EXISTS financials (
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


-- ===================================================================
-- 3. ohlcv       : 일봉 OHLCV
-- ===================================================================
CREATE TABLE IF NOT EXISTS ohlcv (
    stock_code      TEXT NOT NULL,
    date            TEXT NOT NULL,           -- "YYYY-MM-DD"
    open            INTEGER,
    high            INTEGER,
    low             INTEGER,
    close           INTEGER,
    volume          INTEGER,
    PRIMARY KEY (stock_code, date)
);

CREATE INDEX IF NOT EXISTS idx_ohlcv_date ON ohlcv(date);


-- ===================================================================
-- (4. histories 테이블 제거됨 — MongoDB Atlas에서 관리)
--     filmn9.histories collection 에 휘주님 산출물 저장
--     FastAPI 의 /api/history/{stock_code} 는 pymongo 로 조회
-- ===================================================================


-- ===================================================================
-- 4. valuations  : 밸류에이션 (밸류에이션팀 산출물 - A2 방식 기준)
-- ===================================================================
CREATE TABLE IF NOT EXISTS valuations (
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

CREATE INDEX IF NOT EXISTS idx_valuations_quality ON valuations(data_quality);


-- ===================================================================
-- 5. shareholders : 주주 구성 (재무정보 파트 step3b)
--    한 종목 × 한 회계연도 × 주주 순위(rank)별 한 행
-- ===================================================================
CREATE TABLE IF NOT EXISTS shareholders (
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

CREATE INDEX IF NOT EXISTS idx_shareholders_name ON shareholders(name);


-- ===================================================================
-- 6. executives  : 경영인 (재무정보 파트 / DART OpenAPI exctvSttus)
-- ===================================================================
CREATE TABLE IF NOT EXISTS executives (
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

CREATE INDEX IF NOT EXISTS idx_executives_name ON executives(name);


-- ===================================================================
-- 7. disclosures : 최근 공시 (DART OpenAPI list.json)
-- ===================================================================
CREATE TABLE IF NOT EXISTS disclosures (
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

CREATE INDEX IF NOT EXISTS idx_disclosures_date ON disclosures(rcept_dt);


-- ===================================================================
-- 8. financial_detail : 재무제표 상세 (B/S + I/S, account_id 기반)
-- ===================================================================
CREATE TABLE IF NOT EXISTS financial_detail (
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

CREATE INDEX IF NOT EXISTS idx_fdetail_lookup ON financial_detail(stock_code, fiscal_year, statement_type);


-- ===================================================================
-- 9. credit_ratings : 신용등급 추이 (수동 입력)
--    한국기업평가 / 한국신용평가 / NICE신용평가
-- ===================================================================
CREATE TABLE IF NOT EXISTS credit_ratings (
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

CREATE INDEX IF NOT EXISTS idx_credit_stock ON credit_ratings(stock_code);
"""


# ─── 함수 ─────────────────────────────────────────────────────────────────────

def init_db(reset: bool = False) -> None:
    """
    SQLite DB 초기화. CREATE TABLE IF NOT EXISTS 사용으로 재실행 안전.

    Args:
        reset: True 시 기존 filmn9.db 파일 삭제 후 재생성
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if reset and DB_PATH.exists():
        DB_PATH.unlink()
        print(f"[RESET] 기존 DB 삭제: {DB_PATH}")

    new_db = not DB_PATH.exists()

    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(SCHEMA_SQL)
        conn.commit()

    action = "생성" if new_db else "갱신"
    size_kb = DB_PATH.stat().st_size / 1024
    print(f"[OK]    DB {action}: {DB_PATH}")
    print(f"        크기: {size_kb:,.2f} KB")


def verify_db() -> None:
    """
    DB 스키마 검증 및 출력 (테이블·컬럼·인덱스·행수).
    """
    if not DB_PATH.exists():
        print(f"[ERR] DB 파일 없음: {DB_PATH}")
        sys.exit(1)

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()

        # 테이블 목록
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [r[0] for r in cur.fetchall()]

        print(f"\n{'='*70}")
        print(f"  filmn9.db 스키마 검증")
        print(f"{'='*70}")
        print(f"  DB 경로  : {DB_PATH}")
        print(f"  파일 크기: {DB_PATH.stat().st_size / 1024:.2f} KB")
        print(f"  테이블 수: {len(tables)}")
        print(f"{'='*70}")

        for t in tables:
            cur.execute(f"PRAGMA table_info({t})")
            cols = cur.fetchall()
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            count = cur.fetchone()[0]
            print(f"\n[{t}]   컬럼 {len(cols)}개   /   행 {count:,}")
            for col in cols:
                # (cid, name, type, notnull, dflt_value, pk)
                pk = "  PK"      if col[5] else ""
                nn = "  NOT NULL" if col[3] else ""
                df = f"  DEFAULT {col[4]}" if col[4] is not None else ""
                print(f"    - {col[1]:24s} {col[2]:10s}{pk}{nn}{df}")

        # 인덱스
        cur.execute("""
            SELECT name, tbl_name FROM sqlite_master
            WHERE type='index' AND name NOT LIKE 'sqlite_%'
            ORDER BY tbl_name, name
        """)
        indexes = cur.fetchall()
        print(f"\n{'='*70}")
        print(f"  인덱스 ({len(indexes)}개)")
        print(f"{'='*70}")
        for idx_name, tbl_name in indexes:
            print(f"  - {idx_name:35s} on {tbl_name}")

        print(f"\n{'='*70}\n")


# ─── 메인 ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="FILMN9 SQLite 6테이블 초기화")
    parser.add_argument("--reset",  action="store_true", help="기존 DB 삭제 후 재생성")
    parser.add_argument("--verify", action="store_true", help="스키마만 확인 출력 (DB 생성 안 함)")
    args = parser.parse_args()

    if args.verify:
        verify_db()
        return

    init_db(reset=args.reset)
    verify_db()


if __name__ == "__main__":
    main()
