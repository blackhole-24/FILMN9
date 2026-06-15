# -*- coding: utf-8 -*-
"""
backfill_ohlcv_full.py
======================
주가 차트가 종목당 수주~1년만 있는 문제 해결.
yfinance period='max'로 전체 상장종목 장기 이력(가능한 최대) 전수 백필.
"""
from __future__ import annotations
import sqlite3, time
from datetime import timedelta
from pathlib import Path
import yfinance as yf
import FinanceDataReader as fdr

DB = Path(r"C:\Users\Admin\FILMN9\data\filmn9.db")


def pad(s): return str(s).zfill(6)


def fetch_full(code, suffix):
    df = yf.Ticker(code + suffix).history(period="max", auto_adjust=False)
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
    desc = fdr.StockListing("KRX-DESC")
    targets = [(pad(c), "KQ" if "KOSDAQ" in str(m).upper() else "KS")
               for c, m in zip(desc["Code"], desc["Market"])]
    print(f"장기 이력 백필 대상: {len(targets)}개 (period=max)")

    conn = sqlite3.connect(DB, timeout=120)
    conn.execute("PRAGMA busy_timeout=120000")
    ok = nodata = err = 0
    total = 0
    start = time.time()
    for i, (code, mkt) in enumerate(targets, 1):
        try:
            rows = fetch_full(code, "." + mkt)
            if not rows:
                rows = fetch_full(code, ".KQ" if mkt == "KS" else ".KS")
            if rows:
                conn.executemany("""INSERT INTO ohlcv (stock_code,date,open,high,low,close,volume)
                    VALUES (?,?,?,?,?,?,?)
                    ON CONFLICT(stock_code,date) DO UPDATE SET
                      open=excluded.open,high=excluded.high,low=excluded.low,
                      close=excluded.close,volume=excluded.volume""", rows)
                conn.commit()
                total += len(rows); ok += 1
            else:
                nodata += 1
        except Exception:
            err += 1
        if i % 100 == 0 or i == len(targets):
            el = time.time() - start
            eta = (len(targets) - i) / (i / el) / 60 if el > 0 else 0
            print(f"  [{i}/{len(targets)}] OK={ok} 노데이터={nodata} 에러={err} | {total:,}봉 | ETA {eta:.1f}분", flush=True)
        time.sleep(0.12)
    conn.close()
    print(f"\n완료 — {(time.time()-start)/60:.1f}분 / {total:,}봉 적재 / OK={ok} 노데이터={nodata} 에러={err}")


if __name__ == "__main__":
    main()
