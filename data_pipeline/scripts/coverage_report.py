# -*- coding: utf-8 -*-
"""3000 전수 커버리지 집계"""
import sqlite3
from pathlib import Path

DB = Path(r"C:\Users\Admin\FILMN9\data\filmn9.db")
c = sqlite3.connect(DB)


def tbl_exists(name):
    return c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def dcnt(table, col="stock_code"):
    if not tbl_exists(table):
        return "(테이블 없음)"
    return c.execute(f"SELECT COUNT(DISTINCT {col}) FROM {table}").fetchone()[0]


print("=" * 50)
print(" FILMN9 3000 전수 커버리지 (2026-05-31)")
print("=" * 50)
items = [
    ("기업개요  company_info", "company_info"),
    ("주주      shareholders", "shareholders"),
    ("경영인    executives", "executives"),
    ("재무      financial_detail", "financial_detail"),
    ("OHLCV     ohlcv", "ohlcv"),
    ("경쟁사    peer_competitors", "peer_competitors"),
    ("고객사    company_customers", "company_customers"),
]
for label, t in items:
    print(f"  {label:28s}: {dcnt(t)}")

# 재무 statement_type 별
if tbl_exists("financial_detail"):
    print("-" * 50)
    print("  재무 statement_type 분포(종목수):")
    for st, n in c.execute(
        "SELECT statement_type, COUNT(DISTINCT stock_code) FROM financial_detail GROUP BY statement_type ORDER BY 2 DESC"
    ).fetchall():
        print(f"    {st:6s}: {n}")
    print(f"    총 row: {c.execute('SELECT COUNT(*) FROM financial_detail').fetchone()[0]:,}")

c.close()
