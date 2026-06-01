"""
db/verify_data.py - 적재된 데이터 검증용 스크립트
사용: python db/verify_data.py [stock_code]
"""
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "filmn9.db"
code = sys.argv[1] if len(sys.argv) > 1 else "090430"

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

print(f"=== {code} company_info ===")
r = conn.execute("SELECT * FROM company_info WHERE stock_code=?", (code,)).fetchone()
if r:
    for k in r.keys():
        print(f"  {k:15s}: {r[k]}")
else:
    print("  (데이터 없음)")

print(f"\n=== {code} financials (3년치) ===")
rows = conn.execute(
    "SELECT fiscal_year, revenue, op_income, net_income, debt_ratio "
    "FROM financials WHERE stock_code=? ORDER BY fiscal_year DESC", (code,)
).fetchall()
print(f"  {'year':<6}{'revenue':>14}{'op_income':>14}{'net_income':>14}{'debt%':>10}")
for r in rows:
    rev = r["revenue"]; op = r["op_income"]; ni = r["net_income"]; dr = r["debt_ratio"]
    print(f"  {r['fiscal_year']:<6}"
          f"{rev:>14,.0f}" if rev is not None else f"  {r['fiscal_year']:<6}{'':>14}",
          end="")
    print(f"{op:>14,.0f}" if op is not None else f"{'':>14}", end="")
    print(f"{ni:>14,.0f}" if ni is not None else f"{'':>14}", end="")
    print(f"{dr:>10.2f}" if dr is not None else f"{'':>10}")

print(f"\n=== {code} ohlcv 최근 5거래일 ===")
rows = conn.execute(
    "SELECT date, open, high, low, close, volume FROM ohlcv "
    "WHERE stock_code=? ORDER BY date DESC LIMIT 5", (code,)
).fetchall()
print(f"  {'date':<12}{'open':>10}{'high':>10}{'low':>10}{'close':>10}{'volume':>12}")
for r in rows:
    print(f"  {r['date']:<12}{r['open']:>10,}{r['high']:>10,}"
          f"{r['low']:>10,}{r['close']:>10,}{r['volume']:>12,}")

print(f"\n=== {code} ohlcv 전체 범위 ===")
r = conn.execute(
    "SELECT MIN(date) AS min_d, MAX(date) AS max_d, COUNT(*) AS cnt "
    "FROM ohlcv WHERE stock_code=?", (code,)
).fetchone()
print(f"  {r['min_d']} ~ {r['max_d']}  ({r['cnt']:,}일)")

conn.close()
