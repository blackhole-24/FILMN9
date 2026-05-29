"""검색 인터페이스 — Tab 2 / Tab 3 / 챗봇 공통.

사용 예:
    # Tab 2: 주식수 추출용
    chunks = retrieve(
        query="보통주 발행주식 총수 자기주식",
        ticker="000720", year=2025, top_k=15,
    )

    # Tab 3: 사건 분류용
    chunks = retrieve(
        query="해외 공사손실 충당금 일회성",
        ticker="000720", year=2025, top_k=10,
    )

    # 챗봇: 자유 질문
    chunks = retrieve(
        query="현대건설 주요 사업은 무엇인가요?",
        ticker="000720", top_k=8,
    )

    # 피어 비교: 사업 부문
    chunks = retrieve(
        query="사업 부문 매출 구성",
        ticker=peer_ticker, year=2025, top_k=10,
    )
"""
from __future__ import annotations

from typing import Optional

from .embedder import embed_query
from .vector_store import query as vector_query


def retrieve(query: str,
             ticker: Optional[str] = None,
             year: Optional[int] = None,
             section_main: Optional[str] = None,
             top_k: int = 10) -> list[dict]:
    """벡터 검색 + 메타데이터 필터.

    Returns:
        [
            {
                "id":       청크 ID,
                "text":     본문,
                "metadata": {...},
                "distance": 코사인 거리 (낮을수록 유사),
                "similarity": 1 - distance (높을수록 유사),
            },
            ...
        ]
    """
    # 1) 쿼리 임베딩
    query_emb = embed_query(query)

    # 2) 메타데이터 필터 구성
    where = {}
    if ticker:
        where["ticker"] = ticker
    if year is not None:
        where["year"] = year
    if section_main:
        where["section_main"] = section_main

    # ChromaDB where 조건이 빈 dict 면 None 으로
    where_filter = where if where else None
    # ChromaDB 가 단일 조건이 아닌 경우 $and 로 묶어야 함
    if where_filter and len(where_filter) > 1:
        where_filter = {"$and": [{k: v} for k, v in where_filter.items()]}

    # 3) 검색
    result = vector_query(
        query_embedding=query_emb.tolist(),
        top_k=top_k,
        where=where_filter,
    )

    # 4) 결과 정리
    ids       = result.get("ids", [[]])[0]
    documents = result.get("documents", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0]

    out = []
    for i in range(len(ids)):
        dist = distances[i] if i < len(distances) else 1.0
        out.append({
            "id":         ids[i],
            "text":       documents[i] if i < len(documents) else "",
            "metadata":   metadatas[i] if i < len(metadatas) else {},
            "distance":   float(dist),
            "similarity": 1.0 - float(dist),
        })
    return out


def retrieve_for_keyword(keywords: list[str],
                         ticker: Optional[str] = None,
                         year: Optional[int] = None,
                         top_k: int = 15) -> list[dict]:
    """키워드 리스트를 쿼리로 변환해 검색.

    Tab 2 의 fetch_shares_via_rag, fetch_credit_rating_via_rag 등에서 활용.

    예:
        retrieve_for_keyword(
            ["보통주 발행주식 총수", "자기주식수", "주식의 총수"],
            ticker="000720", year=2025,
        )
    """
    query_str = " ".join(keywords)
    return retrieve(query_str, ticker=ticker, year=year, top_k=top_k)


def retrieve_business_segments(ticker: str, year: int, top_k: int = 10) -> list[dict]:
    """사업 부문 정보 검색 — 피어 비교용 헬퍼.

    section_main 정확일치(예: 'II. 사업의 내용')는 회사마다 표기가 미세하게 달라
    (공백·로마자 차이) 0건이 될 위험이 있어, ticker/year 로만 좁혀 넉넉히 검색한 뒤
    '사업' 포함 섹션을 후처리로 우선 필터한다 (부분일치 — ChromaDB metadata 미지원 대응).
    """
    results = retrieve(
        query="사업 부문 매출 구성 주요 제품 서비스",
        ticker=ticker,
        year=year,
        top_k=top_k * 3,
    )
    biz = [r for r in results
           if "사업" in (r.get("metadata", {}).get("section_main", "") or "")]
    return (biz or results)[:top_k]


def format_chunks_for_llm(chunks: list[dict], max_chars: int = 10000) -> str:
    """검색된 청크를 LLM 컨텍스트 문자열로 정리.

    각 청크에 출처 메타데이터 포함 (LLM이 인용 시 활용).
    """
    _RNAME = {"annual": "사업보고서", "q1": "1분기보고서", "q2": "2분기보고서",
              "q3": "3분기보고서", "semiannual": "반기보고서"}
    lines = []
    used = 0
    for i, c in enumerate(chunks, 1):
        meta = c["metadata"]
        # 보고서 종류(신규 청크: report_kind '2026-q1' / 구 청크: 사업보고서로 간주)
        _rk = meta.get("report_kind") or ""
        _period = _rk.split("-")[-1] if "-" in _rk else (meta.get("report_type") or "annual")
        _rname = _RNAME.get(_period, "사업보고서")
        header = (f"[청크 {i} | {meta.get('corp_name','')} {meta.get('year','')} {_rname} "
                  f"| {meta.get('section_path_str','')} | {meta.get('kind','')}]")
        text = c["text"]
        block = f"{header}\n{text}\n"
        if used + len(block) > max_chars:
            break
        lines.append(block)
        used += len(block)
    return "\n---\n".join(lines)
