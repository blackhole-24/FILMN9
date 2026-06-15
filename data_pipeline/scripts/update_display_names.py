# -*- coding: utf-8 -*-
"""
company_info 표시명을 KRX 종목명 기준으로 통일.
 - legal_name 컬럼 신설: 기존 DART 법인 정식명 보존 (출처 명확)
 - corp_name: KRX 종목명(FDR DESC Name)으로 갱신 → 네이버·KRX·키움과 동일 표기
   (FDR에 없으면 ticker_universe.csv → 기존값 순 폴백)
"""
import csv
import sqlite3
from pathlib import Path
import FinanceDataReader as fdr

DB = Path(r"C:\Users\Admin\FILMN9\data\filmn9.db")
CSV = Path(r"C:\Users\Admin\FILMN9\data\ticker_universe.csv")


def pad(s): return str(s).zfill(6)


def main():
    krx = {pad(c): str(n) for c, n in
           zip(fdr.StockListing("KRX-DESC")["Code"], fdr.StockListing("KRX-DESC")["Name"])}
    tu = {}
    if CSV.exists():
        for r in csv.DictReader(open(CSV, encoding="utf-8-sig")):
            sc = (r.get("stock_code") or "").strip()
            if sc:
                tu[sc] = (r.get("corp_name") or "").strip()

    conn = sqlite3.connect(DB, timeout=120)
    conn.execute("PRAGMA busy_timeout=120000")
    cols = [r[1] for r in conn.execute("PRAGMA table_info(company_info)").fetchall()]
    if "legal_name" not in cols:
        conn.execute("ALTER TABLE company_info ADD COLUMN legal_name TEXT")
        # 기존 corp_name(법인 정식명) 보존
        conn.execute("UPDATE company_info SET legal_name = corp_name WHERE legal_name IS NULL")

    rows = conn.execute("SELECT stock_code, corp_name FROM company_info").fetchall()
    upd = 0
    for code, cur in rows:
        disp = krx.get(code) or tu.get(code) or cur
        if disp and disp != cur:
            conn.execute("UPDATE company_info SET corp_name=? WHERE stock_code=?", (disp, code))
            upd += 1
    conn.commit()
    print(f"표시명(corp_name) KRX 종목명으로 갱신: {upd}개")
    print("검증:")
    for cd in ("080160", "042700", "005930", "035420"):
        r = conn.execute("SELECT corp_name, legal_name FROM company_info WHERE stock_code=?", (cd,)).fetchone()
        print(f"  {cd}: 표시명='{r[0]}' / 법인명='{r[1]}'")
    conn.close()


if __name__ == "__main__":
    main()
