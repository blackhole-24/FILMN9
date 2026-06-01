# 팀원 설치·실행 가이드 (SETUP)

한국 주식 **DCF·상대가치 통합 평가 엔진**을 로컬에서 구동하는 방법입니다.
처음 받으시는 분은 이 문서의 순서대로만 따라오시면 됩니다.

---

## 0. 사전 준비

- **Python 3.10+** (conda 권장)
- **별도 전달받을 것: `chroma_db` (임베딩 데이터)** — 용량이 커서 GitHub에 없습니다.
- **API 키 4종** (아래 ④에서 발급)

---

## 1. 설치 — 4단계

### ① 코드 내려받기
```bash
git clone <repository-url>
cd VAR
```
> `krx_desc.csv`(전종목 산업 마스터)는 repo에 포함되어 있습니다 — 피어 선정에 필수.

### ② 의존성 설치
```bash
pip install -r requirements.txt
```
> `torch`는 환경/GPU에 맞는 빌드를 별도 설치하는 것을 권장합니다 → https://pytorch.org

### ③ 임베딩 데이터 배치
별도 전달받은 **`chroma_db`** 폴더를 다음 위치에 둡니다:
```
VAR/embedding/chroma_db/
```
> 이게 없으면 주식수·신용등급·사업유사도 RAG가 동작하지 않습니다.

### ④ API 키 입력
```bash
cp .env.example .env      # Windows: copy .env.example .env
```
`.env` 파일을 열어 4개 키를 채웁니다:

| 키 | 용도 | 발급처 |
|---|---|---|
| `DART_API_KEY` | 재무제표·사업보고서 | https://opendart.fss.or.kr |
| `ECOS_API_KEY` | 무위험수익률(국고채) | https://ecos.bok.or.kr/api |
| `krxdata` | 주가·시가총액 | https://data.krx.co.kr |
| `OPENAI_API_KEY` | 신용등급·주식수 추출 | https://platform.openai.com |

> ⚠ `.env`는 `.gitignore`로 제외됩니다. 절대 커밋하지 마세요.

---

## 2. 실행

### 웹 UI (권장)
```bash
python -m uvicorn valuation_engine.api:app --port 8000
```
→ 브라우저에서 **http://localhost:8000** 접속 → 종목코드/회사명 입력

### CLI 단일 평가
```bash
python -m valuation_engine.run_valuation_auto -t 삼성전기
python -m valuation_engine.run_valuation_auto -t 005930 -d 2026-06-01
```

### 여러 종목 일괄 평가 (선택)
```bash
python -m valuation_engine.db.prewarm --tickers 005930,000660,009150
```

---

## 3. 나머지 데이터는 자동 수집됩니다 (첫 평가만 느림)

캐시(`data/`·`peer_beta/data/` 등)는 repo에 없으므로, **첫 평가 시 코드가 API로 자동 다운로드**합니다:

| 데이터 | 출처 | 필요 키 |
|---|---|---|
| 주가·시가총액 | KRX 자동수집 | `krxdata` |
| 재무제표(XBRL) | DART 자동수집 | `DART_API_KEY` |
| 회사채 수익률 | KOFIA 자동수집 | 불필요 |
| 산업 무차입베타 | Damodaran 자동다운로드 | 불필요 |

→ **첫 평가는 종목당 수 분**(데이터 수집), **이후엔 캐시로 수 초**입니다.

---

## 4. 작동 필수 체크리스트

- [x] 코드 (clone하면 포함)
- [x] `krx_desc.csv` (repo 포함 — 전종목 산업 마스터)
- [ ] `embedding/chroma_db/` (**별도 전달받아 배치**)
- [ ] `.env`에 API 키 4종

세 번째·네 번째가 빠지면:
- **chroma_db 없음** → 주식수 추출 실패로 평가 중단
- **API 키 없음** → 데이터 수집 API 호출 실패

---

## 5. 자주 나는 메시지 (정상 동작)

| 메시지 | 의미 | 조치 |
|---|---|---|
| "통합 인덱스 없음 … fetch_all 실행 필요" | 첫 평가 중 재무 수집 단계 | 정상 — 자동 수집 후 진행됨 |
| "DCF 부적합 (financial/holding)" | 금융·지주회사 | 정상 — 멀티플·NAV 대체 안내 |
| "적정주가 점추정 숨김 (등급 D·E)" | 신뢰도 낮아 범위만 표시 | 정상 — 앵커링 방지 설계 |
| 평가가 매우 느림 | 첫 평가 자동수집 | 정상 — 두 번째부터 빠름 |
| "주식수 추출 실패" | chroma_db 미배치 | `embedding/chroma_db/` 확인 |
| "krxdata 환경변수 없음" | API 키 누락 | `.env` 확인 |

---

## 6. 참고 — 무엇이 어떻게 동작하는지

- 전체 구조·이론적 근거는 **기술문서 PDF**(`한국주식_가치평가시스템_기술문서.pdf`)를 참고하세요.
- 평가 파이프라인: 입력 → 피어 산정 → 베타 → WACC → DCF → 멀티플 → 불확실성 → 결과.
- 모든 산출은 **DCF 등급(A~E)과 멀티플·EPV를 함께** 봐야 합니다(단일 적정가 맹신 금지).
