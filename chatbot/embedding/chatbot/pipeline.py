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


# period_label → 한국어 보고서명
_REPORT_LABEL = {"annual": "사업보고서", "q1": "1분기보고서", "q2": "2분기보고서",
                 "q3": "3분기보고서", "semiannual": "반기보고서"}


def _report_label(m: dict) -> str:
    """메타데이터 → '2026년 1분기보고서' 식 출처 라벨.

    신규 청크는 report_kind('2026-q1')·report_type 보유. 구 청크(연간)는 둘 다 없으므로
    '사업보고서'로 간주(기존 데이터는 전부 사업보고서).
    """
    yr = m.get("year")
    rk = m.get("report_kind") or ""           # 예: "2026-q1" / "2025-annual"
    period = rk.split("-")[-1] if "-" in rk else (m.get("report_type") or "annual")
    label = _REPORT_LABEL.get(period, "사업보고서")
    return f"{yr}년 {label}" if yr else label


def _sources(chunks: list[dict], limit: int = N_SOURCES) -> list[dict]:
    """관련도 높은 순(이미 재랭킹된 순서) 상위 N개를 출처로 정리.

    - report:      '2026년 1분기보고서' 등 보고서 종류+연도 (출처 명확화)
    - section:     해당 청크가 담긴 섹션 경로 (텍스트·표 공통)
    - table_title: 표 청크면 표 제목(캡션)
    - dart_url:    DART 보고서 원문 링크
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
            "report": _report_label(m),
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

    # 연도·보고서종류 결정
    #   - period가 명시되면 year 자동 보정: 분기/반기는 current_year, 사업보고서는 current_year-1
    #     (예: 오늘 2026 → "1분기" 질문 → year=2026 / "사업보고서" 질문 → year=2025)
    #   - 둘 다 명시 없으면 직전 세션 컨텍스트 사용
    year = analysis.get("year")
    period = analysis.get("period")
    if year is None and period:
        year = current_year if period in ("q1", "q2", "h1", "q3") else (current_year - 1)
    if year is None:
        year = session.last_year
    # report_kind: 메타 정확 필터용 (예: "2026-q1", "2025-annual")
    report_kind = f"{year}-{period}" if (period and year) else None

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
        report_kind=report_kind,
        final_top_k=FINAL_TOP_K,
        rerank_extra=rerank_extra,
    )
    return {
        "status": "ok",
        "analysis": analysis,
        "ticker": ticker,
        "corp_name": corp_name,
        "year": year,
        "period": period,
        "report_kind": report_kind,
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
                  current_year: int = 2026, ticker: Optional[str] = None
                  ) -> Iterator[dict]:
    """스트리밍 답변 — 단계별 이벤트 제너레이터.

    yield 하는 dict 의 "type" 필드별 의미:
      - stage   : 진행 상태 표시 ("🔎 질문 분석 중…", "✓ 회사 식별" 등)
      - head    : 회사·연도·intent 등 답변 메타 (status, meta)
      - sources : 출처 카드 + 보고서 원문 URL (답변 전에 도착해 사용자가 미리 읽기 가능)
      - token   : LLM 토큰 ("t" 필드)
      - done    : 종료 신호

    체감 속도 개선: 검은 시간(6~14초)을 단계 진행 표시로 채워 진행감 부여 + 출처를
    답변 전에 보여 사용자가 답을 기다리는 동안 정보 흡수.
    """
    session = STORE.get_or_create(session_id)

    # ── 1) 분석 + 회사 해석 ───────────────────────────────────────
    yield {"type": "stage", "label": "🔎 질문 분석 중…"}
    analysis = query_analyzer.analyze(
        question, prev_company=session.last_corp_name, current_year=current_year)

    ticker_resolved = session.last_ticker
    corp_name = session.last_corp_name
    if ticker:                                            # 후보 칩 클릭 등
        res = company_index.resolve(ticker)
        if res["matched"]:
            ticker_resolved, corp_name = res["ticker"], res["corp_name"]
    elif analysis["company"]:
        names = [analysis["company"]] + (analysis.get("company_aliases") or [])
        res = company_index.resolve_any(names)
        if res["matched"]:
            ticker_resolved, corp_name = res["ticker"], res["corp_name"]
        else:
            yield {"type": "head", "session_id": session.id,
                   "status": "needs_clarification", "analysis": analysis,
                   "candidates": res["candidates"],
                   "message": f"'{analysis['company']}'에 해당하는 회사를 특정하지 못했습니다. "
                              f"아래 후보 중 선택하거나 종목코드를 알려주세요."}
            yield {"type": "done"}
            return

    if not ticker_resolved:
        yield {"type": "head", "session_id": session.id, "status": "needs_company",
               "analysis": analysis,
               "message": "어떤 회사에 대한 질문인지 알려주세요 (회사명 또는 6자리 종목코드)."}
        yield {"type": "done"}
        return

    yield {"type": "stage", "label": f"✓ {corp_name} ({ticker_resolved})"}

    # ── 2) 연도·보고서종류 결정 ────────────────────────────────────
    year = analysis.get("year")
    period = analysis.get("period")
    if year is None and period:
        year = current_year if period in ("q1", "q2", "h1", "q3") else (current_year - 1)
    if year is None:
        year = session.last_year
    report_kind = f"{year}-{period}" if (period and year) else None
    pl = _REPORT_LABEL.get(period) if period else "보고서"
    yield {"type": "stage",
           "label": f"📚 {year}년 {pl} 검색 중…" if year else f"📚 {pl} 검색 중…"}

    # ── 3) 온톨로지 확장 + 질의 준비 ───────────────────────────────
    queries = list(analysis["queries"])
    concepts: list[str] = []
    rerank_extra: list[str] = []
    coverage: list[str] = []
    if ENABLE_ONTOLOGY:
        probe = f"{question} {analysis['search_query']}"
        ob = ontology_b.analyze(probe, max_expand=ONTOLOGY_MAX_TERMS, max_checklist=16)
        concepts, extra, coverage = ob["concepts"], ob["expand_terms"], ob["checklist"]
        for q in extra:
            if q not in queries:
                queries.append(q)
        rerank_extra = [t for t in extra
                        if not t.startswith(("기업회계기준서", "1.", "2.", "3.", "4.",
                                             "5.", "6.", "7.", "8.", "9.", "V", "I", "X"))]
    queries = queries[:MAX_TOTAL_QUERIES]
    analysis["queries"] = queries

    # 사명변경 대응 (구명·약칭 → 정식명)
    llm_question = question
    user_term = analysis.get("company")
    if user_term and corp_name and user_term != corp_name and user_term in question:
        llm_question = question.replace(user_term, corp_name)

    # ── 4) 검색 ────────────────────────────────────────────────
    search_res = retriever.search(
        queries=queries, rerank_query=llm_question,
        ticker=ticker_resolved, year=year, report_kind=report_kind,
        final_top_k=FINAL_TOP_K, rerank_extra=rerank_extra,
    )
    chunks = search_res["chunks"]
    yield {"type": "stage", "label": f"📑 자료 {len(chunks)}건 확보"}

    # 통합 prep dict (meta 빌드용)
    prep = {
        "status": "ok", "analysis": analysis,
        "ticker": ticker_resolved, "corp_name": corp_name,
        "year": year, "period": period, "report_kind": report_kind,
        "ontology_concepts": concepts, "llm_question": llm_question,
        "coverage": coverage, "search": search_res,
    }

    if not chunks:
        msg = "제공된 보고서에서 해당 정보를 찾을 수 없습니다."
        session.add_turn(question, msg)
        session.update_context(ticker_resolved, corp_name, year)
        yield {"type": "head", "session_id": session.id, "status": "ok", "meta": _meta(prep)}
        yield {"type": "sources", "sources": [], "report_url": None}
        yield {"type": "token", "t": msg}
        yield {"type": "done"}
        return

    # ── 5) 출처를 답변 전에 emit (A2 — 사용자가 미리 읽기) ─────────
    context = format_chunks_for_llm(chunks, max_chars=MAX_CONTEXT_CHARS)
    srcs = _sources(chunks)
    meta = _meta(prep)
    yield {"type": "head", "session_id": session.id, "status": "ok", "meta": meta}
    yield {"type": "sources", "sources": srcs, "report_url": _report_url(chunks)}

    # ── 6) 답변 스트리밍 ─────────────────────────────────────────
    yield {"type": "stage", "label": "✍️ 답변 작성 중…"}
    company_label = _company_label(prep)
    buf: list[str] = []
    for tok in llm_client.stream_answer(llm_question, context, history=session.history,
                                        company=company_label, coverage=coverage):
        buf.append(tok)
        yield {"type": "token", "t": tok}
    session.add_turn(question, "".join(buf))
    session.update_context(ticker_resolved, corp_name, year)
    yield {"type": "done"}


def _company_label(prep: dict) -> Optional[str]:
    """LLM 에 주입할 해석된 회사 정체성 라벨."""
    cn = prep.get("corp_name")
    if not cn:
        return None
    tk = prep.get("ticker")
    return f"{cn} (종목코드 {tk})" if tk else cn


_PERIOD_KO = {"annual": "사업보고서", "q1": "1분기보고서", "q2": "2분기보고서",
              "h1": "반기보고서", "q3": "3분기보고서"}


def _meta(prep: dict) -> dict:
    a = prep["analysis"]
    period = prep.get("period")
    return {
        "corp_name": prep["corp_name"],
        "ticker": prep["ticker"],
        "year": prep["year"],
        "period": period,                                     # UI에서 사용
        "period_label": _PERIOD_KO.get(period) if period else None,
        "report_kind": prep.get("report_kind"),
        "intent": a.get("intent"),
        "search_query": a.get("search_query"),
        "queries_used": a.get("queries"),
        "ontology_concepts": prep.get("ontology_concepts", []),
        "reranked": prep["search"]["reranked"],
    }
