# -*- coding: utf-8 -*-
"""20d: DART 2026 1분기(reprt_code=11013) → financials 적재.
- fnlttSinglAcntAll API, 연결(CFS) 우선·없으면 별도(OFS)
- 접두사 정규화, adaptive 스케일(백만원), SQLite+Postgres
- fiscal_year=2026, reprt_code='11013' (분기 구분)"""
import json, urllib.request, urllib.parse, re, sqlite3, psycopg, time
from datetime import datetime
from pathlib import Path

ROOT = Path(r"C:\Users\Admin\FILMN9")
KEY = re.search(r"DART_API_KEY=(\S+)", (ROOT / ".env").read_text(encoding="utf-8")).group(1)
url = [l.split("=", 1)[1].strip() for l in (ROOT / ".env").read_text(encoding="utf-8", errors="ignore").splitlines()
       if l.strip().startswith("DATABASE_URL=")][0]
YEAR, RC = "2026", "11013"
NOW = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def norm(n):
    n = re.sub(r"^\s*[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫXVIxvi0-9]+\s*[.)]\s*", "", n or "")
    return re.sub(r"\(.*?\)", "", n).replace(" ", "").strip()

WANT = {"rev": ["매출액", "영업수익", "수익", "매출"], "op": ["영업이익", "영업이익손실"],
        "ni": ["분기순이익", "분기순이익손실", "당기순이익", "당기순이익손실", "반기순이익", "반기순이익손실",
               "분기순손익", "당기순손익", "반기순손익", "분기손익", "당기손익", "반기손익",
               "연결분기순이익", "연결당기순이익", "연결반기순이익"], "assets": ["자산총계"],
        "liab": ["부채총계"], "equity": ["자본총계"]}
# 합계 줄이 없고 지배/비지배로만 쪼갠 경우의 합산용(연결순이익 = 지배 + 비지배, 회계 정의)
NI_CTRL = ["지배주주순이익", "지배기업소유주지분순이익", "지배기업의소유주에게귀속되는분기순이익",
           "지배기업의소유주에게귀속되는당기순이익", "지배기업의소유주에게귀속되는반기순이익",
           "지배기업소유주지분순손익", "지배주주지분순이익"]
NI_NONCTRL = ["비지배주주순이익", "비지배지분순이익", "비지배지분에귀속되는분기순이익",
              "비지배지분에귀속되는당기순이익", "비지배지분에귀속되는반기순이익", "비지배지분순손익"]

def fetch(cc, fs):
    p = {"crtfc_key": KEY, "corp_code": cc, "bsns_year": YEAR, "reprt_code": RC, "fs_div": fs}
    try:
        d = json.loads(urllib.request.urlopen(
            "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json?" + urllib.parse.urlencode(p),
            timeout=12).read().decode("utf-8"))
        return d.get("list", []) if d.get("status") == "000" else []
    except Exception:
        return []

def extract(lst):
    vals = {}
    ctrl = nonctrl = None
    for it in lst:
        nm = norm(it.get("account_nm", ""))
        amt = it.get("thstrm_amount")
        if not amt:
            continue
        try:
            v = float(str(amt).replace(",", ""))
        except Exception:
            continue
        for k, names in WANT.items():
            if k not in vals and nm in names:
                vals[k] = v
        if ctrl is None and nm in NI_CTRL:
            ctrl = v
        if nonctrl is None and nm in NI_NONCTRL:
            nonctrl = v
    # 합계 줄이 없으면 지배+비지배로 연결순이익 산출 (회계 정의, NO-MOCK)
    if "ni" not in vals and ctrl is not None:
        vals["ni"] = ctrl + (nonctrl or 0)
    return vals

corp = json.load(open(ROOT / "data" / "corp_code_map.json", encoding="utf-8")).get("by_stock_code", {})
targets = [c for c in corp if len(c) == 6 and corp[c].get("corp_code")]
print(f"대상 {len(targets)}종 · DART 2026 1분기 수집 시작")

recs = []
t0 = time.time()
for i, code in enumerate(targets, 1):
    cc = corp[code]["corp_code"]
    lst = fetch(cc, "CFS") or fetch(cc, "OFS")
    if lst:
        v = extract(lst)
        rev, a = v.get("rev"), v.get("assets")
        anchor = abs(a or 0) or abs(rev or 0)
        div = 1_000_000 if anchor >= 1e9 else 1_000 if anchor >= 1e6 else 1
        f = lambda x: round(x / div) if x is not None else None
        li, eq = v.get("liab"), v.get("equity")
        dr = round(li / eq * 100, 2) if (li and eq) else None
        if rev is not None or v.get("op") is not None:
            recs.append((code, 2026, f(rev), f(v.get("op")), f(v.get("ni")), f(a),
                         f(li), f(eq), dr, "백만원", "DART 2026 1분기(11013)", NOW, NOW, "11013"))
    time.sleep(0.06)
    if i % 300 == 0:
        print(f"  {i}/{len(targets)} ... 수집 {len(recs)} ({time.time()-t0:.0f}s)")

cols = ("stock_code,fiscal_year,revenue,op_income,net_income,assets,liabilities,"
        "equity,debt_ratio,unit,source,generated_at,loaded_at,reprt_code")
sq = sqlite3.connect(str(ROOT / "data" / "filmn9.db"))
sq.execute("DELETE FROM financials WHERE fiscal_year=2026 AND reprt_code='11013'")
sq.executemany(f"INSERT OR REPLACE INTO financials ({cols}) VALUES ({','.join('?'*14)})", recs)
sq.commit(); sq.close()
pg = psycopg.connect(url, autocommit=True, connect_timeout=30)
pg.execute("DELETE FROM financials WHERE fiscal_year=2026 AND reprt_code='11013'")
with pg.cursor() as cur:
    cur.executemany(f"INSERT INTO financials ({cols}) VALUES ({','.join(['%s']*14)})", recs)
n = pg.execute("SELECT COUNT(*) FROM financials WHERE reprt_code='11013'").fetchone()[0]
chk = pg.execute("SELECT revenue,op_income,net_income FROM financials WHERE stock_code='005930' AND reprt_code='11013'").fetchone()
pg.close()
print(f"\n=== 완료: 2026 1분기 {n}종 적재 ({time.time()-t0:.0f}s) ===")
def _fmt(x):
    return f"{x:,}" if x is not None else "None"
print(f"삼성전자(005930): 매출={_fmt(chk[0])} 영업익={_fmt(chk[1])} 순익={_fmt(chk[2])} 백만원" if chk else "삼성전자 없음")
ni_cnt = pg2 = None
import psycopg as _pg
_c = _pg.connect(url, autocommit=True, connect_timeout=30)
ni_cnt = _c.execute("SELECT COUNT(*) FROM financials WHERE reprt_code='11013' AND net_income IS NOT NULL").fetchone()[0]
_c.close()
print(f"순이익 채워진 종목: {ni_cnt}종")
