# 기업가치 평가 시스템 (DCF · WACC · FCFF)

설계서 v4 / 데이터 명세서 / 서비스 플로우 기준 구현 상태와 남은 작업.

> **🚀 처음 설치·실행하시나요? → [SETUP.md](SETUP.md) 를 먼저 보세요.**
> (4단계 설치 · API 키 4종 · 임베딩 데이터 배치 · 트러블슈팅)

---

## ★ 지금 당장 디벨롭해야 할 것 — 피어 베타 프로세스

> **베타 모듈은 코드가 동작은 하지만, 한공회(KRX) 공시 베타와 정합되도록 추가 튜닝이 필요한 상태입니다.** 가장 핵심은 **이상치 처리 방식 확정**.

### A. 이상치 처리 방식 결정 (최우선)

현재 상태:
- `peer_beta/config.py`의 `BETA_CONFIG["outlier_handling"]` 디폴트는 **`"winsorize"` (±3σ)** — 일반 투자자 대상 권장 방식
- 한공회(KRX) 공시 베타와의 비교는 사용자 노트북에서 진행 중

후보 5종:
| # | 방식 | 설명 | 상태 |
| --- | --- | --- | --- |
| 1 | `"none"` | 설계서 §1.6 원안. 이상치 일자 기록만, 회귀 포함 | ✅ 옵션 구현 |
| 2 | `"drop"` | 1차 OLS 후 \|z\|>residual_z_max 행 제거 후 재회귀 (표본 감소) | ✅ 옵션 구현 |
| 3 | **`"winsorize"`** | 1차 OLS 후 \|잔차\|>k·σ 행을 ±k·σ로 자르고 재회귀 (**표본 N 유지**) | ✅ **현재 디폴트 (k=3.0)** |
| 4 | 반복 drop | drop을 2~3회 반복하여 잔차 수렴까지 진행 | 미구현 |
| 5 | `residual_z_max` 임계값 조정 | 현재 4.0 → 3.0 또는 2.5로 강화 | `config.py` 한 줄 변경 |

**Winsorize를 디폴트로 채택한 이유 (일반 투자자 대상)**:
1. 표본 보존 (N=104 유지) → "왜 한 주가 빠졌나" 설명 부담 없음
2. UI에서 "특이 사건 주의 영향을 ±3σ로 제한" 한 줄 설명 가능
3. 시뮬레이션상 진짜 β 복원 정확도가 가장 높음 (테스트에서 오차 0.0036 < drop 0.0281 < none 0.0489)

KRX 4사 공시 베타 (2026-05-08 기준, 2년 Weekly):

| 회사 | KRX β_raw | KRX β_adj | pts |
| --- | --- | --- | --- |
| 아모레퍼시픽 | 0.397387 | 0.598258 | 104 |
| LG생활건강 | 0.393045 | 0.595363 | 104 |
| 한국콜마 | 0.325460 | 0.550307 | 104 |
| 에이피알 | 0.745769 | 0.830513 | 104 |

검증 절차 — 노트북 셀 11~12 에서 자동 비교 (현재 노트북에 추가됨):

```python
from peer_beta.run_beta import run

# 3가지 모드 자동 비교 — 셀이 합산 절대오차도 계산
for mode in ['none', 'drop', 'winsorize']:
    r = run(eval_date="2026-05-08", outlier_handling=mode, save_json=False)
    # 각 모드 결과를 KRX 공시값과 비교
```

노트북 실행 후 출력 마지막 줄 `[KRX 4사 절대오차 합산]` 에서 가장 낮은 모드를 채택. 현재는 `winsorize` 가 디폴트. 다른 모드가 더 낮게 나오면 `config.py`의 `outlier_handling` 을 변경.


---

## 모듈 구조 한눈에

```
VAR/
├── .env                              # API 키 (krxdata, DART_API_KEY, ECOS_API_KEY, OPENAI_API_KEY)
├── peer_beta/                        # ★ 피어 Levered Beta 모듈 (완료)
│   ├── config.py                     # 피어 리스트, Blume α=2/3, outlier_handling
│   ├── calendar_utils.py             # 매주 금요일 후보 + 영업일 대체
│   ├── krx_client.py                 # KRX OpenAPI + 일자별 캐시
│   ├── beta_calculator.py            # OLS + Blume + 이상치 옵션
│   ├── run_beta.py                   # 메인 진입점 (CLI/Python)
│   ├── requirements.txt
│   ├── data/raw/                     # KRX 일자별 raw JSON 캐시
│   ├── data/processed/               # 주간 종가/수익률 패널 CSV
│   └── results/                      # peer_beta_<T>.json
├── KOSPI/, KOSDAQ/                   # 팀원의 사업보고서 RAG 청크 (FCFF용)
├── peer_beta_verification.ipynb      # 베타 검증 노트북
├── dashboard.html                    # 결과 대시보드 (mockup, 완성 후 실데이터 연결)
└── README.md                         # 본 문서
```

---

## 진행 상황 (서비스 플로우 Phase 기준)

| Phase | 내용 | 상태 | 담당 |
| --- | --- | --- | --- |
| Phase 0 | 사전 준비 (T, API 키, config) | 완료 | - |
| Phase 1 | 재무 데이터 수집 (FCFF용 손익/CF/BS 추출) | **완료** | 팀원 |
| Phase 2-A | 피어 데이터 — 베타 회귀 (Levered + Blume) | 🔄 **디벨롭 필요** (이상치 처리 미확정) | 본인 |
| Phase 2-B | 피어 데이터 — 자본구조 D (IBD) 추출 | **완료** | 팀원 |
| Phase 2-C | 피어 데이터 — 자본구조 E (보통주 시가총액) 추출 | 미완료 | - |
| Phase 3 | WACC 계산 (Rf, Hamada Unlever/Relever, Ke, Kd, WACC) | 미완료 | - |
| Phase 4 | DCF 계산 (정상화 비율, Fade-out 성장률, FCFF 5년, TV, EV→Equity→주당가치) | 일부 (FCFF 산출) | - |
| Phase 5 | 멀티플 역산 (EV/EBITDA · EV/Sales · PER · PBR) | 미완료 | - |
| Phase 6 | 불확실성 표현 (Bear/Base/Bull, 민감도 매트릭스, 토네이도) | 미완료 | - |
| Phase 7 | 결과 출력 (HTML/Streamlit) | dashboard.html mockup | - |

---

## 남은 작업 상세

### Phase 2-B. 피어 자본구조 D (IBD) — ✅ 완료 (팀원)

연결재무상태표 장부가 기준:
- 유동: 단기차입금, 유동성장기부채, 유동성사채, 유동리스부채
- 비유동: 장기차입금, 사채, 비유동리스부채
- 제외: 매입채무, 미지급금, 미지급비용, 충당부채, 이연법인세부채

→ 팀원의 FCFF 추출 파이프라인 결과물에 포함되어 있음.

### Phase 2-C. 피어 자본구조 E (보통주 시가총액) — 남은 작업

식: **E = T일 보통주 종가 × (보통주 발행주식수 − 자기주식수)**

필요 데이터:
- **T일 보통주 종가** — 이미 베타 모듈이 KRX에서 수집해 `peer_beta/data/raw/stock_KOSPI_<T>.json` 에 캐시되어 있음. 응답 필드 `TDD_CLSPRC` 사용. 추가 호출 불필요.
- **보통주 발행주식수, 자기주식수** — DART OpenAPI `stockTotqyRqSttus` 엔드포인트로 자동 추출. 팀원 파이프라인에서 재사용 가능.
- **우선주 제외**: 아모레퍼시픽우(005945) 등 우선주 종목코드는 시총 산정 제외.

산출물 제안: `peers_capital_structure.json`

```json
{
  "as_of_date": "2026-05-14",
  "peers": {
    "아모레퍼시픽": {
      "ticker": "090430",
      "close_price": 129400,
      "common_issued": 58492759,
      "common_treasury": 0,
      "common_float": 58492759,
      "E_market_cap": 7568962012600,   // 보통주 시총
      "D_ibd": { "current": ..., "non_current": ..., "total": ... },  // 팀원 결과
      "D_over_E": 0.0XX,
      "tax_rate": 0.242                 // 최근 EBIT 기준
    },
    "LG생활건강": { ... }, "한국콜마": { ... }, "에이피알": { ... }
  }
}
```

이 JSON과 `peer_beta/results/peer_beta_<T>.json` (베타) 를 합쳐서 Phase 3 의 Hamada Unlever/Relever 입력으로 사용.

> 참고: KRX 응답의 `MKTCAP` 필드는 우선주 포함 전체 시총일 가능성이 있으므로, 명세서 §A-5 대로 **종가 × (발행 − 자기주식)** 으로 직접 산출하는 것이 안전합니다.

### Phase 3. WACC 계산

설계서 §1 전체 절차. 산출물 `wacc_result.json`:

1. **Rf** — ECOS API 국고채 10년물 SPOT (T일 또는 직전 영업일)
2. **ERP** — 8% 고정 (한공회 가이던스)
3. **SRP** — 평가기준일 직전 사업연도말 시가총액으로 3분위수 매칭 (아모레는 Mid −0.36%)
4. **CRP** — 0%
5. **한계세율** — 타겟·피어 각각의 최근 EBIT 기준 (2억~200억 22%, 200억~3,000억 24.2%, 3,000억 초과 27.5%)
6. **피어 Unlevered Beta** — `β_U,i = β_L,i / [1 + (1-t_i)·D_i/E_i]`
7. **타겟 목표자본구조** — 피어 D/E의 중위값
8. **타겟 Unlevered Beta** — 피어 β_U의 중위값
9. **타겟 Levered Beta (Hamada Relever)** — `β_L,target = β_U,target × [1 + (1-t_target)·(D/E)_target]`
10. **Ke** = Rf + β_L,target × ERP + SRP + CRP
11. **Kd** — 사업보고서 RAG로 추출한 신용등급 × KOFIA 5년물 수익률
12. **WACC** = E/(D+E)·Ke + D/(D+E)·Kd·(1-t)

### Phase 4. DCF 계산

설계서 §2 전체 절차. 산출물 `dcf_result.json`:

- **정상화 비율 (3년 평균)** — OPM, 유효세율, D&A율, CapEx율(Net), NWC율
- **적용 세율** — max(유효세율, 한계세율)
- **매출 성장률 Fade-out** — Y+1: 3년 CAGR, Y+2: ×0.8, Y+3/Y+4: 직전 ×0.7, Y+5: g(2.0%)
- **연도별 FCFF** = EBIT×(1-t) + D&A − CapEx − ΔNWC
- **영구가치** TV = FCFF_(Y+6) / (WACC - g)
  - 위계 검증: g < Rf < WACC
  - Y+5 CapEx > D&A 면 D&A로 강제 조정
- **EV → Equity → 주당가치**
  - Equity Value = EV − Net Debt + NOA − 비지배지분
  - 주당가치 = Equity Value / 보통주 유통주식수
- **NOA 5분류** (설계서 §2.7) — 확실/기본/조건부/OA/별도처리, 업종 override 적용
- **결정론적 검증** — Implied ROIC vs WACC

### Phase 5. 멀티플 역산

설계서 §4. 산출물 `multiples_result.json`:

| 멀티플 | 산식 |
| --- | --- |
| EV/EBITDA | 피어 중위값 × 대상 EBITDA → EV → Equity → Price |
| EV/Sales | 피어 중위값 × 대상 매출 → EV → Equity → Price |
| PER | 피어 중위값 × 대상 EPS = Price |
| PBR | 피어 중위값 × 대상 BPS = Price |

이격 경고: 피어 25~75 백분위 밖이면 "피어 대비 멀티플 이격" 표시.

### Phase 6. 불확실성 표현 (필수 출력 3종)

설계서 §3 전체. 산출물 `uncertainty_result.json`:

1. **Bear / Base / Bull 3시나리오** — 매출 성장률·OPM·CapEx율·NWC율을 3년 데이터의 최저/평균/최고 조합으로
2. **민감도 매트릭스** — WACC ±1%p × g ±0.5%p → 주당가치 3×3 히트맵
3. **토네이도 차트** — 변수별 단독 변동(±2%p, WACC ±1%p, g ±0.5%p)의 주당가치 영향도

### Phase 7. 결과 출력

- **dashboard.html** (mockup) → 실제 JSON 결과 5종(beta, wacc, dcf, multiples, uncertainty)을 fetch해서 렌더링하도록 통합
- 추후 운영 단계에서 Streamlit 앱으로 전환 (서비스 플로우 §9.2 화면 흐름)

---

## 환경

```bash
conda activate dart-rag
pip install -r peer_beta/requirements.txt
```

`.env` 키:
- `krxdata` — KRX OpenAPI (https://openapi.krx.co.kr/)
- `DART_API_KEY` — OpenDART
- `ECOS_API_KEY` — 한국은행 ECOS
- `OPENAI_API_KEY` — ChatGPT-4o (신용등급 RAG)

---

## 결정·합의가 필요한 사항

1. **베타 이상치 처리 방식** (위 ★ 참조)
2. **신용등급 추출 프롬프트 표준** — 환각 방지 (JSON 스키마, 원문 인용 강제)
3. **미평정 기업 fallback 매핑 테이블** — 시총·재무 유사 기업 등급 차용
4. **ΔNWC 처리** — Y+1 점프 smoothing vs 단순 ΔRevenue × NWC율 근사
5. **토네이도 변수 ± 범위** — 사용자 커스터마이즈 허용 여부
6. **SRP 3분위 vs 5분위** — 디폴트 3분위, 5분위 전환 조건

---

## POC 범위

아모레퍼시픽 + 피어 3사 (LG생활건강, 한국콜마, 에이피알). FY2025 사업보고서 기준 3개년(FY2023~FY2025). 운영 단계에서는 4개 타겟 전체로 확장.
