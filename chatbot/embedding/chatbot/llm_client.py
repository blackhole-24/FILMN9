"""OpenAI 클라이언트 + 답변 생성.

- 공유 클라이언트 팩토리(_get_client) — analyzer/generator 공용.
- generate_answer: 검색 컨텍스트 기반 답변 (환각 방지 + 출처 인용).
- 스트리밍/논스트리밍 모두 지원.
"""
from __future__ import annotations

from typing import Iterator, Optional

from .config import (
    OPENAI_MODEL, OPENAI_TEMPERATURE, OPENAI_TIMEOUT_S,
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
_DROPPABLE_PARAMS = ("temperature", "top_p")


def chat_create(*, model, messages, temperature=None, response_format=None,
                stream=False, stream_options=None):
    """chat.completions.create 래퍼 — 미지원 파라미터(예: temperature) 자동 폴백.

    GPT-5/o 계열은 custom temperature 를 거부할 수 있어, 해당 오류 시 그 파라미터를
    제거하고 1회 재시도한다(모델 교체 시 호환성 확보).
    """
    client = _get_client()
    kwargs: dict = {"model": model, "messages": messages}
    if response_format is not None:
        kwargs["response_format"] = response_format
    if temperature is not None:
        kwargs["temperature"] = temperature
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


def generate_answer(question: str, context: str,
                    history: Optional[list[dict]] = None,
                    model: str = OPENAI_MODEL,
                    company: Optional[str] = None,
                    coverage: Optional[list[str]] = None) -> str:
    """논스트리밍 답변 생성."""
    resp = chat_create(
        model=model,
        temperature=OPENAI_TEMPERATURE,
        messages=_build_messages(question, context, history, company, coverage),
    )
    return resp.choices[0].message.content or ""


def stream_answer(question: str, context: str,
                  history: Optional[list[dict]] = None,
                  model: str = OPENAI_MODEL,
                  company: Optional[str] = None,
                  coverage: Optional[list[str]] = None) -> Iterator[str]:
    """스트리밍 답변 생성 (토큰 단위 yield)."""
    stream = chat_create(
        model=model,
        temperature=OPENAI_TEMPERATURE,
        messages=_build_messages(question, context, history, company, coverage),
        stream=True,
    )
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta
