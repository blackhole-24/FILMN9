# -*- coding: utf-8 -*-
"""CSV → Supabase(Postgres) COPY 적재. ohlcv는 인자로 제외/포함 선택."""
import sys, psycopg, time
from pathlib import Path

ROOT = Path(r"C:\Users\Admin\FILMN9")
EXPORT = ROOT / "data" / "db_migration_export"
INCLUDE_OHLCV = "--with-ohlcv" in sys.argv

url = ""
for line in (ROOT / ".env").read_text(encoding="utf-8", errors="ignore").splitlines():
    if line.strip().startswith("DATABASE_URL="):
        url = line.split("=", 1)[1].strip()

# 적재 순서: company_info 먼저(허브), ohlcv 마지막
csvs = sorted(EXPORT.glob("*.csv"))
order = ["company_info"] + [p.stem for p in csvs if p.stem not in ("company_info", "ohlcv")]
if INCLUDE_OHLCV:
    order += ["ohlcv"]

conn = psycopg.connect(url, autocommit=True, connect_timeout=30)
print(f"적재 대상 {len(order)}테이블 (ohlcv {'포함' if INCLUDE_OHLCV else '제외'})\n")

total_rows = 0
for t in order:
    p = EXPORT / f"{t}.csv"
    if not p.exists():
        print(f"  [skip] {t} CSV 없음")
        continue
    t0 = time.time()
    with open(p, "r", encoding="utf-8") as f:
        header = f.readline().rstrip("\n\r")
        if not header:
            print(f"  [skip] {t} 빈 파일")
            continue
        cols = ",".join(f'"{c}"' for c in header.split(","))
        f.seek(0)
        sql = f'COPY "{t}" ({cols}) FROM STDIN WITH (FORMAT CSV, HEADER true, NULL \'\')'
        with conn.cursor() as cur:
            with cur.copy(sql) as cp:
                while chunk := f.read(1 << 20):
                    cp.write(chunk)
    n = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
    total_rows += n
    print(f"  {t:22s} {n:>12,}행  ({time.time()-t0:.1f}s)")

print(f"\n총 적재 행수: {total_rows:,}")
conn.close()
