# 기업가치 평가 시스템 (DCF · WACC · FCFF)

한국 상장사 대상 일반투자자용 DCF 기반 기업가치 평가 시스템.
KRX·DART·ECOS·KOFIA·사업보고서 RAG 를 결합하여 적정주가 산출.

---

## ⚡ 빠른 시작

```bash
# 1) 저장소 클론
git clone <repo-url>
cd <repo>

# 2) Conda 환경 (Python 3.11 권장)
conda create -n dart-rag python=3.11
conda activate dart-rag

# 3) 의존성 설치
pip install -r peer_beta/requirements.txt
pip install -r valuation_engine/requirements.txt

# 4) 환경 변수 설정
copy .env.example .env   # Windows
# cp .env.example .env   # macOS/Linux
# 그리고 .env 파일을 열어 4개 키 채우기 (krxdata, DART_API_KEY, ECOS_API_KEY, OPENAI_API_KEY)

# 5) 외부 데이터 수동 다운로드
#    - KOFIA 채권시가평가기준수익률.csv → VAR/ 폴더
#    - KOFIA cp_수익률.csv             → VAR/ 폴더
#    - 사업보고서 청크 jsonl           → VAR/KOSPI/ 또는 VAR/KOSDAQ/

# 6) 평가 대상 설정 (config 2개 파일)
#    - valuation_engine/config.py 의 TARGET / PEERS
#    - peer_beta/config.py 의 DEFAULT_PEERS

# 7) 실행
python -m valuation_engine.run_valuation

# 8) 결과 시각화
streamlit run valuation_engine/streamlit_app.py
```

---

## 🔑 환경 변수 4종 (`.env`)

| 변수명 | 발급처 | 용도 |
|---|---|---|
| `krxdata` | https://openapi.krx.co.kr/ | 주가·지수 (소문자 필수) |
| `DART_API_KEY` | https://opendart.fss.or.kr/ | XBRL 재무제표 |
| `ECOS_API_KEY` | https://ecos.bok.or.kr/api/ | 국고채 10년 Rf |
| `OPENAI_API_KEY` | https://platform.openai.com/ | ChatGPT 4o-mini RAG |

→ `.env` 는 `.gitignore`에 등재되어 절대 업로드되지 않음.

---

## 📁 폴더 구조

```
.
├── .env.example                        # API 키 템플릿
├── .gitignore                          # 민감 정보 제외 규칙
├── README.md                           # 본 문서
├── 01_설계서_v4.1.md                   # 최신 설계 (v4.1)
├── 02_데이터_명세서_v1.1.md
├── 03_서비스_플로우_v1.1.md
├── poc_valuation_roadmap_v3.1.md
├── peer_beta/                          # 피어 베타 회귀
│   ├── config.py                       # ★ DEFAULT_PEERS 갈아끼우는 곳
│   ├── calendar_utils.py
│   ├── krx_client.py
│   ├── beta_calculator.py
│   ├── run_beta.py
│   └── requirements.txt
├── valuation_engine/                   # 가치평가 본체
│   ├── config.py                       # ★ TARGET / PEERS 갈아끼우는 곳
│   ├── fetch_peers_financials.py
│   ├── ecos_client.py                  # Rf
│   ├── compute_equity.py               # E + 발행/자기주식수 RAG
│   ├── kd_loader.py                    # KOFIA 회사채 CSV 파서
│   ├── cp_loader.py                    # KOFIA CP CSV 파서
│   ├── cp_yield_data.py                # CP 데이터 fallback (하드코드)
│   ├── cp_to_bond_converter.py         # CP→회사채 수익률 변환
│   ├── fetch_credit_rating.py          # 신용등급 RAG
│   ├── wacc_engine.py                  # Hamada + WACC
│   ├── dcf_engine.py                   # FCFF + TV
│   ├── equity_value.py                 # EV → 주당가치
│   ├── multiples_engine.py             # 4종 멀티플 역산
│   ├── uncertainty_engine.py           # Bear/Base/Bull + 민감도 + 토네이도
│   ├── run_valuation.py                # ★ 메인 진입점
│   ├── streamlit_app.py                # 대시보드
│   └── requirements.txt
└── XBRL/                               # 팀원 XBRL 모듈
    ├── xbrl_financials_v4.py           # v4 (현재 사용)
    ├── CLAUDE.md
    └── 서비스화 단계에서 데이터 관리.txt
```

---

## 🚫 제외된 파일 (`.gitignore`)

다음 파일들은 절대 Git에 올라가지 않습니다:
- `.env` — API 키 4종
- `peer_beta/data/`, `peer_beta/results/` — KRX 캐시·산출물
- `valuation_engine/data/`, `valuation_engine/results/` — XBRL 추출·WACC/DCF 산출물
- `채권시가평가기준수익률*.csv`, `cp_수익률*.csv` — KOFIA 라이선스 데이터
- `KOSPI/`, `KOSDAQ/` — 사업보고서 청크 (대용량, 사용자 각자 보유)
- `__pycache__/` 등 Python 부산물

각 팀원이 자기 환경에서 받아 사용해야 합니다.

---

## 🛠️ 평가 대상 변경 방법

**2개 파일만 수정하면 동일 로직으로 다른 회사 분석 가능:**

```python
# 1) valuation_engine/config.py
TARGET = {"name": "회사명", "ticker": "123456",
          "corp_code": "00000000", "market": "KOSPI"}
PEERS = [
    {"name": "피어1", "ticker": "...", "market": "KOSPI"},
    {"name": "피어2", "ticker": "...", "market": "KOSPI"},
    {"name": "피어3", "ticker": "...", "market": "KOSPI"},
]

# 2) peer_beta/config.py
DEFAULT_PEERS = [
    {"name": "회사명", "ticker": "123456", "market": "KOSPI", "role": "target"},
    {"name": "피어1",  "ticker": "...",    "market": "KOSPI", "role": "peer"},
    ...
]
```

**전제:** 사업보고서 청크 jsonl 이 `VAR/<KOSPI|KOSDAQ>/<티커>_..._<연도>_annual_chunks*.jsonl` 패턴으로 존재해야 함.

---

## 📊 주요 산출물

```
valuation_engine/results/valuation_<YYYYMMDD>.json
```

내용:
- summary: 적정주가, 현재가, 상승여력, WACC, ROIC
- scenarios: Bear/Base/Bull
- dcf: 5년 FCFF + TV 분해
- wacc_breakdown: 12개 구성 요소
- peers_hamada: 피어 β_U, D/E, t
- multiples: 4종 멀티플 역산
- sensitivity: 3×3 매트릭스
- tornado: 변수별 영향도
- credit_rating: 회사채 + CP 등급 + Kd 분해

---

## 📚 상세 문서

- [`01_설계서_v4.1.md`](01_설계서_v4.1.md) — WACC·DCF 수식 전체
- [`02_데이터_명세서_v1.1.md`](02_데이터_명세서_v1.1.md) — API·캐시·필드 명세
- [`03_서비스_플로우_v1.1.md`](03_서비스_플로우_v1.1.md) — Phase 0~7 실행 흐름
- [`poc_valuation_roadmap_v3.1.md`](poc_valuation_roadmap_v3.1.md) — 완료 매트릭스 + 확장 계획

---

## ⚠️ 면책

본 시스템은 **일반투자자 대상 투자정보 제공** 목적입니다. 투자 추천이 아니며, 산출값은 가정에 따라 변동될 수 있습니다. Bear/Base/Bull 시나리오와 민감도·토네이도로 범위 확인을 권장합니다.
