# 기업가치 평가 — 프론트엔드 검증 패키지

일반투자자용 가치평가 대시보드의 프론트엔드와, 3종목(NAVER·삼성전기·아모레퍼시픽)
데이터를 담았습니다.

## 파일
| 파일 | 설명 |
|---|---|
| `index_standalone.html` | **더블클릭으로 바로 열어 검증** (백엔드 불필요, 3종목 샘플 내장) |
| `index.html` | 실제 운영 UI (백엔드 API `/api/evaluate` 연동) |
| `data/<코드>_<이름>.json` | 종목별 **서비스 구현용 전체 데이터** (ui_payload + 구조화) |

## 검증 방법
### 1) 가장 빠름 — standalone
`index_standalone.html` 더블클릭 → 검색창에 `NAVER` / `삼성전기` / `아모레퍼시픽`
(또는 `035420`/`009150`/`090430`) 입력 → 전체 UI 확인.
(가격대 막대 차트만 Chart.js CDN 때문에 인터넷 필요. 나머지는 오프라인 OK)

### 2) 백엔드 연동 — index.html
저장소 루트에서:
```
PYTHONIOENCODING=utf-8 python -m uvicorn valuation_engine.api:app --port 8011
```
브라우저에서 http://localhost:8011

## API 계약 (운영 UI)
- `GET /api/evaluate?ticker=<코드|이름>&force=0`
  - 캐시 있음 → `{ "status":"done", "result": <ui_payload> }`
  - 신규/재평가 → `{ "status":"queued", "job_id":"...", "queue_ahead":N }`
- `GET /api/status/{job_id}` (폴링)
  - 진행 → `{ "status":"running", "elapsed":초, "progress":0~0.95 }`
  - 완료 → `{ "status":"done", "result": <ui_payload> }`
  - 실패 → `{ "status":"error", "error":"메시지" }`
- `GET /api/recent` → `[{ "ticker","name","as_of" }, ...]`

## ui_payload 핵심 스키마 (프론트가 소비)
```jsonc
{
  "company": { "name", "ticker", "market" },
  "as_of_date": "YYYY-MM-DD",
  "summary": { "current_price", "fair_price", "upside_pct", "wacc", "ke", "rf",
               "equity_value_won" },
  "valuation_diagnostics": {            // 현재가 적절성 진단 5종
    "valid", "headline", "epv_price", "growth_premium", "implied_growth",
    "implied_growth_verdict", "expectations_gap", "margin_of_safety",
    "gdp_growth_ref"
  },
  "scenarios": { "Bear":{"price"}, "Base":{"price"}, "Bull":{"price"} },
  "multiples": [ { "멀티플","피어 중위","역산가" }, ... ],
  "wacc_breakdown": [ ["항목","값","근거"], ... ],
  "peer_beta": [ { "회사","β_adj","R²","warn" }, ... ]
}
```
※ 데이터 식별자는 팀원 표준(`stock_code`, `corp_name`)에 맞춰 DB(SQLite)에 저장됩니다.
   `data/*.json` 의 `structured_data` 가 그 형식입니다.
