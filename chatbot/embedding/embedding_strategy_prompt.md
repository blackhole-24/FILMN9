# 임베딩 파이프라인 진단·개선 프롬프트

> 이 프롬프트를 다른 AI에게 통째로 붙여넣으면, AI가 현재 임베딩 시스템의 약점을 진단하고
> 전체 아키텍처·메타데이터·속도·검색 품질 4개 축에서 종합 개선안을 제시하도록 설계됨.

---

## 0. 당신의 역할

당신은 **한국 금융 도메인의 RAG(Retrieval-Augmented Generation) 시스템 아키텍트**이자
**벡터 검색·임베딩 모델 운영 전문가**입니다.

이 문서를 처음 본다고 가정하고 읽으세요. 아래에 제공되는 현재 시스템의 모든 디테일을 검토한 뒤,
**(a) 진단 → (b) 개선 우선순위 → (c) 구체적 액션 플랜**의 3단계로 답변해야 합니다.
추측하지 말고, 근거가 있는 부분은 "왜 그게 더 나은가"를 함께 적어주세요.
모르거나 확인이 필요한 부분은 "확인 필요"로 명시하고 넘어가도 됩니다.

답변 언어: **한국어**. 코드 예시는 영어 식별자 + 한국어 주석을 권장합니다.

---

## 1. 프로젝트 배경 — 처음 보는 사람을 위한 컨텍스트

### 1.1 우리가 만드는 것

**FILMN9**라는 한국 주식 밸류에이션(가치평가) 시스템의 일부분인 **RAG 챗봇용 임베딩 인덱스**입니다.

사용자(주로 애널리스트·운용역·KPMG PoC 팀)는 챗봇에 다음과 같은 질문을 합니다.

- "현대건설의 2025 사업보고서에서 해외 공사손실 충당금 관련 내용이 뭐였지?"
- "삼성전자의 사업 부문 매출 구성을 알려줘"
- "보통주 발행주식 총수와 자기주식 수를 추출해줘"
- "아모레퍼시픽의 신용등급 정보가 어느 부분에 있어?"

이 질문에 답하려면 **한국 코스피·코스닥 전종목의 사업보고서·분기보고서**에서 관련 청크를
벡터 검색으로 찾아 LLM 컨텍스트로 주입해야 합니다.

### 1.2 데이터 소스 — DART란?

**DART(Data Analysis, Retrieval and Transfer System)** = 한국 금융감독원이 운영하는
전자공시 시스템(https://dart.fss.or.kr). 상장사가 의무적으로 제출하는 공시 문서가 여기 모임.

이 프로젝트가 다루는 것:

- **사업보고서(annual)** — 매년 한 번, 회계연도 종료 후 90일 이내 제출. 가장 두꺼움(수백 페이지).
- **분기보고서(quarterly, Q1/Q3)** — 분기 종료 후 45일 이내.
- **반기보고서(semiannual)** — 6월 결산 후.

각 보고서는 **DART 자체 XML 포맷**으로 제공됨. HTML도 아니고 표준 XML도 아닌
"DART 방언"이라서 lxml로 바로 못 읽음(이유는 §3.2에서).

DART OpenAPI는 분당 약 1000회 호출 한도 + corp_code → 종목 매핑 XML(`corpCode.xml`)이
이따금 다운됨(점검·장애). 그래서 **외부 의존성을 격리하는 게 중요**함.

### 1.3 한국어 금융 도메인의 특수성

이 부분이 일반 RAG 튜토리얼과 다른 핵심 차이임. AI는 이걸 모르고 답하면 안 됨.

- **표(table)가 정보의 절대 다수**: 재무제표·주식수·신용등급·매출구성 등 핵심은 거의 표.
  표를 어떻게 다루느냐가 검색 품질의 60% 이상을 결정함.
- **"(단위: 백만원)" / "(단위: 천원)" 같은 단위 행이 표마다 따로 있음** — 분리되면 숫자가 무의미.
- **회사명 변형**: "현대건설보통주" vs "현대건설" vs "현대건설(주)" — 같은 회사라도
  발행 주식 종류·DART 등록 명칭이 다양해 정규화가 필수.
- **섹션 표기 미세 차이**: "II. 사업의 내용" vs "Ⅱ. 사업의 내용"(로마 숫자 유니코드 차이),
  공백·점 차이로 같은 섹션이라도 metadata exact match가 안 됨.
- **단축코드(stock_code)와 corp_code 분리**: 단축코드는 6자리(예: `005930`),
  corp_code는 DART 내부 8자리(예: `00126380`). 매핑은 `corpcode.xml`로 해야 함.
- **회계연도와 결산월**: 대부분 12월 결산이지만 일부 회사는 3월·6월 결산. period 정규화 주의.

---

## 2. 현재 시스템 전체 구조 — 파일별 상세

### 2.1 디렉토리 레이아웃

```
C:\Users\Admin\Desktop\VAR\
├── KOSPI\                              # KOSPI 청크 jsonl 저장소
│   └── {ticker}_{회사명}_{year}_{plabel}_chunks.jsonl
├── KOSDAQ\                             # KOSDAQ 청크 jsonl 저장소 (구조 동일)
├── embedding\
│   ├── chroma_db\                      # ★ 최종 벡터 인덱스 (PersistentClient)
│   │   ├── chroma.sqlite3              # 문서 + 메타데이터
│   │   └── <uuid>/                     # HNSW 벡터 인덱스 (~192만 청크 × 1024차원)
│   ├── export\                         # 외부 팀(PoC) 인계용 export
│   │   └── {ticker}\
│   │       ├── chunks.jsonl
│   │       ├── embeddings.npy
│   │       └── metadata.json
│   ├── config.py                       # 모든 설정 한곳 (model, dim, paths, batch)
│   ├── __init__.py                     # 패키지 진입점 (retrieve, get_stats 등 export)
│   ├── phaseA_collect.py               # ★ Phase A: DART 수집 + 청킹 → jsonl
│   ├── phaseA_recover_failed.py        # 첨부정정 잘못 잡힌 케이스 재시도
│   ├── dc_xml_cleaner.py               # DART XML → 표준 XML 정제 (v4.1)
│   ├── dc_chunker.py                   # XML root → 임베딩용 청크 리스트
│   ├── phaseB_embed.py                 # ★ Phase B: jsonl → 임베딩 → ChromaDB
│   ├── embedder.py                     # BGE-M3 호출 (FP16, SDPA, 길이정렬 적응형 배치)
│   ├── vector_store.py                 # ChromaDB 래퍼 (upsert, query, get_existing_ids)
│   ├── chunk_loader.py                 # jsonl 로드 + corp_name 정규화 + 메타 정제
│   ├── retrieval.py                    # 검색 헬퍼 (retrieve, retrieve_business_segments)
│   ├── run_embed_all.py                # 통합 진입점 (CLI: --market, --reset, --dry-run)
│   ├── reembed_truncated.py            # 512 토큰 초과 청크 선별 재임베딩
│   ├── export_for_poc.py               # 데모 3종목 외부 전달용 export
│   ├── cleanup_q1.py                   # 2026 q1 청크 + DB + progress 일괄 정리
│   ├── _dart_watch.py                  # corpCode.xml 다운 시 폴링
│   ├── _wave_watch.py                  # 처리율 측정 워처
│   ├── corpcode.xml                    # DART 종목 코드 캐시
│   ├── collect_progress.json           # Phase A 진행 상태
│   ├── embed_progress.json             # Phase B 진행 상태 (완료 파일 목록)
│   ├── phaseA_collect.log
│   ├── phaseB_embed.log
│   └── SHARE_README.md                 # 외부 팀에 보내는 임베딩 사양서
```

### 2.2 2-Phase 분리 구조 — 가장 중요한 설계 결정

```
[Phase A: 수집/전처리]                  [Phase B: 임베딩/저장]
  DART API 의존                         DART 의존성 0
  ↓                                     ↓
phaseA_collect.py                       phaseB_embed.py
  ├ list_periodic_reports (스레드 8)    ├ KOSPI/*.jsonl, KOSDAQ/*.jsonl 스캔
  ├ download_document (프로세스 8)      ├ 첫줄/끝줄 ID로 빠른 스킵
  ├ dc_xml_cleaner.clean_xml()          ├ embedder.embed_texts() (GPU FP16)
  ├ dc_chunker.build_chunks()           ├ vector_store.add_batch() (CPU)
  └ KOSPI/*.jsonl, KOSDAQ/*.jsonl       └ chroma_db/ (collection=annual_reports)
       (Phase B의 input)                     (writer 스레드로 GPU/CPU 오버랩)
```

**왜 분리?**
1. DART 점검·장애가 빈번 → Phase B는 DART 끊겨도 동작해야 함.
2. 청킹은 결정적(deterministic) → 한 번 만든 jsonl은 영구 보관, 정책 변경 시 Phase A만 다시.
3. 임베딩 모델 교체 실험 시 Phase A 결과는 그대로 두고 Phase B만 재실행.
4. 책임 분리: Phase A는 네트워크·파싱, Phase B는 GPU·DB.

### 2.3 Phase A 상세 — `phaseA_collect.py`

**입력**: KOSPI/KOSDAQ 다운로드 CSV(증권거래소 발급, `data_1426_…csv`, `data_1439_…csv`)
**출력**: `KOSPI/{ticker}_{회사명}_{year}_{plabel}_chunks.jsonl`

처리 흐름:

1. **유니버스 로드** — CSV에서 보통주만 필터(`증권구분=주권`, `주식종류=보통주`).
   우선주·DR 등은 제외. cp949 인코딩 주의(한국 거래소 표준).
2. **corp_code 매핑** — `corpcode.xml` 파싱하여 `stock_code → corp_code` 딕셔너리 빌드.
3. **Phase 1 — 탐색(ThreadPool 8개)** — `list_periodic_reports(corp_code, bgn_de, end_de)`로
   각 종목의 대상 기간 보고서 목록 조회. list.json은 가벼우니 스레드.
4. **Phase 2 — 수집(ProcessPool 8개)** — 다음을 프로세스 병렬로 수행:
   - `download_document(rcept_no)` — XML 다운로드
   - `clean_xml()` — DART XML 정제 (§3.2)
   - `parse_with_fallback()` — lxml strict → recover 폴백
   - `build_chunks(root, meta)` — 청크 리스트 생성 (§3.3)
   - 원자적 저장 (`.jsonl.tmp` → `.jsonl` rename)
5. **재개 가능성** — `collect_progress.json`에 `{stock}:{year}-{plabel}: "done"` 기록.
   `already_have()`로 jsonl 존재 시 스킵.

**왜 ProcessPool인가?** 거대 표 파싱이 CPU 바운드(큰 보고서 1건당 27초)인데 GIL 때문에
ThreadPool에서는 1코어로 직렬화됨. ProcessPool로 16코어 중 8코어를 진짜 병렬.

**Rate limiter**: 분당 600회(DART 한도 1000회의 60%). 프로세스 공유 `multiprocessing.Lock` +
`Value('d')`로 마지막 호출 시각 동기화. `REQUEST_DELAY=0.1`.

**재시도 정책**: `_retry_mp(fn, tries=5, base=1.0)` — 지수 백오프 + 랜덤 지터.

### 2.4 DART XML 정제 — `dc_xml_cleaner.py` (v4.1)

DART XML이 표준이 아닌 이유:

- 네임스페이스 미사용인데 본문에 `<ME:I>`, `<IS:SUE>` 같은 콜론 토큰이 등장(아마 그룹명·약어).
  표준 XML 파서는 이걸 네임스페이스로 오해해 에러.
- `<A>` 태그가 anchor일 수도 있고 본문 글자(예: `<A>#(KJ)`)일 수도 있음.
  정상 anchor는 `<A REFNO="...">목차</A>` 형태.
- `&` 가 escape 안 된 상태로 등장하는 경우 다수.

정제 전략:

1. `&` 가 valid entity ref(`&amp;`, `&#123;` 등)가 아니면 `&amp;`로 치환.
2. **화이트리스트** 태그(`KNOWN_DART_TAGS` 약 50개)에 없는 토큰은 본문 글자로 escape(`<` → `&lt;`).
   네임스페이스 토큰(`:` 포함)도 무조건 본문.
3. **모호한 짧은 태그**(`AMBIGUOUS_REQUIRES_ATTR = {"A"}`)는 속성 없이 등장하면 본문으로 escape.
4. `parse_with_fallback()` — 정제본을 lxml strict로 시도, 실패 시 `recover=True` 모드.
   파싱 모드는 메타데이터(`parse_mode`)에 기록.

### 2.5 청킹 정책 — `dc_chunker.py`

이 부분이 검색 품질의 핵심. 청크 1개 = 임베딩 1건 = JSONL 한 줄.

**파라미터** (현재 값):

```python
CHAR_LIMIT           = 1500   # 청크당 최대 글자 (BGE-M3 1024토큰 창 대응)
OVERLAP              = 200    # 분할 시 오버랩
PROSE_CELL_THRESHOLD = 300    # 단일 셀이 이보다 길면 prose-table로 처리
PROSE_TABLE_TOTAL    = 600    # 1x1, 1x2 표 총 글자 임계
```

**처리 흐름**:

1. **DOM 순회** — `SECTION-1/2/3` 진입 시 path에 heading 추가, `<P>`와 `<TABLE>` 수집.
2. **표 직전 짧은 P → 캡션 결합** — `looks_like_caption()`은 다음 패턴을 캡션으로 판단:
   - 길이 < 40자
   - 시작이 `[`, `<`, `(`, `「`, `【`
   - 끝이 `추이|현황|내역|목록|구성|요약|총괄|분포|통계|구분|상세|개요|비교|규모|실적`
3. **prose-table 감지** — 단일 셀이 300자 넘거나, 1~2행/1~2열 표가 총 600자 넘으면
   "레이아웃을 위한 표"로 보고 일반 텍스트로 변환.
4. **표 → markdown 청크** — 다음을 prefix로 매 분할 조각에 **복제**:
   - `[표] 캡션` (있으면)
   - `(단위: 백만원)` 행 (있으면)
   - 상위 헤더 (있으면) + `| col1 | col2 | ... |` + `| --- | --- | ... |`
   → 표가 잘려도 각 조각이 자기 헤더·단위·캡션을 가짐.
5. **텍스트 분할 — `hard_split()`**:
   - `CHAR_LIMIT` 초과 시 `\n\n` 우선 분할 (limit의 50% 이상 위치에서)
   - 안 되면 한국어 문장 경계(`(?<=[다요음])\s+`, `(?<=[\.\?\!])\s+`) — 한국어 종결어미 패턴
   - `OVERLAP`만큼 다음 조각에 겹침.
6. **메타 부착** — 각 청크에 `id = {stock_code}-{report_kind}-{i:05d}`,
   `section_path`, `section_path_str`, `kind`(text/table), `char_len`, 모든 원본 메타 부착.

**출력 청크 스키마**:

```json
{
  "id": "000720-2025-annual-00010",
  "group": "KOSPI",
  "stock_code": "000720",
  "corp_code": "00164742",
  "corp_name": "현대건설보통주",
  "report_nm": "사업보고서 (2025.12)",
  "report_kind": "2025-annual",
  "report_type": "annual",
  "rcept_no": "20260318000785",
  "rcept_dt": "20260318",
  "fiscal_period": "2025-annual",
  "source_url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=...",
  "parse_mode": "strict",
  "kind": "table",
  "section_path": ["II. 사업의 내용", "1. 사업의 개요"],
  "section_path_str": "II. 사업의 내용 > 1. 사업의 개요",
  "char_len": 1247,
  "text": "..."
}
```

### 2.6 임베딩 모델 — `embedder.py` + `config.py`

```python
EMBEDDING_MODEL = "BAAI/bge-m3"
EMBEDDING_DIM   = 1024
BATCH_SIZE      = 64
USE_GPU         = True
MIN_CHAR_LEN    = 30
```

- **모델**: BGE-M3 (BAAI 발표, Apache 2.0). 한국어 retrieval 벤치마크 상위, 1024차원,
  최대 8192 토큰 컨텍스트, dense/sparse/multi-vector 동시 출력 가능(현재는 dense만 사용).
- **풀링**: CLS 토큰 (`last_hidden_state[:, 0]`).
- **정규화**: L2 (cosine = dot product).
- **max_length**: 1024 (원래 512였는데, 실측상 청크의 ~16.6%가 512 초과로 잘려서 상향).
- **정밀도**: GPU에서 FP16(`model.half()`), 메모리 절반 + 속도 2배.
  forward 결과는 FP32 캐스팅 후 정규화(수치 안정).
- **어텐션 구현**: `attn_implementation="sdpa"` 시도, 실패 시 eager 폴백.
  SDPA는 긴 시퀀스(표) forward 가속 + 메모리 절감.
- **모델 로딩**: `local_files_only=True` — 오프라인 환경 대응(한 번 받아두면 인터넷 없이 동작).

**왜 sentence-transformers 안 쓰는가?** Windows에서 sentence-transformers 5.x가
SSL 인증서 로딩 단계에서 silent crash. transformers.AutoModel 직접 사용으로 우회.

### 2.7 길이정렬 적응형 배치 — `embedder.py:embed_texts`

이 부분이 임베딩 속도의 핵심 최적화.

**문제**: HuggingFace 토크나이저는 `padding=True`로 호출하면 배치 내 최장 길이에 맞춰 패딩.
길이가 섞인 배치(예: 50자 청크 + 1024자 청크)에서는 짧은 청크가 긴 청크에 맞춰 헛계산됨.

**해법**:

1. 모든 청크의 대략적 토큰 수를 `min(max_length, len(text))`로 추정(한국어는 실제 ~0.5tok/char라
   과대추정이지만 안전).
2. 추정 토큰 수로 인덱스 정렬.
3. **토큰 버짓 그룹화** — `개수 × 그룹최대토큰 ≤ token_budget = batch_size × max_length`
   조건을 만족하는 한 같은 그룹에 묶음. 짧은 청크들은 한 그룹에 수백 개까지 묶임.
4. 그룹별로 `padding=True, truncation=True, max_length=1024`로 토크나이즈 → forward → CLS 풀링
   → L2 정규화 → 원순서로 복원.

**수치 정합성**: padding은 attention mask로 무시되므로 각 청크의 CLS 임베딩은 배치 구성과
무관하게 동일. 즉, 배치 순서가 결과를 바꾸지 않음.

### 2.8 벡터 저장 — `vector_store.py`

```python
import chromadb
CHROMA_DB_DIR   = VAR_ROOT / "embedding" / "chroma_db"
COLLECTION_NAME = "annual_reports"   # 모든 종목·모든 연도 단일 컬렉션
```

- **PersistentClient** — 디스크 영구 저장.
- **단일 컬렉션 정책** — 종목별 분리 안 함. 메타데이터 필터(`where`)로 좁힘.
  이유: 컬렉션 수가 많으면 HNSW 인덱스 관리 오버헤드, 종목 간 검색(피어 비교) 시 합치기 복잡.
- **HNSW 파라미터** — 명시적 설정 없음(ChromaDB 기본값 사용).
- **upsert 정책** — id 같으면 덮어쓰기. 멱등성 보장 → 재실행 안전.
- **버전 호환** — `chromadb==1.5.9` 명시(인덱스 로드 호환).

### 2.9 Phase B 상세 — `phaseB_embed.py`

```python
UPSERT_BATCH = 4000        # ChromaDB upsert 분할 (최대 5461 미만)
CHUNK_CAP    = 40000       # 한 그룹에 모을 최대 청크 수 (메모리 + 정렬창)
QUEUE_MAX    = 8           # upsert 큐 버퍼 (오버랩 폭)
```

**파이프라인**:

1. **파일 빠른 스킵** — `file_already_embedded(path)`가 jsonl 첫 줄·끝 줄 id만 읽어 DB 조회.
   둘 다 있으면 임베딩 완료로 간주. 파일 전체를 안 읽으니 매우 빠름.
2. **그룹 누적** — `CHUNK_CAP=40000`까지 jsonl 청크를 메모리에 모음.
   클수록 정렬창이 커져 패딩 낭비 ↓, 작을수록 메모리 안전.
3. **그룹 flush**:
   - 5000 단위로 `get_existing_ids()` 호출해 이미 임베딩된 id 제외(2단계 안전망).
   - `embed_texts()` (내부에서 길이정렬 적응형 배치).
   - `UPSERT_BATCH=4000` 단위로 writer 큐에 push.
4. **writer 스레드** — `add_batch()`만 전담. GPU와 CPU(upsert)가 오버랩.
   동시 쓰기 없음(스레드 1개) → 락 충돌 회피.
5. **진행 기록** — `embed_progress.json`에 완료 파일 경로 sorted set으로 저장.

**중단 안전**: 어디서 죽어도 다음 실행 시 (a) 파일 단위 스킵 + (b) 청크 단위 `get_existing_ids`
2중 안전망으로 이어 받음.

### 2.10 청크 로더 — `chunk_loader.py`

jsonl → 임베딩 입력 변환 과정의 정제 로직:

1. **corp_name 정규화** — 정규식 `(보통주|우선주|1우B|1우|2우B|2우|종류우선주|전환우선주)$` 제거.
   예: "현대건설보통주" → "현대건설", "현대차2우B" → "현대차". 원본은 `corp_name_raw`로 보존.
2. **year 추출** — `fiscal_period`("2025-annual") 첫 토큰 int 캐스트.
3. **스킵 정책**:
   - `char_len < 30` (의미 없는 짧은 청크)
   - `section_main == "(문서 본문)"` AND `section_sub` 없음 (cover page)
   - `text` 비어있음
   - id 중복 (jsonl 내부 + 파일 간)
4. **파일 선택** — 같은 ticker에 여러 jsonl 버전이 있으면(예: `_chunks.jsonl` + `_chunks_v3.jsonl`)
   sorted last(보통 최신).

### 2.11 검색 인터페이스 — `retrieval.py`

```python
def retrieve(query, ticker=None, year=None, section_main=None, top_k=10) -> list[dict]
def retrieve_for_keyword(keywords: list[str], ticker=None, year=None, top_k=15)
def retrieve_business_segments(ticker, year, top_k=10)
def format_chunks_for_llm(chunks, max_chars=10000) -> str
```

핵심 패턴:

- 메타 필터 2개 이상이면 `{"$and": [...]}` 로 묶음 (ChromaDB 문법).
- `retrieve_business_segments`는 `section_main exact match` 대신
  넉넉히 검색 후 `"사업" in section_main` 후처리 필터 — 회사별 섹션 표기 차이 흡수.
- 거리(distance)는 cosine, `similarity = 1 - distance`.
- `format_chunks_for_llm`은 `[청크 N | 회사 연도 보고서종류 | 섹션경로 | kind]` 헤더로
  LLM이 인용할 출처를 명시.

### 2.12 운영 보조 스크립트

- **`reembed_truncated.py`** — fast tokenizer로 배치 측정하여 512 초과 청크만 골라
  `max_length=1024`로 재임베딩. upsert로 덮어씀. 처음 512였던 시기 마이그레이션용.
- **`export_for_poc.py`** — `export/{ticker}/chunks.jsonl + embeddings.npy + metadata.json`로
  외부 팀(KPMG PoC) 인계. 모델·차원 metadata.json에 명시(text-embedding-3 1536과 혼동 방지).
- **`cleanup_q1.py`** — 특정 report_kind(예: 2026-q1)만 DB·jsonl·progress에서 일괄 제거.
  포맷 변경 시 재수집·재임베딩 트리거.
- **`phaseA_recover_failed.py`** — [첨부정정]이 잘못 채택된 케이스에서 같은 period의
  원본(비정정) rcept_no를 우선 시도하여 복구.
- **`_dart_watch.py`** — corpCode.xml 다운 시 5분 간격 폴링.
- **`_wave_watch.py`** — 임베딩 처리율 측정.

---

## 3. 현재 시스템의 정량 지표

| 항목 | 값 |
|---|---|
| 총 청크 수 | 약 1,922,942 |
| 임베딩 모델 | BAAI/bge-m3 |
| 차원 | 1024 |
| ChromaDB 버전 | 1.5.9 |
| 컬렉션 | annual_reports (단일) |
| Phase A 처리율 | (확인 필요 — 로그 참조) |
| Phase B 처리율 | 약 200~400 청크/sec (FP16 GPU 기준 노트북) |
| GPU | RTX 4060 Laptop 8GB |
| max_length | 1024 |
| BATCH_SIZE | 64 |
| 청크 char_limit | 1500 |
| 청크 overlap | 200 |

---

## 4. 하드웨어·환경 제약

- **OS**: Windows 11 + WSL 안 씀 (네이티브 Windows Python).
- **Python**: 3.11.
- **GPU**: RTX 4060 Laptop 8GB VRAM. FP16에서 batch 64 안전.
- **DB**: 로컬 디스크 ChromaDB. 외부 벡터 DB(Pinecone, Qdrant Cloud 등) 미사용.
- **인터넷**: DART API + HuggingFace 모델 다운로드만 필요. 그 외 오프라인 가능해야 함.
- **모델 라이선스**: Apache 2.0 / MIT 등 상용 가능 라이선스만 허용.

---

## 5. 현재 시스템에서 의도적으로 한 결정들

이 결정들은 이유가 있어서 한 거임. 당신이 바꾸자고 제안하려면
"왜 그게 더 나은가"를 명시적으로 비교해야 함.

1. **단일 컬렉션 정책** — 종목별 분리 안 함. 메타 필터로 좁힘.
2. **BGE-M3 dense only** — sparse/multi-vector 출력은 미사용.
3. **CLS 풀링** — mean pooling 아님 (BGE-M3 권장).
4. **L2 정규화 + cosine** — 다른 거리 metric 미사용.
5. **단일 max_length=1024** — 청크 길이 분포에 동적 적응 안 함.
6. **청킹 시 메타 필드 부착** — 검색 시 별도 메타 조회 안 해도 되도록.
7. **표 prefix 복제** — 분할 조각마다 캡션·단위·헤더 중복 (저장 비용 < 검색 품질).
8. **ChromaDB upsert 멱등** — 재실행 안전이 모든 최적화보다 우선.
9. **외부 의존 격리** — Phase A/B 완전 분리.
10. **corp_name 정규화 시 원본 보존** — `corp_name_raw` 디버깅용.

---

## 6. 당신이 해야 할 일 — 진단 → 개선안

### 6.1 진단 (Diagnosis)

먼저 위 시스템을 종합 평가하세요. 다음 4개 축에서 각각:

1. **전체 아키텍처** — 분리 구조, 데이터 흐름, 확장성, 장애 격리, 재현성.
2. **메타데이터·필터링** — 스키마, 정규화, 검색 시 필터 표현력.
3. **속도·처리량** — Phase A/B 병렬 전략, GPU 활용, DB 쓰기, 인덱스.
4. **검색 품질** — 청킹 정책, 임베딩 모델 활용, 검색 전략, 재순위.

각 축에서:
- **잘 되어 있는 점** (3~5개) — 그대로 두라고 명시.
- **약점·위험 요소** (5~10개) — 구체적 시나리오로. 예: "이 케이스에서 이런 식으로 실패할 것".
- **불확실한 점** — 정량 데이터로 검증 필요한 가설.

### 6.2 개선 우선순위 (Prioritized Plan)

발견한 약점을 다음 기준으로 순위화:

- **임팩트** — 사용자가 체감할 검색 품질·속도 개선 폭.
- **노력** — 구현·재임베딩·마이그레이션 비용.
- **위험** — 기존 결과를 깨뜨릴 가능성.

**우선순위 매트릭스** (high impact / low effort부터):

| 우선순위 | 항목 | 임팩트 | 노력 | 위험 | 비고 |
|---|---|---|---|---|---|

### 6.3 구체적 액션 플랜 (Action Plan)

각 우선순위 항목에 대해:

1. **현재 동작** — 어디 파일 어느 함수에서 어떻게 처리되는지.
2. **개선 후 동작** — 무엇이 어떻게 바뀌는지.
3. **구체적 구현 스케치** — 함수 시그니처 + 의사 코드 + 필요한 라이브러리.
4. **검증 방법** — 어떤 쿼리·메트릭으로 개선을 확인할지.
   예: "현대건설 2025 사업보고서에서 '해외 공사손실'로 검색 시 top-5에 해당 섹션 포함 여부"
5. **롤백 전략** — 실패 시 어떻게 되돌릴지.
6. **마이그레이션 필요 여부** — 전체 재임베딩이 필요하면 명시.

### 6.4 특별히 검토해주면 좋은 후보 영역들

(이건 힌트일 뿐, 당신이 진단해서 새로운 영역을 발견해도 좋음)

- **하이브리드 검색** — dense + BM25/sparse 결합. BGE-M3는 sparse도 출력 가능.
- **재순위(re-ranker)** — bge-reranker-v2 등으로 top-k 재정렬.
- **쿼리 분해·확장** — HyDE, multi-query, sub-question.
- **표 전용 임베딩** — 표를 자연어 문장으로 변환한 뒤 임베딩(현재는 markdown).
- **메타데이터 확장** — 산업 분류(KSIC), 지배구조, 회사 동일성(합병·분할 추적).
- **온톨로지 기반 필터** — 회사명 alias, 섹션명 표준화 사전.
- **청킹 정책 개선** — 의미 단위 청킹(LLM 기반), 적응형 길이, 슬라이딩 윈도우.
- **인덱스 최적화** — HNSW M·ef 튜닝, PQ 양자화, FAISS 이전 고려.
- **장기 운영** — 신규 보고서 증분 파이프라인 자동화, 모델 버전 관리, A/B 테스트 기반.
- **평가 프레임워크** — 골든 쿼리셋, recall@k, nDCG, MRR 측정 인프라.
- **연도 간 일관성** — 같은 회사의 시계열 청크 비교 시 정렬·정규화 어떻게 할지.
- **다국어·영문 보고서** — 외국인 투자자용 영문 보고서 어떻게 처리할지.

---

## 7. 답변 형식 — 엄격히 준수

```markdown
# 임베딩 파이프라인 진단 및 개선안

## 1. 진단

### 1.1 전체 아키텍처
- 잘 된 점:
  - …
- 약점:
  - …
- 불확실:
  - …

### 1.2 메타데이터·필터링
(동일 구조)

### 1.3 속도·처리량
(동일 구조)

### 1.4 검색 품질
(동일 구조)

## 2. 우선순위 매트릭스
| # | 항목 | 임팩트 | 노력 | 위험 | 마이그레이션 |
|---|---|---|---|---|---|

## 3. 액션 플랜

### #1. {제목}
- 현재:
- 개선:
- 구현 스케치:
  ```python
  …
  ```
- 검증:
- 롤백:
- 마이그레이션:

### #2. {제목}
(동일 구조)
…
```

## 8. 답변 시 주의사항

- **추측 금지** — 모르면 "확인 필요"로 적고 어떤 데이터로 검증할지 적기.
- **상용 모델·API 의존 제안 시 라이선스 명시** — Apache 2.0 / MIT 외 사용 시 사유 적기.
- **전체 재임베딩이 필요한 제안은 별도 표시** — 192만 청크 × FP16 RTX 4060 기준
  최소 수 시간 소요.
- **한국어 도메인 특수성 무시 금지** — 영문 RAG 베스트 프랙티스를 그대로 적용 시 깨질 수 있음.
  특히: 표 비중, 회사명 변형, 섹션 로마숫자 차이, 단위 행.
- **현재 사용자 흐름과 일관성 유지** — `retrieve()` 시그니처를 깰 거면 마이그레이션 경로 제시.
- **제안은 구체적으로** — "더 좋은 임베딩 모델 쓰자" 같은 모호한 표현 금지.
  구체적 모델명, 차원, 라이선스, 예상 성능 변화 명시.

---

준비됐으면 진단부터 시작하세요. 끝.
