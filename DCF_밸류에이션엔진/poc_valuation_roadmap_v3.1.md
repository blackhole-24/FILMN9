# POC Valuation Roadmap v3.1

기업가치 평가 시스템 POC 완료 상태 및 향후 운영 단계 확장 계획.
v3 대비 추가: Kd 동적 산정 완성, CP→회사채 변환, 매년 세율 갱신.

---

## 0. POC 범위

- **타겟:** 아모레퍼시픽 (090430, KOSPI)
- **피어:** LG생활건강 (051900), 한국콜마 (161890), 에이피알 (278470) — 모두 KOSPI
- **회계연도:** FY2023, FY2024, FY2025 (3개년)
- **평가기준일:** `date.today()` 자동

---

## 1. 완료 (Done)

### 1.1 Phase 0 — 사전 준비
- ✅ `.env` 키 4종 (krxdata / DART_API_KEY / ECOS_API_KEY / OPENAI_API_KEY)
- ✅ 평가 대상·피어 설정 (`valuation_engine/config.py`, `peer_beta/config.py`)

### 1.2 Phase 1 — 재무 데이터 수집
- ✅ 팀원 모듈 `XBRL/xbrl_financials_v4.py` (DART → XBRL → 손익·CF·BS·IBD·NOA 추출)
- ✅ `valuation_engine/fetch_peers_financials.py` (4사 × 3년 일괄 추출 + 캐시)
- ✅ 산출: `data/xbrl/<회사>_<연도>.json` (12개) + `all_financials_<T>.json`

### 1.3 Phase 2-A — 피어 베타
- ✅ KRX OpenAPI 클라이언트 + 일자별 캐시 (`peer_beta/krx_client.py`)
- ✅ 매주 금요일 후보 + 영업일 fallback (`calendar_utils.py`)
- ✅ OLS 회귀 + Blume 조정 (`beta_calculator.py`)
- ✅ **Blume α = 2/3 정확값** (KRX 공시 베타와 정합)
- ✅ **이상치 처리: Winsorize ±3σ 디폴트** (표본 N 보존, 일반투자자 친화)
- ✅ 검증 노트북 (`peer_beta_verification.ipynb`)
- ✅ KRX 공시 베타와 절대오차 합산 0.124 달성 (winsorize)

### 1.4 Phase 2-C — 시가총액 E
- ✅ KRX 캐시 재사용으로 종가 추출 (`compute_equity.fetch_close_from_cache`)
- ✅ **사업보고서 청크 RAG + ChatGPT 4o-mini로 발행/자기주식수** (`fetch_shares_via_rag`)
- ✅ 임의값 절대 금지 — 추출 실패 시 RuntimeError
- ✅ E = T일 종가 × (발행 − 자기주식)

### 1.5 Phase 3 — WACC
- ✅ Rf: ECOS API 국고채 10년 실시간 (`ecos_client.fetch_rf`)
- ✅ ERP = 8% 고정, CRP = 0% (POC)
- ✅ SRP: 타겟 시총 자동 매칭 3분위 (`config.match_srp`)
- ✅ 한계세율: 타겟·피어 각자 EBIT 기준 (`xbrl_financials_v4.get_marginal_tax_rate`)
- ✅ 피어 Hamada Unlever (피어 3사, 타겟 제외)
- ✅ 피어 집계: β_U, D/E 중위값 (Median)
- ✅ 타겟 Hamada Relever
- ✅ Ke = Rf + β_L·ERP + SRP + CRP
- ✅ **Kd 동적 산정** (v3.1 신규):
  - 사업보고서 RAG로 회사채 + CP 신용등급 추출 (`fetch_credit_rating.py`)
  - 우선순위: 회사채 등급 > CP 등급
  - 회사채 등급 → KOFIA 회사채 I(공모사채) 무보증 5년 lookup (`kd_loader.py`)
  - CP 등급만 있음 → **Term-Credit Spread 분해 변환** (`cp_to_bond_converter.py`)
- ✅ KOFIA CSV 자동 로드 (회사채: `kd_loader.py`, CP: `cp_loader.py`)
- ✅ **하드코드 Kd = 3.15% 완전 제거**
- ✅ WACC = E·Ke + D·Kd_after_tax

### 1.6 Phase 4 — DCF
- ✅ 정상화 비율 3년 평균 (OPM, D&A율, CapEx율, NWC율)
- ✅ 이상치 ±50% 이격 경고
- ✅ Fade-out 곡선 (Y1=CAGR, Y2=×0.8, Y3/Y4=×0.7, Y5=g)
- ✅ **세율: 매년 예측 EBIT 기준 갱신** (v3.1 변경)
- ✅ Gordon Growth TV
- ✅ 위계 검증 (g < Rf < WACC)
- ✅ Y+5 CapEx > D&A 정상화

### 1.7 Phase 5 — Equity Value
- ✅ Equity = EV − Net Debt + NOA_clean − 비지배지분
- ✅ **현금 이중차감 방지** (Net Debt에서만 차감)
- ✅ NOA 5분류 (팀원 `NOA_RULES_FINAL_V3`)

### 1.8 Phase 6 — 멀티플
- ✅ EV/EBITDA, EV/Sales, PER, PBR 4종
- ✅ 피어 중위값
- ✅ 25~75 백분위 이격 경고

### 1.9 Phase 7 — 불확실성
- ✅ Bear/Base/Bull (매출성장·OPM·CapEx·NWC 3년 min/avg/max 조합)
- ✅ 민감도 매트릭스 (WACC ±1%p × g ±0.5%p, 3×3)
- ✅ 토네이도 (변수별 단독 변동 영향도)

### 1.10 통합 + 대시보드
- ✅ `run_valuation.py` 통합 진입점
- ✅ Streamlit 대시보드 (`streamlit_app.py`)
- ✅ **mockup·임의값 완전 제거** — JSON 없으면 안내 화면
- ✅ HTML 대시보드 디자인 유지 (CSS·레이아웃)

---

## 2. 8개 결정사항 (확정)

| # | 항목 | 결정 | 구현 위치 |
|---|---|---|---|
| 1 | 현금성자산 처리 | Net Debt에서만 차감, NOA 제외 | `equity_value.py` |
| 2 | 정상화 비율 | 모두 3년 평균 | `dcf_engine.py` |
| 3 | 세율 | 한계세율 (DCF는 매년 갱신) | `dcf_engine.py`, `wacc_engine.py` |
| 4 | SRP | 시총 자동 매칭 3분위 | `config.match_srp` |
| 5 | NOA | 팀원 NOA_RULES_FINAL_V3 그대로 | XBRL 모듈 |
| 6 | 에이피알 피어 포함 | 포함 | `config.PEERS` |
| 7 | 평가기준일 T | `date.today()` 자동 | `run_valuation.py` |
| 8 | 추가 필드 | 별도 모듈 분리 | `compute_equity.py`, `kd_loader.py` 등 |

---

## 3. 운영 단계 확장 계획

### 3.1 대상 종목 확장 — TARGET/PEERS 갈아끼우기만으로 대응
**바꿀 위치 (2개 파일):**
```python
# valuation_engine/config.py
TARGET = {"name": "...", "ticker": "...", "corp_code": "...", "market": "KOSPI"}
PEERS  = [...]

# peer_beta/config.py
DEFAULT_PEERS = [...]
```

**전제 조건:**
- 새 대상의 사업보고서 청크 jsonl이 `VAR/<KOSPI|KOSDAQ>/` 에 존재해야 함
- 코스닥 종목은 `market: "KOSDAQ"` 정확히 표기 (베타 회귀 시 지수 매칭)

### 3.2 데이터 갱신 자동화 (수동 → 자동)
- ⚠ **KOFIA CSV 자동 다운로드** — 현재 수동. 추후 KOFIA API 연동 검토
- ⚠ **신용등급 갱신 알림** — 사업보고서 정기 갱신 외 정정공시 발생 시 RAG 재실행 필요
- ⚠ **사업보고서 청크 자동 임베딩** — 팀원 파이프라인 자동화 필요

### 3.3 추가 보강 항목 (현재 POC 단순화)
- ⚠ **유효세율 추가** → `max(유효, 한계)` 보수 적용 (현재는 한계세율만)
- ⚠ **발행자별 실측 CP yield** → 현재 KOFIA 평균 사용 (결과적으로 등급 매핑과 동일)
- ⚠ **CRP 도입** (한국 외 해외사업 비중 ≥ 30% 등 기준)

### 3.4 신용평가 데이터 보강
- ✅ 회사채 CSV: 10개 등급 전체 수록 (AAA~BBB-)
- ⚠ **CP CSV: 현재 3개 등급만 (A1/A2+/A3+)** → A2, A2-, A3, A3- 등 미수록
  - 필요 회사 분석 시 사용자가 KOFIA에서 추가 다운로드
  - 기본적으로 BBB- 보수 폴백 (B+ 이하)

### 3.5 검증·테스트
- ✅ KRX 공시 베타와의 정합성 검증 (winsorize 모드 채택 근거)
- ⚠ Implied ROIC vs WACC 비교 자동 출력 (현재 출력은 됨, 의사결정 미반영)
- ⚠ 멀티플 4종 정합성 자동 검증 (현재 25~75 백분위 경고만)

### 3.6 UI/UX
- ✅ Streamlit 대시보드 (1차 완성)
- ⚠ 다종목 비교 기능 (현재 단일 종목)
- ⚠ 시계열 추이 (분기별 평가 결과 누적)
- ⚠ PDF/Excel 리포트 자동 생성

---

## 4. 미구현·결정 보류 항목

| 항목 | 사유 | 향후 |
|---|---|---|
| 유효세율 함수 | 팀원 XBRL 결과에 세전이익·법인세 필드 없음 | XBRL 모듈 보강 후 활성화 |
| CP CSV 자동 갱신 | KOFIA 무료 API 없음 | 사용자 수동 유지 또는 유료 데이터벤더 검토 |
| 발행자별 CP yield | 사업보고서 본문 추출 불확실 | RAG 프롬프트 후속 실험 |
| 미평정 기업 fallback | "임의값 절대 금지" 정책에 위배 | 사용자 명시적 입력 옵션 검토 |
| 분기별 평가 | 사업보고서 분기 공시 처리 미구현 | 운영 단계 |
| 다국가 확장 | CRP·환율·세제 차이 처리 | 운영 단계 |

---

## 5. 실행 매뉴얼

### 5.1 사전 설치 (1회)
```bash
conda activate dart-rag
cd C:\Users\Admin\Desktop\VAR
pip install -r peer_beta/requirements.txt
pip install -r valuation_engine/requirements.txt
```

### 5.2 데이터 준비 (매 갱신 시)
```bash
# 1) KOFIA CSV 2종 수동 다운로드 → VAR/ 폴더 저장
#    채권시가평가기준수익률[_YYYYMMDD].csv
#    cp_수익률[_YYYYMMDD].csv
# 2) .env 키 4종 확인 (krxdata / DART_API_KEY / ECOS_API_KEY / OPENAI_API_KEY)
# 3) 사업보고서 청크 jsonl 존재 확인
```

### 5.3 평가 실행
```bash
# Phase 2-A: 피어 베타 (캐시 활용)
python -m peer_beta.run_beta --outlier-handling winsorize

# Phase 1-B ~ 7: 통합 평가
python -m valuation_engine.run_valuation

# 결과: valuation_engine/results/valuation_<T>.json
```

### 5.4 결과 확인
```bash
streamlit run valuation_engine/streamlit_app.py
```

---

## 6. 진행 상태 요약

| Phase | 내용 | v3 상태 | v3.1 상태 |
|---|---|---|---|
| 0 | 사전 준비 | ✅ | ✅ |
| 1 | 재무 데이터 수집 | ✅ | ✅ |
| 2-A | 피어 베타 | ✅ | ✅ |
| 2-B | 피어 D (IBD) | ✅ | ✅ |
| 2-C | 피어 E (시가총액) | ✅ | ✅ |
| 3-Rf | 무위험수익률 | ✅ | ✅ |
| 3-Ke | Hamada + Ke | ✅ | ✅ |
| 3-Kd | 타인자본비용 | ❌ 하드코드 | ✅ **RAG×KOFIA 동적** |
| 3-Kd-CP | CP 폴백 | ❌ | ✅ **Term-Credit Spread 변환** |
| 4 | DCF | ⚠ 세율 1회 산정 | ✅ **매년 세율 갱신** |
| 5 | Equity Value | ✅ | ✅ |
| 6 | 멀티플 | ✅ | ✅ |
| 7 | 시나리오·민감도·토네이도 | ✅ | ✅ |
| - | Streamlit 대시보드 | ⚠ mockup | ✅ **실데이터만** |

---

## 7. v3 → v3.1 핵심 변경 사항 (요약)

1. **Kd 하드코드 제거** (3.15% → 동적)
   - 신용등급 RAG (회사채/CP 동시 추출, 우선순위 적용)
   - KOFIA 회사채 CSV + CP CSV 자동 로드
   - Term-Credit Spread 분해 변환 (CP only 회사)
2. **DCF 세율 매년 갱신**
   - 예측 EBIT가 세율 구간을 넘어가도 자동 반영
3. **Streamlit mockup 완전 제거**
   - 임의값 없으면 안내 화면, 실데이터 JSON만 표시
4. **CP CSV 5사 평균 자동 필터링**
   - 개별 5사 행은 자동 제외
