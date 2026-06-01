# Mermaid AI ERD 작성 프롬프트 — FILMN9 (2026-05-26 기준)

> 아래 내용을 복사해서 Mermaid AI 또는 ChatGPT/Claude에게 그대로 붙여넣으세요.

---

## 📋 프롬프트 본문 (복사용)

```
아래는 "FILMN9" (AI 기반 기업 분석 자동화 플랫폼) 프로젝트의 SQLite + MongoDB + JSON 파일
복합 데이터 스토어 구조입니다. Mermaid ERD 문법(erDiagram)으로 작성해주세요.

요구사항:
- 모든 컬럼명·타입·PK·관계를 정확히 표기
- 복합 PK는 PK 표시
- 데이터 스토어가 다른 경우(SQLite vs MongoDB vs JSON 파일) 주석으로 구분
- 관계선(||--o{ 등)은 의미가 명확하도록 라벨 추가
- 종목코드(stock_code)가 거의 모든 테이블의 외래키 역할

────────────────────────────────────────
[데이터 스토어 1] SQLite — data/filmn9.db (9개 테이블)
────────────────────────────────────────

■ company_info (기업 기본 정보 — DART company.json)
  - stock_code: TEXT PK
  - corp_name: TEXT NOT NULL
  - market: TEXT (KOSPI/KOSDAQ)
  - sector: TEXT (DART KSIC 코드)
  - listing_date: TEXT
  - ceo: TEXT
  - employees: INTEGER
  - homepage: TEXT
  - address: TEXT
  - phone: TEXT
  - fiscal_month: INTEGER
  - source: TEXT
  - generated_at: TEXT
  - loaded_at: TEXT

■ financials (재무 요약 — 연도별, 매출/영업이익/순이익/B-S 핵심 지표)
  - stock_code: TEXT PK (복합 PK)
  - fiscal_year: INTEGER PK (복합 PK)
  - revenue: REAL
  - op_income: REAL
  - net_income: REAL
  - assets: REAL
  - liabilities: REAL
  - equity: REAL
  - debt_ratio: REAL
  - cashflow_op: REAL
  - cashflow_inv: REAL
  - cashflow_fin: REAL
  - unit: TEXT (백만원)
  - source: TEXT (DART OpenAPI)
  - generated_at: TEXT
  - loaded_at: TEXT

■ financial_detail (재무제표 상세 — B/S, I/S 계정별)
  - stock_code: TEXT PK (복합 PK)
  - fiscal_year: INTEGER PK (복합 PK)
  - statement_type: TEXT PK (복합 PK, BS/IS)
  - account_id: TEXT PK (복합 PK)
  - statement_scope: TEXT PK (복합 PK, 연결/별도)
  - account_nm: TEXT (계정명 한글)
  - amount: REAL
  - unit: TEXT
  - display_order: INTEGER
  - source: TEXT (DART XBRL)
  - loaded_at: TEXT

■ ohlcv (일봉 시계열)
  - stock_code: TEXT PK (복합 PK)
  - date: TEXT PK (복합 PK)
  - open: INTEGER
  - high: INTEGER
  - low: INTEGER
  - close: INTEGER
  - volume: INTEGER

■ shareholders (주주 구성)
  - stock_code: TEXT PK (복합 PK)
  - fiscal_year: INTEGER PK (복합 PK)
  - rank: INTEGER PK (복합 PK)
  - name: TEXT (주주명)
  - relation: TEXT (관계)
  - shares: INTEGER (보유주식수)
  - ratio: REAL (지분율 %)
  - source: TEXT
  - loaded_at: TEXT

■ executives (경영진)
  - stock_code: TEXT PK (복합 PK)
  - fiscal_year: INTEGER PK (복합 PK)
  - rank: INTEGER PK (복합 PK)
  - name: TEXT
  - position: TEXT (직책)
  - role: TEXT (담당)
  - birth_year: TEXT
  - career: TEXT (경력)
  - shares: INTEGER (보유주식)
  - appointed_at: TEXT (선임일)
  - term_end: TEXT (임기종료일)
  - source: TEXT
  - loaded_at: TEXT

■ disclosures (공시 목록)
  - stock_code: TEXT PK (복합 PK)
  - rcept_no: TEXT PK (복합 PK, 접수번호)
  - report_nm: TEXT (보고서명)
  - flr_nm: TEXT (제출인)
  - rcept_dt: TEXT (접수일)
  - rm: TEXT (비고)
  - url: TEXT (DART 원문 링크)
  - source: TEXT
  - loaded_at: TEXT

■ credit_ratings (신용등급 추이)
  - stock_code: TEXT PK (복합 PK)
  - rating_year: INTEGER PK (복합 PK)
  - agency: TEXT PK (복합 PK, 신용평가사)
  - rating: TEXT NOT NULL (AAA/AA+/A0 등)
  - rating_score: INTEGER (1~10 수치 매핑)
  - outlook: TEXT (Stable/Negative/Positive)
  - rating_date: TEXT
  - source: TEXT
  - loaded_at: TEXT

■ valuations (밸류에이션 — 종목당 1행, DCF + 멀티플 + 컨센서스)
  - stock_code: TEXT PK
  - fair_price_avg: REAL (적정주가 평균)
  - fair_price_min: REAL
  - fair_price_max: REAL
  - upside_pct: REAL (상승여력 %)
  - analyst_count: INTEGER
  - opinion_majority: TEXT (매수/보유/매도)
  - dcf_value: REAL
  - wacc: REAL
  - perpetual_growth: REAL
  - roic: REAL
  - roic_vs_wacc: REAL
  - relative_per_value: REAL
  - relative_pbr_value: REAL
  - forecast_revenue: TEXT (JSON 직렬화)
  - forecast_op_income: TEXT (JSON)
  - forecast_net_income: TEXT (JSON)
  - forecast_eps: TEXT (JSON)
  - forecast_per: TEXT (JSON)
  - forecast_pbr: TEXT (JSON)
  - forecast_roe: TEXT (JSON)
  - data_quality: TEXT (high/medium/low)
  - data_sources: TEXT (JSON)
  - generated_at: TEXT
  - loaded_at: TEXT

────────────────────────────────────────
[데이터 스토어 2] MongoDB Atlas — filmn9.histories (히스토리 브리핑)
────────────────────────────────────────

■ histories (LLM 자동 요약 사업보고서 브리핑)
  - stock_code: STRING (식별자)
  - corp_name: STRING
  - generated_at: STRING (ISO datetime)
  - brief: OBJECT
    - summary: STRING (사업 요약)
    - price_factors: ARRAY (주가 영향 요인)
    - financial_health: STRING
    - business_model: STRING
    - risks: STRING
  - source: STRING (DART 사업보고서 + LLM gpt-5-mini)
  - confidence: STRING (high/medium/low)
  - _source: STRING (mongo/file 폴백 표시)
  - (실패 시 폴백) data/parsed_history/{stock_code}_*.json 로컬 파일

────────────────────────────────────────
[데이터 스토어 3] JSON 파일 (외부 API 캐시 / 팀원 산출물)
────────────────────────────────────────

■ data/valuation_share/{stock_code}_{corp_name}.json
  (밸류에이션팀 산출물 — DCF·WACC·민감도·토네이도·피어 등 ui_payload 전체)
  - stock_code, corp_name, generated_at
  - ui_payload: { summary, scenarios, dcf, wacc_breakdown, multiples,
                  sensitivity, tornado, peer_beta, valuation_diagnostics, ... }
  - structured_data: { company, financials[], credit_rating, wacc, dcf,
                       equity, diagnostics, beta }

────────────────────────────────────────
[관계 정의]
────────────────────────────────────────

company_info 1 — N financials                (한 종목, 다년도 재무)
company_info 1 — N financial_detail          (한 종목, 다년도×다계정 상세)
company_info 1 — N ohlcv                     (한 종목, 다일자 시세)
company_info 1 — N shareholders              (한 종목, 다년도×다주주)
company_info 1 — N executives                (한 종목, 다년도×다경영진)
company_info 1 — N disclosures               (한 종목, 다공시)
company_info 1 — N credit_ratings            (한 종목, 다년도×다평가사 등급)
company_info 1 — 1 valuations                (한 종목당 1행)
company_info 1 — 1 histories (MongoDB)       (한 종목당 1 히스토리 문서)
company_info 1 — 1 valuation_share JSON      (한 종목당 1 ui_payload 파일)

[중요] 모든 자식 테이블의 stock_code 는 company_info.stock_code 를 참조하는
       논리적 외래키입니다 (SQLite에선 FK 제약을 걸지 않았지만 ERD에선 관계로 표시)

────────────────────────────────────────
[추가 요청]
────────────────────────────────────────

1. SQLite 9개 테이블은 erDiagram 본체에 포함
2. MongoDB와 JSON 파일은 별도 entity 로 표시하되 다른 스타일(주석 또는 별도 노트)로 구분
3. 복합 PK 는 모든 필드에 "PK" 표기
4. JSON 직렬화 컬럼(forecast_*, data_sources)은 "TEXT (JSON)" 으로 명기
5. 관계선 라벨에 "1:N", "1:1" 등 카디널리티 명시
6. 최종 결과는 Mermaid erDiagram 코드블록 1개로 출력

위 요구사항대로 Mermaid ERD 다이어그램을 작성해주세요.
```

---

## 📌 사용 팁

1. **Mermaid Live Editor**(https://mermaid.live)에 그대로 붙여넣으면 즉시 시각화
2. **dbdiagram.io DBML**로 변환이 필요하면 별도 요청
3. ERD 그림 PNG/SVG로 export 가능

## 🔗 관련 파일

- DB 실파일: `C:\Users\Admin\FILMN9\data\filmn9.db`
- 스키마 확인 스크립트: `C:\Users\Admin\FILMN9\check_full_schema.py`
- 팀원 산출물 (밸류에이션): `C:\Users\Admin\FILMN9\data\valuation_share\` (통합 예정)
