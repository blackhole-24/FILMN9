# FILMN9 — 사업보고서 임베딩 인덱스 (Tab3 RAG 챗봇용)

전종목(KOSPI+KOSDAQ) 사업보고서 청크 임베딩 ChromaDB 저장소.

---

## 1. 구성

```
chroma_db/                  ← ChromaDB PersistentClient 저장소 (그대로 사용)
  ├── chroma.sqlite3        ← 청크 문서 + 메타데이터
  └── <uuid>/               ← HNSW 벡터 인덱스 (192만 청크 × 1024차원)
retrieval.py                ← 검색 인터페이스 참고 코드 (필터·질의 예시)
README_임베딩사양.md         ← 본 문서
```

## 2. 임베딩 사양 (★ 질의 시 반드시 동일 모델 사용)

| 항목 | 값 |
|---|---|
| **임베딩 모델** | `BAAI/bge-m3` |
| **차원(dim)** | **1024** |
| **정규화** | L2 정규화됨 (코사인 유사도 = 내적) |
| **풀링** | CLS 토큰 ([0]) |
| **max_length** | 1024 토큰 |
| **ChromaDB 버전** | **1.5.9** (호환 버전 사용 필요 — 인덱스 로드 호환성) |
| **총 청크 수** | 약 1,922,942 |

> ⚠ **중요**: 우리는 BGE-M3(1024차원)를 사용합니다. (text-embedding-3-small/1536 아님)
> Tab3 RAG 챗봇이 **질의(query) 문장도 반드시 BGE-M3로 임베딩**해야 검색이 정합합니다.
> 다른 모델로 질의하면 벡터 공간이 달라 검색 결과가 무의미해집니다.

## 3. Collection / 메타데이터

- **Collection 이름**: `annual_reports` (전종목 통합 — 종목별 분리 아님)
- **메타데이터 필터 필드**:
  | 필드 | 예시 | 용도 |
  |---|---|---|
  | `ticker` | `"090430"` | 종목 필터 (6자리 단축코드) |
  | `corp_name` | `"아모레퍼시픽"` | 회사명 (suffix 정규화됨) |
  | `year` | `2025` (int) | 회계연도 필터 |
  | `section_main` | `"II. 사업의 내용"` | 대섹션 |
  | `section_path_str` | `"I. 회사의 개요 > 1. 회사의 개요"` | 전체 섹션 경로 |
  | `kind` | `"table"` / `"text"` | 청크 유형 |
  | `rcept_no` | `"20260318000785"` | DART 접수번호 |

## 4. 사용 예시

```python
import chromadb
from transformers import AutoModel, AutoTokenizer
import torch, numpy as np

# 1) 저장소 로드
client = chromadb.PersistentClient(path="chroma_db")
coll = client.get_collection("annual_reports")

# 2) 질의 임베딩 (반드시 BGE-M3)
tok = AutoTokenizer.from_pretrained("BAAI/bge-m3")
model = AutoModel.from_pretrained("BAAI/bge-m3").eval()
def embed(text):
    enc = tok([text], padding=True, truncation=True, max_length=1024, return_tensors="pt")
    with torch.inference_mode():
        v = model(**enc).last_hidden_state[:, 0]      # CLS 풀링
        v = torch.nn.functional.normalize(v, p=2, dim=1)  # L2 정규화
    return v[0].numpy().tolist()

# 3) 검색 (특정 종목·연도 필터)
res = coll.query(
    query_embeddings=[embed("주요 사업 부문과 매출 구성")],
    n_results=10,
    where={"$and": [{"ticker": "090430"}, {"year": 2025}]},
)
```

> `retrieval.py`에 `retrieve()`, `retrieve_for_keyword()`, `retrieve_business_segments()`,
> `format_chunks_for_llm()` 등 검색 헬퍼가 구현되어 있으니 그대로 참고/재사용 가능합니다.

## 5. 출처

- DART 사업보고서 청크 (KOSPI/KOSDAQ annual_chunks jsonl) → BGE-M3 임베딩 → ChromaDB
