"""ChromaDB 래퍼 — 영구 저장 + 증분 업데이트 + 메타데이터 필터.

영구 저장 위치: VAR/embedding/chroma_db/
컬렉션:        annual_reports (모든 회사 + 모든 연도)
"""
from __future__ import annotations

from typing import Optional

from .config import CHROMA_DB_DIR, COLLECTION_NAME, EMBEDDING_DIM


# 전역 클라이언트·컬렉션 캐시
_CLIENT = None
_COLLECTION = None


def _get_client():
    """ChromaDB persistent client (1회만 초기화)."""
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT
    try:
        import chromadb
        from chromadb.config import Settings
    except ImportError as e:
        raise RuntimeError(
            "chromadb 패키지 필요: pip install chromadb"
        ) from e
    _CLIENT = chromadb.PersistentClient(
        path=str(CHROMA_DB_DIR),
        settings=Settings(anonymized_telemetry=False),
    )
    return _CLIENT


def get_collection():
    """기존 컬렉션 가져오거나 신규 생성 (1회만)."""
    global _COLLECTION
    if _COLLECTION is not None:
        return _COLLECTION
    client = _get_client()
    _COLLECTION = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={
            "embedding_dim": EMBEDDING_DIM,
            "description": "한국 사업보고서 청크 임베딩 (BGE-M3, KOSPI+KOSDAQ)",
        },
    )
    return _COLLECTION


def add_batch(ids: list[str],
              texts: list[str],
              embeddings: list[list[float]],
              metadatas: list[dict]) -> None:
    """배치 단위 upsert (이미 있는 id 는 덮어씀)."""
    if not ids:
        return
    coll = get_collection()
    coll.upsert(
        ids=ids,
        embeddings=embeddings,
        documents=texts,
        metadatas=metadatas,
    )


def get_existing_ids(ids: list[str]) -> set[str]:
    """주어진 ID 중 이미 DB에 있는 것들 반환 (증분 업데이트용)."""
    if not ids:
        return set()
    coll = get_collection()
    # ChromaDB get 은 없으면 빈 결과
    res = coll.get(ids=ids, include=[])
    return set(res.get("ids", []))


def get_embeddings_by_ids(ids: list[str]) -> list[list[float]]:
    """주어진 ID 들의 저장된 임베딩 벡터 반환 (재임베딩 없이 재사용).

    피어 사업유사도 등에서 청크별 저장 벡터를 평균(centroid)낼 때 사용.
    반환 순서는 ChromaDB get 결과 순서이며, 누락 id 는 빠진다.
    """
    if not ids:
        return []
    coll = get_collection()
    res = coll.get(ids=ids, include=["embeddings"])
    embs = res.get("embeddings")
    if embs is None:
        return []
    # ChromaDB 버전에 따라 numpy array 또는 list — list 로 정규화
    return [list(e) for e in embs]


def query(query_embedding: list[float],
          top_k: int = 10,
          where: Optional[dict] = None) -> dict:
    """벡터 검색 + 메타데이터 필터.

    Args:
        query_embedding: 1D 임베딩 벡터
        top_k:           상위 N개
        where:           메타데이터 필터 (예: {"ticker": "000720", "year": 2025})

    Returns:
        {
            "ids":       [[...]],
            "documents": [[...]],
            "metadatas": [[...]],
            "distances": [[...]],
        }
    """
    coll = get_collection()
    return coll.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        where=where,
    )


def get_stats() -> dict:
    """현재 컬렉션 통계."""
    coll = get_collection()
    count = coll.count()
    return {
        "collection": COLLECTION_NAME,
        "total_chunks": count,
        "db_path": str(CHROMA_DB_DIR),
    }


def reset_collection() -> None:
    """⚠ 컬렉션 전체 삭제 후 재생성 (개발용)."""
    global _COLLECTION
    client = _get_client()
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    _COLLECTION = None
    get_collection()   # 재생성
    print(f"[vector_store] 컬렉션 '{COLLECTION_NAME}' 초기화 완료")
