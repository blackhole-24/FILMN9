# -*- coding: utf-8 -*-
"""20f-fix: financials PK를 (stock_code, fiscal_year) → (stock_code, fiscal_year, reprt_code)로 확장.
- 분기(11013)+연간(11011)을 같은 연도에 공존시키기 위함(2026 Q1 YoY용 2025 Q1 보관).
- DART 재호출 없음: 이미 받은 정상 데이터로 양쪽 DB 교차 복구.
  · Postgres: 2025 연간(11011) 온전 → PK확장 후 SQLite의 정상 2025 Q1(11013) 주입.
  · SQLite: 정상 2025 Q1(11013) 보존(연간이 REPLACE로 깨짐) → PK확장 후 PG의 정상 2025 연간 복구.
- NO-MOCK: 모든 값은 DART 원천. 임의 생성 없음."""
import psycopg, sqlite3
from decimal import Decimal
from pathlib import Path

ROOT = Path(r"C:\Users\Admin\FILMN9")
url = [l.split("=", 1)[1].strip() for l in (ROOT / ".env").read_text(encoding="utf-8", errors="ignore").splitlines()
       if l.strip().startswith("DATABASE_URL=")][0]
COLS = ("stock_code,fiscal_year,revenue,op_income,net_income,assets,liabilities,equity,debt_ratio,"
        "cashflow_op,cashflow_inv,cashflow_fin,unit,source,generated_at,loaded_at,reprt_code")
N = len(COLS.split(","))

def deci(rows):
    """Decimal → float (sqlite3가 Decimal 바인딩 못함)."""
    return [tuple(float(x) if isinstance(x, Decimal) else x for x in r) for r in rows]

sq = sqlite3.connect(str(ROOT / "data" / "filmn9.db"))
pg = psycopg.connect(url, autocommit=True, connect_timeout=30)

# 0) 정상 데이터 확보 (마이그레이션 전에 읽어둠)
q1_2025 = sq.execute(f"SELECT {COLS} FROM financials WHERE fiscal_year=2025 AND reprt_code='11013'").fetchall()
annual_2025 = pg.execute(f"SELECT {COLS} FROM financials WHERE fiscal_year=2025 AND reprt_code='11011'").fetchall()
print(f"SQLite 정상 2025 Q1 = {len(q1_2025)}종 / PG 정상 2025 연간 = {len(annual_2025)}종")
# 삼성 검증(읽은 데이터)
chk_q1 = [r for r in q1_2025 if r[0] == '005930']
chk_an = [r for r in annual_2025 if r[0] == '005930']
print(f"  삼성 2025 Q1 매출 = {chk_q1[0][2] if chk_q1 else '없음'} / 2025 연간 매출 = {chk_an[0][2] if chk_an else '없음'}")

# 1) Postgres: PK 확장 + 2025 Q1 주입
pg.execute("ALTER TABLE financials DROP CONSTRAINT IF EXISTS financials_pkey")
pg.execute("ALTER TABLE financials ADD PRIMARY KEY (stock_code, fiscal_year, reprt_code)")
pg.execute("DELETE FROM financials WHERE fiscal_year=2025 AND reprt_code='11013'")
ph = ",".join(["%s"] * N)
with pg.cursor() as cur:
    cur.executemany(f"INSERT INTO financials ({COLS}) VALUES ({ph})", q1_2025)
print("PG 마이그레이션+Q1주입 완료. 분포:")
for r in pg.execute("SELECT fiscal_year, reprt_code, COUNT(*) FROM financials GROUP BY 1,2 ORDER BY 1,2").fetchall():
    print(f"  PG {r[0]}/{r[1]}: {r[2]}종")

# 2) SQLite: PK 확장(테이블 재생성) + 깨진 2025 연간 복구
sq.execute("""CREATE TABLE financials_new (
    stock_code TEXT NOT NULL, fiscal_year INTEGER NOT NULL, revenue REAL, op_income REAL,
    net_income REAL, assets REAL, liabilities REAL, equity REAL, debt_ratio REAL,
    cashflow_op REAL, cashflow_inv REAL, cashflow_fin REAL, unit TEXT DEFAULT '백만원',
    source TEXT, generated_at TEXT, loaded_at TEXT, reprt_code TEXT DEFAULT '11011',
    PRIMARY KEY (stock_code, fiscal_year, reprt_code))""")
# 깨진 2025/11011 제외하고 전부 복사
sq.execute(f"INSERT INTO financials_new ({COLS}) SELECT {COLS} FROM financials "
           f"WHERE NOT (fiscal_year=2025 AND reprt_code='11011')")
# PG의 정상 2025 연간 복구
qm = ",".join(["?"] * N)
sq.executemany(f"INSERT OR REPLACE INTO financials_new ({COLS}) VALUES ({qm})", deci(annual_2025))
sq.execute("DROP TABLE financials")
sq.execute("ALTER TABLE financials_new RENAME TO financials")
sq.commit()
print("SQLite 마이그레이션+연간복구 완료. 분포:")
for r in sq.execute("SELECT fiscal_year, reprt_code, COUNT(*) FROM financials GROUP BY 1,2 ORDER BY 1,2").fetchall():
    print(f"  SQLite {r[0]}/{r[1]}: {r[2]}종")

# 3) 최종 검증: 삼성 4개 데이터셋 + YoY 계산
print("\n=== 삼성전자(005930) 최종 ===")
for r in pg.execute("SELECT fiscal_year,reprt_code,revenue,op_income,net_income FROM financials "
                    "WHERE stock_code='005930' ORDER BY fiscal_year DESC, reprt_code").fetchall():
    print(f"  PG {r[0]}/{r[1]}: 매출={r[2]} 영업익={r[3]} 순익={r[4]}")
q26 = pg.execute("SELECT revenue FROM financials WHERE stock_code='005930' AND fiscal_year=2026 AND reprt_code='11013'").fetchone()
q25 = pg.execute("SELECT revenue FROM financials WHERE stock_code='005930' AND fiscal_year=2025 AND reprt_code='11013'").fetchone()
if q26 and q25 and q25[0]:
    print(f"  → 2026 Q1 매출 YoY = {(q26[0]-q25[0])/abs(q25[0])*100:+.1f}% (2025 Q1 대비)")
sq.close(); pg.close()
print("\n완료.")
