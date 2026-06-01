"""텍스트 데이터 → MongoDB-ready JSONL 저장소.

설계(사용자 결정): 텍스트 데이터는 MongoDB 에 담을 수 있도록 JSON 파일로 저장.
  · 형식: JSONL(한 줄당 한 문서) — `mongoimport --collection X --file X.jsonl` 호환.
  · 위치: data/mongo/<collection>.jsonl
  · 멱등성: 문서에 `_id` 부여, 같은 _id 재적재 시 교체(append 후 dedup 보장은
            upsert_doc 가 처리 — 파일 전체를 _id 기준으로 재기록).

컬렉션:
  · report_chunks     — 사업보고서 청크(원문 텍스트). _id = 청크 id.
  · valuation_results — 통합 평가 결과(텍스트 포함 전체 문서). _id = "<ticker>_<eval_date>".

대용량 report_chunks 는 append-only 로 적재(중복 시 _id dedup 은 migrate 단계에서
회사·연도 단위로 관리). valuation_results 는 소량이라 upsert(전체 재기록) 사용.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Iterator, Optional

_VAR_ROOT = Path(__file__).resolve().parent.parent.parent
MONGO_DIR = _VAR_ROOT / "data" / "mongo"

COLLECTIONS = ("report_chunks", "valuation_results")


def _path(collection: str) -> Path:
    if collection not in COLLECTIONS:
        raise ValueError(f"알 수 없는 컬렉션: {collection}")
    MONGO_DIR.mkdir(parents=True, exist_ok=True)
    return MONGO_DIR / f"{collection}.jsonl"


def append_docs(collection: str, docs: Iterable[dict]) -> int:
    """문서 다건을 JSONL 에 append (중복 검사 없음 — 대량 적재용).

    Returns: append 한 문서 수.
    """
    p = _path(collection)
    n = 0
    with p.open("a", encoding="utf-8") as f:
        for d in docs:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
            n += 1
    return n


def iter_docs(collection: str) -> Iterator[dict]:
    """JSONL 스트리밍 읽기 (대용량 안전)."""
    p = _path(collection)
    if not p.exists():
        return
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def upsert_doc(collection: str, doc: dict, id_field: str = "_id") -> None:
    """단일 문서 upsert — 같은 _id 가 있으면 교체, 없으면 append.

    소량 컬렉션(valuation_results)용. 전체를 읽어 _id 기준 교체 후 재기록.
    """
    if id_field not in doc:
        raise ValueError(f"문서에 '{id_field}' 필요")
    p = _path(collection)
    docs: list[dict] = []
    replaced = False
    if p.exists():
        for d in iter_docs(collection):
            if d.get(id_field) == doc[id_field]:
                docs.append(doc)
                replaced = True
            else:
                docs.append(d)
    if not replaced:
        docs.append(doc)
    tmp = p.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for d in docs:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    tmp.replace(p)


def get_doc(collection: str, doc_id: str, id_field: str = "_id") -> Optional[dict]:
    for d in iter_docs(collection):
        if d.get(id_field) == doc_id:
            return d
    return None


def existing_ids(collection: str, id_field: str = "_id") -> set[str]:
    return {d.get(id_field) for d in iter_docs(collection) if d.get(id_field) is not None}


def count(collection: str) -> int:
    return sum(1 for _ in iter_docs(collection))


def counts() -> dict[str, int]:
    return {c: count(c) for c in COLLECTIONS}


if __name__ == "__main__":
    print(f"Mongo-JSON 디렉터리: {MONGO_DIR}")
    for c, n in counts().items():
        print(f"  {c:22s} {n:>8d}")
