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


def safe_json_loads(raw: str):
    """LLM 응답 JSON 파싱 — 실패 시 코드펜스 제거·잘린 JSON 복구 시도. 최종 실패 시 None.

    response_format=json_object 를 써도 토큰 한도 초과로 응답이 잘리거나(GS 등
    청크 많은 지주회사) 앞뒤에 텍스트가 붙는 경우가 있어 graceful 복구를 시도한다.
    """
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        pass
    s = raw.strip()
    # 코드펜스 제거
    if s.startswith("```"):
        s = s.split("```", 2)[1] if s.count("```") >= 2 else s.lstrip("`")
        if s.startswith("json"):
            s = s[4:]
    # 첫 '{' ~ 마지막 '}' 추출
    i, j = s.find("{"), s.rfind("}")
    if 0 <= i < j:
        try:
            return json.loads(s[i:j + 1])
        except Exception:
            return None
    return None


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
        # 발행/자기주식수는 표(table) 형태가 핵심 — 텍스트 키워드보다 높게 가중
        if score > 0 and c.get("kind") == "table":
            score += 20
        # 우선주만 있고 보통주 언급 없는 청크는 패널티 (오추출 방지)
        if "우선주" in text and "보통주" not in text:
            score = max(0, score - 50)
        if score > 0:
            scored.append((score, c))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:max_chunks]]


def _mirror_shares_to_db(ticker: str, year: int, data: dict) -> None:
    """shares 결과를 DB(shares 테이블)에 미러 — 멱등 upsert.

    파일 캐시(shares_*.json)가 원본이고 DB 는 SQL 질의·일관성용 미러.
    common_float 미산출이면 적재 안 함. 실패해도 파일이 원본이라 무해.
    """
    try:
        if not data or data.get("common_float") is None:
            return
        from valuation_engine import db
        db.save_shares(ticker, year, data)
    except Exception:
        pass


def fetch_shares_via_rag(ticker: str, name: str, year: int,
                          market: str = "KOSPI",
                          model: str = "gpt-4o-mini",
                          verbose: bool = False,
                          use_cache: bool = True) -> dict:
    """발행/자기주식수 RAG — 사업보고서 단위(ticker+year) 캐시 래퍼.

    발행/자기주식수는 사업보고서 신규 공시 전까지 불변 → eval_date 무관 캐시.
    캐시 hit: LLM 호출 0. miss: _impl 호출 후 저장.
    """
    cache_dir = _VAR_ROOT / "data" / "rag_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"shares_{ticker}_{year}.json"
    if use_cache and cache_path.exists():
        try:
            with cache_path.open("r", encoding="utf-8") as f:
                cached = json.load(f)
            if verbose:
                print(f"   [주식수 RAG] 캐시 hit ({ticker}_{year}): "
                      f"유통 {cached.get('common_float'):,}")
            _mirror_shares_to_db(ticker, year, cached)   # DB 미러 백필(멱등)
            return cached
        except Exception:
            pass
    result = _fetch_shares_via_rag_impl(ticker, name, year, market, model, verbose)
    try:
        with cache_path.open("w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    _mirror_shares_to_db(ticker, year, result)           # DB write-through
    return result


def _fetch_shares_via_rag_impl(ticker: str, name: str, year: int,
                          market: str = "KOSPI",
                          model: str = "gpt-4o-mini",
                          verbose: bool = False) -> dict:
    """사업보고서 청크에서 RAG + LLM(GPT-4o-mini)으로 발행/자기주식수 추출.

    명세서 §A-5: E = T일 보통주 종가 × (보통주 발행주식 총수 − 자기주식수)

    임의값 절대 금지 — LLM 응답에서 null 또는 추출 실패 시 RuntimeError.
    """
    try:
        from openai import OpenAI
    except ImportError as e:
        raise RuntimeError(
            "openai 패키지가 필요합니다: pip install openai"
        ) from e

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("환경변수 'OPENAI_API_KEY' 가 설정되어 있지 않습니다.")

    # 1) chroma 의미 검색 우선 (BGE-M3 임베딩 활용)
    relevant = []
    chroma_used = False
    try:
        from embedding.retrieval import retrieve_for_keyword
        chunks = retrieve_for_keyword(
            keywords=list(_SHARES_KEYWORDS) + ["주식의 총수", "발행주식 총수", "자기주식"],
            ticker=ticker, year=year, top_k=15,
        )
        if chunks:
            # chroma 결과 → 기존 청크 형식으로 변환
            for c in chunks:
                md = c.get("metadata", {}) or {}
                relevant.append({
                    "text":              c.get("text", ""),
                    "section_path_str":  md.get("section_path_str", md.get("section_main", "")),
                    "kind":              md.get("kind", ""),
                    "similarity":        c.get("similarity", 0),
                })
            chroma_used = True
            if verbose:
                print(f"   [RAG/chroma] 의미검색 {len(relevant)}개 청크")
    except Exception as e:
        if verbose:
            print(f"   [RAG/chroma] 검색 실패 ({e}) — jsonl fallback")

    # 2) chroma 결과 없으면 jsonl 키워드 필터 fallback
    if not relevant:
        chunks_path = _find_chunks_file(ticker, year, market)
        if verbose:
            print(f"   [RAG/jsonl] 청크 파일: {chunks_path.name}")
        all_chunks = _load_chunks(chunks_path)
        if not all_chunks:
            raise RuntimeError(f"청크 파일이 비어있음: {chunks_path}")
        relevant = _filter_relevant_chunks(all_chunks)
        if not relevant:
            raise RuntimeError(
                f"{name} 청크 {len(all_chunks)}개 중 주식 총수 관련 청크 없음 "
                f"(chroma·jsonl 모두 실패)"
            )
        if verbose:
            print(f"   [RAG/jsonl] 키워드 필터 {len(relevant)}개")

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

    # 4) LLM 호출 — GPT-4o-mini (response_format=json_object 강제)
    client = OpenAI(api_key=api_key)
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

    # 5) JSON 파싱 + 검증 — 잘린 응답 복구 시도 (주식수는 필수 데이터 → 복구 실패 시 에러)
    result = safe_json_loads(raw)
    if result is None:
        raise RuntimeError(f"LLM 응답이 JSON이 아님 (복구 실패): {raw[:300]}")

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

    # ── 출력 검산 (LLM 환각 차단) ──────────────────────────────
    # (a) 발행주식수 합리 범위 — 한국 상장사 통상 10만 ~ 100억주
    if not (100_000 <= issued <= 10_000_000_000):
        raise RuntimeError(
            f"[{name}] 발행주식 총수 {issued:,} 가 합리 범위(10만~100억주) 밖 — "
            f"LLM 오추출 의심. 응답: {raw}"
        )
    # (b) 자기주식 음수 불가 + 발행주식 초과 불가
    if treasury < 0:
        raise RuntimeError(f"[{name}] 자기주식수 음수: {treasury:,}")
    if treasury >= issued:
        raise RuntimeError(
            f"[{name}] 자기주식({treasury:,}) ≥ 발행주식({issued:,}) — "
            f"LLM 오추출(우선주 혼입 등) 의심. 응답: {raw}"
        )

    # 메타데이터 — chroma 분기 / jsonl 분기 모두 안전
    first_chunk = relevant[0] if relevant else {}
    return {
        "common_issued":   issued,
        "common_treasury": treasury,
        "common_float":    issued - treasury,   # 검산 통과 → 항상 양수
        "corp_code":       first_chunk.get("corp_code"),   # chroma metadata 또는 jsonl 청크 필드
        "rcept_no":        first_chunk.get("rcept_no"),
        "source":          f"RAG (chroma·jsonl) + LLM({model})",
        "source_quote":    result.get("source_quote", ""),
        "confidence":      result.get("confidence", "medium"),
    }



def fetch_close_from_cache(ticker: str, market: str, eval_date: date,
                           max_lookback: int = 7) -> tuple[float, date]:
    """밸류에이션용 종가 — eval_date '당일 종가'를 KRX 라이브 fetch(매일 갱신).
    실패 시 peer_beta 주간 패널 캐시(직전 영업일)로 폴백.

    ※ 베타 회귀분석은 주간 종가 패널(fetch_stock_weekly)을 별도로 사용한다.
      이 함수는 평가 시점 '현재가/시가총액(E)/상승여력'용이므로 매일 최신이어야 하며,
      주간 스냅샷만 읽던 기존 방식(최대 ~1주 지연)을 당일 라이브 조회로 교체했다.
    """
    # 1) 당일(직전영업일 포함) 종가 라이브 조회 + 당일 스냅샷 캐싱 → 매일 갱신
    try:
        from peer_beta.krx_client import fetch_stock_close
        cp = fetch_stock_close(ticker, market, eval_date, max_lookback=max_lookback)
        if cp is not None and getattr(cp, "close", 0) and cp.close > 0:
            return float(cp.close), cp.actual_date
    except Exception:
        pass
    # 2) 폴백 — 기존 주간 패널 캐시에서 직전 영업일 종가
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
    """피어 보통주 시가총액 계산.

    실데이터만 사용 - 사업보고서 RAG 로 발행/자기주식수 추출 (OpenAI 필수).
    추출 실패 시 RuntimeError 발생 (임의값 절대 사용 안 함).
    """
    eval_d = parse_date(eval_date)

    # 팀원 XBRL 경로 sys.path 추가 (xbrl_financials_v4 의존성)
    sys.path.insert(0, str(_VAR_ROOT / "XBRL"))

    out: dict = {"as_of_date": eval_d.isoformat(),
                 "fiscal_year_shares": fiscal_year,
                 "companies": {}}

    def _process(comp: dict):
        """회사 1개 — 종가(파일) + 발행/자기주식 RAG(LLM). 회사들 간 독립 → 병렬."""
        name = comp["name"]
        close, actual_date = fetch_close_from_cache(
            comp["ticker"], comp["market"], eval_d)
        shares = fetch_shares_via_rag(
            ticker=comp["ticker"], name=name, year=fiscal_year,
            market=comp["market"], verbose=verbose)
        E = close * shares["common_float"]
        rec = {
            "ticker": comp["ticker"], "market": comp["market"],
            "corp_code": shares.get("corp_code"), "rcept_no": shares.get("rcept_no"),
            "close_price": close, "close_date": actual_date.isoformat(),
            "common_issued":   shares["common_issued"],
            "common_treasury": shares["common_treasury"],
            "common_float":    shares["common_float"],
            "shares_source":   shares["source"],
            "shares_quote":    shares.get("source_quote", ""),
            "shares_confidence": shares.get("confidence", ""),
            "E_market_cap":    E,
        }
        return name, rec

    # ★ LLM 병렬 (속도): 발행/자기주식 RAG 추출은 회사별 독립 OpenAI 호출.
    from concurrent.futures import ThreadPoolExecutor
    workers = max(1, min(5, len(ALL_COMPANIES)))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="equity") as ex:
        futs = {ex.submit(_process, comp): comp for comp in ALL_COMPANIES}
        results = {}
        for fut, comp in futs.items():
            name, rec = fut.result()   # 실패 시 예외 전파(임의값 금지 정책 유지)
            results[comp["name"]] = rec
    # config 순서 보존
    for comp in ALL_COMPANIES:
        if comp["name"] in results:
            out["companies"][comp["name"]] = results[comp["name"]]
            if verbose:
                rec = results[comp["name"]]
                print(f"[{comp['name']}] E = ₩{rec['E_market_cap']/1e12:.3f}조  "
                      f"유통 {rec['common_float']:,}  [{rec['shares_source']}]")

    # ── write-through: market_snapshot (병렬 종료 후 일괄 저장 → SQLite 락 회피) ──
    # 읽기는 fetch_close(라이브) 유지 → 매일 갱신 불변. DB 는 종가·시총 이력 기록용.
    try:
        from valuation_engine import db as _db
        _snap = [{"stock_code": str(r.get("ticker")).zfill(6),
                  "snap_date":  r.get("close_date") or eval_d.isoformat(),
                  "close":      r.get("close_price"),
                  "mktcap":     r.get("E_market_cap"),
                  "shares":     r.get("common_float"),
                  "market":     r.get("market")}
                 for r in out["companies"].values() if r.get("close_price")]
        if _snap:
            _db.save_market_snapshot(_snap)
    except Exception:
        pass

    # 저장 — ticker 포함 (회사별 분리, stale 혼입 방지)
    from .config import TARGET as _TARGET
    tag = eval_d.strftime("%Y%m%d")
    path = EQUITY_DIR / f"peers_equity_{_TARGET['ticker']}_{tag}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    # 호환성 — 옛 파일명도 동시 저장 (이전 모듈 호환)
    alias = EQUITY_DIR / f"peers_equity_{tag}.json"
    with alias.open("w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    if verbose:
        print(f"\n저장: {path}")
    return out


def load_latest(ticker: Optional[str] = None,
                eval_date: Optional[date] = None) -> dict:
    """E 결과 로드 — ticker+eval_date 우선, 없으면 최신 파일.

    Args:
        ticker:    명시 시 valuation_<ticker>_*.json 만 검색
        eval_date: 명시 시 그 날짜 파일 우선
    """
    # 1) ticker + eval_date 명시 → 정확 매칭
    if ticker and eval_date:
        tag = eval_date.strftime("%Y%m%d") if not isinstance(eval_date, str) else eval_date.replace("-", "")
        exact = EQUITY_DIR / f"peers_equity_{ticker}_{tag}.json"
        if exact.exists():
            with exact.open("r", encoding="utf-8") as f:
                return json.load(f)

    # 2) ticker 만 명시 → 그 ticker 의 최신
    if ticker:
        candidates = sorted(EQUITY_DIR.glob(f"peers_equity_{ticker}_*.json"))
        if candidates:
            with candidates[-1].open("r", encoding="utf-8") as f:
                return json.load(f)

    # 3) eval_date 만 명시 → 그 날짜 (옛 호환 파일명)
    if eval_date:
        tag = eval_date.strftime("%Y%m%d") if not isinstance(eval_date, str) else eval_date.replace("-", "")
        old = EQUITY_DIR / f"peers_equity_{tag}.json"
        if old.exists():
            with old.open("r", encoding="utf-8") as f:
                return json.load(f)

    # 4) Fallback — 가장 최근
    candidates = sorted(EQUITY_DIR.glob("peers_equity_*.json"))
    if not candidates:
        raise FileNotFoundError("E 결과가 없습니다. compute_all() 먼저 실행.")
    with candidates[-1].open("r", encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    compute_all(verbose=True)
