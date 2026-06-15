# -*- coding: utf-8 -*-
"""ticker_suffix 테이블 생성: 종목코드 → yfinance 접미사(.KS/.KQ). realtime 정확도용."""
import sqlite3
from pathlib import Path
import FinanceDataReader as fdr

DB = Path(r"C:\Users\Admin\FILMN9\data\filmn9.db")


def pad(s): return str(s).zfill(6)


def main():
    desc = fdr.StockListing("KRX-DESC")
    rows = []
    for c, m in zip(desc["Code"], desc["Market"]):
        mk = str(m).upper()
        suffix = ".KS" if "KOSPI" in mk else ".KQ"  # KOSDAQ/KOSDAQ GLOBAL/KONEX → .KQ
        rows.append((pad(c), suffix, str(m)))
    conn = sqlite3.connect(DB, timeout=120)
    conn.execute("PRAGMA busy_timeout=120000")
    conn.execute("""CREATE TABLE IF NOT EXISTS ticker_suffix (
        stock_code TEXT PRIMARY KEY, suffix TEXT, market TEXT)""")
    conn.execute("DELETE FROM ticker_suffix")
    conn.executemany("INSERT OR REPLACE INTO ticker_suffix VALUES (?,?,?)", rows)
    conn.commit()
    ks = sum(1 for r in rows if r[1] == ".KS")
    kq = len(rows) - ks
    print(f"ticker_suffix 적재: {len(rows)}개 (.KS={ks} / .KQ={kq})")
    conn.close()


if __name__ == "__main__":
    main()
