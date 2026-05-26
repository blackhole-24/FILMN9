# FILMN9 프로젝트 설계도 — 워터폴(Waterfall) 방식 v1.0

> 작성일: 2026-05-24 | 방법론: 전통적 폭포수 모델 (Sequential)
> 전제: FILMN9 PoC를 고전적 워터폴로 진행했을 경우의 전체 설계

---

## 워터폴 방법론 개요

```
요구사항 분석
     │
     ▼
시스템 설계
     │
     ▼
상세 설계
     │
     ▼
구현 (개발)
     │
     ▼
테스트 & QA
     │
     ▼
배포 & 운영
```

> 각 단계는 **이전 단계 완료 후 다음 단계 진입**
> 단계 간 되돌아가기는 공식적으로 변경 요청(CR) 필요

---

## Phase 1 — 요구사항 수집 및 분석
> 기간: Week 1 (5/7 ~ 5/9) | 3일

### 1.1 이해관계자 인터뷰 & 요구사항 수집

| 활동 | 내용 | 담당 |
|---|---|---|
| 킥오프 미팅 | KPMG AI Lab과 목표/범위 정의 | PM |
| 사용자 니즈 분석 | 페르소나 3종 작성 | PM |
| 벤치마크 분석 | 기존 서비스(네이버 주식, 증권사 HTS) 비교 | 팀 전체 |
| 데이터 소스 조사 | DART, FinanceDataReader, yfinance 가용성 확인 | 백엔드 |

### 1.2 기능 요구사항 정의

#### 비즈니스 요구사항 (BR)

| ID | 요구사항 |
|---|---|
| BR-01 | 일반 투자자가 종목코드 없이도 기업 검색 가능 |
| BR-02 | AI가 기업 히스토리를 3개 카드로 자동 요약 |
| BR-03 | DCF 밸류에이션을 자동 산출하고 결과 시각화 |
| BR-04 | WACC 계산 전 과정 투명하게 공개 |
| BR-05 | DCF 불신뢰 시 자동 경고 + 대안 방법론 제시 |
| BR-06 | 손익 흐름을 시각적 다이어그램으로 표시 |

#### 기능 요구사항 (FR)

| ID | 기능 | 우선순위 |
|---|---|---|
| FR-01 | 종목 검색 (회사명/코드) | 필수 |
| FR-02 | 주가 차트 (캔들+이동평균+거래량) | 필수 |
| FR-03 | 재무 지표 카드 | 필수 |
| FR-04 | AI 브리핑 3카드 | 필수 |
| FR-05 | Sankey 손익 다이어그램 | 높음 |
| FR-06 | DCF 3시나리오 자동 산출 | 필수 |
| FR-07 | WACC 상세 산출 표시 | 높음 |
| FR-08 | 민감도 히트맵 | 높음 |
| FR-09 | DCF 유효성 검증 + 경고 | 필수 |
| FR-10 | 멀티플 역산 적정가 | 높음 |
| FR-11 | SWOT 자동 생성 | 낮음 (Sprint 2) |
| FR-12 | RAG 챗봇 | 낮음 (Sprint 2) |

#### 비기능 요구사항 (NFR)

| ID | 요구사항 | 목표값 |
|---|---|---|
| NFR-01 | 응답 속도 | 5초 이내 (캐시 포함) |
| NFR-02 | 정확도 | DCF ±5% 이내 |
| NFR-03 | 가용성 | 데모 시간 100% |
| NFR-04 | 유지보수성 | 모듈화 구조, 문서화 |

### 1.3 Phase 1 산출물

| 산출물 | 위치 |
|---|---|
| 요구사항 명세서 (SRS) | `docs/01_FILMN9_프로젝트기획서_v1.md` |
| 사용자 페르소나 | `docs/02_FILMN9_페르소나_v1.md` |
| 프로젝트 헌장 | `docs/03_FILMN9_프로젝트헌장_v1.md` |
| WBS 초안 | `Downloads/FILMN9_WBS_v3.xlsx` |

### 1.4 Phase 1 완료 기준 (Exit Criteria)
- [ ] 요구사항 목록 확정 및 우선순위 합의
- [ ] 이해관계자 서명 완료
- [ ] 기술 스택 확정
- [ ] 일정 / 예산 승인

---

## Phase 2 — 시스템 아키텍처 설계
> 기간: Week 1 후반 (5/9 ~ 5/11) | 3일

### 2.1 시스템 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│                       사용자 브라우저                         │
│                    (localhost:3000)                          │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP / REST API
┌──────────────────────────▼──────────────────────────────────┐
│                    Next.js Frontend                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────┐ │
│  │  Tab 1   │  │  Tab 2   │  │  Tab 3   │  │  Sankey    │ │
│  │ 기업 개요 │  │ 밸류에이션│  │ AI 분석  │  │  iframe   │ │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └─────┬──────┘ │
└───────┼─────────────┼─────────────┼───────────────┼────────┘
        │             │             │               │
┌───────▼─────────────▼─────────────▼───────────────▼────────┐
│                    FastAPI Backend (:8000)                   │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  /search  /stock/{code}  /valuation/{code}           │  │
│  │  /wacc/{code}  /sankey/{code}  /briefing/{code}      │  │
│  └──────────────────┬───────────────────────────────────┘  │
│                     │                                        │
│  ┌──────────────────▼─────────────────────────────────────┐ │
│  │               Business Logic Layer                      │ │
│  │  ┌──────────┐ ┌──────────┐ ┌───────────┐ ┌─────────┐  │ │
│  │  │DCF Engine│ │WACC Calc │ │LLM Service│ │Sankey   │  │ │
│  │  └─────┬────┘ └──────┬───┘ └─────┬─────┘ │Builder  │  │ │
│  │        │             │           │        └────┬────┘  │ │
│  └────────┼─────────────┼───────────┼─────────────┼───────┘ │
└───────────┼─────────────┼───────────┼─────────────┼─────────┘
            │             │           │             │
┌───────────▼─────────────▼───────────▼─────────────▼────────┐
│                       Data Layer                            │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────────┐   │
│  │  SQLite DB  │  │ DART API    │  │  OpenAI GPT-4o   │   │
│  │ (재무 데이터)│  │ (공시 원본) │  │  (브리핑/SWOT)   │   │
│  └─────────────┘  └─────────────┘  └──────────────────┘   │
│  ┌─────────────┐  ┌─────────────┐                          │
│  │FinanceData  │  │  Chroma DB  │                          │
│  │Reader/yfinance│ │ (RAG 벡터)  │                          │
│  └─────────────┘  └─────────────┘                          │
└────────────────────────────────────────────────────────────┘
```

### 2.2 데이터베이스 설계

#### 핵심 테이블 구조

```sql
-- 기업 마스터
CREATE TABLE company (
    stock_code  TEXT PRIMARY KEY,
    company_nm  TEXT NOT NULL,
    market      TEXT,          -- KOSPI / KOSDAQ
    sector      TEXT,
    listed_date TEXT
);

-- 재무 요약 (연간)
CREATE TABLE financial_summary (
    stock_code  TEXT,
    year        INTEGER,
    revenue     REAL,          -- 매출액 (원)
    op_income   REAL,          -- 영업이익 (원)
    net_income  REAL,          -- 당기순이익 (원)
    total_asset REAL,
    total_debt  REAL,
    PRIMARY KEY (stock_code, year)
);

-- 재무 세부 (손익계산서 항목별)
CREATE TABLE financial_detail (
    stock_code    TEXT,
    year          INTEGER,
    account_nm    TEXT,        -- 계정명
    amount        REAL,        -- 금액 (원)
    display_order INTEGER,
    PRIMARY KEY (stock_code, year, account_nm)
);

-- 주가 (일별)
CREATE TABLE stock_price (
    stock_code  TEXT,
    date        TEXT,
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    volume      INTEGER,
    PRIMARY KEY (stock_code, date)
);

-- DCF 결과 캐시
CREATE TABLE dcf_result (
    stock_code  TEXT,
    scenario    TEXT,          -- bear / base / bull
    fair_value  REAL,          -- 주당 적정가
    wacc        REAL,
    upside_pct  REAL,          -- 업사이드 (%)
    created_at  TEXT,
    PRIMARY KEY (stock_code, scenario)
);
```

### 2.3 API 설계

| Method | Endpoint | 응답 | 설명 |
|---|---|---|---|
| GET | `/search?q={keyword}` | `[{code, name}]` | 종목 검색 |
| GET | `/stock/{code}/summary` | `{price, metrics}` | 기본 정보 |
| GET | `/stock/{code}/chart` | `[{date, ohlcv}]` | 주가 데이터 |
| GET | `/stock/{code}/briefing` | `{overview, model, factors}` | AI 브리핑 |
| GET | `/stock/{code}/sankey` | `HTML redirect` | Sankey 파일 |
| GET | `/valuation/{code}/dcf` | `{bear, base, bull}` | DCF 결과 |
| GET | `/valuation/{code}/wacc` | `{rf, beta, mrp, kd, wacc}` | WACC 상세 |
| GET | `/valuation/{code}/sensitivity` | `[[적정가 매트릭스]]` | 민감도 |
| GET | `/valuation/{code}/multiples` | `{ev_ebitda, pe, pb}` | 멀티플 역산 |

### 2.4 Phase 2 산출물
- 시스템 아키텍처 다이어그램
- DB ERD (Entity Relationship Diagram)
- API 명세서
- 화면 설계서 (와이어프레임)

---

## Phase 3 — 상세 설계
> 기간: Week 2 초반 (5/12 ~ 5/14) | 3일

### 3.1 화면 설계

#### 메인 레이아웃
```
┌─────────────────────────────────────────────────────────────┐
│  FILMN9 로고         [검색창: 종목명/코드 입력...]  [검색]    │
├─────────────────────────────────────────────────────────────┤
│  [Tab1: 기업 개요]  [Tab2: 밸류에이션]  [Tab3: AI 분석]      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Tab 내용 영역                                              │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

#### Tab2 레이아웃
```
┌────────────────────────────────────────────────────────────┐
│  Hero 영역: [✓ 실데이터]  Base ₩112,677  +23.5% ▲         │
│            Bear ₩89,xxx | Base ₩112,677 | Bull ₩134,xxx   │
├────────────────────────────────────────────────────────────┤
│  [DCF] [WACC] [민감도] [멀티플]                             │
├────────────────────────────────────────────────────────────┤
│                                                             │
│  선택된 서브탭 내용                                          │
│                                                             │
└────────────────────────────────────────────────────────────┘
```

### 3.2 DCF 로직 상세 설계

```python
# DCF 계산 흐름 (의사코드)

def calculate_dcf(stock_code: str, scenario: str) -> DCFResult:
    
    # 1. 데이터 수집
    financial = get_financials(stock_code)         # DART
    stock_info = get_stock_info(stock_code)         # 주가, 시총
    
    # 2. WACC 산출
    rf    = get_risk_free_rate()                    # 국고채 10년물
    beta  = calculate_beta(stock_code, period=2y)   # 회귀분석
    mrp   = 0.055                                   # 시장위험프리미엄
    ke    = rf + beta * mrp                         # 자기자본비용
    kd    = financial.interest_exp / financial.total_debt  # 타인자본비용
    t     = financial.tax_rate                      # 실효세율
    e_ratio = market_cap / (market_cap + net_debt)
    d_ratio = 1 - e_ratio
    wacc  = e_ratio * ke + d_ratio * kd * (1 - t)
    
    # 3. 시나리오별 가정 설정
    assumptions = get_scenario_assumptions(scenario)
    # Bear: 성장률 낮음, 마진 낮음
    # Base: 현재 추세 유지
    # Bull: 성장률 높음, 마진 개선
    
    # 4. FCFF 추정 (5개년)
    fcff_list = []
    for year in range(1, 6):
        revenue    = prev_revenue * (1 + assumptions.growth)
        ebit       = revenue * assumptions.op_margin
        nopat      = ebit * (1 - t)
        capex      = revenue * assumptions.capex_ratio
        delta_nwc  = revenue * assumptions.nwc_ratio
        da         = revenue * assumptions.da_ratio
        fcff       = nopat + da - capex - delta_nwc
        fcff_list.append(fcff)
    
    # 5. DCF 유효성 검증
    if fcff_list[0] < 0:
        return DCFResult(valid=False, warning="Y+1 FCFF 음수 — 멀티플 방법론 권장")
    
    # 6. 터미널 밸류
    terminal_growth = assumptions.terminal_g
    tv = fcff_list[-1] * (1 + terminal_growth) / (wacc - terminal_growth)
    
    # 7. 현재가치 합산
    enterprise_value = sum(
        fcff / (1 + wacc) ** t for t, fcff in enumerate(fcff_list, 1)
    ) + tv / (1 + wacc) ** 5
    
    # 8. 주당 적정가
    equity_value = enterprise_value - net_debt
    fair_value   = equity_value / shares_outstanding
    
    return DCFResult(
        fair_value=fair_value,
        wacc=wacc,
        upside=(fair_value / current_price - 1) * 100,
        fcff_list=fcff_list,
        valid=True
    )
```

### 3.3 Phase 3 산출물
- UI 컴포넌트 목록 및 Props 정의
- 핵심 비즈니스 로직 의사코드
- 데이터 플로우 다이어그램
- 기술 설계 문서

---

## Phase 4 — 구현 (개발)
> 기간: Week 2 중반 ~ Week 3 초반 (5/14 ~ 5/21) | 8일

### 4.1 개발 순서 및 의존성

```
Day 1-2: 백엔드 기반 작업
│  ├── FastAPI 프로젝트 구조 설정
│  ├── SQLite DB 스키마 생성
│  └── DART API 연동 + 데이터 수집 스크립트

Day 3-4: 핵심 로직 구현
│  ├── DCF 계산 엔진
│  ├── WACC 자동 산출
│  └── 민감도 분석 행렬

Day 4-5: 프론트엔드 기반
│  ├── Next.js 앱 구조 설정
│  ├── 공통 레이아웃 컴포넌트
│  └── 검색 기능

Day 5-6: Tab1 구현
│  ├── 주가 차트 (Recharts)
│  ├── 재무 지표 카드
│  └── AI 브리핑 카드 (LLM 연동)

Day 6-7: Tab2 구현
│  ├── Hero 적정가 영역
│  ├── DCF 테이블
│  ├── WACC 상세
│  ├── 민감도 히트맵
│  └── 멀티플 역산

Day 7-8: Sankey + Tab3
│  ├── build_sankey.py 개발
│  ├── Plotly Sankey HTML 생성
│  ├── Tab3 UI (SWOT + 챗봇 레이아웃)
│  └── API-프론트 연동 전체 통합
```

### 4.2 코딩 표준

| 구분 | 표준 |
|---|---|
| Python | PEP8, type hints 필수, docstring 작성 |
| TypeScript | strict mode, 컴포넌트 Props 타입 정의 |
| Git | `feat/`, `fix/`, `refactor/` 브랜치 전략 |
| 커밋 메시지 | `[TAB1] 주가 차트 캔들스틱 구현` 형식 |

### 4.3 Phase 4 산출물
- 백엔드 소스코드 (FastAPI)
- 프론트엔드 소스코드 (Next.js)
- 데이터 수집 스크립트
- Sankey HTML 파일 (3종목)

---

## Phase 5 — 테스트 & QA
> 기간: Week 3 중반 (5/21 ~ 5/24) | 4일

### 5.1 테스트 유형

#### 단위 테스트 (Unit Test)
```
테스트 대상                  기준
────────────────────────────────────────────
DCF 계산 엔진               DART 원장 ±5%
WACC 산출                   수동 계산값 ±0.1%
Sankey 단위 변환 (원→조/억)  정확한 단위 표기
DCF 유효성 검증              FCFF<0 → 100% 감지
멀티플 역산                  피어 멀티플 정상 반영
```

#### 통합 테스트 (Integration Test)
```
시나리오 1: 아모레퍼시픽 전체 플로우
  검색 → Tab1 로딩 → Sankey → Tab2 DCF → WACC → 민감도

시나리오 2: 삼성전기 DCF Invalid
  검색 → Tab2 → 경고 배너 표시 → 멀티플 탭 확인

시나리오 3: NAVER 영업비용 구조
  검색 → Tab1 Sankey → 영업비용 직접 연결 확인
```

#### 회귀 테스트 (Regression Test)
- 버그 수정 후 기존 정상 케이스 재확인
- 3종목 × 전 탭 크로스체크

### 5.2 QA 체크리스트

| 영역 | 항목 | 기준 |
|---|---|---|
| 숫자 정확도 | DCF 적정가 | DART 기준 ±5% |
| 단위 표기 | Sankey 조/억 | 소수점 2자리 정확 |
| 경고 감지 | DCF Invalid | 삼성전기 100% 감지 |
| 화면 로딩 | 3종목 전 탭 | 5초 이내 |
| UI 레이아웃 | 브라우저 zoom 110% | 깨짐 없음 |
| 에러 핸들링 | API 실패 시 | graceful fallback |

### 5.3 버그 추적
```
우선순위 분류:
  P1 (Critical): 데모 시연 불가 → 즉시 수정
  P2 (High)    : 주요 기능 오류 → 당일 수정
  P3 (Medium)  : UI 이슈       → 데모 전 수정
  P4 (Low)     : 사소한 문제   → Sprint 2 수정
```

### 5.4 Phase 5 산출물
- 테스트 결과 리포트
- 버그 목록 및 해결 여부
- QA 완료 확인서

---

## Phase 6 — 배포 & 운영
> 기간: Week 3 후반 (5/24 ~ 5/26) | PoC는 로컬 배포

### 6.1 PoC 배포 구성

```
start.bat 실행
│
├── cmd /k "cd /d C:\Users\Admin\FILMN9 && uvicorn main:app --reload --port 8000"
└── cmd /k "cd /d C:\Users\Admin\FILMN9\frontend && npm run dev"
```

### 6.2 최종 체크리스트

```
데모 10분 전 체크
─────────────────────────────────────
□ start.bat 실행 → :8000, :3000 기동 확인
□ 브라우저 localhost:3000 열기
□ 아모레퍼시픽(090430) 화면 미리 열기
□ 브라우저 zoom 110% 설정
□ 화면 공유 확인
□ 시연 스크립트 최종 확인
□ 백업 노트북 준비
```

### 6.3 Sprint 2 이후 프로덕션 배포 계획 (워터폴 연장)

| 항목 | 기술 |
|---|---|
| 클라우드 | AWS EC2 or GCP Cloud Run |
| DB 마이그레이션 | SQLite → PostgreSQL |
| 인증 | Supabase Auth / NextAuth |
| CDN | Vercel (프론트엔드) |
| 모니터링 | Sentry, CloudWatch |

---

## 전체 일정 요약 (워터폴 간트 차트)

```
              Week 1           Week 2           Week 3
Phase         M T W T F S S   M T W T F S S   M T W T F S S
─────────────────────────────────────────────────────────────
1. 요구사항  ■ ■ ■
2. 아키텍처          ■ ■ ■
3. 상세설계                   ■ ■ ■
4. 구현                           ■ ■ ■ ■ ■ ■ ■ ■
5. 테스트                                         ■ ■ ■ ■
6. 배포                                                   ■ ■
─────────────────────────────────────────────────────────────
마일스톤     K               A               B   C       D
             (킥오프)         (Alpha)         (Beta)(완성)(데모)
```

---

## 워터폴 vs. 실제 진행 비교

| 구분 | 워터폴 이상적 흐름 | FILMN9 실제 진행 |
|---|---|---|
| 요구사항 | 고정 후 변경 없음 | 개발 중 기능 추가/변경 |
| 문서화 | 선행, 상세 | 병행 또는 후행 |
| 테스트 | Phase 5 일괄 | 개발 중 지속 |
| 일정 | 순차적 | Sprint 병렬 진행 |
| 변경 대응 | 느림 (CR 필요) | 빠름 (당일 수정) |

> **결론**: FILMN9 같은 PoC 프로젝트는 요구사항이 유동적이므로
> 실제로는 **애자일 방식이 더 적합**하다. (다음 문서 참고)

---

*END OF 워터폴 설계도*
