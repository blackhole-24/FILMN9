# -*- coding: utf-8 -*-
"""ohlcv(주가 1,067만행)만 Supabase에 COPY 적재."""
import psycopg, time
from pathlib import Path

ROOT = Path(r"C:\Users\Admin\FILMN9")
p = ROOT / "data" / "db_migration_export" / "ohlcv.csv"
url = [l.split("=", 1)[1].strip() for l in (ROOT / ".env").read_text(encoding="utf-8", errors="ignore").splitlines()
       if l.strip().startswith("DATABASE_URL=")][0]

conn = psycopg.connect(url, autocommit=True, connect_timeout=30)
# 일부 주가값이 INTEGER(21억) 초과 → BIGINT로 확대 (원본 보존, NO-MOCK)
for col in ("open", "high", "low", "close"):
    conn.execute(f'ALTER TABLE "ohlcv" ALTER COLUMN "{col}" TYPE BIGINT')
conn.execute('TRUNCATE "ohlcv"')  # 중복 방지(현재 0행이라 무해)
conn.execute("SET statement_timeout = 0")  # 대용량 COPY → 시간제한 해제

t0 = time.time()
with open(p, "r", encoding="utf-8") as f:
    header = f.readline().rstrip("\n\r")
    cols = ",".join(f'"{c}"' for c in header.split(","))
    f.seek(0)
    sql = f'COPY "ohlcv" ({cols}) FROM STDIN WITH (FORMAT CSV, HEADER true, NULL \'\')'
    with conn.cursor() as cur:
        with cur.copy(sql) as cp:
            while chunk := f.read(1 << 20):
                cp.write(chunk)

n = conn.execute('SELECT COUNT(*) FROM "ohlcv"').fetchone()[0]
size = conn.execute("SELECT pg_size_pretty(pg_database_size(current_database()))").fetchone()[0]
print(f"ohlcv 적재 완료: {n:,}행 ({time.time()-t0:.0f}s)")
print(f"전체 DB 크기: {size}")
conn.close()
