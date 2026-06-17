"""5년 시계열 XBRL 자동 수집 (v3 통합 — 재무 + 자본·NCI·EPS).

대상 회사 (사용자 지정 또는 자동 피어):
  - 단일 ticker: 사용자 입력
  - 자동 피어: peer_selector.select_peers_for_target 호출 후 그 4사
  - 전종목: CSV 파일에서 일괄 로드

5년 시계열: FY2021, FY2022, FY2023, FY2024, FY2025

저장: VAR/data/xbrl/<corp_name>_<year>.json (통일 경로)
       — 팀원 기본 필드 + v3 자본·NCI·EPS 통합

skip:
  - 우선주/스팩 (run_all_2차 의 SKIP_KEYWORDS 차용)
  - 캐시 이미 있고 v3 통합돼있으면 skip (--force 옵션 시 강제)

실행:
    # 단일 회사 5년
    python -m valuation_engine.run_xbrl_collection --ticker 현대건설

    # 자동 피어 + 타깃 (5사 × 5년 = 25건)
    python -m valuation_engine.run_xbrl_collection --target 000720 --auto-peers

    # CSV 파일 (전종목)
    python -m valuation_engine.run_xbrl_collection --csv 전종목리스트.csv

    # 캐시 강제 갱신
    python -m valuation_engine.run_xbrl_collection --ticker 현대건설 --force
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Optional

_VAR_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_VAR_ROOT))

from .xbrl_collector import (
    extract_company_v3, load_cached, has_balance_sheet_fields,
    UNIFIED_XBRL_DIR,
)
from .config import FISCAL_YEARS


# ─────────────────────────────────────────────────────────────
# 설정 — FISCAL_YEARS 는 config 단일 출처 (중복 정의 제거)
# ─────────────────────────────────────────────────────────────

# 우선주/스팩 자동 skip (run_all_2차 차용 + 확장)
SKIP_KEYWORDS = [
    # 우선주
    "우선주", "1우", "2우", "3우", "우B", "우C", "1우B", "2우B",
    # 스팩 (기업인수목적회사 — 영업 없음, 가치평가 무의미)
    "SPAC", "스팩", "기업인수목적",
    # 청산·관리종목 (선택적, 주석 처리 — 사용자가 원하면 활성화)
    # "관리종목", "정리매매",
]

# 금융사 분류 — IBD 6 component 구조 다름. 별도 처리 표시 (skip 아님).
FINANCIAL_KEYWORDS = [
    "은행", "증권", "투자증권", "캐피탈", "카드",
    "보험", "생명", "화재", "손해보험",
    "지주",   # 일부 지주사도 영업회사처럼 처리 가능 (예외)
]


def is_financial_company(name: str) -> bool:
    """금융사 분류 — DCF 직접 적용 부적합 (별도 처리 권장).

    True 반환 시 호출 측에서 멀티플만 사용하거나 별도 로직 분기.
    """
    return any(kw in name for kw in FINANCIAL_KEYWORDS)

# DART API 호출 간격 (rate limit 회피). 속도 최적화 #1: 3.0→0.5
# OpenDART 분당 한도 대비 3초는 과보수. 0.5초로 단축(429 시 호출부가 재시도).
SLEEP_SEC = 0.5


def _should_skip(name: str) -> bool:
    """우선주/스팩 등 skip 키워드 포함 여부."""
    return any(kw in name for kw in SKIP_KEYWORDS)


# ─────────────────────────────────────────────────────────────
# 5년 수집 — 단일 회사
# ─────────────────────────────────────────────────────────────
def collect_one_company_5yr(name_or_code: str,
                            force: bool = False,
                            verbose: bool = True,
                            ticker: Optional[str] = None) -> dict:
    """1개 회사 × 5년 (FY2021~FY2025) 수집.

    캐시 (`UNIFIED_XBRL_DIR/<name>_<year>.json`) 가 v3 통합 상태면 skip.

    Args:
        name_or_code: 캐시 키 (회사명). 캐시 조회용.
        ticker:       DART 호출 시 우선 사용 (6자리 종목코드).
                      회사명 모호성 회피 (예: "KT" → KTis 폴백 방지).

    Returns:
        {"name": ..., "results": {2021: {...}, ..., 2025: {...}},
         "ok_years": [...], "failed_years": [...]}
    """
    out = {"name_or_code": name_or_code,
           "results": {}, "ok_years": [], "failed_years": []}

    if _should_skip(name_or_code):
        if verbose:
            print(f"  ⏭ {name_or_code} → skip (우선주/스팩)")
        out["skipped"] = True
        return out

    # DART 호출 식별자: ticker (숫자) 우선 → stock_code exact 매칭
    dart_id = ticker if (ticker and str(ticker).isdigit()) else name_or_code

    for year in FISCAL_YEARS:
        # 캐시 점검
        cached = load_cached(name_or_code, year)
        if cached and has_balance_sheet_fields(cached) and not force:
            if verbose:
                print(f"  [{year}] 캐시 사용 (v3 통합 완료)")
            out["results"][year] = cached
            out["ok_years"].append(year)
            continue

        # 신규 추출
        if verbose:
            print(f"  [{year}] DART 호출 중...")
        try:
            result = extract_company_v3(
                name_or_code=dart_id,
                year=year,
                save=True,
                verbose=False,
            )
            out["results"][year] = result
            out["ok_years"].append(year)
            if verbose:
                fin = result.get("financials", {})
                rev = (fin.get("매출액") or 0) / 1e8
                ebit = (fin.get("영업이익") or 0) / 1e8
                eq_p = (fin.get("equity_parent") or 0) / 1e8
                mi   = (fin.get("minority_interest") or 0) / 1e8
                eps  = fin.get("basic_eps")
                eps_str = f"EPS {eps:,.0f}원" if eps is not None else "EPS N/A"
                print(f"    매출 {rev:>9,.0f}억  EBIT {ebit:>7,.0f}억  "
                      f"지배자본 {eq_p:>7,.0f}억  NCI {mi:>7,.0f}억  {eps_str}")
            time.sleep(SLEEP_SEC)   # rate limit
        except Exception as e:
            if verbose:
                print(f"    ✗ 실패: {e}")
            out["failed_years"].append((year, str(e)))
            time.sleep(SLEEP_SEC / 2)

    return out


# ─────────────────────────────────────────────────────────────
# 5사 × 5년 — 자동 피어 통합
# ─────────────────────────────────────────────────────────────
def collect_target_and_peers(target_input: str,
                              top_n_peers: int = 3,
                              force: bool = False,
                              use_rag: bool = False,
                              verbose: bool = True) -> dict:
    """타깃 + 자동 피어 N사 × 5년 일괄 수집.

    Args:
        target_input: 타깃 ticker 또는 회사명
        top_n_peers:  피어 개수 (기본 4)
        force:        캐시 무시 강제 갱신
        use_rag:      피어 산정 시 사업보고서 RAG 사용
    """
    from .ticker_lookup import lookup
    from .peer_selector import select_peers_for_target

    # 1) 타깃 정규화
    look = lookup(target_input)
    if look["status"] != "exact":
        print(f"[오류] 타깃 입력 매칭 실패: {look}")
        return {}
    target = look["match"]

    print("=" * 70)
    print(f"  XBRL 5년 시계열 수집 — 타깃 + 자동 피어 {top_n_peers}사")
    print("=" * 70)
    print(f"  타깃: {target['corp_name']} ({target['ticker']})")

    # 2) 자동 피어 산정 (피어가 부족하면 fallback)
    peers = []
    try:
        peers = select_peers_for_target(
            target["ticker"], target_data=None,
            top_n=top_n_peers, use_rag=use_rag, verbose=False)
    except Exception as e:
        print(f"  [WARN] 자동 피어 산정 실패: {e}")
        print(f"         → config.PEERS 사용 (fallback)")
        from .config import PEERS
        peers = [{"ticker": p["ticker"], "name": p["name"]} for p in PEERS]

    companies = [{"ticker": target["ticker"], "name": target["corp_name"]}]
    companies.extend([{"ticker": p["ticker"], "name": p["name"]} for p in peers[:top_n_peers]])

    print(f"  피어: {', '.join(p['name'] for p in peers[:top_n_peers])}")
    print(f"  대상 회사: {len(companies)}사 × {len(FISCAL_YEARS)}년 = {len(companies)*len(FISCAL_YEARS)}건\n")

    # 3) 수집 루프
    all_results = {}
    for i, comp in enumerate(companies, 1):
        print(f"\n[{i}/{len(companies)}] {comp['name']} ({comp['ticker']})")
        r = collect_one_company_5yr(comp["name"], force=force, verbose=verbose)
        all_results[comp["name"]] = r

    # 4) 요약
    print("\n" + "=" * 70)
    print(f"  완료 요약")
    print("=" * 70)
    ok_total = 0
    fail_total = 0
    for name, r in all_results.items():
        ok = len(r.get("ok_years", []))
        fail = len(r.get("failed_years", []))
        print(f"  {name:<15s}  성공 {ok}/{len(FISCAL_YEARS)}년"
              + (f"  실패 {fail}년" if fail else ""))
        ok_total += ok
        fail_total += fail
    print(f"\n  총 {ok_total}건 성공, {fail_total}건 실패")
    print(f"  저장 폴더: {UNIFIED_XBRL_DIR}")
    return all_results


# ─────────────────────────────────────────────────────────────
# 전종목 CSV 일괄
# ─────────────────────────────────────────────────────────────
def collect_from_csv(csv_path: str,
                     years: Optional[list[int]] = None,
                     force: bool = False,
                     verbose: bool = True) -> dict:
    """CSV 의 종목 리스트 × N년 일괄 수집 (팀원 run_all 패턴)."""
    years = years or FISCAL_YEARS
    csv_path = Path(csv_path)
    if not csv_path.exists():
        print(f"[오류] {csv_path} 없음")
        return {}

    names = []
    with csv_path.open("r", encoding="utf-8") as f:
        for line in f:
            n = line.strip()
            if n and not n.startswith("["):
                names.append(n)

    print(f"\n[CSV 일괄] {len(names)}개 × {len(years)}년 = {len(names)*len(years)}건")
    all_results = {}
    failed = []
    skipped = []

    for i, name in enumerate(names, 1):
        if _should_skip(name):
            skipped.append(name)
            if verbose:
                print(f"  [{i}/{len(names)}] {name} → skip")
            continue

        print(f"\n[{i}/{len(names)}] {name}")
        try:
            r = collect_one_company_5yr(name, force=force, verbose=verbose)
            all_results[name] = r
            if r.get("failed_years"):
                failed.extend([(name, y, e) for y, e in r["failed_years"]])
        except Exception as e:
            if verbose:
                print(f"  ✗ 전체 실패: {e}")
            failed.append((name, "all", str(e)))

    print("\n" + "=" * 70)
    print(f"  CSV 일괄 완료: 처리 {len(all_results)} / skip {len(skipped)} / 실패 {len(failed)}")
    print("=" * 70)
    return all_results


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────
def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="XBRL 5년 시계열 자동 수집 (v3)")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--ticker", "-t", type=str,
                   help="단일 회사 5년 수집 (회사명 또는 ticker)")
    g.add_argument("--target", "-T", type=str,
                   help="타깃 + 자동 피어 4사 × 5년 수집")
    g.add_argument("--csv", type=str, help="CSV 파일 일괄")

    parser.add_argument("--peers", "-n", type=int, default=3,
                        help="자동 피어 개수 (--target 사용 시, 기본 3)")
    parser.add_argument("--force", "-f", action="store_true",
                        help="캐시 무시 강제 갱신")
    parser.add_argument("--use-rag", action="store_true",
                        help="피어 산정 시 RAG 사용 (--target 시)")
    parser.add_argument("--quiet", "-q", action="store_true")
    args = parser.parse_args(argv)

    if args.ticker:
        collect_one_company_5yr(args.ticker, force=args.force,
                                verbose=not args.quiet)
    elif args.target:
        collect_target_and_peers(args.target, top_n_peers=args.peers,
                                  force=args.force, use_rag=args.use_rag,
                                  verbose=not args.quiet)
    elif args.csv:
        collect_from_csv(args.csv, force=args.force,
                          verbose=not args.quiet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
