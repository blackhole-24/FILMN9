# DART 사업보고서 RAG 챗봇

KOSPI·KOSDAQ 상장사의 **DART 정기보고서(사업·분기·반기보고서)** 를 검색해 근거와 함께 답하는 RAG 챗봇.
BGE-M3 임베딩 + ChromaDB + Multi-Query/HyDE + bge-reranker-v2-m3 + 도메인 온톨로지 기반 질의 확장.

---

## 핵심 기능
- 📄 **회사명 자연어 질의** → 정확한 종목 매칭(rapidfuzz + 한글/영문 변형 + 별칭 + 사명변경 대응)
- 🔍 **다중 보고서 검색** — 2025 사업보고서 + 2026 1분기 보고서 (확장 가능)
- 🎯 **표 인식 청킹** — 마크다운 형식으로 컬럼/단위/캡션 보존
- 🧠 **온톨로지 질의 확장** — 28개 금융공시 개념(우발부채→지급보증·담보, 매출→수주현황 등)
- ⚡ **단계별 진행 표시 + 출처 미리보기** (SSE 스트리밍)
- 📌 **출처 = DART 원문 deep-link** — 답변 수치를 한 클릭에 검증
- 🔄 **자동 업데이트** — 정기보고서 공시기한 맞춰 8회/년 자동 교체·임베딩 (옵션)

---

## 빠른 시작 (5단계)

> 사전 준비: Python 3.11, CUDA 12.x 호환 GPU 권장(8GB+ VRAM). CPU도 가능하나 느림.

```bash
# 1) 클론
git clone <your-repo-url> dart-rag-chatbot
cd dart-rag-chatbot

# 2) 패키지 설치 (가상환경 권장)
python -m venv .venv
.venv\Scripts\activate         # Windows
# source .venv/bin/activate    # macOS/Linux
pip install -r requirements.txt

# 3) 환경변수 설정
cp .env.example .env
# .env 열어서 DART_API_KEY · OPENAI_API_KEY 채우기

# 4) 사전 임베딩된 ChromaDB 받아 압축 풀기 (별도 공유 — Drive/S3 링크 받기)
#    embedding/chroma_db/ 에 들어가야 함
#    (또는 6장 "데이터 처음부터 구축"으로 직접 수집)

# 5) 챗봇 실행
python -m uvicorn embedding.chatbot.api:app --host 0.0.0.0 --port 8000
# → 브라우저에서 http://localhost:8000
```

또는 Windows에서는 `run_chatbot.bat` 더블클릭 1회로 동일.

---

## 아키텍처

```
질문 ──▶ 분석기(LLM)        ──▶ 회사 해석 + period 추출
             │                       │
             ▼                       ▼
       Multi-Query + HyDE      온톨로지 확장(28 concepts)
             │                       │
             └──┬─────────────────┘
                ▼
         BGE-M3 임베딩(GPU)
                ▼
        ChromaDB HNSW 검색  (ticker + year/report_kind 메타필터)
                ▼
            RRF 융합
                ▼
   bge-reranker-v2-m3 재랭킹(GPU, 확장 인지 max-pool)
                ▼
         stub 표 강등 → Top-K
                ▼
   생성기(LLM) ──▶ 스트리밍 답변 + 출처 deep-link
```

---

## 프로젝트 구조

```
.
├─ README.md                        ← 이 파일
├─ .env.example                     ← 환경변수 템플릿
├─ requirements.txt
├─ run_chatbot.bat                  ← Windows 1-클릭 실행
├─ .gitignore
│
├─ embedding/
│  ├─ config.py                     ← 경로·임베딩 설정
│  ├─ embedder.py                   ← BGE-M3 (FP16, 길이정렬 적응 배치, SDPA)
│  ├─ vector_store.py               ← ChromaDB 래퍼
│  ├─ retrieval.py                  ← format_chunks_for_llm 등
│  │
│  ├─ dc_chunker.py                 ← 마크다운 표 인식 청킹 (vendored)
│  ├─ dc_xml_cleaner.py             ← DART XML 정제 (vendored)
│  │
│  ├─ chatbot/                      ← ★ 챗봇 본체
│  │  ├─ api.py                     ← FastAPI + SSE 스트리밍
│  │  ├─ pipeline.py                ← 단계별 이벤트 제너레이터
│  │  ├─ query_analyzer.py
│  │  ├─ retriever.py               ← Multi-Query + RRF + 재랭킹
│  │  ├─ reranker.py                ← bge-reranker-v2-m3
│  │  ├─ llm_client.py
│  │  ├─ company_index.py           ← 회사 해석 (퍼지 + 사명변경)
│  │  ├─ ontology_b.py              ← 도메인 온톨로지(B안)
│  │  ├─ dart_links.py              ← DART 섹션 deep-link
│  │  ├─ companies.json             ← (데이터) 회사 인덱스
│  │  ├─ ontology_b.json/_seed.json ← (데이터) 온톨로지
│  │  └─ static/index.html          ← 단일 페이지 UI
│  │
│  ├─ phaseA_collect.py             ← 데이터 수집(병렬 8, 분당 600회)
│  ├─ phaseB_embed.py               ← 임베딩(길이정렬 + 오버랩 upsert)
│  ├─ phaseA_recover_failed.py      ← [첨부정정] 실패 복구
│  │
│  ├─ auto_update.py                ← 자동 정기 업데이트
│  ├─ auto_update.bat               ← Windows 작업 진입점
│  ├─ register_auto_update.ps1      ← 작업 스케줄러 8회 등록
│  └─ AUTO_UPDATE_README.md         ← 자동 업데이트 상세 가이드
│
└─ valuation_engine/                ← (재사용 의존) DART API 헬퍼
   ├─ report_ingest.py              ← download_document
   └─ report_detector.py            ← list_periodic_reports
```

---

## 외부에서 따로 받아야 할 것 (저장소엔 없음 — 용량 문제)

| 파일/폴더 | 크기 | 어디에 두는지 |
|---|---|---|
| `embedding/chroma_db/` | 약 20GB | 압축 받아서 `embedding/chroma_db/`로 풀기 |
| (옵션) `KOSPI/`, `KOSDAQ/` jsonl | 약 5GB+ | 원본 텍스트 백업 — 옵션 |
| `embedding/corpcode.xml` | 약 30MB | Phase A 첫 실행 시 자동 다운로드 |

저장소 관리자에게 위 파일들의 **Drive/S3 링크**를 받아 위 경로에 배치하면 됩니다.

---

## 데이터를 처음부터 구축하는 경우 (chroma_db 받을 수 없을 때)

```bash
# 1) corpCode 자동 다운로드 + KOSPI/KOSDAQ 전종목 보고서 수집
python embedding/phaseA_collect.py
# → KOSPI/, KOSDAQ/ 디렉터리에 jsonl 생성 (약 10-30분, 분당 600회 throttle)

# 2) 임베딩 (GPU 권장, 수 시간)
python embedding/phaseB_embed.py

# 3) (실패한 [첨부정정] 보고서 복구 — 선택)
python embedding/phaseA_recover_failed.py
```

KOSPI/KOSDAQ 종목 CSV는 [KRX 정보데이터시스템](http://data.krx.co.kr/)에서 다운로드 후 phaseA의 경로 변수 수정 필요.

---

## 자동 업데이트 활성화 (선택)

DART 정기보고서 공시 일정(연 4회: 3·5·8·11월)에 맞춰 자동으로 새 보고서 수집 + 이전 보고서 교체.

**Windows 작업 스케줄러 등록**:
```powershell
# 관리자 PowerShell
PowerShell -ExecutionPolicy Bypass -File embedding\register_auto_update.ps1
# → 4/6/9/12월 1·15일 03:00 KST 자동 실행 (연 8회)
```

상세는 [`embedding/AUTO_UPDATE_README.md`](embedding/AUTO_UPDATE_README.md) 참고 (정책 + AWS 클라우드 이전 가이드 + 비용 견적 ~$72/년).

---

## 기술 스택

| 분류 | 선택 | 비고 |
|---|---|---|
| LLM | OpenAI **gpt-5.4-mini** (분석·생성 모두) | 모델 기본 추론 사용(reasoning_effort 미지정), temperature 0.1 |
| 임베딩 | **BAAI/bge-m3** (1024차원, CLS, L2 정규화) | GPU FP16 + SDPA |
| 재랭커 | **BAAI/bge-reranker-v2-m3** | 확장 인지 max-pool |
| 벡터 DB | **ChromaDB 1.5.9** (PersistentClient) | HNSW |
| 청킹 | 자체 마크다운 인식 chunker (`dc_chunker.py`) | 표 헤더/단위 prefix 보존, 1500자 |
| 검색 | Multi-Query + HyDE + RRF + Cross-encoder rerank + 온톨로지 확장 |  |
| UI | Vanilla HTML + SSE 스트리밍 | 단계별 진행 + 출처 미리 표시 |
| API | FastAPI + uvicorn |  |
| 회사 해석 | rapidfuzz + 한글/영문 변형 + 통칭 별칭 사전 + 엔티티 접미사 가드 + unique substring containment | 예: 현대차→현대자동차, 네이버→NAVER |

---

## 주의사항

- **답변은 보고서에 실린 내용만 근거**로 합니다. 없는 정보는 "찾을 수 없음"으로 답변. **수치는 반드시 출처 원문에서 직접 재확인**하세요.
- **투자 권유가 아님** — 정보 제공 목적.
- DART OpenAPI 사용 시 **분당 1,000회 호출 제한** 준수 (본 코드는 분당 600회 throttle).
- ChromaDB는 **단일 프로세스만 쓰기 접근** — 자동 업데이트 실행 시 챗봇 서버는 자동 종료됩니다.

---

## 라이선스 / 크레딧

- DART OpenAPI © 금융감독원
- BGE-M3, bge-reranker-v2-m3: [BAAI](https://huggingface.co/BAAI)
- ChromaDB: Apache 2.0
- 본 프로젝트: (저장소 라이선스는 별도 명시)
