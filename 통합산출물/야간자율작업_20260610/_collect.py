# -*- coding: utf-8 -*-
"""야간 자율작업 데이터 수집: current_price 검증 CSV + SQLite 스키마 추출."""
import sqlite3, csv
from pathlib import Path
from collections import Counter

OUT = Path(__file__).resolve().parent
DB = r"C:\Users\Admin\FILMN9\data\filmn9.db"
c = sqlite3.connect(DB)

# 1) current_price 검증
rows = c.execute('''SELECT v.stock_code, v.corp_name, v.current_price, v.as_of_date,
  v.fair_price, v.upside_pct,
  (SELECT close FROM ohlcv o WHERE o.stock_code=v.stock_code ORDER BY date DESC LIMIT 1),
  (SELECT date  FROM ohlcv o WHERE o.stock_code=v.stock_code ORDER BY date DESC LIMIT 1)
  FROM valuation_summary v ORDER BY v.stock_code''').fetchall()

p = OUT / "current_price_검증.csv"
flagged = 0
with open(p, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["종목코드","종목명","밸류_current_price","밸류_as_of","적정가","상승여력%",
                "ohlcv_최신종가","ohlcv_기준일","괴리%","판정"])
    for sc, nm, cp, ao, fp, up, oc, od in rows:
        gap = round((cp-oc)/oc*100, 1) if cp and oc else None
        verdict = "과대의심" if (gap and gap > 5) else ("과소의심" if (gap and gap < -5) else "정상범위")
        if verdict != "정상범위":
            flagged += 1
        w.writerow([sc, nm, cp, ao, fp, up, oc, od, gap, verdict])
print(f"[1] current_price 검증 CSV 저장: {p.name} / {len(rows)}종 / 의심 {flagged}종")
print("    as_of_date 분포:", dict(Counter(r[3] for r in rows)))

# 2) SQLite 스키마 추출
ddl = [r[0] for r in c.execute(
    "SELECT sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL ORDER BY name")]
p2 = OUT / "_filmn9_sqlite_schema.sql"
p2.write_text(";\n\n".join(ddl) + ";\n", encoding="utf-8")
print(f"[2] SQLite 스키마 저장: {p2.name} / 테이블 {len(ddl)}개")

# 3) 테이블별 행수 (DDL 변환·이관 규모 참고)
tabs = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
print("[3] 테이블 행수:")
for t in tabs:
    try:
        n = c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
    except Exception:
        n = -1
    print(f"    {t:22s} {n:>12,}")
c.close()
