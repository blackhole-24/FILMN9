# -*- coding: utf-8 -*-
"""2b: dcf_result.json 2,224개 → valuation_summary 적재 (SQLite + Postgres).
NO-MOCK: dcf_grade(A~E) 6파일에 없음 → null. 대신 dcf_confidence(엔진 산출) 사용."""
import sqlite3, psycopg, json
from pathlib import Path

ROOT = Path(r"C:\Users\Admin\FILMN9")
VR = ROOT / "data" / "valuation_results"
url = [l.split("=", 1)[1].strip() for l in (ROOT / ".env").read_text(encoding="utf-8", errors="ignore").splitlines()
       if l.strip().startswith("DATABASE_URL=")][0]

# company_info 맵 (corp_name·market·sector)
sq = sqlite3.connect(str(ROOT / "data" / "filmn9.db")); sq.row_factory = sqlite3.Row
ci = {r["stock_code"]: (r["corp_name"], r["market"], r["sector"])
      for r in sq.execute("SELECT stock_code, corp_name, market, sector FROM company_info")}

rows = []
for d in VR.glob("*"):
    f = d / "dcf_result.json"
    if not f.exists():
        continue
    try:
        j = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        continue
    code = j.get("stock_code")
    if not code:
        continue
    nm, mkt, sec = ci.get(code, (None, None, None))
    rows.append((
        code, nm, mkt, sec,
        None,                              # dcf_grade (NO-MOCK: 6파일에 없음)
        j.get("dcf_confidence"),           # high/medium/low (엔진 산출)
        None,                              # peer_confidence_grade
        j.get("fair_value_per_share"),     # fair_price
        j.get("current_price"),
        j.get("upside_pct"),
        j.get("wacc_pct"),                 # wacc
        j.get("as_of_date"),
        "v8",                              # model_version
        "dcf_result.json",                 # source_file
    ))

cols = ["stock_code","corp_name","market","industry","dcf_grade","dcf_confidence",
        "peer_confidence_grade","fair_price","current_price","upside_pct","wacc",
        "as_of_date","model_version","source_file"]

# SQLite 적재 (전체 교체)
sq.execute("DELETE FROM valuation_summary")
sq.executemany(f"INSERT INTO valuation_summary ({','.join(cols)}) VALUES ({','.join('?'*len(cols))})", rows)
sq.commit()
n_sq = sq.execute("SELECT COUNT(*) FROM valuation_summary").fetchone()[0]
sq.close()

# Postgres 적재 (전체 교체)
pg = psycopg.connect(url, autocommit=True, connect_timeout=30)
pg.execute('DELETE FROM valuation_summary')
with pg.cursor() as cur:
    cur.executemany(f'INSERT INTO valuation_summary ({",".join(cols)}) VALUES ({",".join(["%s"]*len(cols))})', rows)
n_pg = pg.execute("SELECT COUNT(*) FROM valuation_summary").fetchone()[0]
# 신뢰도 분포
dist = pg.execute("SELECT dcf_confidence, COUNT(*) FROM valuation_summary GROUP BY dcf_confidence").fetchall()
pg.close()

print(f"적재: SQLite {n_sq}행 / Postgres {n_pg}행")
print("신뢰도 분포:", dict(dist))
