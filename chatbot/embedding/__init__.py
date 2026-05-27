"""사업보고서 청크 임베딩 + 검색 패키지.

주요 인터페이스:
    from embedding.retrieval import retrieve, retrieve_business_segments
    from embedding.vector_store import get_stats
"""
from .retrieval import retrieve, retrieve_for_keyword, retrieve_business_segments, format_chunks_for_llm
from .vector_store import get_stats, get_embeddings_by_ids
from .embedder import get_device_info

__all__ = [
    "retrieve",
    "retrieve_for_keyword",
    "retrieve_business_segments",
    "format_chunks_for_llm",
    "get_stats",
    "get_embeddings_by_ids",
    "get_device_info",
]
