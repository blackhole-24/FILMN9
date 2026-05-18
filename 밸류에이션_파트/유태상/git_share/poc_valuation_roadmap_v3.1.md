# POC Valuation Roadmap v3.1

기업가치 평가 시스템 POC 완료 상태 및 향후 운영 단계 확장 계획.

---

## 0. POC 범위

- **타겟:** 아모레퍼시픽 (090430, KOSPI)
- **피어:** LG생활건강, 한국콜마, 에이피알 — 모두 KOSPI
- **회계연도:** FY2023, FY2024, FY2025
- **평가기준일:** `date.today()` 자동

---

## 1. 완료 (Done)

### 1.1 Phase 0 — 사전 준비
- ✅ `.env` 키 4종 / 평가 대상·피어 설정

### 1.2 Phase 1 — 재무 데이터 수집
- ✅ 팀원 `xbrl_financials_v4.py` (DART → XBRL → 재무 추출)
- ✅ 4사 × 3년 일괄 추출 + 캐시

### 1.3 Phase 2-A — 피어 베타
- ✅ KRX OpenAPI 클라이언트 + 일자별 캐시
- ✅ OLS 회귀 + Blume α = 2/3 정확값
- ✅ **Winsorize ±3σ 이상치 처리** (디폴트)
- ✅ KRX 공시 베타 절대오차 합산 0.124

### 1.4 Phase 2-C — 시가총액 E
- ✅ **사업보고서 청크 RAG + ChatGPT 4o-mini**로 발행/자기주식수
- ✅ 임의값 절대 금지 — 추출 실패 시 RuntimeError

### 1.5 Phase 3 — WACC
- ✅ Rf (ECOS), ERP 8%, CRP 0%, SRP 자동 매칭
- ✅ Hamada Unlever (피어) + Relever (타겟)
- ✅ Ke = Rf + β_L·ERP + SRP
- ✅ **Kd 동적 산정** (v3.1 신규):
  - RAG로 회사채 + CP 신용등급 추출
  - 우선순위: 회사채 > CP
  - CP 등급만 있음 → **Term-Credit Spread 변환**
- ✅ KOFIA CSV 자동 로드 (회사채 + CP)
- ✅ **하드코드 Kd = 3.15% 완전 제거**

### 1.6 Phase 4 — DCF
- ✅ 3년 평균 정상화 비율
- ✅ Fade-out 곡선
- ✅ **세율: 매년 예측 EBIT 기준 갱신** (v3.1 변경)
- ✅ Gordon Growth TV
- ✅ 위계 검증 + Y+5 CapEx 정상화

### 1.7 Phase 5 — Equity Value
- ✅ EV − Net Debt + NOA_clean − 비지배지분
- ✅ **현금 이중차감 방지**

### 1.8 Phase 6 — 멀티플
- ✅ 4종 (EV/EBITDA, EV/Sales, PER, PBR) 피어 중위값

### 1.9 Phase 7 — 불확실성
- ✅ Bear/Base/Bull, 민감도, 토네이도

### 1.10 통합 + 대시보드
- ✅ Streamlit 대시보드
- ✅ **mockup·임의값 완전 제거** — JSON 없으면 안내 화면

---

## 2. 8개 결정사항 (확정)

| # | 항목 | 결정 | 구현 위치 |
|---|---|---|---|
| 1 | 현금성자산 처리 | Net Debt에서만 차감 | `equity_value.py` |
| 2 | 정상화 비율 | 3년 평균 | `dcf_engine.py` |
| 3 | 세율 | 한계세율 (DCF 매년 갱신) | `dcf_engine.py`, `wacc_engine.py` |
| 4 | SRP | 시총 자동 매칭 3분위 | `config.match_srp` |
| 5 | NOA | 팀원 NOA_RULES_FINAL_V3 | XBRL 모듈 |
| 6 | 에이피알 피어 포함 | 포함 | `config.PEERS` |
| 7 | 평가기준일 T | today() 자동 | `run_valuation.py` |
| 8 | 추가 필드 | 별도 모듈 분리 | `compute_equity.py` 등 |

---

## 3. 운영 단계 확장 계획

### 3.1 대상 종목 확장
**2개 파일만 갈아끼우면 됨:**
- `valuation_engine/config.py` 의 TARGET / PEERS
- `peer_beta/config.py` 의 DEFAULT_PEERS

**전제:** 새 대상의 사업보고서 청크 jsonl이 `VAR/<KOSPI|KOSDAQ>/` 에 존재

### 3.2 데이터 갱신 자동화 (수동 → 자동)
- ⚠ KOFIA CSV 자동 다운로드 (현재 수동)
- ⚠ 신용등급 갱신 알림
- ⚠ 사업보고서 청크 자동 임베딩

### 3.3 추가 보강 항목
- ⚠ 유효세율 추가 → max(유효, 한계)
- ⚠ 발행자별 실측 CP yield
- ⚠ CRP 도입

### 3.4 신용평가 데이터 보강
- ✅ 회사채 CSV: 10개 등급 전체
- ⚠ CP CSV: 현재 3개 등급만 (A1/A2+/A3+)

### 3.5 UI/UX
- ⚠ 다종목 비교
- ⚠ 시계열 추이
- ⚠ PDF/Excel 리포트

---

## 4. 미구현·결정 보류

| 항목 | 사유 | 향후 |
|---|---|---|
| 유효세율 함수 | 팀원 XBRL 결과에 세전이익·법인세 필드 없음 | XBRL 모듈 보강 후 |
| CP CSV 자동 갱신 | KOFIA 무료 API 없음 | 수동 유지 |
| 발행자별 CP yield | 사업보고서 본문 추출 불확실 | RAG 프롬프트 후속 |
| 미평정 기업 fallback | 임의값 정책 위배 | 사용자 명시적 입력 |
| 분기별 평가 | 미구현 | 운영 단계 |
| 다국가 확장 | CRP·환율·세제 차이 | 운영 단계 |

---

## 5. 실행 매뉴얼

```bash
# 1) 사전 설치 (1회)
conda activate dart-rag
cd C:\Users\Admin\Desktop\VAR
pip install -r peer_beta/requirements.txt
pip install -r valuation_engine/requirements.txt

# 2) 데이터 준비
#    - .env 키 4종
#    - KOFIA CSV 2종 (채권/CP)
#    - 사업보고서 청크 jsonl

# 3) 실행
python -m peer_beta.run_beta --outlier-handling winsorize
python -m valuation_engine.run_valuation

# 4) 결과 확인
streamlit run valuation_engine/streamlit_app.py
```

---

## 6. v3 → v3.1 핵심 변경 사항

1. **Kd 하드코드 제거** (3.15% → 동적, RAG × KOFIA)
2. **CP→회사채 Term-Credit Spread 변환** 추가
3. **DCF 세율 매년 갱신**
4. **Streamlit mockup 완전 제거**
5. **CP CSV 5사 평균 자동 필터링**
