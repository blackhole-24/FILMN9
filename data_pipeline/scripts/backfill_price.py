# -*- coding: utf-8 -*-
"""
backfill_price.py
=================
상장중인데 주가 누락된 종목(backfill_targets.json:gap_price)을
yfinance로 1년치 OHLCV 백필. 백필 후에도 비면 진짜 거래정지.
"""
from __future__ import annotations
import json
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
import yfinance as yf
import FinanceDataReader as fdr

DB = Path(r"C:\Users\Admin\FILMN9\data\filmn9.db")
TARGETS = Path(r"C:\Users\Admin\FILMN9\data\backfill_targets.json")
DAYS = 365


def pad(s): return str(s).zfill(6)


def fetch(code, suffix, since, until):
    df = yf.Ticker(code + suffix).history(
        start=since.strftime("%Y-%m-%d"),
        end=(until + timedelta(days=1)).strftime("%Y-%m-%d"))
    if df.empty:
        return []
    rows = []
    for idx, r in df.iterrows():
        d = idx.strftime("%Y-%m-%d")
        try:
            o, h, l, c = int(r["Open"]), int(r["High"]), int(r["Low"]), int(r["Close"])
            v = int(r["Volume"])
        except (ValueError, KeyError):
            continue
        if any(x <= 0 for x in (o, h, l, c)) or v < 0:
            continue
        if h < max(o, c, l) or l > min(o, c, h):
            continue
        rows.append((code, d, o, h, l, c, v))
    return rows


def main():
    codes = json.load(open(TARGETS, encoding="utf-8"))["gap_price"]
    print(f"주가 백필 대상: {len(codes)}개")

    # 시장 접미사 매핑 (FDR DESC)
    desc = fdr.StockListing("KRX-DESC")
    mkt = {pad(c): ("KQ" if "KOSDAQ" in str(m).upper() else "KS")
           for c, m in zip(desc["Code"], desc["Market"])}

    conn = sqlite3.connect(DB, timeout=120)
    conn.execute("PRAGMA busy_timeout=120000")
    today = datetime.now()
    since = today - timedelta(days=DAYS)
    stat = {"OK": 0, "노데이터": 0, "에러": 0}
    total = 0
    start = time.time()
    for i, code in enumerate(codes, 1):
        suffix = "." + mkt.get(code, "KS")
        # KS 실패 시 KQ도 시도
        try:
            rows = fetch(code, suffix, since, today)
            if not rows:
                alt = ".KQ" if suffix == ".KS" else ".KS"
                rows = fetch(code, alt, since, today)
            if rows:
                conn.executemany("""INSERT INTO ohlcv (stock_code,date,open,high,low,close,volume)
                    VALUES (?,?,?,?,?,?,?)
                    ON CONFLICT(stock_code,date) DO UPDATE SET
                      open=excluded.open,high=excluded.high,low=excluded.low,
                      close=excluded.close,volume=excluded.volume""", rows)
                conn.commit()
                total += len(rows)
                stat["OK"] += 1
            else:
                stat["노데이터"] += 1
        except Exception:
            stat["에러"] += 1
        if i % 50 == 0 or i == len(codes):
            el = time.time() - start
            eta = (len(codes) - i) / (i / el) / 60 if el > 0 else 0
            print(f"  [{i}/{len(codes)}] OK={stat['OK']} 노데이터={stat['노데이터']} "
                  f"에러={stat['에러']} | {total}건 | ETA {eta:.1f}분", flush=True)
        time.sleep(0.15)

    conn.close()
    print(f"\n완료 — {(time.time()-start)/60:.1f}분 / {total}건 적재")
    print(f"채워짐(OK)={stat['OK']} / 여전히 빔(거래정지 확정)={stat['노데이터']} / 에러={stat['에러']}")


if __name__ == "__main__":
    main()
