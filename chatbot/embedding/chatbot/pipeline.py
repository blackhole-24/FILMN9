"""RAG 오케스트레이션: 분석 → 회사해석 → 강화검색 → 생성.

answer():        논스트리밍 (한 번에 답변+출처)
answer_stream(): 스트리밍 (토큰 제너레이터 + 사전 메타)

회사 해석 실패 시 사용자에게 되묻는 분기(needs_clarification)를 반환한다.
"""
from __future__ import annotations

import re
from typing import Iterator, Optional

from ..retrieval import format_chunks_for_llm
from .config import (
    MAX_CONTEXT_CHARS, FINAL_TOP_K,
    ENABLE_ONTOLOGY, ONTOLOGY_MAX_TERMS, MAX_TOTAL_QUERIES,
)
from . import query_analyzer, company_index, retriever, llm_client, dart_links, ontology_b
from .session import Session, STORE

# 표 청크 캡션 추출용 패턴
_TABLE_CAPTION_RE = re.compile(r"^\s*\[표\]\s*\(?\s*([^|\n)]+?)\s*\)?\s*(?:\||\n|$)")
_TABLE_HEADER_RE = re.compile(r"^\s*\(상위 헤더:\s*(.+?)\)")

# UI 출처 표시 개수
N_SOURCES = 5


def _table_title(text: str) -> Optional[str]:
    """표 청크에서 표 제목(캡션) 추출. 없으면 None → 섹션명으로 폴백."""
    if not text:
        return None
    m = _TABLE_CAPTION_RE.match(text)
    if m and m.group(1).strip():
        return m.group(1).strip()
    m = _TABLE_HEADER_RE.match(text)
    if m and m.group(1).strip():
        return "헤더: " + m.group(1).strip()
    return None


def _sources(chunks: list[dict], limit: int = N_SOURCES) -> list[dict]:
    """관련도 높은 순(이미 재랭킹된 순서) 상위 N개를 출처로 정리.

    - section:     해당 청크가 담긴 섹션 경로 (텍스트·표 공통)
    - table_title: 표 청크면 표 제목(캡션)
    - dart_url:    DART 사업보고서 원문 링크
    """
    out = []
    for c in chunks[:limit]:
        m = c.get("metadata", {})
        kind = m.get("kind", "")
        text = c.get("text", "")
        rcept = m.get("rcept_no", "")
        out.append({
            "kind": kind,
            "corp_name": m.get("corp_name", ""),
            "year": m.get("year"),
            "section": m.get("section_path_str", "") or m.get("section_main", ""),
            "table_title": _table_title(text) if kind == "table" else None,
            # 섹션 deep-link (실패 시 보고서 첫 화면으로 폴백)
            "dart_url": dart_links.section_url(
                rcept, m.get("section_main", ""), m.get("section_sub", "")),
            "snippet": " ".join(text[:180].split()),
        })
    return out


def _report_url(chunks: list[dict]) -> Optional[str]:
    """대표 사업보고서 첫 화면 URL (헤더 링크용)."""
    if not chunks:
        return None
    return dart_links.report_url(chunks[0].get("metadata", {}).get("rcept_no", ""))


def _prepare(question: str, session: Session, current_year: int,
             forced_ticker: Optional[str] = None) -> dict:
    """분석 + 회사해석 + 검색까지 수행 (생성 직전 상태 반환).

    forced_ticker: 후보 칩 클릭 등으로 종목코드가 명시되면 회사 해석을 건너뛰고 강제 사용.
    """
    analysis = query_analyzer.analyze(
        question, prev_company=session.last_corp_name, current_year=current_year)

    ticker = session.last_ticker
    corp_name = session.last_corp_name

    if forced_ticker:
        # 종목코드 강제 지정 — 분석기 회사명 무시(결정적 해석)
        res = company_index.resolve(forced_ticker)
        if res["matched"]:
            ticker, corp_name = res["ticker"], res["corp_name"]
    elif analysis["company"]:
        # 원문 + 별칭을 모두 대조 (한글↔영문·약자 표기차 흡수)
        names = [analysis["company"]] + (analysis.get("company_aliases") or [])
        res = company_index.resolve_any(names)
        if res["matched"]:
            ticker, corp_name = res["ticker"], res["corp_name"]
        else:
            # 못 찾음 → 후보 제시하고 되묻기
            return {
                "status": "needs_clarification",
                "analysis": analysis,
                "candidates": res["candidates"],
                "message": f"'{analysis['company']}'에 해당하는 회사를 특정하지 못했습니다. "
                           f"아래 후보 중 선택하거나 종목코드를 알려주세요.",
            }

    if not ticker:
        return {
            "status": "needs_company",
            "analysis": analysis,
            "message": "어떤 회사에 대한 질문인지 알려주세요 (회사명 또는 6자리 종목코드).",
        }

    year = analysis["year"] if analysis["year"] is not None else session.last_year

    # 하이브리드 질의 확장: 분석기 질의 + 온톨로지 도메인 확장어
    queries = list(analysis["queries"])
    concepts: list[str] = []
    rerank_extra: list[str] = []
    coverage: list[str] = []               # 답변 커버리지 체크리스트(누락 방지)
    if ENABLE_ONTOLOGY:
        # 정교 온톨로지(scope/hierarchy/components). 데이터 없으면 빈 결과로 graceful no-op.
        probe = f"{question} {analysis['search_query']}"
        ob = ontology_b.analyze(probe, max_expand=ONTOLOGY_MAX_TERMS, max_checklist=16)
        concepts, extra, coverage = ob["concepts"], ob["expand_terms"], ob["checklist"]
        for q in extra:
            if q not in queries:
                queries.append(q)
        # 확장 인지 재랭킹용: 개념어(섹션명/기준서참조 제외)
        rerank_extra = [t for t in extra
                        if not t.startswith(("기업회계기준서", "1.", "2.", "3.", "4.",
                                             "5.", "6.", "7.", "8.", "9.", "V", "I", "X"))]
    queries = queries[:MAX_TOTAL_QUERIES]
    analysis["queries"] = queries          # _meta 에 확장 반영

    # 사명변경 대응: 질문 속 사용자 용어(구명·약칭)를 해석된 정식명으로 치환.
    # 재랭킹·생성이 컨텍스트 주체명(정식명)과 어긋나지 않게 함(예: 현대중공업→에이치디현대중공업).
    llm_question = question
    user_term = analysis.get("company")
    if user_term and corp_name and user_term != corp_name and user_term in question:
        llm_question = question.replace(user_term, corp_name)

    search_res = retriever.search(
        queries=queries,
        rerank_query=llm_question,
        ticker=ticker,
        year=year,
        final_top_k=FINAL_TOP_K,
        rerank_extra=rerank_extra,
    )
    return {
        "status": "ok",
        "analysis": analysis,
        "ticker": ticker,
        "corp_name": corp_name,
        "year": year,
        "ontology_concepts": concepts,
        "llm_question": llm_question,
        "coverage": coverage,              # 답변 커버리지 체크리스트(B안 components / fallback 확장어)
        "search": search_res,
    }


def answer(question: str, session_id: Optional[str] = None,
           current_year: int = 2025, ticker: Optional[str] = None) -> dict:
    """논스트리밍 end-to-end 답변."""
    session = STORE.get_or_create(session_id)
    prep = _prepare(question, session, current_year, forced_ticker=ticker)

    if prep["status"] != "ok":
        return {"session_id": session.id, **prep}

    chunks = prep["search"]["chunks"]
    if not chunks:
        msg = "제공된 보고서에서 해당 정보를 찾을 수 없습니다."
        session.add_turn(question, msg)
        session.update_context(prep["ticker"], prep["corp_name"], prep["year"])
        return {"session_id": session.id, "status": "ok", "answer": msg,
                "sources": [], "meta": _meta(prep)}

    context = format_chunks_for_llm(chunks, max_chars=MAX_CONTEXT_CHARS)
    ans = llm_client.generate_answer(prep.get("llm_question", question), context,
                                     history=session.history, company=_company_label(prep),
                                     coverage=prep.get("coverage"))

    session.add_turn(question, ans)
    session.update_context(prep["ticker"], prep["corp_name"], prep["year"])
    srcs = _sources(chunks)
    meta = _meta(prep)
    meta["report_url"] = _report_url(chunks)
    return {
        "session_id": session.id,
        "status": "ok",
        "answer": ans,
        "sources": srcs,
        "meta": meta,
    }


def answer_stream(question: str, session_id: Optional[str] = None,
                  current_year: int = 2025, ticker: Optional[str] = None
                  ) -> tuple[dict, Optional[Iterator[str]]]:
    """스트리밍 답변.

    Returns (head, token_iter):
        head      — 즉시 보낼 메타(상태/출처/해석). status!=ok 면 token_iter=None.
        token_iter— 답변 토큰 제너레이터 (소비하면서 세션에 누적 저장).
    """
    session = STORE.get_or_create(session_id)
    prep = _prepare(question, session, current_year, forced_ticker=ticker)

    if prep["status"] != "ok":
        return {"session_id": session.id, **prep}, None

    chunks = prep["search"]["chunks"]
    if not chunks:
        msg = "제공된 보고서에서 해당 정보를 찾을 수 없습니다."
        session.add_turn(question, msg)
        session.update_context(prep["ticker"], prep["corp_name"], prep["year"])

        def _one():
            yield msg
        return ({"session_id": session.id, "status": "ok",
                 "sources": [], "meta": _meta(prep)}, _one())

    context = format_chunks_for_llm(chunks, max_chars=MAX_CONTEXT_CHARS)
    srcs = _sources(chunks)
    meta = _meta(prep)
    meta["report_url"] = _report_url(chunks)
    head = {"session_id": session.id, "status": "ok",
            "sources": srcs, "meta": meta}

    company = _company_label(prep)
    llm_question = prep.get("llm_question", question)
    coverage = prep.get("coverage")

    def _gen():
        buf = []
        for tok in llm_client.stream_answer(llm_question, context, history=session.history,
                                            company=company, coverage=coverage):
            buf.append(tok)
            yield tok
        session.add_turn(question, "".join(buf))
        session.update_context(prep["ticker"], prep["corp_name"], prep["year"])

    return head, _gen()


def _company_label(prep: dict) -> Optional[str]:
    """LLM 에 주입할 해석된 회사 정체성 라벨."""
    cn = prep.get("corp_name")
    if not cn:
        return None
    tk = prep.get("ticker")
    return f"{cn} (종목코드 {tk})" if tk else cn


def _meta(prep: dict) -> dict:
    a = prep["analysis"]
    return {
        "corp_name": prep["corp_name"],
        "ticker": prep["ticker"],
        "year": prep["year"],
        "intent": a.get("intent"),
        "search_query": a.get("search_query"),
        "queries_used": a.get("queries"),
        "ontology_concepts": prep.get("ontology_concepts", []),
        "reranked": prep["search"]["reranked"],
    }
