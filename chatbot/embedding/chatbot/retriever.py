"""검색 강화: Multi-Query + RRF 융합 + Cross-encoder 재랭킹.

흐름:
  1) 변형 쿼리 각각으로 기존 retrieve() 벡터검색 (ticker/year 메타필터)
  2) Reciprocal Rank Fusion(RRF) 으로 랭킹 리스트들을 융합 → 후보 풀
  3) BGE-reranker 로 원본 질문 기준 재정렬 → 최종 top_k
     (재랭커 불가 시 RRF 점수 순으로 graceful degrade)
"""
from __future__ import annotations

from typing import Optional

from ..embedder import embed_texts
from ..vector_store import get_collection
from .config import (
    RECALL_TOP_K, RERANK_POOL, FINAL_TOP_K, RRF_K, ENABLE_RERANK,
    ENABLE_EXPANSION_RERANK, RERANK_MAX_QUERIES,
    ENABLE_STUB_DEMOTE, STUB_TABLE_MAX_CHARS, STUB_MIN_DIGITS, STUB_PENALTY,
)
from . import reranker


def _is_stub_table(chunk: dict) -> bool:
    """값 없는 헤더/라벨뿐인 빈 표인지 판단(키워드만 있고 데이터 없음).

    '짧으면서(헤더 수준) 숫자가 거의 없는' table 청크만 stub 으로 본다.
    → 값 있는 짧은 표("자기주식 1,234,567")나 긴 정성표(소송 서술)는 stub 아님.
    """
    if chunk.get("metadata", {}).get("kind") != "table":
        return False
    t = chunk.get("text", "")
    if len(t) >= STUB_TABLE_MAX_CHARS:
        return False
    digits = sum(ch.isdigit() for ch in t)
    return digits < STUB_MIN_DIGITS


def _demote_stubs(chunks: list[dict]) -> list[dict]:
    """stub 표의 재랭킹 점수를 강등하고 재정렬(값 있는 표가 위로)."""
    if not ENABLE_STUB_DEMOTE:
        return chunks
    for c in chunks:
        if _is_stub_table(c):
            c["stub"] = True
            if c.get("rerank_score") is not None:
                c["rerank_score"] -= STUB_PENALTY
    return sorted(
        chunks,
        key=lambda c: c.get("rerank_score", c.get("rrf_score", 0.0)),
        reverse=True,
    )


def _build_where(ticker: Optional[str], year: Optional[int],
                 report_kind: Optional[str] = None) -> Optional[dict]:
    """ChromaDB 메타데이터 필터 구성 (retrieval.retrieve 와 동일 규칙).

    호환성 주의:
      - 백업 era로 임베딩된 2025 사업보고서 청크(약 192만)에는 report_kind/report_type 메타가
        없다(year/ticker 등 13개 키만 있음). 따라서 report_kind="2025-annual"로 필터하면 그 청크가
        전부 누락된다 → 사업보고서는 year로만 필터한다(모든 청크에 year 있음).
      - 분기/반기 청크는 모두 새 dc_chunker로 임베딩돼 report_kind가 항상 있음 → 정확 필터 가능.
    """
    where: dict = {}
    if ticker:
        where["ticker"] = ticker
    # annual 은 백업 호환을 위해 year 로만 필터, 나머지(q1/q2/h1/q3)는 report_kind 정확 필터
    if report_kind and not report_kind.endswith("-annual"):
        where["report_kind"] = report_kind
    elif year is not None:
        where["year"] = year
    if not where:
        return None
    if len(where) > 1:
        return {"$and": [{k: v} for k, v in where.items()]}
    return where


def _rrf_fuse(ranked_lists: list[list[dict]], k: int = RRF_K) -> list[dict]:
    """여러 랭킹 리스트를 RRF 로 융합. 청크 id 기준 dedup.

    RRF score = Σ 1/(k + rank). rank 는 각 리스트 내 0-based 순위.
    """
    fused: dict[str, dict] = {}
    for lst in ranked_lists:
        for rank, item in enumerate(lst):
            cid = item["id"]
            if cid not in fused:
                fused[cid] = dict(item)
                fused[cid]["rrf_score"] = 0.0
            fused[cid]["rrf_score"] += 1.0 / (k + rank)
    return sorted(fused.values(), key=lambda x: x["rrf_score"], reverse=True)


def search(queries: list[str],
           rerank_query: str,
           ticker: Optional[str] = None,
           year: Optional[int] = None,
           report_kind: Optional[str] = None,
           final_top_k: int = FINAL_TOP_K,
           rerank_extra: Optional[list[str]] = None) -> dict:
    """강화 검색 실행.

    Args:
        queries:      검색에 쓸 쿼리 묶음 (원본 + 변형 + HyDE + 온톨로지 확장).
        rerank_query: 재랭킹 기준 질의 (보통 사용자 원본 질문).
        rerank_extra: 확장 인지 재랭킹용 추가 질의(온톨로지 개념어). 원본과 함께
                      각각 채점해 청크별 최고점을 쓴다.
        ticker/year:  메타데이터 필터.
        final_top_k:  최종 반환 청크 수.

    Returns:
        {"chunks": [...], "reranked": bool, "pool_size": int}
    """
    # 1) 모든 변형 쿼리를 1회 배치로 임베딩 (GPU 패스 N→1) 후
    #    ChromaDB 멀티 쿼리 1회 호출 (왕복 N→1)
    qs = [q.strip() for q in queries if q and q.strip()]
    if not qs:
        return {"chunks": [], "reranked": False, "pool_size": 0}

    embs = embed_texts(qs, show_progress=False)
    coll = get_collection()
    res = coll.query(
        query_embeddings=[e.tolist() for e in embs],
        n_results=RECALL_TOP_K,
        where=_build_where(ticker, year, report_kind),
    )

    ids_all   = res.get("ids", []) or []
    docs_all  = res.get("documents", []) or []
    metas_all = res.get("metadatas", []) or []
    dists_all = res.get("distances", []) or []

    ranked_lists = []
    for qi in range(len(ids_all)):
        ids = ids_all[qi]
        lst = []
        for i, cid in enumerate(ids):
            dist = float(dists_all[qi][i]) if qi < len(dists_all) and i < len(dists_all[qi]) else 1.0
            lst.append({
                "id": cid,
                "text": docs_all[qi][i] if qi < len(docs_all) and i < len(docs_all[qi]) else "",
                "metadata": metas_all[qi][i] if qi < len(metas_all) and i < len(metas_all[qi]) else {},
                "distance": dist,
                "similarity": 1.0 - dist,
            })
        if lst:
            ranked_lists.append(lst)

    if not ranked_lists:
        return {"chunks": [], "reranked": False, "pool_size": 0}

    # 2) RRF 융합
    pool = _rrf_fuse(ranked_lists)[:RERANK_POOL]

    # 3) 재랭킹 (실패 시 RRF 순서 유지)
    #    확장 인지: [원본 질문] + [온톨로지 개념어]로 각각 채점 후 청크별 max
    reranked = False
    if ENABLE_RERANK:
        rerank_qs = [rerank_query]
        if ENABLE_EXPANSION_RERANK and rerank_extra:
            for q in rerank_extra:
                if q and q.strip() and q not in rerank_qs:
                    rerank_qs.append(q.strip())
        rerank_qs = rerank_qs[:RERANK_MAX_QUERIES]
        try:
            # 전체 풀을 재랭킹(절단X) → stub 강등 후 재정렬 → 최종 절단
            pool = reranker.rerank(rerank_qs, pool, top_k=len(pool))
            pool = _demote_stubs(pool)[:final_top_k]
            reranked = True
        except reranker.RerankUnavailable as e:
            print(f"[retriever] 재랭킹 스킵 (graceful degrade): {e}", flush=True)
            pool = pool[:final_top_k]
    else:
        pool = pool[:final_top_k]

    return {"chunks": pool, "reranked": reranked, "pool_size": len(ranked_lists)}
