"""
build_overview.py
=================
종목코드 또는 기업명 입력 → company_info.json + financials.json 산출.
2,596개 전 기업 지원 (corp_code_map.json 자동 조회).

출력
----
  data/parsed/{stock_code}/company_info.json
  data/parsed/{stock_code}/financials.json

사용법
------
  cd C:/Users/Admin/FILMN9/기업개요_파트/재무정보

  # 종목코드로 검색
  python build_overview.py 090430        # 아모레퍼시픽
  python build_overview.py 005930        # 삼성전자
  python build_overview.py 051910        # LG화학

  # 기업명으로 검색 (부분 일치 가능)
  python build_overview.py 아모레퍼시픽
  python build_overview.py 삼성전자
  python build_overview.py 삼성            # 후보 목록 출력 후 선택

  # 기본값 (인수 없음)
  python build_overview.py                # 090430 아모레퍼시픽

스키마 (step2 기준 2026-05-19)
-------------------------------
company_info : stock_code / corp_name / market / sector / listing_date
               / ceo / employees / homepage / address / phone / fiscal_month
financials   : stock_code / fiscal_years / revenue / op_income / net_income
               / assets / liabilities / equity / debt_ratio
               / cashflow_op / cashflow_inv / cashflow_fin
               (수치 단위: 백만원, debt_ratio 단위: %)

주의
----
- history.json 은 휘주님 파트 → 이 스크립트에서 건드리지 않는다
- 수치는 Python 계산만, LLM 환각 금지
- 값은 전부 JSON 경유, 코드 하드코딩 금지
"""

from __future__ import annotations

import sys
import json
import re
import math
from pathlib import Path
from datetime import datetime

# ─── 경로 설정 ────────────────────────────────────────────────────────────────
_HERE = Path(__file__).resolve().parent   # 재무정보/
_ROOT = _HERE.parent.parent               # FILMN9/
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# ─── 기존 파서 임포트 ──────────────────────────────────────────────────────────
from src.collectors.dart_api_collector import get_company_info
from src.processors.financial_parser  import get_financial_highlight, get_financial_detail
from src.processors.ratio_calculator  import _get_val

# ─── corp_code_map 임포트 ─────────────────────────────────────────────────────
_MAP_PATH = _ROOT / "data" / "corp_code_map.json"
_map_cache: dict | None = None

def _load_map() -> dict:
    global _map_cache
    if _map_cache is None:
        with open(_MAP_PATH, encoding="utf-8") as f:
            _map_cache = json.load(f)
    return _map_cache


# =============================================================================
# 종목 조회 — 코드 또는 기업명 → (stock_code, corp_code, corp_name)
# =============================================================================

def resolve_company(query: str) -> tuple[str, str, str] | None:
    """
    종목코드 또는 기업명(부분 일치) → (stock_code, corp_code, corp_name).

    - 6자리 코드 입력 → 정확히 일치하는 종목 반환
    - 기업명 입력    → 포함 검색, 1개면 바로 반환 / 여러 개면 선택 프롬프트
    - 없으면 None 반환
    """
    cmap   = _load_map()
    by_sc  = cmap["by_stock_code"]
    index  = cmap["search_index"]
    q      = query.strip()

    # ── 종목코드 직접 조회 ──────────────────────────────────────────────────
    if re.match(r"^[A-Z0-9]{6}$", q.upper()):
        q_upper = q.upper()
        info = by_sc.get(q_upper)
        if info:
            return q_upper, info["corp_code"], info["corp_name"]
        print(f"[ERROR] 종목코드 {q}를 corp_code_map에서 찾을 수 없습니다.")
        return None

    # ── 기업명 부분 일치 검색 ─────────────────────────────────────────────
    hits = [it for it in index if q in it["corp_name"]]

    if not hits:
        print(f"[ERROR] '{q}' 검색 결과 없음.")
        return None

    if len(hits) == 1:
        it = hits[0]
        return it["stock_code"], it["corp_code"], it["corp_name"]

    # 복수 후보 → 터미널에서 번호 선택
    print(f"\n  '{q}' 검색 결과 {len(hits)}개:")
    for i, it in enumerate(hits[:20], 1):
        jsonl_mark = "[사업보고서O]" if it["has_jsonl"] else "[사업보고서X]"
        print(f"  {i:>3}. {it['stock_code']}  {it['corp_name']:<30} {jsonl_mark}")
    if len(hits) > 20:
        print(f"       ... 외 {len(hits)-20}개 (더 구체적인 이름을 입력하세요)")

    try:
        choice = input("\n  번호를 입력하세요 (취소: 0): ").strip()
        idx = int(choice) - 1
        if idx < 0 or idx >= min(len(hits), 20):
            print("  취소 또는 잘못된 번호.")
            return None
        it = hits[idx]
        return it["stock_code"], it["corp_code"], it["corp_name"]
    except (ValueError, KeyboardInterrupt):
        print("  취소됨.")
        return None


# =============================================================================
# 내부 유틸
# =============================================================================

def _safe_float(val) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _row_val(df, keyword: str, year: str, exact: bool = False) -> float | None:
    if df is None or df.empty:
        return None
    return _get_val(df, keyword, year, exact=exact)


def _year_dict(df, keyword: str, years: list[str],
               exact: bool = False) -> dict[str, float | None]:
    return {y: _safe_float(_row_val(df, keyword, y, exact)) for y in years}


# =============================================================================
# 1) company_info.json 빌드
# =============================================================================

def build_company_info(stock_code: str, corp_code: str, corp_name_fallback: str = "") -> dict:
    """DART API → company_info 스키마 dict."""
    if corp_code:
        print(f"  [company_info] DART API 호출... corp_code={corp_code}")
        raw = get_company_info(corp_code)
    else:
        print("  [company_info] corp_code 없음 → DART 스킵 (JSONL 전용 기업)")
        raw = {}

    market_map = {
        "Y": "KOSPI", "유가증권": "KOSPI",
        "K": "KOSDAQ", "코스닥": "KOSDAQ",
        "N": "KONEX", "E": "기타",
    }
    market = market_map.get(raw.get("corp_cls", ""), raw.get("corp_cls", ""))

    info = {
        "stock_code"    : stock_code,
        "corp_name"     : raw.get("corp_name", "") or corp_name_fallback,
        "market"        : market,
        "sector"        : raw.get("induty_code", ""),
        "listing_date"  : raw.get("est_dt", ""),
        "ceo"           : raw.get("ceo_nm", ""),
        "employees"     : None,
        "homepage"      : raw.get("hm_url", ""),
        "address"       : raw.get("adres", ""),
        "phone"         : raw.get("phn_no", ""),
        "fiscal_month"  : raw.get("acc_mt", ""),
        "_source"       : "DART company.json",
        "_generated_at" : datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

    if not info["corp_name"]:
        print("  [company_info] WARNING: 기업명 없음 — 종목코드로 대체")
        info["corp_name"] = stock_code

    return info


# =============================================================================
# 2) financials.json 빌드
# =============================================================================

def build_financials(stock_code: str) -> dict:
    """JSONL 파싱 → financials 스키마 dict."""
    print("  [financials] JSONL 파싱 시작...")

    highlight = get_financial_highlight(stock_code)
    hl_연결   = highlight.get("연결")

    if hl_연결 is not None and not hl_연결.empty:
        year_cols = [c for c in hl_연결.columns if re.match(r"^\d{4}$", str(c))]
    else:
        year_cols = ["2025", "2024", "2023"]
    years = year_cols[:3]
    print(f"  [financials] 감지 연도: {years}")

    detail = get_financial_detail(stock_code)
    bs_df  = detail.get("재무상태표(연결)")
    cf_df  = detail.get("현금흐름표(연결)")
    pl_df  = detail.get("포괄손익계산서(연결)")

    # ── 손익 (하이라이트 우선 → 포괄손익계산서 fallback) ──────────────────
    def _hl_dict(keyword: str) -> dict[str, float | None]:
        if hl_연결 is None or hl_연결.empty:
            return {y: None for y in years}
        mask = hl_연결["구분"].str.contains(keyword, na=False)
        if not mask.any():
            return {y: None for y in years}
        row = hl_연결[mask].iloc[0]
        return {y: _safe_float(row.get(y)) for y in years}

    revenue    = _hl_dict("매출액")
    op_income  = _hl_dict("영업이익")
    net_income = _hl_dict("당기순이익")

    if all(v is None for v in revenue.values()) and pl_df is not None:
        print("  [financials] 하이라이트 매출 없음 → 포괄손익계산서 재시도")
        revenue    = _year_dict(pl_df, "매출액",    years)
        op_income  = _year_dict(pl_df, "영업이익",  years)
        net_income = _year_dict(pl_df, "당기순이익", years)

    # ── 재무상태표 ────────────────────────────────────────────────────────
    assets      = _year_dict(bs_df, "자산총계", years, exact=True)
    liabilities = _year_dict(bs_df, "부채총계", years, exact=True)
    equity      = _year_dict(bs_df, "자본총계", years, exact=True)

    # ── 현금흐름표 ────────────────────────────────────────────────────────
    def _cf_dict(keywords: list[str]) -> dict[str, float | None]:
        for kw in keywords:
            d = _year_dict(cf_df, kw, years)
            if any(v is not None for v in d.values()):
                return d
        return {y: None for y in years}

    cashflow_op  = _cf_dict(["영업활동으로 인한 현금흐름", "영업활동현금흐름",
                              "영업활동으로인한현금흐름"])
    cashflow_inv = _cf_dict(["투자활동으로 인한 현금흐름", "투자활동현금흐름",
                              "투자활동으로인한현금흐름"])
    cashflow_fin = _cf_dict(["재무활동으로 인한 현금흐름", "재무활동현금흐름",
                              "재무활동으로인한현금흐름"])

    # ── 부채비율 (Python 계산) ────────────────────────────────────────────
    debt_ratio: dict[str, float | None] = {}
    for y in years:
        l_val = liabilities.get(y)
        e_val = equity.get(y)
        if l_val is not None and e_val and e_val != 0:
            debt_ratio[y] = round(l_val / e_val * 100, 2)
        else:
            debt_ratio[y] = None

    return {
        "stock_code"     : stock_code,
        "fiscal_years"   : years,
        "unit"           : "백만원",
        "revenue"        : revenue,
        "op_income"      : op_income,
        "net_income"     : net_income,
        "assets"         : assets,
        "liabilities"    : liabilities,
        "equity"         : equity,
        "debt_ratio"     : debt_ratio,
        "debt_ratio_unit": "%",
        "cashflow_op"    : cashflow_op,
        "cashflow_inv"   : cashflow_inv,
        "cashflow_fin"   : cashflow_fin,
        "_source"        : "JSONL 파싱 (연결재무제표)",
        "_generated_at"  : datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


# =============================================================================
# 3) 메인
# =============================================================================

def main(query: str = "090430") -> None:

    # ── 종목 조회 ─────────────────────────────────────────────────────────
    resolved = resolve_company(query)
    if resolved is None:
        sys.exit(1)

    stock_code, corp_code, corp_name = resolved
    has_jsonl = _load_map()["by_stock_code"].get(stock_code, {}).get("has_jsonl", False)

    print(f"\n{'='*55}")
    print(f"  build_overview  [{corp_name} / {stock_code}]")
    print(f"  corp_code : {corp_code or '(없음)'}")
    print(f"  사업보고서: {'있음' if has_jsonl else '없음 (financials 빈값 예상)'}")
    print(f"{'='*55}")

    out_dir = _ROOT / "data" / "parsed" / stock_code
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── company_info.json ─────────────────────────────────────────────────
    print("\n[1/2] company_info.json 빌드...")
    ci      = build_company_info(stock_code, corp_code, corp_name)
    ci_path = out_dir / "company_info.json"
    ci_path.write_text(json.dumps(ci, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  저장: {ci_path}")

    # ── financials.json ───────────────────────────────────────────────────
    print("\n[2/2] financials.json 빌드...")
    fin      = build_financials(stock_code)
    fin_path = out_dir / "financials.json"
    fin_path.write_text(json.dumps(fin, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  저장: {fin_path}")

    # ── 완료 요약 ─────────────────────────────────────────────────────────
    print(f"\n{'='*55}")
    print(f"  완료 요약")
    print(f"{'='*55}")
    print(f"  기업명   : {ci.get('corp_name')}")
    print(f"  시장     : {ci.get('market') or '미확인'}")
    print(f"  대표이사 : {ci.get('ceo') or '-'}")
    print(f"  결산월   : {ci.get('fiscal_month') or '-'}월")
    print(f"  연도     : {fin.get('fiscal_years')}")

    years = fin.get("fiscal_years", [])
    if years:
        y0  = years[0]
        r   = fin["revenue"].get(y0)
        o   = fin["op_income"].get(y0)
        n   = fin["net_income"].get(y0)
        d   = fin["debt_ratio"].get(y0)
        cf  = fin["cashflow_op"].get(y0)
        if r is not None and o is not None and n is not None:
            print(f"  [{y0}] 매출={r:>14,.0f} 백만원  영업이익={o:>12,.0f}  순이익={n:>12,.0f}")
        elif r is not None:
            print(f"  [{y0}] 매출={r:>14,.0f} 백만원  (영업이익/순이익 일부 NULL)")
        if d is not None and cf is not None:
            print(f"  [{y0}] 부채비율={d}%  영업CF={cf:>12,.0f} 백만원")

    print(f"\n  company_info.json : {ci_path.stat().st_size:,} bytes")
    print(f"  financials.json   : {fin_path.stat().st_size:,} bytes")
    print(f"\n[완료] data/parsed/{stock_code}/")


if __name__ == "__main__":
    query = sys.argv[1] if len(sys.argv) > 1 else "090430"
    main(query)
