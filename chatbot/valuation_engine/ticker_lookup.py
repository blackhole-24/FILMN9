"""사용자 입력 (종목명 또는 티커) → 정규화된 (ticker, corp_name, market) 튜플.

지원 입력 형식:
  - 6자리 티커: "000720"
  - 회사명:    "현대건설"
  - 회사명 + 주식종류: "현대건설보통주" (suffix 자동 제거)
  - 부분 일치: "현대건" → "현대건설" + 유사 후보 제시
  - 공백/하이픈: "삼성 전자" → "삼성전자"

데이터 소스:
  - 1차: 사업보고서 청크 파일명 (VAR/KOSPI, KOSDAQ) — 임베딩 안 됐어도 가능
  - 2차: KRX OpenAPI (선택, 정확한 시장 구분에 사용)
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from functools import lru_cache
from typing import Optional


_VAR_ROOT = Path(__file__).resolve().parent.parent
_KOSPI_DIR  = _VAR_ROOT / "KOSPI"
_KOSDAQ_DIR = _VAR_ROOT / "KOSDAQ"

# 주식 종류 suffix (회사명 정규화용)
_SUFFIX_RE = re.compile(r"(보통주|우선주|1우B|1우|2우B|2우|종류우선주|전환우선주)$")

# 한글/영문/별칭 정규화 매핑 (사용자 친화)
# 입력 정규화 후 매칭 단계에서 적용. 양방향 보장 (한글→영문, 영문→한글 모두).
_BRAND_ALIASES = {
    # IT/통신/플랫폼
    "네이버": "NAVER",
    "naver": "NAVER",
    "다음카카오": "카카오",
    "kakao": "카카오",
    "에스케이텔레콤": "SK텔레콤",
    "skt": "SK텔레콤",
    "케이티": "KT",
    "엘지유플러스": "LG유플러스",
    "lguplus": "LG유플러스",
    "케이티엔지": "KT&G",
    "ktng": "KT&G",
    "kt&g": "KT&G",

    # 정유/화학
    "에쓰오일": "S-Oil",
    "에스오일": "S-Oil",
    "soil": "S-Oil",
    "엘지화학": "LG화학",
    "엘지전자": "LG전자",
    "엘지생활건강": "LG생활건강",
    "엘지이노텍": "LG이노텍",
    "엘지에너지솔루션": "LG에너지솔루션",
    "엘지디스플레이": "LG디스플레이",
    "엘지": "LG",

    # 반도체/IT 하드웨어
    "에스케이하이닉스": "SK하이닉스",
    "skhynix": "SK하이닉스",
    "삼성에스디아이": "삼성SDI",
    "samsungsdi": "삼성SDI",
    "삼성이엔에이": "삼성E&A",
    "samsung": "삼성전자",

    # 자동차/조선
    "기아자동차": "기아",
    "현대자동차": "현대차",
    "에이치디현대중공업": "HD현대중공업",
    "현대중공업": "HD현대중공업",
    "한화에어로": "한화에어로스페이스",

    # 식음료
    "씨제이제일제당": "CJ제일제당",
    "cj제일제당": "CJ제일제당",
    "롯데칠성": "롯데칠성음료",

    # 엔터/게임
    "에이치와이비이": "하이브",
    "hybe": "하이브",
    "에스엠엔터": "에스엠",
    "와이지엔터": "와이지엔터테인먼트",
    "제이와이피": "JYP엔터",
    "엔씨": "엔씨소프트",
    "ncsoft": "엔씨소프트",

    # 금융
    "케이비금융": "KB금융",
    "케이비국민은행": "KB금융",
    "케이비": "KB금융",
    "신한금융": "신한지주",
    "신한은행": "신한지주",
    "하나금융": "하나금융지주",
    "하나은행": "하나금융지주",
    "우리금융": "우리금융지주",
    "우리은행": "우리금융지주",
    "ibk": "기업은행",

    # 바이오/제약
    "삼성바이오": "삼성바이오로직스",
    "셀트리온헬스": "셀트리온헬스케어",
}


def _apply_alias(name: str) -> str:
    """별칭 정규화 — 입력 회사명을 표준 회사명으로 변환."""
    if not name:
        return name
    lower = name.lower()
    if lower in _BRAND_ALIASES:
        return _BRAND_ALIASES[lower]
    if name in _BRAND_ALIASES:
        return _BRAND_ALIASES[name]
    return name


def normalize_corp_name(name: str) -> str:
    """회사명 정규화 — 공백 제거 + 주식종류 suffix 제거 + 유니코드 정규화."""
    if not name:
        return ""
    # 유니코드 정규화 (전각·반각 차이 통일)
    n = unicodedata.normalize("NFKC", name)
    # 영문 대소문자 통일 (sk하이닉스 ↔ SK하이닉스 동일 취급; suffix 는 한글이라 무관)
    n = n.upper()
    # 공백·하이픈 제거
    n = re.sub(r"[\s\-_]+", "", n).strip()
    # suffix 제거
    n = _SUFFIX_RE.sub("", n)
    return n


@lru_cache(maxsize=1)
def _load_krx_desc_companies() -> list[dict]:
    """krx_desc.csv → 전종목 매핑 (청크 jsonl 없는 종목도 매칭 가능).

    Returns:
        [{"ticker", "corp_name_raw", "corp_name", "market": "(unknown)",
          "year": None, "has_chunk": False, "krx_industry": "..."}]
    """
    csv_path = _VAR_ROOT / "krx_desc.csv"
    if not csv_path.exists():
        return []
    try:
        import pandas as pd
        df = pd.read_csv(csv_path, encoding="utf-8-sig")
    except Exception:
        return []

    if "Code" not in df.columns or "Name" not in df.columns:
        return []

    out = []
    for _, r in df.iterrows():
        ticker = str(r["Code"]).zfill(6)
        name_raw = str(r["Name"])
        if not name_raw or name_raw in ("nan", "None"):
            continue
        out.append({
            "ticker":        ticker,
            "corp_name_raw": name_raw,
            "corp_name":     normalize_corp_name(name_raw),
            "market":        "(unknown)",   # krx_desc.csv 에 시장 컬럼 없음
            "year":          None,
            "has_chunk":     False,         # ★ 청크 없음 표시
            "krx_industry":  str(r.get("Industry", "")),
        })
    return out


@lru_cache(maxsize=1)
def _scan_chunk_files() -> list[dict]:
    """KOSPI/KOSDAQ 폴더의 청크 jsonl 파일명에서 매핑 추출.

    파일명 패턴: <ticker>_<corp_name>_<year>_annual_chunks*.jsonl

    Returns:
        [{"ticker": "000720", "corp_name_raw": "현대건설보통주",
          "corp_name": "현대건설", "market": "KOSPI", "year": 2025}, ...]
    """
    out = []
    seen = set()    # (ticker) 중복 방지 (다양 연도가 있어도 ticker 1개 행)

    for market, d in [("KOSPI", _KOSPI_DIR), ("KOSDAQ", _KOSDAQ_DIR)]:
        if not d.exists():
            continue
        # Phase 7: 연도 내림차순 정렬 → ticker 별 첫(=최신) 매칭 유지 (glob 비결정 순서 보정).
        #   파일명 끝이 연도라 reverse 정렬 시 같은 ticker 는 최신연도가 먼저 온다.
        for p in sorted(d.glob("*_annual_chunks*.jsonl"), reverse=True):
            # 파일명에서 추출 — 예: "000720_현대건설보통주_2025_annual_chunks.jsonl"
            stem = p.stem    # 확장자 제외
            # _v3 같은 suffix 제거
            stem = re.sub(r"_v\d+$", "", stem)
            # _annual_chunks 제거
            stem = stem.replace("_annual_chunks", "")
            parts = stem.split("_", 2)    # ticker, corp_name, year
            if len(parts) < 3:
                continue
            ticker = parts[0]
            year_str = parts[-1]
            try:
                year = int(year_str)
            except ValueError:
                continue
            # corp_name = ticker 와 year 사이 (공백 _ 있을 수 있음)
            corp_raw = stem[len(ticker)+1 : -(len(year_str)+1)]

            if ticker in seen:
                # 가장 큰 연도만 유지
                continue
            seen.add(ticker)

            out.append({
                "ticker":         ticker,
                "corp_name_raw":  corp_raw,
                "corp_name":      normalize_corp_name(corp_raw),
                "market":         market,
                "year":           year,
            })
    return out


def lookup(user_input: str, max_suggestions: int = 5) -> dict:
    """사용자 입력 → 매칭 결과.

    Returns:
        {
            "status": "exact" | "ambiguous" | "not_found",
            "match":  {ticker, corp_name, market, year} or None,
            "suggestions": [최대 N개 후보 — ambiguous/not_found 시],
            "input_normalized": "정규화된 입력 (디버깅용)",
        }
    """
    if not user_input or not user_input.strip():
        return {"status": "not_found", "match": None, "suggestions": [],
                "input_normalized": ""}

    raw = user_input.strip()
    # ★ B 옵션: 청크 jsonl + krx_desc.csv (전종목) 결합 — 청크 없는 종목도 매칭 가능
    chunk_companies = _scan_chunk_files()
    krx_companies = _load_krx_desc_companies()

    # 청크 보유 ticker 집합 (has_chunk 표시 위함)
    chunk_tickers = {c["ticker"] for c in chunk_companies}

    # 합치기: 청크 있는 회사 우선, krx_desc 의 나머지는 has_chunk=False 로 추가.
    # ★ 사명변경 대응: 같은 ticker 라도 청크(구명, 예 '현대중공업')와 krx_desc(신명,
    #   'HD현대중공업')의 이름이 다르면 둘 다 매칭 후보로 추가 → 신·구 회사명 모두 검색 가능.
    all_companies = list(chunk_companies)
    for c in chunk_companies:
        c.setdefault("has_chunk", True)
    chunk_name_by_ticker = {c["ticker"]: c["corp_name"] for c in chunk_companies}
    for kc in krx_companies:
        if (kc["ticker"] not in chunk_tickers
                or kc["corp_name"] != chunk_name_by_ticker.get(kc["ticker"])):
            all_companies.append(kc)

    if not all_companies:
        return {"status": "not_found", "match": None, "suggestions": [],
                "input_normalized": raw,
                "note": "청크 파일·krx_desc.csv 모두 없음"}

    # 1) 6자리 숫자 — ticker 매칭
    if re.fullmatch(r"\d{6}", raw):
        for c in all_companies:
            if c["ticker"] == raw:
                return {"status": "exact", "match": c, "suggestions": [],
                        "input_normalized": raw}
        return {"status": "not_found", "match": None, "suggestions": [],
                "input_normalized": raw,
                "note": f"{raw} ticker 청크 파일 없음"}

    # 2) 회사명 — 정규화 + 별칭 매핑 후 정확 매칭
    normed = normalize_corp_name(raw)
    # ★ 별칭 정규화 (네이버 → NAVER 등)
    aliased = _apply_alias(normed)
    if aliased != normed:
        exact_alias = [c for c in all_companies if c["corp_name"] == aliased]
        if len(exact_alias) == 1:
            return {"status": "exact", "match": exact_alias[0], "suggestions": [],
                    "input_normalized": aliased,
                    "note": f"별칭 매핑: '{normed}' → '{aliased}'"}
    exact = [c for c in all_companies if c["corp_name"] == normed]
    if len(exact) == 1:
        return {"status": "exact", "match": exact[0], "suggestions": [],
                "input_normalized": normed}
    if len(exact) > 1:
        # 동명회사 (KOSPI/KOSDAQ 양쪽 등) — 모두 제시
        return {"status": "ambiguous", "match": None,
                "suggestions": exact[:max_suggestions],
                "input_normalized": normed,
                "note": "동명회사 다수 — 시장 명시 필요"}

    # 3) 회사명 — 부분 매칭 (startswith → contains)
    starts = [c for c in all_companies if c["corp_name"].startswith(normed)]
    if starts:
        return {"status": "ambiguous", "match": None,
                "suggestions": starts[:max_suggestions],
                "input_normalized": normed,
                "note": f"\"{raw}\" 로 시작하는 회사 {len(starts)}개 발견"}

    contains = [c for c in all_companies if normed in c["corp_name"]]
    if contains:
        return {"status": "ambiguous", "match": None,
                "suggestions": contains[:max_suggestions],
                "input_normalized": normed,
                "note": f"\"{raw}\" 를 포함하는 회사 {len(contains)}개 발견"}

    # 4) 매칭 실패
    return {"status": "not_found", "match": None, "suggestions": [],
            "input_normalized": normed,
            "note": f"\"{raw}\" 매칭 회사 없음"}


def list_all() -> list[dict]:
    """KOSPI + KOSDAQ 전종목 매핑 반환 (디버깅·통계용)."""
    return _scan_chunk_files()


if __name__ == "__main__":
    # 다양한 입력 테스트
    cases = [
        "000720",
        "현대건설",
        "현대건설보통주",
        "삼양식품",
        "현대건",
        "삼양",
        "999999",
        "존재하지않는회사명",
    ]
    for c in cases:
        r = lookup(c)
        print(f"\n입력: '{c}'  → status={r['status']}")
        if r["match"]:
            m = r["match"]
            print(f"   match: {m['ticker']}  {m['corp_name']}  {m['market']}")
        if r["suggestions"]:
            for s in r["suggestions"]:
                print(f"   ※ {s['ticker']}  {s['corp_name']}  {s['market']}")
        if r.get("note"):
            print(f"   note: {r['note']}")
