# -*- coding: utf-8 -*-
"""
ohlcv_daily_sync.py
===================
KOSPI/KOSDAQ 일별 OHLCV 자동 동기화

데이터 소스 우선순위:
  1순위 yfinance (안정, 한국 주식 .KS/.KQ 접미사)
  2순위 pykrx (KRX 차단 시 보조)

특징:
- 누락일 자동 탐지 후 갭만 보충
- UPSERT (ON CONFLICT) — 중복 자동 갱신
- 데모 3종목 우선 검증
"""
from __future__ import annotations
import argparse
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
import csv

import yfinance as yf

DB = Path(r"C:\Users\Admin\FILMN9\data\filmn9.db")
TICKER_CSV = Path(r"C:\Users\Admin\FILMN9\data\ticker_universe.csv")
DEMO_CODES = ["090430", "009150", "035420"]


def get_suffix(market: str) -> str:
    """KOSPI=.KS, KOSDAQ=.KQ"""
    m = (market or "").upper()
    if "KOSDAQ" in m:
        return ".KQ"
    return ".KS"


def load_targets(demo_only: bool = False) -> list[tuple[str, str]]:
    """[(stock_code, suffix), ...] 반환"""
    if demo_only:
        return [(c, ".KS") for c in DEMO_CODES]
    out = []
    if not TICKER_CSV.exists():
        print(f"⚠️ {TICKER_CSV} 없음 → 데모 3종목만")
        return [(c, ".KS") for c in DEMO_CODES]
    with open(TICKER_CSV, encoding="utf-8-sig") as f:
        rdr = csv.DictReader(f)
        for r in rdr:
            code = r.get("stock_code", "").strip()
            market = r.get("market", "KOSPI")
            if not code or len(code) != 6:
                continue
            if r.get("is_spac", "").lower() == "true":
                continue
            if r.get("is_preferred", "").lower() == "true":
                continue
            out.append((code, get_suffix(market)))
    return out


def fetch_yfinance(code: str, suffix: str, since: datetime, until: datetime):
    """yfinance로 OHLCV 가져오기. 반환: list of tuples"""
    ticker = yf.Ticker(code + suffix)
    df = ticker.history(start=since.strftime("%Y-%m-%d"),
                        end=(until + timedelta(days=1)).strftime("%Y-%m-%d"))
    if df.empty:
        return []
    rows = []
    for idx, r in df.iterrows():
        date_str = idx.strftime("%Y-%m-%d")
        try:
            o, h, l, c = int(r["Open"]), int(r["High"]), int(r["Low"]), int(r["Close"])
            v = int(r["Volume"])
        except (ValueError, KeyError):
            continue
        if any(x <= 0 for x in (o, h, l, c)) or v < 0:
            continue
        if h < max(o, c, l) or l > min(o, c, h):
            continue
        rows.append((code, date_str, o, h, l, c, v))
    return rows


def get_last_date(conn, code: str) -> datetime | None:
    r = conn.execute("SELECT MAX(date) FROM ohlcv WHERE stock_code = ?", (code,)).fetchone()
    if r and r[0]:
        return datetime.strptime(r[0], "%Y-%m-%d")
    return None


def sync_stock(conn, code: str, suffix: str, fallback_days: int = 14) -> tuple[int, str]:
    """한 종목 누락일 보충. 반환: (적재 행수, 상태)"""
    last = get_last_date(conn, code)
    today = datetime.now()
    if last is None:
        since = today - timedelta(days=fallback_days)
    else:
        since = last + timedelta(days=1)

    if since.date() > today.date():
        return 0, "최신"

    rows = fetch_yfinance(code, suffix, since, today)
    if not rows:
        return 0, "데이터 없음"

    conn.executemany("""
        INSERT INTO ohlcv (stock_code, date, open, high, low, close, volume)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(stock_code, date) DO UPDATE SET
          open=excluded.open, high=excluded.high, low=excluded.low,
          close=excluded.close, volume=excluded.volume
    """, rows)
    conn.commit()
    return len(rows), "OK"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo-only", action="store_true")
    ap.add_argument("--limit", type=int, default=0,
                    help="최대 N종목 (테스트용, 0=무제한)")
    ap.add_argument("--fallback-days", type=int, default=14)
    args = ap.parse_args()

    print("=" * 70)
    print(f"OHLCV yfinance 동기화 — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"demo_only={args.demo_only} / limit={args.limit}")
    print("=" * 70)

    targets = load_targets(args.demo_only)
    if args.limit > 0:
        targets = targets[:args.limit]
    print(f"대상 종목: {len(targets)}개\n")

    conn = sqlite3.connect(DB)
    stats = {"OK": 0, "최신": 0, "데이터 없음": 0, "에러": 0}
    total_rows = 0
    start = time.time()

    for i, (code, suffix) in enumerate(targets, 1):
        try:
            n, status = sync_stock(conn, code, suffix, args.fallback_days)
            stats[status] = stats.get(status, 0) + 1
            total_rows += n
            if code in DEMO_CODES or i % 50 == 0 or i == len(targets):
                elapsed = time.time() - start
                rate = i / elapsed if elapsed > 0 else 0
                eta = (len(targets) - i) / rate / 60 if rate > 0 else 0
                print(f"  [{i:>4}/{len(targets)}] {code}{suffix} {status} {n}건 "
                      f"| OK={stats['OK']} 최신={stats['최신']} "
                      f"노데이터={stats.get('데이터 없음',0)} | ETA {eta:.1f}분")
        except Exception as e:
            stats["에러"] += 1
            if i % 50 == 0:
                print(f"  ⚠️ {code} 에러: {e}")
        time.sleep(0.2)  # rate limit

    # 데모 3종목 최신 종가
    print("\n[데모 3종목 최신 종가]")
    for code in DEMO_CODES:
        r = conn.execute("""
            SELECT date, close FROM ohlcv WHERE stock_code = ?
            ORDER BY date DESC LIMIT 1
        """, (code,)).fetchone()
        if r:
            print(f"  {code}  {r[0]}  종가 {r[1]:,}원")

    conn.close()
    print("=" * 70)
    print(f"완료 — {(time.time()-start)/60:.1f}분 / 총 {total_rows}건 적재")
    print(f"상태: OK={stats['OK']} 최신={stats['최신']} "
          f"노데이터={stats.get('데이터 없음',0)} 에러={stats['에러']}")
    print("=" * 70)


if __name__ == "__main__":
    main()
