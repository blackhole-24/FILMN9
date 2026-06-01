"""
NAVER FY2024, FY2023 연결 재무제표 보충
- DART API fnlttSinglAcntAll 호출
- bsns_year=2024, 2023 각각
- fs_div=CFS (연결) + OFS (별도)
"""
import os
import sys
import json
import sqlite3
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path

ROOT = Path(r"C:\Users\Admin\FILMN9")
DB   = ROOT / "data" / "filmn9.db"
ENV  = ROOT / ".env"

def load_env():
    for line in ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

load_env()
DART_KEY = os.environ.get("DART_API_KEY", "").strip()

NAVER_CORP = "00266961"
STOCK_CODE = "035420"

def fetch_dart(year: int, fs_div: str):
    url = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
    params = {
        "crtfc_key": DART_KEY,
        "corp_code": NAVER_CORP,
        "bsns_year": str(year),
        "reprt_code": "11011",
        "fs_div": fs_div,
    }
    full = url + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(full, timeout=10) as r:
        data = json.loads(r.read().decode("utf-8"))
    if data.get("status") != "000":
        return []
    return data.get("list", [])

def parse_amount(s):
    if not s:
        return None
    t = str(s).replace(",", "")
    if t.startswith("(") and t.endswith(")"):
        t = "-" + t[1:-1]
    try:
        return float(t)
    except:
        return None

conn = sqlite3.connect(DB)
total = 0

for year in [2024, 2023]:
    for fs_div, scope in [("CFS", "연결"), ("OFS", "별도")]:
        items = fetch_dart(year, fs_div)
        if not items:
            print(f"  FY{year} {scope}: 데이터 없음")
            continue
        rows = []
        for i, it in enumerate(items):
            sj = it.get("sj_div", "")
            if sj not in ("BS", "CIS", "IS"):
                continue
            acc_id = it.get("account_id") or ""
            if not acc_id:
                continue
            amount = parse_amount(it.get("thstrm_amount"))
            rows.append((
                STOCK_CODE, year, sj, acc_id, scope,
                it.get("account_nm") or "", amount, "원", i,
                "DART fnlttSinglAcntAll (NAVER 보충)",
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ))
        # 기존 같은 연도+범위 삭제 후 재적재
        conn.execute("""
            DELETE FROM financial_detail
            WHERE stock_code=? AND fiscal_year=? AND statement_scope=?
        """, (STOCK_CODE, year, scope))
        conn.executemany("""
            INSERT OR REPLACE INTO financial_detail
            (stock_code, fiscal_year, statement_type, account_id, statement_scope,
             account_nm, amount, unit, display_order, source, loaded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)
        conn.commit()
        total += len(rows)
        print(f"  FY{year} {scope}: {len(rows)}건 적재")

print(f"\n총 {total}건 적재 완료")
conn.close()

# 검증
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
print("\n=== NAVER 최종 상태 ===")
for r in conn.execute("""
    SELECT fiscal_year, statement_type, statement_scope, COUNT(*) cnt
    FROM financial_detail WHERE stock_code='035420'
    GROUP BY fiscal_year, statement_type, statement_scope
    ORDER BY fiscal_year DESC, statement_type, statement_scope
"""):
    print(f"  FY{r['fiscal_year']}  {r['statement_type']:3}  {r['statement_scope']:4}  {r['cnt']}건")
conn.close()
