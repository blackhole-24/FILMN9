"""베타 계산 메인 실행 스크립트.

CLI 실행:
    python -m peer_beta.run_beta                 # 오늘 기준
    python -m peer_beta.run_beta 2026-05-14      # 특정일 기준

Python import:
    from peer_beta.run_beta import run
    result = run(eval_date="2026-05-14")

산출물:
    peer_beta/results/peer_beta_<YYYYMMDD>.json   # 메인 결과
    peer_beta/data/processed/weekly_prices_<YYYYMMDD>.csv  # 주간 종가 패널
    peer_beta/data/processed/weekly_returns_<YYYYMMDD>.csv # 주간 수익률 패널
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd
from dotenv import load_dotenv

from .beta_calculator import compute_beta
from .calendar_utils import parse_date, weekly_friday_dates
from .config import BETA_CONFIG, DEFAULT_PEERS, PROC_DIR, RESULTS_DIR
from .krx_client import (
    fetch_index_weekly,
    fetch_stock_weekly,
    get_cache_stats,
    reset_cache_stats,
)


def _load_env() -> None:
    """프로젝트 루트의 .env 자동 로드.

    탐색 순서:
        1) 현재 작업디렉토리/.env
        2) peer_beta/../.env  (모듈 루트의 부모)
    """
    candidates = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parent.parent / ".env",
    ]
    for p in candidates:
        if p.exists():
            load_dotenv(p, override=False)
            return
    # 못 찾아도 OS 환경변수에 있으면 OK


# ---------------------------------------------------------------------------
# 데이터 수집 (피어별 주간 종가 + 시장별 지수)
# ---------------------------------------------------------------------------
def _collect_market_indices(peers: list[dict], fridays: list[date]) -> dict:
    """피어 집합에서 사용된 시장(KOSPI/KOSDAQ)별로 지수 시계열을 1회씩만 수집."""
    markets = sorted({p["market"] for p in peers})
    out = {}
    for m in markets:
        pts = fetch_index_weekly(m, fridays)
        out[m] = [cp.to_dict() for cp in pts]
    return out


def _collect_stock(peer: dict, fridays: list[date]) -> list[dict]:
    pts = fetch_stock_weekly(peer["ticker"], peer["market"], fridays)
    return [cp.to_dict() for cp in pts]


# ---------------------------------------------------------------------------
# 결과 정리/저장
# ---------------------------------------------------------------------------
def _save_panels(eval_d: date, stock_panel: dict, index_panel: dict) -> tuple[Path, Path]:
    """주간 종가/수익률 패널을 CSV로 저장."""
    tag = eval_d.strftime("%Y%m%d")

    # 종가 패널
    series = []
    for name, pts in stock_panel.items():
        if not pts:
            continue
        df = pd.DataFrame(pts)
        df = df[["actual_date", "close"]].rename(columns={"close": name})
        df["actual_date"] = pd.to_datetime(df["actual_date"])
        series.append(df.set_index("actual_date"))
    for market, pts in index_panel.items():
        if not pts:
            continue
        df = pd.DataFrame(pts)
        col = f"{market}_INDEX"
        df = df[["actual_date", "close"]].rename(columns={"close": col})
        df["actual_date"] = pd.to_datetime(df["actual_date"])
        series.append(df.set_index("actual_date"))

    if series:
        panel = pd.concat(series, axis=1).sort_index()
    else:
        panel = pd.DataFrame()
    prices_path = PROC_DIR / f"weekly_prices_{tag}.csv"
    panel.to_csv(prices_path, encoding="utf-8-sig")

    # 수익률 패널 — 산술수익률 (베타 회귀와 동일 방식, 한공회 정합)
    if not panel.empty:
        returns = panel.pct_change().dropna(how="all")
    else:
        returns = panel
    returns_path = PROC_DIR / f"weekly_returns_{tag}.csv"
    returns.to_csv(returns_path, encoding="utf-8-sig")

    return prices_path, returns_path


# ---------------------------------------------------------------------------
# 메인 진입점
# ---------------------------------------------------------------------------
def run(
    eval_date: Optional[str | date] = None,
    peers: Optional[list[dict]] = None,
    *,
    save_json: bool = True,
    save_csv: bool = True,
    verbose: bool = True,
    outlier_handling: Optional[str] = None,
) -> dict:
    """피어 베타 계산 전체 흐름.

    Args:
        eval_date: 평가기준일 T. None이면 today.
        peers:     피어 리스트. None이면 DEFAULT_PEERS.
        save_json: results/peer_beta_<T>.json 저장 여부.
        save_csv:  data/processed/ 패널 CSV 저장 여부.

    Returns:
        {
          "eval_date": "...",
          "config": {...},
          "fridays_requested": int,
          "indices": { "KOSPI": [...], ... },
          "peers": {
              "아모레퍼시픽": { "ticker": "...", "beta_raw": ..., "beta_adjusted": ..., ... },
              ...
          }
        }
    """
    _load_env()
    reset_cache_stats()

    eval_d = parse_date(eval_date)
    peers  = peers or DEFAULT_PEERS

    lookback = BETA_CONFIG["lookback_years"]
    fridays  = weekly_friday_dates(eval_d, lookback)

    if verbose:
        print(f"[T={eval_d}] lookback={lookback}년, 금요일 후보 {len(fridays)}개")
        print(f"피어/타겟 {len(peers)}사: " +
              ", ".join(f"{p['name']}({p['ticker']}/{p['market']})" for p in peers))

    # 1) 지수 수집 (시장별 1회)
    if verbose:
        print("\n[1/3] 시장 지수 수집...")
    index_panel = _collect_market_indices(peers, fridays)
    for m, pts in index_panel.items():
        if verbose:
            print(f"  - {m}: 관측 {len(pts)}건")

    # 2) 종목 수집
    if verbose:
        print("\n[2/3] 종목 주간 종가 수집...")
    stock_panel: dict[str, list[dict]] = {}
    for p in peers:
        pts = _collect_stock(p, fridays)
        stock_panel[p["name"]] = pts
        if verbose:
            print(f"  - {p['name']}({p['ticker']}): 관측 {len(pts)}건")

    # 3) 베타 계산
    if verbose:
        print("\n[3/3] OLS 회귀 + Blume 조정...")
    expected_returns = len(fridays) - 1  # 종가 N개 -> 수익률 N-1개

    peer_results: dict[str, dict] = {}
    for p in peers:
        market = p["market"]
        idx_pts   = index_panel.get(market, [])
        stock_pts = stock_panel.get(p["name"], [])
        res = compute_beta(
            name=p["name"], ticker=p["ticker"], market=market,
            stock_points=stock_pts, index_points=idx_pts,
            eval_date=eval_d,
            expected_weeks=expected_returns,
            outlier_handling=outlier_handling,
        )
        peer_results[p["name"]] = res.to_dict()
        if verbose:
            extra = ""
            if res.outlier_handling == "drop" and res.n_outliers_dropped > 0:
                extra = f", dropped={res.n_outliers_dropped}"
            elif res.outlier_handling == "winsorize" and res.n_outliers_winsorized > 0:
                extra = f", winsorized={res.n_outliers_winsorized}(±{res.winsorize_k}σ)"
            print(f"  - {p['name']}: β_raw={res.beta_raw:.4f}, "
                  f"β_adj={res.beta_adjusted:.4f}, R²={res.r_squared:.3f}, "
                  f"n={res.n_weeks_used}{extra}, warn={res.warnings or 'none'}")

    cache_stats = get_cache_stats()
    if verbose:
        total_lookups = cache_stats["hits"] + cache_stats["misses"]
        hit_rate = (cache_stats["hits"] / total_lookups * 100) if total_lookups else 0.0
        print()
        print(f"[캐시] 조회 {total_lookups}회 = HIT {cache_stats['hits']} / "
              f"MISS(API호출) {cache_stats['misses']} "
              f"(빈응답 미저장 {cache_stats['empty_skips']}) "
              f"→ HIT rate {hit_rate:.1f}%")

    output = {
        "eval_date":          eval_d.isoformat(),
        "generated_at":       datetime.now().isoformat(timespec="seconds"),
        "config":             BETA_CONFIG,
        "fridays_requested":  len(fridays),
        "cache_stats":        cache_stats,
        "peers_input":        peers,
        "indices":            index_panel,
        "stocks_weekly":      stock_panel,
        "peers":              peer_results,
    }

    if save_json:
        tag = eval_d.strftime("%Y%m%d")
        out_path = RESULTS_DIR / f"peer_beta_{tag}.json"
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2, default=str)
        if verbose:
            print(f"\nJSON 저장: {out_path}")

    if save_csv:
        prices_path, returns_path = _save_panels(eval_d, stock_panel, index_panel)
        if verbose:
            print(f"CSV 저장 : {prices_path.name}, {returns_path.name}")

    return output


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Peer Levered Beta (Blume-adjusted)")
    ap.add_argument("eval_date", nargs="?", default=None,
                    help="평가기준일 YYYY-MM-DD (생략 시 today)")
    ap.add_argument("--no-csv",  action="store_true", help="CSV 패널 저장 생략")
    ap.add_argument("--no-json", action="store_true", help="결과 JSON 저장 생략")
    ap.add_argument("--quiet",   action="store_true", help="진행 메시지 출력 안 함")
    ap.add_argument("--outlier-handling", choices=["none", "drop", "winsorize"], default=None,
                    help="이상치 처리 (none: 기록만, drop: |z|>4 행 제거, winsorize: ±3σ로 자름)")
    args = ap.parse_args(argv)

    run(
        eval_date=args.eval_date,
        save_json=not args.no_json,
        save_csv=not args.no_csv,
        verbose=not args.quiet,
        outlier_handling=args.outlier_handling,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
