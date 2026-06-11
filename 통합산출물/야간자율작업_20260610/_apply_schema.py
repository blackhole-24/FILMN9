# -*- coding: utf-8 -*-
"""Supabase에 스키마(DDL) 적용 — 02_postgres_schema.sql 실행."""
import psycopg, re
from pathlib import Path

ROOT = Path(r"C:\Users\Admin\FILMN9")
url = ""
for line in (ROOT / ".env").read_text(encoding="utf-8", errors="ignore").splitlines():
    if line.strip().startswith("DATABASE_URL="):
        url = line.split("=", 1)[1].strip()

sql = (ROOT / "통합산출물" / "야간자율작업_20260610" / "02_postgres_schema.sql").read_text(encoding="utf-8")
# 주석(-- ...) 제거 후 ; 로 statement 분리
sql_nocomment = re.sub(r"--[^\n]*", "", sql)
stmts = [s.strip() for s in sql_nocomment.split(";") if s.strip()]

conn = psycopg.connect(url, autocommit=True, connect_timeout=20)
ok, fail = 0, []
for s in stmts:
    try:
        conn.execute(s)
        ok += 1
    except Exception as e:
        fail.append((s[:50], str(e)[:80]))

tabs = [r[0] for r in conn.execute(
    "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").fetchall()]
print(f"실행: {ok} statements 성공 / {len(fail)} 실패")
print(f"생성된 테이블 {len(tabs)}개: {', '.join(tabs)}")
if fail:
    print("\n실패:")
    for s, e in fail:
        print(f"  [{s}...] {e}")
conn.close()
