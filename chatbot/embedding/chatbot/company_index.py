"""회사명 → ticker 해석.

DB 가 전종목(192만 청크) 통합이라, ticker 필터 없이 자유 질문을 검색하면
여러 회사 결과가 섞여 무의미해진다. 따라서 질문에서 회사를 식별해 ticker 로
좁히는 것이 검색 정확도의 출발점이다.

소스: KOSPI/KOSDAQ 의 *_annual_chunks*.jsonl 각 파일 첫 줄
      (stock_code / corp_name / corp_code / fiscal_period → year).
ChromaDB 전체 스캔(192만 행)보다 빠르고, jsonl 의 corp_name 이 권위 소스.

매칭: rapidfuzz 로 오타·부분명("현대건설" vs "현대건설보통주")에 강건.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from ..config import KOSPI_DIR, KOSDAQ_DIR
from .config import COMPANY_INDEX_PATH, FUZZY_MIN_SCORE, MAX_CANDIDATES

# 주식 종류 suffix (chunk_loader 와 동일 정책) — 정규화해 깔끔한 회사명만 보관
_SUFFIX_RE = re.compile(r"(보통주|우선주|1우B|1우|2우B|2우|종류우선주|전환우선주)$")


def _normalize(name: str) -> str:
    if not name:
        return ""
    return _SUFFIX_RE.sub("", name.strip())


# 라틴 약자 → 한글 발음 (DART 는 HD/LG/SK 등을 한글로 풀어 등록: 에이치디/엘지/에스케이)
_LETTER_KO = {
    "A": "에이", "B": "비", "C": "씨", "D": "디", "E": "이", "F": "에프",
    "G": "지", "H": "에이치", "I": "아이", "J": "제이", "K": "케이", "L": "엘",
    "M": "엠", "N": "엔", "O": "오", "P": "피", "Q": "큐", "R": "알",
    "S": "에스", "T": "티", "U": "유", "V": "브이", "W": "더블유", "X": "엑스",
    "Y": "와이", "Z": "제트",
}
_LATIN_RUN_RE = re.compile(r"[A-Za-z]{2,}")


def _expand_latin(name: str) -> str:
    """이름 속 2글자 이상 라틴 연속을 글자별 한글 발음으로 치환.

    예: "HD현대중공업" → "에이치디현대중공업", "LG화학" → "엘지화학".
    (NAVER·S-Oil 처럼 DART 가 라틴으로 두는 경우는 원본 변형이 따로 매칭됨)
    """
    return _LATIN_RUN_RE.sub(
        lambda m: "".join(_LETTER_KO.get(ch.upper(), ch) for ch in m.group(0)), name)


def _query_variants(name: str) -> list[str]:
    """매칭에 시도할 질의 변형들 (원본 + 라틴→한글 확장)."""
    q = _normalize(name)
    variants = [q]
    exp = _expand_latin(q)
    if exp and exp != q:
        variants.append(exp)
    return variants


# 통칭·약칭 → DART 등록 정식명 별칭 사전.
# _expand_latin 은 라틴→한글(SK하이닉스→에스케이하이닉스)만 처리하므로,
# ① 한글통칭→라틴등록명(엘지화학→LG화학), ② 줄임말(삼전→삼성전자),
# ③ 접미사 다른 동명회사 혼동(현대차→현대자동차, NOT 현대차증권) 을 보완한다.
# 키는 _normalize 적용형. 값은 DB 실재 종목명(검증됨)이라 exact-match 로 즉시 확정된다.
_ALIASES: dict[str, str] = {
    "현대차": "현대자동차",
    "기아차": "기아",
    "네이버": "NAVER",
    "하이닉스": "에스케이하이닉스",
    "엘지화학": "LG화학",
    "엘지전자": "LG전자",
    "엘지에너지솔루션": "LG에너지솔루션",
    "엘지엔솔": "LG에너지솔루션",
    "포스코": "POSCO홀딩스",
    "삼전": "삼성전자",
    "삼바": "삼성바이오로직스",
    "한전": "한국전력",
    "카뱅": "카카오뱅크",
    "KB금융": "KB금융지주",
    "신한금융": "신한지주",
    "하나금융": "하나금융지주",
    "우리금융": "우리금융지주",
    "에스케이텔레콤": "SK텔레콤",
    "삼성에스디아이": "삼성SDI",
}


def _build_from_source() -> dict:
    """jsonl 첫 줄들을 스캔해 회사 인덱스 구성."""
    entries: dict[str, dict] = {}   # ticker -> {ticker, corp_name, corp_code, years}
    files = sorted(KOSPI_DIR.glob("*_annual_chunks*.jsonl")) + \
            sorted(KOSDAQ_DIR.glob("*_annual_chunks*.jsonl"))
    for p in files:
        try:
            with p.open("r", encoding="utf-8") as f:
                first = f.readline().strip()
            if not first:
                continue
            raw = json.loads(first)
        except (OSError, json.JSONDecodeError):
            continue

        ticker = (raw.get("stock_code") or "").strip()
        if not ticker:
            continue
        name = _normalize(raw.get("corp_name", ""))

        # fiscal_period: "2025-annual" → 2025
        year = None
        fp = raw.get("fiscal_period", "")
        if fp:
            try:
                year = int(fp.split("-")[0])
            except (ValueError, IndexError):
                year = None

        e = entries.setdefault(ticker, {
            "ticker": ticker,
            "corp_name": name,
            "corp_code": raw.get("corp_code", ""),
            "years": [],
        })
        if year is not None and year not in e["years"]:
            e["years"].append(year)
        # 동일 ticker 의 더 깔끔한 이름이 나오면 갱신(빈 값 방지)
        if name and not e["corp_name"]:
            e["corp_name"] = name

    for e in entries.values():
        e["years"].sort()
    return {"companies": list(entries.values())}


# 전역 캐시
_INDEX: Optional[dict] = None
_NAME_TO_ENTRY: dict[str, dict] = {}
_NAMES: list[str] = []


def _ensure_loaded(rebuild: bool = False) -> dict:
    """인덱스 로드(없으면 빌드 후 캐싱). 메모리 + 디스크 캐시."""
    global _INDEX, _NAME_TO_ENTRY, _NAMES
    if _INDEX is not None and not rebuild:
        return _INDEX

    if COMPANY_INDEX_PATH.exists() and not rebuild:
        _INDEX = json.loads(COMPANY_INDEX_PATH.read_text(encoding="utf-8"))
    else:
        _INDEX = _build_from_source()
        COMPANY_INDEX_PATH.write_text(
            json.dumps(_INDEX, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    _NAME_TO_ENTRY = {e["corp_name"]: e for e in _INDEX["companies"] if e["corp_name"]}
    _NAMES = list(_NAME_TO_ENTRY.keys())
    return _INDEX


def rebuild_index() -> dict:
    """소스 jsonl 에서 인덱스를 강제 재구성하고 통계 반환."""
    idx = _ensure_loaded(rebuild=True)
    return {"companies": len(idx["companies"]), "path": str(COMPANY_INDEX_PATH)}


def _matched_result(entry: dict) -> dict:
    return {"matched": True, "ticker": entry["ticker"], "corp_name": entry["corp_name"],
            "years": entry["years"], "score": 100.0, "candidates": []}


# 부분문자열 유일 포함 매칭 최소 길이 (사명변경/접두 변형 대응; 짧은 토큰 노이즈 방지)
_CONTAIN_MIN_LEN = 3

# 엔티티 종류 접미사 — 질의에 이게 붙은 별개 법인(예: 현대차+증권)을 동일시하지 않기 위함.
# "현대차" ⊂ "현대차증권" 같은 접두 포함은 다른 회사이므로 containment 확정에서 제외한다.
# 반대로 그룹접두가 '앞에' 붙는 사명변경(현대중공업 ⊂ 에이치디현대중공업)은 영향 없음.
_ENTITY_SUFFIX = ("증권", "홀딩스", "지주", "금융지주", "금융", "생명", "화재", "손해보험",
                  "손보", "카드", "캐피탈", "은행", "저축은행", "자산운용", "인베스트먼트")


def _unique_containment(names: list[str]) -> Optional[dict]:
    """질의가 '단 하나'의 회사명에 부분문자열로 포함되면 그 회사로 확정.

    사명변경·그룹접두 부류 대응(예: "현대중공업" ⊂ "에이치디현대중공업").
    여러 회사가 포함하면(모호) None — 퍼지/되묻기로 넘긴다.
    엔티티 접미사 가드: 질의가 후보명의 '접두'이고 나머지가 증권/지주 등 별개 법인 접미사면 제외.
    """
    hits: set[str] = set()
    hit_entry: dict = {}
    for raw in names:
        q = _normalize(raw)
        if len(q) < _CONTAIN_MIN_LEN:
            continue
        for cand in _INDEX["companies"]:
            cn = cand.get("corp_name", "")
            if len(cn) < _CONTAIN_MIN_LEN or q not in cn:
                continue
            # 가드: cn = q + 엔티티접미사 (예: "현대차"+"증권") → 별개 법인이므로 제외
            if cn != q and cn.startswith(q):
                rest = cn[len(q):]
                if any(rest.startswith(suf) for suf in _ENTITY_SUFFIX):
                    continue
            hits.add(cand["ticker"])
            hit_entry[cand["ticker"]] = cand
    if len(hits) == 1:
        return hit_entry[next(iter(hits))]
    return None


def _match_one(name: str) -> tuple[Optional[dict], dict[str, float]]:
    """단일 이름 매칭. 정확/코드 일치면 (entry, {}), 아니면 (None, {corp_name: score})."""
    query = _normalize(name)
    if not query:
        return None, {}
    # 원본 + 라틴→한글 확장 변형 (HD현대중공업 → 에이치디현대중공업)
    variants = _query_variants(name)

    # 1) 6자리 종목코드
    if re.fullmatch(r"[0-9A-Z]{6}", query):
        for e in _INDEX["companies"]:
            if e["ticker"] == query:
                return e, {}

    # 2) 정확 일치 (변형 포함)
    for v in variants:
        if v in _NAME_TO_ENTRY:
            return _NAME_TO_ENTRY[v], {}

    # 3) 퍼지 — 변형별 결과를 엔트리당 최고점으로
    from rapidfuzz import process, fuzz

    best_score: dict[str, float] = {}
    for v in variants:
        for matched_name, score, _ in process.extract(
                v, _NAMES, scorer=fuzz.WRatio, limit=MAX_CANDIDATES):
            if score > best_score.get(matched_name, -1):
                best_score[matched_name] = float(score)
    return None, best_score


def resolve(name: str) -> dict:
    """회사명 1개를 ticker 로 해석. (resolve_any 의 단일 입력 버전)"""
    return resolve_any([name])


def resolve_any(names: list[str]) -> dict:
    """여러 후보 표기(원문 + 별칭)를 모두 대조해 해석.

    어느 하나라도 정확/코드 일치하면 즉시 확정. 아니면 모든 표기의 퍼지 결과를
    엔트리당 최고점으로 합쳐 후보를 만든다.

    Returns:
        {matched, ticker, corp_name, years, score, candidates[{ticker,corp_name,score}]}
    """
    _ensure_loaded()
    empty = {"matched": False, "ticker": None, "corp_name": None,
             "years": [], "score": 0.0, "candidates": []}
    names = [n for n in (names or []) if n and n.strip()]
    if not names:
        return empty

    # 통칭·약칭 별칭 확장 (예: 현대차→현대자동차, 네이버→NAVER, 하이닉스→에스케이하이닉스).
    # 별칭 값은 DB 실재 정식명이라 아래 _match_one 에서 exact-match 로 즉시 확정된다.
    expanded = list(names)
    for nm in names:
        alias = _ALIASES.get(_normalize(nm))
        if alias and alias not in expanded:
            expanded.append(alias)
    names = expanded

    merged: dict[str, float] = {}
    for nm in names:
        entry, scores = _match_one(nm)
        if entry is not None:                 # 정확/코드 일치 → 즉시 확정
            return _matched_result(entry)
        for cn, sc in scores.items():
            if sc > merged.get(cn, -1):
                merged[cn] = sc

    # 부분문자열 유일 포함(사명변경/접두 변형) → 신뢰 매칭 (퍼지 동점 가드보다 우선)
    contained = _unique_containment(names)
    if contained is not None:
        return _matched_result(contained)

    candidates = sorted(
        ({"ticker": _NAME_TO_ENTRY[n]["ticker"], "corp_name": n, "score": s}
         for n, s in merged.items()),
        key=lambda c: c["score"], reverse=True,
    )[:MAX_CANDIDATES]
    if not candidates:
        return empty

    best = candidates[0]
    matched = best["score"] >= FUZZY_MIN_SCORE
    # 1등이 2등을 충분히 앞서야 단독 확정, 아니면 후보 제시(되묻기)
    if matched and len(candidates) > 1 and (best["score"] - candidates[1]["score"]) < 8:
        matched = False

    e = _NAME_TO_ENTRY[best["corp_name"]]
    return {
        "matched": matched,
        "ticker": best["ticker"] if matched else None,
        "corp_name": best["corp_name"] if matched else None,
        "years": e["years"] if matched else [],
        "score": best["score"],
        "candidates": candidates,
    }


def list_companies() -> list[dict]:
    """전체 회사 목록(가벼운 형태)."""
    _ensure_loaded()
    return [{"ticker": e["ticker"], "corp_name": e["corp_name"],
             "years": e["years"]} for e in _INDEX["companies"]]
