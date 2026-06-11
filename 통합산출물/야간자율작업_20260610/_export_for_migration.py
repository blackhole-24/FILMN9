# -*- coding: utf-8 -*-
"""DB 이관 준비: SQLite 16테이블 → CSV 덤프 (Postgres \copy 적재용).
대용량 ohlcv(1,067만행)는 마지막에 별도 처리(요금제 결정 후 적재)."""
import sqlite3, csv, time
from pathlib import Path

DB = r"C:\Users\Admin\FILMN9\data\filmn9.db"
OUT = Path(r"C:\Users\Admin\FILMN9\data\db_migration_export")
OUT.mkdir(parents=True, exist_ok=True)

c = sqlite3.connect(DB)
c.row_factory = sqlite3.Row
tabs = [r[0] for r in c.execute(
    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]

# ohlcv는 대용량이라 맨 마지막
tabs = [t for t in tabs if t != "ohlcv"] + (["ohlcv"] if "ohlcv" in tabs else [])

summary = []
for t in tabs:
    t0 = time.time()
    cur = c.execute(f'SELECT * FROM "{t}"')
    cols = [d[0] for d in cur.description]
    p = OUT / f"{t}.csv"
    n = 0
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for row in cur:
            w.writerow([row[col] for col in cols])
            n += 1
    mb = p.stat().st_size / 1024 / 1024
    summary.append((t, n, round(mb, 1), round(time.time()-t0, 1)))
    print(f"  {t:22s} {n:>12,}행  {mb:>8.1f}MB  {time.time()-t0:>5.1f}s")

c.close()
total_mb = sum(s[2] for s in summary)
print(f"\n총 {len(summary)}테이블 / 합계 {total_mb:,.1f}MB → {OUT}")
