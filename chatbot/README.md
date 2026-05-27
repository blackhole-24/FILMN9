# 사업보고서 RAG 챗봇 (DART Annual Report RAG Chatbot)

KOSPI·KOSDAQ 전종목 **사업보고서(DART)** 를 검색해, 근거(원문 청크)와 함께 답하는
RAG 챗봇입니다. 임베딩(BGE-M3) + ChromaDB 검색 위에 재랭킹·온톨로지·OpenAI 생성 레이어를 얹었습니다.

## 주요 특징
- **검색**: BGE-M3(1024d) 임베딩 + ChromaDB(약 192만 청크) + Multi-Query/HyDE + RRF 융합
- **재랭킹**: BAAI/bge-reranker-v2-m3 cross-encoder + 확장 인지 재랭킹 + 빈 표(stub) 강등
- **온톨로지**: 금융공시 28개 개념(우발부채·배당·차입금 등) — 질의 확장 + 답변 커버리지 체크리스트
- **회사 해석**: 회사명→종목코드(퍼지 + 라틴↔한글 + 사명변경 부분문자열 매칭)
- **생성**: OpenAI(gpt-5.4-mini 기본) — 환각 방지(청크 근거만) + 출처 표기 + DART 섹션 deep-link
- **UI**: 단일 HTML 채팅 페이지(SSE 스트리밍), 멀티턴 대화

## ⚠️ 이 저장소는 "코드"만 포함합니다
실행하려면 아래가 **추가로** 필요합니다.

| 필요한 것 | 비고 |
|---|---|
| **`embedding/chroma_db/`** | 임베딩 벡터 DB (수~십수 GB). 용량 문제로 저장소 미포함 — **별도 공유**받아 배치 |
| 임베딩/재랭킹 모델 | `BAAI/bge-m3`, `BAAI/bge-reranker-v2-m3` — 최초 실행 시 HuggingFace 에서 자동 다운로드 |
| `.env` | 본인 `OPENAI_API_KEY` (`.env.example` 복사) |
| Python 환경 | Python 3.11 + CUDA GPU 권장 |

## 설치 & 실행
```bash
# 1) 의존성
pip install -r requirements.txt        # chromadb==1.5.9 / torch(CUDA 권장)

# 2) API 키
cp .env.example .env                   # .env 의 OPENAI_API_KEY 채우기

# 3) 임베딩 DB 배치
#    공유받은 chroma_db 를  embedding/chroma_db/  에 둡니다.
#    (collection 이름: annual_reports, BGE-M3 / 1024d / chromadb 1.5.9)

# 4) 실행
python -m uvicorn embedding.chatbot.api:app --host 127.0.0.1 --port 8000
#    또는 Windows: run_chatbot.bat
```
→ 브라우저에서 **http://127.0.0.1:8000**

## API
| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/` | 채팅 UI |
| GET | `/health` | 상태·DB·디바이스 |
| GET | `/companies?q=현대건설` | 회사 해석/후보 |
| POST | `/chat` | 답변 + 출처 + 메타 |
| POST | `/chat/stream` | SSE 스트리밍 |
| POST | `/session/reset` | 세션 초기화 |

## 구조
```
embedding/
├── config.py / embedder.py / retrieval.py / vector_store.py   # 임베딩·검색 인프라
├── chunk_loader.py                                            # (선택) 전처리
└── chatbot/
    ├── api.py            FastAPI 엔드포인트 + 채팅 UI 서빙
    ├── pipeline.py       오케스트레이션(분석→검색→생성)
    ├── query_analyzer.py 질문 분석(회사·연도·의도·쿼리변환)
    ├── company_index.py  회사명→종목코드 해석
    ├── retriever.py      Multi-Query + RRF + 재랭킹
    ├── reranker.py       cross-encoder 재랭킹
    ├── ontology_b.py     금융공시 온톨로지 런타임 (+ ontology_b.json)
    ├── llm_client.py     OpenAI 생성(근거·출처·커버리지)
    ├── dart_links.py     DART 섹션 deep-link
    ├── session.py        멀티턴 세션
    └── static/index.html 단일 페이지 채팅 UI
```

## 비용 (참고)
gpt-5.4-mini 기준 질의당 약 **10~30원**(임베딩·재랭킹은 로컬, 무료). 환경변수로 모델 교체 가능.

## 라이선스 / 출처
- 데이터: DART 사업보고서(KOSPI/KOSDAQ). 임베딩 모델: BAAI/bge-m3, bge-reranker-v2-m3 (Apache-2.0).
- 본 답변은 정보 제공용이며 투자 권유가 아닙니다.
