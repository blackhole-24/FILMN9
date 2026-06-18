"""질문 분석 + 쿼리 변환 (gpt-4o-mini, 단일 호출).

한 번의 OpenAI 호출로 다음을 모두 추출/생성한다 (비용 효율):
  - company: 공식 회사명 (통칭→공식명 정규화, 예 "네이버"→"NAVER")
  - year:    회계연도 (상대표현 "작년" 등 해석)
  - intent:  질문 의도(짧은 라벨)
  - search_query:  검색 최적화 핵심 질의 (회사명 제외, 키워드 중심)
  - query_variants: Multi-Query 변형들 (표현 누락 보완)
  - hypothetical_answer: HyDE 가상답변 (사업보고서 문체)

회사명이 없으면 company=null → 파이프라인이 세션의 직전 회사로 폴백.
"""
from __future__ import annotations

import json
from typing import Optional

from .config import (
    OPENAI_ANALYZER_MODEL, ENABLE_HYDE, ENABLE_MULTI_QUERY, N_QUERY_VARIANTS,
)
from .llm_client import chat_create

_ANALYZER_SYSTEM = """당신은 한국 상장사 사업보고서 검색을 위한 질문 분석기입니다.
사용자 질문을 분석해 JSON 으로만 응답하십시오. 설명 금지.

추출 규칙:
- "company": 질문에서 가리키는 회사 이름을 **사용자가 쓴 그대로(원문)** 적으십시오.
  철자·표기를 바꾸지 마십시오 — 한글↔영문 변환, 약자 변환, 정식명 추정 모두 금지.
  (예: "에이치디현대중공업"이면 그대로 "에이치디현대중공업", "HD현대중공업"이면 그대로
  "HD현대중공업".) 회사 언급이 없으면 null.
- "company_aliases": 같은 회사를 가리키는 **다른 표기들**을 아는 대로 배열로 적으십시오.
  한글 정식명·영문명·약칭 등 (예: "네이버" → ["NAVER","네이버주식회사"];
  "HD현대중공업" → ["에이치디현대중공업"]; "엘지화학" → ["LG화학"]). 모르면 [].
- "year": 회계연도(정수). "작년"·"최근" 등 상대표현은 기준연도 {current_year} 로 환산.
  명시 없으면 null.
- "period": 보고서 종류. 다음 중 하나 또는 null:
  · "annual" : "사업보고서"·"연간"·"연차"·"사업연도" 언급
  · "q1"     : "1분기"·"Q1"·"1Q"·"first quarter" 언급
  · "q2"     : "2분기"·"Q2"·"2Q"
  · "h1"     : "반기"·"상반기"·"H1"
  · "q3"     : "3분기"·"Q3"·"3Q"
  명시 없으면 null.
- "intent": 질문 의도를 한국어 짧은 라벨로 (예: "사업개요", "재무실적", "주식수", "신용등급").
- "search_query": 벡터 검색에 최적화한 핵심 질의. 회사명은 빼고 사업보고서에 나올 법한
  명사·키워드 중심으로 재작성.
- "query_variants": search_query 의 의미는 같되 표현이 다른 변형 {n_variants}개 (한국어).
- "hypothetical_answer": 이 질문에 대해 사업보고서 본문에 실릴 법한 가상의 답변 1~2문장
  (정확한 수치 지어내지 말고, 문체·용어만 보고서처럼)."""

_USER_TMPL = """이전 대화에서 마지막으로 다룬 회사: {prev_company}

질문: {question}

JSON 형식:
{{"company": str|null, "company_aliases": [str, ...], "year": int|null,
  "period": "annual"|"q1"|"q2"|"h1"|"q3"|null, "intent": str,
  "search_query": str, "query_variants": [str, ...], "hypothetical_answer": str}}"""


def analyze(question: str,
            prev_company: Optional[str] = None,
            current_year: int = 2025) -> dict:
    """질문 분석 결과 dict 반환. 실패 시 안전한 폴백."""
    system = (_ANALYZER_SYSTEM
              .replace("{current_year}", str(current_year))
              .replace("{n_variants}", str(max(0, N_QUERY_VARIANTS - 1))))
    user = _USER_TMPL.format(
        prev_company=prev_company or "(없음)",
        question=question,
    )
    try:
        resp = chat_create(
            model=OPENAI_ANALYZER_MODEL,
            temperature=0.2,
            reasoning_effort="minimal",   # 구조화 JSON 추출 — 깊은 추론 불필요(속도)
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        data = json.loads(resp.choices[0].message.content or "{}")
    except Exception:
        data = {}

    # 정규화 + 폴백
    search_query = (data.get("search_query") or question).strip()
    variants = data.get("query_variants") or []
    if not isinstance(variants, list):
        variants = []

    # 검색에 실제로 쓸 쿼리 묶음 구성: 원본 핵심질의 + 변형(+ HyDE)
    queries = [search_query]
    if ENABLE_MULTI_QUERY:
        for v in variants:
            if isinstance(v, str) and v.strip() and v.strip() not in queries:
                queries.append(v.strip())
        queries = queries[:N_QUERY_VARIANTS]
    if ENABLE_HYDE:
        hyde = data.get("hypothetical_answer")
        if isinstance(hyde, str) and hyde.strip():
            queries.append(hyde.strip())

    year = data.get("year")
    if not isinstance(year, int):
        year = None

    period = data.get("period")
    if period not in ("annual", "q1", "q2", "h1", "q3"):
        period = None

    aliases = data.get("company_aliases") or []
    if not isinstance(aliases, list):
        aliases = []
    aliases = [a.strip() for a in aliases if isinstance(a, str) and a.strip()]

    return {
        "company": (data.get("company") or None),
        "company_aliases": aliases,    # 회사 해석 시 원문과 함께 모두 대조
        "year": year,
        "period": period,              # annual/q1/q2/h1/q3 또는 None (메타 필터용)
        "intent": data.get("intent") or "",
        "search_query": search_query,
        "queries": queries,            # 실제 검색에 사용할 쿼리 리스트
        "hypothetical_answer": data.get("hypothetical_answer") or "",
    }
