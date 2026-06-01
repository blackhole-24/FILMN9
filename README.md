# FILMN9 — AI 기반 KOSPI/KOSDAQ 종목 분석 플랫폼

KOSPI·KOSDAQ 약 2,700개 상장사를 대상으로 **기업개요·주가·재무·밸류에이션·거래상태**를
한 화면에서 제공하는 웹 서비스. (KPMG AI Lab 1차 POC)

종목을 검색하면 기업개요·히스토리 브리핑·주가차트·재무제표(B/S·I/S·손익흐름 Sankey)·
주주·경영인·전자공시·경쟁사/고객사·밸류에이션이 한 번에 표시되며,
상장폐지·거래정지 종목은 한국거래소(KRX)·DART 기반으로 자동 식별해 상태를 안내한다.

---

## 🏗️ 시스템 아키텍처 (폴더 = 구성요소)

| 계층 | 폴더 | 기술 | 역할 |
|---|---|---|---|
| **프론트엔드** | `frontend/` | Next.js 16 · React 19 · Turbopack (port 3000) | 종목 검색·대시보드 UI |
| **백엔드 API** | `backend/` | FastAPI · Python 3.11 (port 8000) | 20+ REST 엔드포인트 (주가·재무·공시·뉴스·상태 등) |
| **데이터베이스** | `database/` + `data/`(비공개) | SQLite(filmn9.db) · MongoDB Atlas · Chroma | 스키마·적재 스크립트 / 실데이터 |
| **데이터 수집** | `data_pipeline/` | DART OpenAPI · 사업보고서 XML | 원천 데이터 수집·전처리 파이프라인 |
| **데이터 파이프라인** | 루트 `*.py` 스크립트 | yfinance · pykrx · FinanceDataReader | 주가·재무·경쟁사·거래상태 적재 (아래 표) |

> 시스템 아키텍처 다이어그램: **`deliverables_main/FILMN9_시스템아키텍처_로컬·AWS.excalidraw`**

---

## 📂 파트별 산출물

| 폴더 | 내용 |
|---|---|
| `기업개요_파트/` | 기업개요·히스토리 브리핑 (재무정보·MongoDB 브리핑) |
| `밸류에이션_파트/` | DCF·상대가치·컨센서스 수집(consensus)·peer·XBRL |
| `ui_share/` | 밸류에이션 UI 공유본 |
| `docs/` | 기획서·페르소나·프로젝트헌장·설계도·요구사항정의서·AI기능 설계서 |
| `deliverables_docs/` | WBS·발표 스크립트·밸류에이션 해설서·스케줄·기업목록·분석 가이드 |
| `deliverables_main/` | ★ 시스템 아키텍처 등 대표 최종 산출물 |

---

## ⚙️ 핵심 데이터 파이프라인 스크립트 (루트)

| 스크립트 | 역할 |
|---|---|
| `unified_financial_loader.py` | 재무제표(B/S·I/S·CIS) 통합 적재 (사업보고서 XML + DART API) |
| `parse_jsonl_chunks_to_db.py` | 외감법인 재무 JSONL 파싱·적재 |
| `load_all_extras_dart.py` | 주주·경영인·기업개요 DART 일괄 적재 |
| `ohlcv_daily_sync.py` / `backfill_price.py` | 주가(OHLCV) 동기화·백필 (yfinance) |
| `build_competitors.py` / `build_customers.py` / `rerank_competitors.py` | 경쟁사·고객사 추출 (WICS + TF-IDF) |
| `build_sankey_all.py` | 손익흐름 Sankey 다이어그램 생성 |
| `build_stock_status.py` + `halt_sources.py` + `dart_halt_scan.py` | 상장폐지·거래정지 상태 판정 (KRX/KIND + DART 3년 공시 + 거래량) |
| `build_analyst_targets.py` | 애널리스트 리포트 FCFF 타깃 선정 |
| `daily_status_update.py` | 위 적재·상태 갱신 일일 자동 실행 (18:30 스케줄) |

---

## ▶️ 실행

```bash
# 1) 백엔드 (FastAPI)
uvicorn backend.main:app --reload --port 8000
# 2) 프론트엔드 (Next.js)
cd frontend && npm run dev   # http://localhost:3000
# 또는 원클릭
start.bat
```

- 의존성: `requirements.txt` (Python) / `frontend/package.json` (Node)
- 환경변수: `.env` (DART/OpenAI/MongoDB 키) — **비공개, 저장소 미포함**

---

## 🔒 비공개 항목 (저장소 제외)

용량·보안상 다음은 Git에 포함하지 않는다: 실데이터(`data/`, 42GB)·데이터 백업 zip·
`.env`(API 키)·`node_modules`·빌드 캐시. 데이터는 별도 전달.
