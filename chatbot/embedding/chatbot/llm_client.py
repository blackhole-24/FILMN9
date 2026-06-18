"""OpenAI 클라이언트 + 답변 생성.

- 공유 클라이언트 팩토리(_get_client) — analyzer/generator 공용.
- generate_answer: 검색 컨텍스트 기반 답변 (환각 방지 + 출처 인용).
- 스트리밍/논스트리밍 모두 지원.
"""
from __future__ import annotations

from typing import Iterator, Optional

from .config import (
    OPENAI_MODEL, OPENAI_TEMPERATURE, OPENAI_TIMEOUT_S, MAX_COMPLETION_TOKENS,
)

_CLIENT = None


def _get_client():
    """OpenAI 클라이언트 (1회 초기화). OPENAI_API_KEY 환경변수 필요."""
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT
    try:
        from openai import OpenAI
    except ImportError as e:
        raise RuntimeError("openai 패키지 필요: pip install openai") from e
    _CLIENT = OpenAI(timeout=OPENAI_TIMEOUT_S)
    return _CLIENT


# 모델별로 미지원할 수 있는 파라미터 (GPT-5/o 계열은 custom temperature 거부 사례)
# reasoning_effort/verbosity 는 GPT-5 계열 전용 — 미지원 모델에선 자동 폴백
# max_completion_tokens 미지원(구형) 모델이면 자동 폴백으로 제거(상한만 사라짐, 호출은 성공)
_DROPPABLE_PARAMS = ("reasoning_effort", "verbosity", "max_completion_tokens", "temperature", "top_p")


def chat_create(*, model, messages, temperature=None, response_format=None,
                stream=False, stream_options=None,
                reasoning_effort=None, verbosity=None, max_completion_tokens=None):
    """chat.completions.create 래퍼 — 미지원 파라미터 자동 폴백.

    GPT-5 계열은 reasoning_effort("minimal"/"low"/"medium"/"high")로 추론 깊이 조절,
    max_completion_tokens 로 추론+출력 토큰 상한 지정(장문 잘림 방지).
    미지원 모델은 해당 오류 시 그 파라미터만 제거하고 재시도(모델 교체 호환성).
    """
    client = _get_client()
    kwargs: dict = {"model": model, "messages": messages}
    if response_format is not None:
        kwargs["response_format"] = response_format
    if temperature is not None:
        kwargs["temperature"] = temperature
    if reasoning_effort is not None:
        kwargs["reasoning_effort"] = reasoning_effort
    if verbosity is not None:
        kwargs["verbosity"] = verbosity
    if max_completion_tokens is not None:
        kwargs["max_completion_tokens"] = max_completion_tokens
    if stream:
        kwargs["stream"] = True
        if stream_options:
            kwargs["stream_options"] = stream_options

    for _ in range(len(_DROPPABLE_PARAMS) + 1):
        try:
            return client.chat.completions.create(**kwargs)
        except Exception as e:
            msg = str(e).lower()
            dropped = False
            for p in _DROPPABLE_PARAMS:
                if p in kwargs and p in msg and ("support" in msg or "unsupported" in msg
                                                 or "invalid" in msg):
                    kwargs.pop(p, None)
                    dropped = True
                    break
            if not dropped:
                raise
    return client.chat.completions.create(**kwargs)


SYSTEM_PROMPT = """당신은 한국 상장사 사업보고서(DART) 기반 금융 분석 어시스턴트입니다.

내용 규칙:
1. 아래 제공된 "검색된 보고서 청크"에 근거해서만 답하십시오.
2. 청크에 없는 내용은 추측하지 말고 "제공된 보고서에서 해당 정보를 찾을 수 없습니다"라고 답하십시오.
   단, **회사명 표기 차이(구명·약칭·영문명 등)만을 이유로 정보가 없다고 답하지 마십시오.**
   질문 대상 회사가 지정돼 있으면, 청크의 '당사'·'회사'는 그 회사를 가리키는 것으로 보고 답하십시오.
   ★ **표·청크에 실제 수치·내역이 들어 있으면 반드시 그 값을 읽어 답하십시오.** 단지 다른 곳을
   "참조하시기 바랍니다" 같은 안내 문구가 있다고 해서 "정보가 없다/명시되어 있지 않다"고 답하지
   마십시오 — 안내 문구뿐인 청크는 무시하고, 수치가 든 표를 우선 사용하십시오.
3. 표·목록형 데이터(보증내역·주식수·소송·재무·배당 등)는 컨텍스트에 있는
   **관련 항목을 빠짐없이** 항목별로 구체적으로 제시하십시오 — 상위 몇 건만 요약하지 말고,
   각 항목의 핵심 수치(금액·비율·기간·상대방 등)를 정확히 인용하십시오. 임의로 계산하지 마십시오.
   - **★ 모든 금액·재무 수치에는 단위를 반드시 함께 표기**하십시오. 표 청크 상단에 보통
     "(단위 : 백만원)" / "(단위 : 천원)" / "(단위 : 원)" / "(단위 : USD 천)" 등이 있습니다.
     이 단위를 답변에서 수치 뒤에 적으십시오 (예: "333,605,938 백만원").
     - 같은 청크(또는 바로 위 문장)에 단위가 명시돼 있으면 그 단위를 쓰십시오.
     - 단위 정보가 전혀 없는 경우에만 "(단위 미확인)"이라고 표기하십시오.
     - 단위를 절대 임의로 추정하지 마십시오 (백만원과 천원은 1,000배 차이).
   - **우발부채를 물으면 회사가 '의무자'인 항목을 빠짐없이 포함하십시오** —
     제공한 지급보증·채무보증·타인을 위한 담보제공·약정사항·계류 중 소송·충당부채 등.
     단, **'제공받은 지급보증'처럼 회사가 수혜자인 항목은 회사의 우발부채(부채)가 아니므로**
     우발부채로 답하지 마십시오(별도로 물으면 약정·신용공여로 구분해 설명). 표의 한도·금액은
     정확히 인용하십시오.
   - **전치된 표 주의**: 행이 항목명(보증처·한도·금액 등), 열이 구분(예: 계약이행보증/선박선수금)인
     표도 값을 정확히 매칭해 읽으십시오. "보증금액 한도 2,760,577" 같은 수치를 빠뜨리지 마십시오.
4. 출처를 본문 안에 [회사 연도 | 섹션]·[청크 N] 같은 괄호 형태로 끼워 넣지 마십시오.
   (출처는 화면 하단에 자동으로 표시됩니다.) 필요하면 "사업의 내용 항목에 따르면"처럼
   자연스럽게만 언급하십시오.

출력 형식 규칙(중요):
5. 마크다운 문법을 절대 쓰지 마십시오. 별표(**, *), 우물정(#), 백틱(`), 표 기호(|),
   밑줄(__) 등을 사용하지 말고 깔끔한 평문으로 작성하십시오.
6. 여러 항목을 나열할 때는 한 줄에 하나씩, 줄 앞에 "1) " 또는 "- " 를 붙이십시오.
7. 질문 성격에 맞게 작성하십시오 — 수치·내역·목록을 묻는 질문은 항목을 빠짐없이 담아
   충분히 상세하게, 일반·서술형 질문은 간결하게. 한국어로 줄바꿈하여 가독성 있게.
8. 청크 헤더에는 출처 보고서(예: "2026 1분기보고서", "2025 사업보고서")가 표기돼 있습니다.
   **수치를 언급할 때 어느 보고서·연도 기준인지 밝히고**, 서로 다른 보고서(연간/분기) 수치가
   섞이면 각각 어느 보고서 것인지 구분해 답하십시오.
"""


def _build_messages(question: str, context: str,
                    history: Optional[list[dict]] = None,
                    company: Optional[str] = None,
                    coverage: Optional[list[str]] = None) -> list[dict]:
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    if history:
        msgs.extend(history)
    # 해석된 회사 정체성 주입 — 사용자가 구명·약칭으로 불러도 동일 회사로 간주하게 함
    id_line = ""
    if company:
        id_line = (f"질문 대상 회사: {company}. 사용자가 구명·약칭·영문명으로 불러도 "
                   f"이 회사를 가리키며, 청크의 '당사'·'회사'는 이 회사입니다.\n\n")
    # 커버리지 체크리스트 — 넓은 질문에서 모델이 일부 항목만 보고 누락하는 것 방지
    cov_line = ""
    if coverage:
        cov_line = ("\n\n※ 아래 항목 중 위 청크에 **실제로 나오는 것**은 한 항목도 빠뜨리지 말고 "
                    "각각의 수치를 찾아 포함하십시오. 단, 청크에 없는 항목은 'X: 정보 없음'처럼 "
                    "나열하지 말고 **그냥 생략**하십시오(없는 항목을 굳이 언급하지 말 것): "
                    + ", ".join(coverage) + ".")
    user = (f"{id_line}검색된 보고서 청크:\n{context}\n\n"
            f"---\n질문: {question}{cov_line}\n\n"
            f"위 청크에 근거해, 마크다운 기호 없이 평문으로 답하십시오.")
    msgs.append({"role": "user", "content": user})
    return msgs


# 추론 깊이(reasoning_effort) — 데모 속도용 env 조절. 기본 'low'(high는 정확하나 느림 20~40s).
# CHATBOT_REASONING_EFFORT=minimal|low|medium|high
import os as _os
_REASONING = _os.getenv("CHATBOT_REASONING_EFFORT", "low")


def generate_answer(question: str, context: str,
                    history: Optional[list[dict]] = None,
                    model: str = OPENAI_MODEL,
                    company: Optional[str] = None,
                    coverage: Optional[list[str]] = None) -> str:
    """논스트리밍 답변 생성. reasoning_effort='high' — 표 독해·수치추출 누락 최소화.

    빈 응답 자동 복구(3단계, 추론 high 기본 유지):
      1~2차: reasoning='high'로 시도(산발 빈응답은 재시도로 대부분 복구)
      3차(최후): high가 2회 연속 빈응답인 무거운 질문에 한해 reasoning='medium' 폴백
                 → '빈 답변'보다 medium 답변이 낫다(데모 치명적 빈응답 방지). 평소엔 high 유지.
    """
    msgs = _build_messages(question, context, history, company, coverage)
    content = ""
    for effort in (_REASONING, _REASONING, "medium"):
        resp = chat_create(
            model=model,
            temperature=OPENAI_TEMPERATURE,
            reasoning_effort=effort,
            max_completion_tokens=MAX_COMPLETION_TOKENS,
            messages=msgs,
        )
        content = resp.choices[0].message.content or ""
        if content.strip():
            break
    return content


def stream_answer(question: str, context: str,
                  history: Optional[list[dict]] = None,
                  model: str = OPENAI_MODEL,
                  company: Optional[str] = None,
                  coverage: Optional[list[str]] = None) -> Iterator[str]:
    """스트리밍 답변 생성 (토큰 단위 yield). reasoning_effort='high'.

    빈 응답 자동 복구: 스트림이 토큰을 하나도 못 내면(산발 빈응답), 논스트리밍
    generate_answer(자체 재시도 포함)로 폴백해 그 결과를 한 번에 yield.
    """
    stream = chat_create(
        model=model,
        temperature=OPENAI_TEMPERATURE,
        reasoning_effort=_REASONING,
        max_completion_tokens=MAX_COMPLETION_TOKENS,
        messages=_build_messages(question, context, history, company, coverage),
        stream=True,
    )
    emitted = False
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta.content
        if delta:
            emitted = True
            yield delta
    # 산발 빈응답 폴백: 토큰이 하나도 안 나왔으면 논스트리밍(재시도 포함)으로 복구
    if not emitted:
        fb = generate_answer(question, context, history, model, company, coverage)
        if fb.strip():
            yield fb


# ─────────────────────────────────────────────────────────────
# 지식 폴백 (RAG 미검색 시 일반지식 답변) — DART 근거가 아님을 명확히 분리
# ─────────────────────────────────────────────────────────────
FALLBACK_SYSTEM_PROMPT = """당신은 한국 기업·금융·회계 전반에 밝은 AI 어시스턴트입니다.
지금은 사용자의 질문에 대해 DART 사업보고서에서 근거 자료를 찾지 못한 상황입니다.
당신의 일반 지식으로 도움을 주되, 다음을 반드시 지키십시오.

1. 이 답변은 DART 보고서에서 검증된 것이 아닙니다. **특정 회사의 구체적 재무 수치(매출액·영업이익·
   부채 등)를 보고서에서 확인한 것처럼 단정하지 마십시오.** 확실하지 않으면 "정확한 수치는 해당 기업의
   공시·DART 전자공시에서 확인하시기 바랍니다"라고 안내하십시오.
2. 일반 개념·정의·제도·업계 상식·계산 방법 등은 아는 범위에서 명확하고 정확하게 설명하십시오.
3. 시점에 따라 달라지는 정보(주가·환율·최근 실적·인사 등)는 추정하지 말고 한계를 밝히십시오.
4. 모르면 모른다고 정직하게 말하십시오(없는 사실을 지어내지 마십시오).
5. 마크다운 기호(별표·우물정·표기호 등) 없이 평문으로, 한국어로 간결·정확하게 답하십시오.
"""


def _build_fallback_messages(question: str, history: Optional[list[dict]] = None) -> list[dict]:
    msgs = [{"role": "system", "content": FALLBACK_SYSTEM_PROMPT}]
    if history:
        msgs.extend(history)
    msgs.append({"role": "user", "content": question})
    return msgs


def generate_fallback_answer(question: str, history: Optional[list[dict]] = None,
                             model: str = OPENAI_MODEL) -> str:
    """일반지식 답변(논스트리밍). DART 근거가 아니므로 호출부에서 경고 라벨을 함께 표시한다."""
    msgs = _build_fallback_messages(question, history)
    content = ""
    for effort in ("high", "medium"):
        resp = chat_create(model=model, temperature=OPENAI_TEMPERATURE, reasoning_effort=effort,
                           max_completion_tokens=MAX_COMPLETION_TOKENS, messages=msgs)
        content = resp.choices[0].message.content or ""
        if content.strip():
            break
    return content


def stream_fallback_answer(question: str, history: Optional[list[dict]] = None,
                           model: str = OPENAI_MODEL) -> Iterator[str]:
    """일반지식 답변(스트리밍). 무토큰 시 논스트리밍으로 폴백."""
    stream = chat_create(model=model, temperature=OPENAI_TEMPERATURE, reasoning_effort="high",
                         max_completion_tokens=MAX_COMPLETION_TOKENS,
                         messages=_build_fallback_messages(question, history), stream=True)
    emitted = False
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta.content
        if delta:
            emitted = True
            yield delta
    if not emitted:
        fb = generate_fallback_answer(question, history, model)
        if fb.strip():
            yield fb


# ─────────────────────────────────────────────────────────────
# 첨부파일(PDF 추출텍스트 / 이미지) 멀티모달 답변
# ─────────────────────────────────────────────────────────────
ATTACHMENT_SYSTEM_PROMPT = """당신은 사용자가 첨부한 자료(PDF에서 추출한 텍스트, 이미지)를 읽고 질문에
답하는 어시스턴트입니다. 다음을 지키십시오.
1. 첨부된 내용에 근거해 답하십시오. 첨부에 없는 사실을 지어내지 마십시오(없으면 "첨부 자료에서 찾을 수 없습니다").
2. 표·수치는 정확히 인용하고, 단위가 있으면 함께 표기하십시오. 이미지의 글자·표·차트도 최대한 정확히 읽으십시오.
3. 질문이 비어 있으면 첨부 자료의 핵심을 요약하십시오.
4. 마크다운 기호 없이 평문으로, 한국어로 간결·정확하게 답하십시오.
5. "[비교용 DART 보고서 발췌]"가 함께 제공되면, 첨부 자료의 수치·내용을 그 DART 발췌와 비교·대조해
   차이를 설명하십시오. 어느 값이 첨부 자료이고 어느 값이 DART인지 출처를 구분해 인용하십시오.
"""


def generate_attachment_answer(question: str, pdf_text: Optional[str] = None,
                               images: Optional[list] = None,
                               dart_context: Optional[str] = None,
                               history: Optional[list[dict]] = None,
                               model: str = OPENAI_MODEL) -> str:
    """첨부(PDF 추출텍스트/이미지) 기반 멀티모달 답변.

    images: [(base64_str, mime_type), ...]  — 비전 입력으로 전달.
    pdf_text: PDF에서 추출한 텍스트(있으면 질문과 함께 텍스트 파트로 전달).
    dart_context: 첨부+DART 비교용 보고서 발췌(있으면 비교 답변).
    """
    q = (question or "").strip() or "첨부한 자료의 핵심 내용을 분석해 요약해 주세요."
    text_part = q
    if pdf_text:
        text_part += "\n\n[첨부 PDF에서 추출한 텍스트]\n" + pdf_text
    if dart_context:
        text_part += "\n\n[비교용 DART 보고서 발췌]\n" + dart_context
    content: list = [{"type": "text", "text": text_part}]
    for b64, mime in (images or []):
        content.append({"type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}"}})
    msgs = [{"role": "system", "content": ATTACHMENT_SYSTEM_PROMPT}]
    if history:
        msgs.extend(history)
    msgs.append({"role": "user", "content": content})
    out = ""
    for effort in ("high", "medium"):
        resp = chat_create(model=model, temperature=OPENAI_TEMPERATURE, reasoning_effort=effort,
                           max_completion_tokens=MAX_COMPLETION_TOKENS, messages=msgs)
        out = resp.choices[0].message.content or ""
        if out.strip():
            break
    return out
