"""오프라인 프리워밍 CLI (속도 최적화 #6) — 종목 리스트를 미리 평가해 DB 적재.

목적:
  · 데모/서비스 전, 주요 종목의 XBRL·신용등급·임베딩·평가 결과를 미리 계산.
  · 파이프라인이 산출물을 자동으로 DB(+Mongo-JSON)에 적재(financials/credit/
    wacc/dcf/equity/diagnostics/valuation_runs) → 사용자 조회는 캐시 hit(수 초).
  · 이어하기(resume): 같은 평가일에 이미 적재된 종목은 건너뜀.

실행:
    python -m valuation_engine.db.prewarm --tickers 005930,000660,035420
    python -m valuation_engine.db.prewarm --file tickers.txt
    python -m valuation_engine.db.prewarm --file tickers.txt --date 2026-05-26 --resume
    python -m valuation_engine.db.prewarm --file tickers.txt --no-resume   # 전부 재평가

입력 파일(--file): 한 줄당 종목코드 또는 회사명 (# 주석/빈 줄 무시).
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime
from pathlib import Path

from . import store
from .. import db as api

_VAR_ROOT = Path(__file__).resolve().parent.parent.parent

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _load_tickers(args) -> list[str]:
    out: list[str] = []
    if args.tickers:
        out += [t.strip() for t in args.tickers.split(",") if t.strip()]
    if args.file:
        p = Path(args.file)
        if not p.exists():
            raise FileNotFoundError(f"리스트 파일 없음: {p}")
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                out.append(line)
    # 중복 제거(순서 보존)
    seen, uniq = set(), []
    for t in out:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq


def _already_done(stock_code: str, eval_date: str) -> bool:
    """같은 평가일에 valuation_runs 에 이미 있으면 done."""
    sc = str(stock_code).zfill(6) if str(stock_code).isdigit() else stock_code
    r = store.query_one(
        "SELECT 1 FROM valuation_runs WHERE stock_code=? AND eval_date=?",
        (sc, eval_date))
    return r is not None


def run(tickers: list[str], eval_date: date, resume: bool = True,
        verbose: bool = False) -> dict:
    from ..run_valuation_auto import run_for_ticker

    ed = eval_date.isoformat()
    n = len(tickers)
    ok, skip, fail = 0, 0, 0
    failures: list[tuple[str, str]] = []
    t0 = time.time()
    print("=" * 64)
    print(f"  오프라인 프리워밍 — {n}종목  (평가일 {ed}, resume={resume})")
    print("=" * 64)

    for i, tk in enumerate(tickers, 1):
        # resume: 종목코드 입력이면 바로 확인 (회사명 입력은 평가 후 판정)
        if resume and str(tk).isdigit() and _already_done(tk, ed):
            skip += 1
            print(f"[{i}/{n}] {tk:8s} ⏭ 이미 적재됨 — skip")
            continue
        print(f"[{i}/{n}] {tk:8s} 평가 중...", flush=True)
        st = time.time()
        try:
            result = run_for_ticker(tk, eval_date=eval_date, verbose=verbose)
            comp = (result or {}).get("company", {})
            fp = (result or {}).get("summary", {}).get("fair_price")
            ok += 1
            fp_str = f"{fp:,.0f}" if fp else "-"
            print(f"           ✓ {comp.get('name','')} ({comp.get('ticker','')}) "
                  f"적정주가 {fp_str}  ({time.time()-st:.0f}s)")
        except Exception as e:
            fail += 1
            failures.append((tk, str(e)[:160]))
            print(f"           ✗ 실패: {str(e)[:160]}  ({time.time()-st:.0f}s)")

    dt = time.time() - t0
    print("-" * 64)
    print(f"  완료: 성공 {ok} / 스킵 {skip} / 실패 {fail}  (총 {dt:.0f}s, "
          f"평균 {dt/max(1,ok):.0f}s/종목)")
    if failures:
        print("  실패 목록:")
        for tk, msg in failures[:20]:
            print(f"    - {tk}: {msg}")
    print("  DB 적재 현황:")
    for t, c in store.table_counts().items():
        if c:
            print(f"    {t:22s} {c:>7d}")
    print("=" * 64)
    return {"ok": ok, "skip": skip, "fail": fail, "failures": failures,
            "elapsed_sec": dt}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="오프라인 프리워밍 (DB 적재)")
    ap.add_argument("--tickers", type=str, default=None,
                    help="콤마구분 종목코드/회사명 (예: 005930,000660)")
    ap.add_argument("--file", type=str, default=None,
                    help="종목 리스트 파일 (한 줄당 하나, # 주석 가능)")
    ap.add_argument("--date", type=str, default=None,
                    help="평가기준일 YYYY-MM-DD (기본 today)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--resume", dest="resume", action="store_true", default=True,
                   help="이미 적재된 종목 건너뜀 (기본)")
    g.add_argument("--no-resume", dest="resume", action="store_false",
                   help="전부 재평가")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args(argv)

    tickers = _load_tickers(args)
    if not tickers:
        print("[오류] --tickers 또는 --file 로 종목을 지정하세요.", file=sys.stderr)
        return 1
    ed = (datetime.strptime(args.date, "%Y-%m-%d").date()
          if args.date else date.today())
    res = run(tickers, ed, resume=args.resume, verbose=args.verbose)
    return 0 if res["fail"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
