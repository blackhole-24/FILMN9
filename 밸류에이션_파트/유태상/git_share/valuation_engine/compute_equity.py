"""Phase 2-A — 피어 4사 보통주 시가총액(E) 산출.

데이터 소스:
  - T일 종가         : peer_beta/data/raw/stock_KOSPI_<T>.json (KRX 캐시 재사용)
  - 발행/자기주식수  : DART stockTotqyRqSttus 엔드포인트

산식:
  E = T일 보통주 종가 × (보통주 발행주식수 − 자기주식수)
  우선주 제외 (보통주만)
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Optional

import requests

_VAR_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_VAR_ROOT))

from peer_beta.calendar_utils import previous_business_day_candidates, as_yyyymmdd, parse_date
from peer_beta.config import RAW_DIR as PEER_BETA_RAW

from .config import ALL_COMPANIES, EQUITY_DIR, ENV_KEY_DART, FISCAL_YEARS

DART_BASE = "https://opendart.fss.or.kr/api"


def _dart_key() -> str:
    key = os.getenv(ENV_KEY_DART)
    if not key:
        raise RuntimeError(f"환경변수 '{ENV_KEY_DART}' 가 설정되어 있지 않습니다.")
    return key


# ─────────────────────────────────────────────────────────────────────
# 사업보고서 RAG + LLM (ChatGPT 4o-mini) — 보통주 발행/자기주식수 추출
#
# XBRL 재무제표에는 주식 총수 정보가 들어 있지 않음.
# 사업보고서 본문 "I. 회사의 개요 → 4. 주식의 총수" 표에서 RAG로 추출.
#
# 청크 파일: VAR/<market>/<ticker>_<corp_name>_<year>_annual_chunks.jsonl
#   각 줄 = {"text": "...", "section_path_str": "...", "kind": "table"|"text", ...}
#
# LLM: gpt-4o-mini (response_format=json_object 강제)
# ─────────────────────────────────────────────────────────────────────

_SHARES_KEYWORDS = [
    "주식의 총수", "주식총수", "발행주식", "발행한 주식",
    "자기주식", "유통주식", "보통주", "현재까지 발행",
]

_RAG_SYSTEM_PROMPT = """당신은 한국 사업보고서를 정확히 읽고 데이터를 추출하는 분석가입니다.
- 임의 추정 절대 금지. 본문에 없는 숫자는 null로 반환.
- 단위: 주 (예: 58,492,759주 → 58492759)
- 보통주(또는 기명식 보통주식)만 사용. 우선주는 제외.
- 자기주식은 보통주 자기주식만 (우선주 자기주식 제외).
- "보통주식", "기명식 보통주식", "의결권 있는 보통주" 모두 보통주로 간주.
응답은 반드시 다음 JSON 스키마 그대로:
{
  "common_issued":   <보통주 발행주식 총수, 정수>,
  "common_treasury": <보통주 자기주식수, 정수, 없으면 0>,
  "common_float":    <유통주식수 = 발행 − 자기주식, 정수>,
  "source_quote":    "<원문 인용 50자 이내>",
  "confidence":      "high" | "medium" | "low"
}"""


def _find_chunks_file(ticker: str, year: int, market: str = "KOSPI") -> Path:
    """청크 jsonl 파일 경로 검색."""
    patterns = [
        _VAR_ROOT / market / f"{ticker}_*_{year}_annual_chunks*.jsonl",
        _VAR_ROOT / "KOSPI" / f"{ticker}_*_{year}_annual_chunks*.jsonl",
        _VAR_ROOT / "KOSDAQ" / f"{ticker}_*_{year}_annual_chunks*.jsonl",
    ]
    for p in patterns:
        # glob
        hits = list(p.parent.glob(p.name))
        if hits:
            # _v3 같은 변형 있으면 가장 최신 (이름 기준 정렬 후 마지막)
            return sorted(hits)[-1]
    raise FileNotFoundError(
        f"청크 파일을 찾을 수 없음: ticker={ticker}, year={year}\n"
        f"  검색 위치: {_VAR_ROOT}/KOSPI|KOSDAQ/{ticker}_*_{year}_annual_chunks*.jsonl"
    )


def _load_chunks(path: Path) -> list[dict]:
    """jsonl 청크 파일 로드."""
    out = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _filter_relevant_chunks(chunks: list[dict],
                            keywords: list[str] = _SHARES_KEYWORDS,
                            max_chunks: int = 25) -> list[dict]:
    """주식 총수 관련 키워드를 포함한 청크만 필터링.

    추가 우선순위:
      1) section_path_str 에 "주식의 총수" 포함 — 가장 강함
      2) text 에 "주식의 총수" 또는 "발행주식" 포함
      3) kind == "table" 우선 (표가 핵심)
    """
    scored = []
    for c in chunks:
        text = c.get("text", "") or ""
        section = c.get("section_path_str", "") or ""

        score = 0
        if "주식의 총수" in section or "주식 총수" in section:
            score += 100
        for kw in keywords:
            if kw in text:
                score += 5
            if kw in section:
                score += 10
        if score > 0 and c.get("kind") == "table":
            score += 3
        if score > 0:
            scored.append((score, c))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:max_chunks]]


def fetch_shares_via_rag(ticker: str, name: str, year: int,
                          market: str = "KOSPI",
                          model: str = "gpt-4o-mini",
                          verbose: bool = False) -> dict:
    """사업보고서 청크에서 RAG + LLM으로 발행/자기주식수 추출.

    명세서 §A-5: E = T일 보통주 종가 × (보통주 발행주식 총수 − 자기주식수)

    임의값 절대 금지 — LLM 응답에서 null 또는 추출 실패 시 RuntimeError.
    """
    try:
        import openai
    except ImportError as e:
        raise RuntimeError(
            "openai 패키지가 필요합니다: pip install openai"
        ) from e

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("환경변수 'OPENAI_API_KEY' 가 설정되어 있지 않습니다.")

    # 1) 청크 파일 검색·로드
    chunks_path = _find_chunks_file(ticker, year, market)
    if verbose:
        print(f"   [RAG] 청크 파일: {chunks_path.name}")
    all_chunks = _load_chunks(chunks_path)
    if not all_chunks:
        raise RuntimeError(f"청크 파일이 비어있음: {chunks_path}")

    # 2) 관련 청크 필터링
    relevant = _filter_relevant_chunks(all_chunks)
    if not relevant:
        raise RuntimeError(
            f"{name} 청크 {len(all_chunks)}개 중 주식 총수 관련 청크가 없음. "
            f"키워드: {_SHARES_KEYWORDS}"
        )
    if verbose:
        print(f"   [RAG] 관련 청크 {len(relevant)}개 추출 (전체 {len(all_chunks)}개 중)")

    # 3) LLM 컨텍스트 구성
    context_lines = []
    for i, c in enumerate(relevant, 1):
        sec = c.get("section_path_str", "")
        kind = c.get("kind", "")
        context_lines.append(f"[청크 {i}] section={sec} kind={kind}\n{c.get('text', '')}")
    context = "\n\n---\n\n".join(context_lines)

    user_prompt = (
        f"회사: {name} ({ticker})\n"
        f"회계연도: FY{year}\n\n"
        f"아래 청크에서 보통주 발행주식 총수와 자기주식수를 추출하세요.\n"
        f"===\n{context}\n===\n\n"
        f"JSON으로만 응답:"
    )

    # 4) LLM 호출
    client = openai.OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _RAG_SYSTEM_PROMPT},
            {"role": "user",   "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    raw = response.choices[0].message.content
    if verbose:
        print(f"   [RAG] LLM 응답: {raw[:200]}...")

    # 5) JSON 파싱 + 검증
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"LLM 응답이 JSON이 아님: {raw}") from e

    issued = result.get("common_issued")
    treasury = result.get("common_treasury")

    if issued is None or not isinstance(issued, (int, float)) or issued <= 0:
        raise RuntimeError(
            f"[{name}] LLM이 보통주 발행주식 총수를 추출하지 못함 (null 또는 0).\n"
            f"  응답: {raw}\n"
            f"  청크 파일을 확인하거나 키워드/프롬프트를 보완하세요."
        )
    issued = int(issued)
    treasury = int(treasury) if treasury is not None else 0

    return {
        "common_issued":   issued,
        "common_treasury": treasury,
        "common_float":    max(issued - treasury, 0),
        "corp_code":       (all_chunks[0].get("corp_code") if all_chunks else None),
        "rcept_no":        (all_chunks[0].get("rcept_no") if all_chunks else None),
        "source":          f"RAG({chunks_path.name}) + LLM({model})",
        "source_quote":    result.get("source_quote", ""),
        "confidence":      result.get("confidence", "medium"),
    }


# 하위 호환 — 기존 fetch_shares 시그니처 유지 (corp_code 인자는 무시)
def fetch_shares(corp_code: str, year: int) -> dict:
    """[Deprecated] DART API 대신 KRX 캐시 사용. 호환성 위해 시그니처만 유지.

    실제로는 compute_all() 에서 fetch_shares_from_krx() 를 직접 호출.
    """
    raise NotImplementedError(
        "fetch_shares() 는 더 이상 사용하지 않음. "
        "fetch_shares_from_krx(ticker, market, eval_date) 사용."
    )


def fetch_close_from_cache(ticker: str, market: str, eval_date: date,
                           max_lookback: int = 7) -> tuple[float, date]:
    """peer_beta 캐시에서 T일 종가 가져옴. 없으면 직전 영업일."""
    for cand in previous_business_day_candidates(eval_date, max_lookback):
        cache_path = PEER_BETA_RAW / f"stock_{market}_{as_yyyymmdd(cand)}.json"
        if not cache_path.exists():
            continue
        with cache_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        for row in data.get("OutBlock_1", []):
            code = (row.get("ISU_SRT_CD") or row.get("ISU_CD") or "")
            if len(code) == 12 and code.upper().startswith("KR"):
                code = code[3:9]
            if code.zfill(6) == ticker.zfill(6):
                close = float(str(row.get("TDD_CLSPRC", "0")).replace(",", ""))
                if close > 0:
                    return close, cand
    raise RuntimeError(f"{ticker} ({market}) 종가를 peer_beta 캐시에서 찾을 수 없음. "
                       f"먼저 peer_beta.run_beta 실행 필요.")


def compute_all(eval_date: Optional[date] = None,
                fiscal_year: int = max(FISCAL_YEARS),
                verbose: bool = True) -> dict:
    """4사 보통주 시가총액 계산."""
    eval_d = parse_date(eval_date)

    # 팀원 XBRL 결과에서 corp_code 가져오기
    sys.path.insert(0, str(_VAR_ROOT / "XBRL"))
    from xbrl_financials_v4 import get_corp_code

    out: dict = {"as_of_date": eval_d.isoformat(),
                 "fiscal_year_shares": fiscal_year,
                 "companies": {}}

    for comp in ALL_COMPANIES:
        name = comp["name"]
        if verbose:
            print(f"\n[{name}] {comp['ticker']} ({comp['market']})")

        # 1) 보통주 종가 (peer_beta 캐시에서)
        close, actual_date = fetch_close_from_cache(
            comp["ticker"], comp["market"], eval_d)

        # 2) 발행/자기주식수 — 사업보고서 청크 RAG + ChatGPT 4o-mini 추출
        shares = fetch_shares_via_rag(
            ticker=comp["ticker"],
            name=name,
            year=fiscal_year,
            market=comp["market"],
            verbose=verbose,
        )

        # 3) E 산출 = 종가 × (발행 − 자기주식)
        E = close * shares["common_float"]

        out["companies"][name] = {
            "ticker": comp["ticker"],
            "market": comp["market"],
            "corp_code": shares.get("corp_code"),
            "rcept_no":  shares.get("rcept_no"),
            "close_price": close,
            "close_date":  actual_date.isoformat(),
            "common_issued":   shares["common_issued"],
            "common_treasury": shares["common_treasury"],
            "common_float":    shares["common_float"],
            "shares_source":   shares["source"],
            "shares_quote":    shares.get("source_quote", ""),
            "shares_confidence": shares.get("confidence", ""),
            "E_market_cap":    E,                # 보통주 시총 (원)
        }

        if verbose:
            print(f"   종가({actual_date}) ₩{close:,.0f}")
            print(f"   발행 {shares['common_issued']:,} − "
                  f"자기 {shares['common_treasury']:,} = "
                  f"유통 {shares['common_float']:,}")
            print(f"   confidence={shares.get('confidence')}  "
                  f"인용=\"{shares.get('source_quote', '')[:60]}\"")
            print(f"   E = ₩{E/1e12:.3f}조  [{shares['source']}]")

    # 저장
    path = EQUITY_DIR / f"peers_equity_{eval_d.strftime('%Y%m%d')}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    if verbose:
        print(f"\n저장: {path}")
    return out


def load_latest() -> dict:
    candidates = sorted(EQUITY_DIR.glob("peers_equity_*.json"))
    if not candidates:
        raise FileNotFoundError("E 결과가 없습니다. compute_all() 먼저 실행.")
    with candidates[-1].open("r", encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    compute_all(verbose=True)
