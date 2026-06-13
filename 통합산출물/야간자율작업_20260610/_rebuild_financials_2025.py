# -*- coding: utf-8 -*-
"""[DEPRECATED 2026-06-13 — 재실행 금지]
이 방식(financial_detail 경유)은 financial_detail의 단위 혼재(대형주는 사실상 백만원,
소형주는 원으로 섞여 저장됨) 때문에 adaptive 스케일이 대형주 174종의 매출을 1000배 축소함
(예: 삼성 2025 매출 333조 → 333억). 정본은 DART API 직접 수집 방식인
_refetch_financials_2025.py (20e) 사용. 이 스크립트는 절대 다시 돌리지 말 것.

B-1: financial_detail 2025 → financials(2025 연간) 재생성.
- 로마숫자/번호 접두사(Ⅴ.영업이익·XI.당기순이익) 정규화 → 매칭 누락 해소
- adaptive 스케일(원/천원/백만원 → 백만원 통일)
- SQLite + Postgres 둘 다 적재 (현재 화면=Postgres)
- DART API 미사용(이미 financial_detail에 2025 있음) → 빠름"""
import sqlite3, psycopg, re
from datetime import datetime
from pathlib import Path

ROOT = Path(r"C:\Users\Admin\FILMN9")
NOW = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
url = [l.split("=", 1)[1].strip() for l in (ROOT / ".env").read_text(encoding="utf-8", errors="ignore").splitlines()
       if l.strip().startswith("DATABASE_URL=")][0]

# 로마숫자(유니코드+ASCII)·아라비아 번호 접두사 제거 + 괄호·공백 제거
_PREFIX = re.compile(r"^\s*[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫXVIxvi0-9]+\s*[.)]\s*")
def norm(nm):
    nm = _PREFIX.sub("", nm or "")
    return re.sub(r"\(.*?\)", "", nm).replace(" ", "").strip()

REV = ("매출액", "영업수익", "수익", "매출")
OP  = ("영업이익", "영업이익손실")
NI  = ("당기순이익", "당기순이익손실")
ASv = ("자산총계",); LI = ("부채총계",); EQ = ("자본총계",)

sq = sqlite3.connect(str(ROOT / "data" / "filmn9.db"))
rows = sq.execute("SELECT stock_code, statement_scope, account_nm, amount "
                  "FROM financial_detail WHERE fiscal_year=2025").fetchall()
bag = {}
for c, sc, acc, amt in rows:
    if amt is None:
        continue
    bag.setdefault(c, {}).setdefault((norm(acc), sc or ""), amt)

def pick(d, ks):
    for s in ("연결", "별도", ""):     # 연결 우선, 없으면 별도
        for k in ks:
            if (k, s) in d:
                return d[(k, s)]
    return None

cols = ("stock_code,fiscal_year,revenue,op_income,net_income,assets,"
        "liabilities,equity,debt_ratio,unit,source,generated_at,loaded_at")
recs = []
for c, d in bag.items():
    rev_raw, as_raw, li_raw, eq_raw = pick(d, REV), pick(d, ASv), pick(d, LI), pick(d, EQ)
    op_raw, ni_raw = pick(d, OP), pick(d, NI)
    anchor = abs(as_raw or 0) or abs(rev_raw or 0)
    div = 1_000_000 if anchor >= 1e9 else 1_000 if anchor >= 1e6 else 1
    f = lambda x: round(x / div) if x is not None else None
    dr = round(li_raw / eq_raw * 100, 2) if (li_raw and eq_raw) else None
    if rev_raw is not None or op_raw is not None or as_raw is not None:
        recs.append((c, 2025, f(rev_raw), f(op_raw), f(ni_raw), f(as_raw),
                     f(li_raw), f(eq_raw), dr, "백만원", "financial_detail 2025(정규화)", NOW, NOW))

# SQLite (2025 행만 교체)
sq.execute("DELETE FROM financials WHERE fiscal_year=2025")
sq.executemany(f"INSERT OR REPLACE INTO financials ({cols}) VALUES ({','.join('?'*13)})", recs)
sq.commit()
n_sq = sq.execute("SELECT COUNT(*) FROM financials WHERE fiscal_year=2025").fetchone()[0]
sq.close()

# Postgres (2025 행만 교체)
pg = psycopg.connect(url, autocommit=True, connect_timeout=30)
pg.execute("DELETE FROM financials WHERE fiscal_year=2025")
with pg.cursor() as cur:
    cur.executemany(f"INSERT INTO financials ({cols}) VALUES ({','.join(['%s']*13)})", recs)
n_pg = pg.execute("SELECT COUNT(*) FROM financials WHERE fiscal_year=2025").fetchone()[0]
chk = pg.execute("SELECT fiscal_year,revenue,op_income,net_income FROM financials "
                 "WHERE stock_code='010130' ORDER BY fiscal_year DESC").fetchall()
miss_op = pg.execute("SELECT COUNT(*) FROM financials WHERE fiscal_year=2025 AND op_income IS NOT NULL").fetchone()[0]
pg.close()

print(f"financials 2025 적재: SQLite {n_sq}행 / Postgres {n_pg}행 (영업이익 있는 행 {miss_op})")
print("고려아연(010130):", chk)
