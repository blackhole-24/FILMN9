# -*- coding: utf-8 -*-
"""
_backfill_op_income.py
======================
financials.op_income 이 NULL 인데 매출은 있는 종목(계정명 변형 '영업순손익'·'영업손익'
등으로 기존 빌더가 못 잡은 경우)을 DART fnlttSinglAcntAll 에서 재수집해 채운다.
- 기존 빌더는 '영업이익' 만 매칭 → '영업순손익'(예: 원익IPS) 누락 → 영업이익 빈칸.
- 확장 매칭: norm() 으로 괄호 제거 후 {영업이익, 영업손익, 영업순손익} 중 하나.
- 연결(CFS) 우선, 없으면 별도(OFS). 원 단위 → /1e6 백만원 통일(기존 테이블과 동일).
- op_income 컬럼만 UPDATE (다른 값 무손상). 실행: python _backfill_op_income.py [--apply]
"""
import re, json, sqlite3, urllib.request, urllib.parse, time, sys
from pathlib import Path

ROOT = Path(r"C:\Users\Admin\FILMN9")
DB   = ROOT / "data" / "filmn9.db"
ENV  = ROOT / ".env"
CORP = ROOT / "data" / "corp_code_map.json"
KEY  = re.search(r"DART_API_KEY=(\S+)", ENV.read_text(encoding="utf-8")).group(1)

APPLY = "--apply" in sys.argv

def norm(n):
    return re.sub(r"\(.*?\)", "", n or "").replace(" ", "").strip()

OP_NAMES = {"영업이익", "영업손익", "영업순손익"}

corp_map = json.load(open(CORP, encoding="utf-8")).get("by_stock_code", {})

_cache = {}
def fetch(corp_code, year, reprt, fs):
    k = (corp_code, year, reprt, fs)
    if k in _cache:
        return _cache[k]
    p = {"crtfc_key": KEY, "corp_code": corp_code, "bsns_year": str(year),
         "reprt_code": str(reprt), "fs_div": fs}
    try:
        d = json.loads(urllib.request.urlopen(
            "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json?" + urllib.parse.urlencode(p),
            timeout=15).read().decode("utf-8"))
        lst = d.get("list", []) if d.get("status") == "000" else []
    except Exception:
        lst = []
    _cache[k] = lst
    return lst

def find_op(lst):
    for it in lst:
        if norm(it.get("account_nm", "")) in OP_NAMES:
            amt = it.get("thstrm_amount")
            if amt:
                try:
                    return float(str(amt).replace(",", ""))
                except Exception:
                    pass
    return None

con = sqlite3.connect(str(DB)); cur = con.cursor()
rows = cur.execute(
    "SELECT stock_code, fiscal_year, reprt_code FROM financials "
    "WHERE op_income IS NULL AND revenue IS NOT NULL").fetchall()
print(f"대상 NULL op_income 행: {len(rows)}")

fixed = 0; miss = 0; nocorp = 0; updates = []
for sc, fy, rc in rows:
    info = corp_map.get(sc)
    if not info or not info.get("corp_code"):
        nocorp += 1; continue
    cc = info["corp_code"]
    val = None
    for fs in ("CFS", "OFS"):
        lst = fetch(cc, fy, rc or "11011", fs)
        val = find_op(lst)
        if val is not None:
            break
        time.sleep(0.04)
    if val is None:
        miss += 1; continue
    op_mil = val / 1e6  # 원 → 백만원
    updates.append((op_mil, sc, fy, rc))
    fixed += 1
    if fixed <= 12:
        print(f"  {sc} {fy} rc={rc}: 영업이익 {op_mil:,.0f} 백만원")

print(f"\n채울 수 있음: {fixed} · DART에도 없음: {miss} · corp_code 없음: {nocorp}")
if APPLY and updates:
    for op_mil, sc, fy, rc in updates:
        if rc is None:
            cur.execute("UPDATE financials SET op_income=? WHERE stock_code=? AND fiscal_year=? AND reprt_code IS NULL",
                        (op_mil, sc, fy))
        else:
            cur.execute("UPDATE financials SET op_income=? WHERE stock_code=? AND fiscal_year=? AND reprt_code=?",
                        (op_mil, sc, fy, rc))
    con.commit()
    print(f"✅ APPLY 완료: {len(updates)}행 UPDATE (SQLite)")
else:
    print("ℹ️ dry-run (적용하려면 --apply). RDS 동기화는 별도.")
con.close()
