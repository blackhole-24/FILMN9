"""텍스트 데이터 저장소 — SQLite 백엔드(조회 O(log n)) + JSONL(대용량 append).

설계:
  · valuation_results(통합 결과 doc, 조회 빈번) → SQLite `mongo_docs` 테이블.
      PK (collection, doc_id) 인덱스로 get_doc 이 O(log n) — 기존 JSONL 전수 스캔(O(n)) 제거.
  · report_chunks(원문 청크, 대용량 append·조회 드묾) → JSONL(data/mongo/*.jsonl).
  · 인터페이스(get_doc/upsert_doc/iter_docs/existing_ids/count)는 동일 →
    호출부(save_valuation_result / get_latest_result) 변경 없음.
  · JSONL 은 mongoimport 호환 유지(report_chunks).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Iterator, Optional

_VAR_ROOT = Path(__file__).resolve().parent.parent.parent
MONGO_DIR = _VAR_ROOT / "data" / "mongo"

COLLECTIONS = ("report_chunks", "valuation_results")
# 조회가 잦은 컬렉션은 SQLite 백엔드(인덱스 조회). 그 외는 JSONL.
_SQLITE_COLLECTIONS = {"valuation_results"}


def _path(collection: str) -> Path:
    if collection not in COLLECTIONS:
        raise ValueError(f"알 수 없는 컬렉션: {collection}")
    MONGO_DIR.mkdir(parents=True, exist_ok=True)
    return MONGO_DIR / f"{collection}.jsonl"


def _is_sqlite(collection: str) -> bool:
    return collection in _SQLITE_COLLECTIONS


def append_docs(collection: str, docs: Iterable[dict]) -> int:
    """문서 다건 적재. SQLite 컬렉션은 _id 기준 upsert, JSONL 은 append."""
    if _is_sqlite(collection):
        n = 0
        for d in docs:
            upsert_doc(collection, d); n += 1
        return n
    p = _path(collection)
    n = 0
    with p.open("a", encoding="utf-8") as f:
        for d in docs:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
            n += 1
    return n


def iter_docs(collection: str) -> Iterator[dict]:
    """전체 문서 스트리밍."""
    if _is_sqlite(collection):
        from . import store
        for r in store.query("SELECT doc FROM mongo_docs WHERE collection=?", (collection,)):
            yield json.loads(r["doc"])
        return
    p = _path(collection)
    if not p.exists():
        return
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def upsert_doc(collection: str, doc: dict, id_field: str = "_id") -> None:
    """단일 문서 upsert — 같은 _id 교체, 없으면 삽입."""
    if id_field not in doc:
        raise ValueError(f"문서에 '{id_field}' 필요")
    if _is_sqlite(collection):
        from . import store
        store.upsert("mongo_docs", {
            "collection": collection,
            "doc_id": str(doc[id_field]),
            "doc": doc,   # store._encode 가 dict→JSON TEXT 로 직렬화(numpy 정화 포함)
        })
        return
    p = _path(collection)
    docs: list[dict] = []
    replaced = False
    if p.exists():
        for d in iter_docs(collection):
            if d.get(id_field) == doc[id_field]:
                docs.append(doc); replaced = True
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
    """단일 문서 조회. SQLite 컬렉션은 PK 인덱스로 O(log n)."""
    if _is_sqlite(collection):
        from . import store
        r = store.query_one(
            "SELECT doc FROM mongo_docs WHERE collection=? AND doc_id=?",
            (collection, str(doc_id)))
        return json.loads(r["doc"]) if r else None
    for d in iter_docs(collection):
        if d.get(id_field) == doc_id:
            return d
    return None


def existing_ids(collection: str, id_field: str = "_id") -> set[str]:
    if _is_sqlite(collection):
        from . import store
        return {r["doc_id"] for r in
                store.query("SELECT doc_id FROM mongo_docs WHERE collection=?", (collection,))}
    return {d.get(id_field) for d in iter_docs(collection) if d.get(id_field) is not None}


def count(collection: str) -> int:
    if _is_sqlite(collection):
        from . import store
        r = store.query_one("SELECT COUNT(*) AS n FROM mongo_docs WHERE collection=?", (collection,))
        return int(r["n"]) if r else 0
    return sum(1 for _ in iter_docs(collection))


def counts() -> dict[str, int]:
    return {c: count(c) for c in COLLECTIONS}
