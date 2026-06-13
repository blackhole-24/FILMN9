# -*- coding: utf-8 -*-
"""21-rev: financials 테이블 '매출 None' 보강 (확장 매출 계정명 + 원가법 폴백).
대상: revenue IS NULL AND op_income IS NOT NULL 인 (종목,연도,보고서) — 4개 데이터셋 전체.
원인: 일부 기업이 매출을 '매출 및 기타수익'(LG화학)·'보험료수익' 등 비표준 명칭으로 표기.
방법: DART fnlttSinglAcntAll 재호출 → 확장 매출명 우선매칭, 없으면 매출원가+매출총이익(원가법 항등식).
스케일은 기존 20d/20e/20f와 동일한 adaptive(anchor=자산 or 매출) 사용.
"""
import json, urllib.request, urllib.parse, re, sqlite3, psycopg, time
from pathlib import Path

ROOT = Path(r"C:\Users\Admin\FILMN9")
KEY = re.search(r"DART_API_KEY=(\S+)", (ROOT / ".env").read_text(encoding="utf-8")).group(1)
url = [l.split("=", 1)[1].strip() for l in (ROOT / ".env").read_text(encoding="utf-8", errors="ignore").splitlines()
       if l.strip().startswith("DATABASE_URL=")][0]

def norm(n):
    n = re.sub(r"^\s*[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫXVIxvi0-9]+\s*[.)]\s*", "", n or "")
    return re.sub(r"\(.*?\)", "", n).replace(" ", "").strip()

# 우선순위 매출 계정명 (앞쪽일수록 우선). norm() 적용 기준.
REV_NAMES = ["매출액", "영업수익", "매출및기타수익", "영업수익및기타수익",
             "보험료수익", "경과보험료", "보험영업수익", "수익매출액", "매출", "수익"]

def fetch(cc, yr, rc, fs):
    p = {"crtfc_key": KEY, "corp_code": cc, "bsns_year": yr, "reprt_code": rc, "fs_div": fs}
    try:
        d = json.loads(urllib.request.urlopen(
            "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json?" + urllib.parse.urlencode(p),
            timeout=12).read().decode("utf-8"))
        return d.get("list", []) if d.get("status") == "000" else []
    except Exception:
        return []

def extract_rev_assets(lst):
    """매출(확장+폴백), 자산총계 추출."""
    byname = {}
    cogs = gp = None
    assets = None
    for it in lst:
        if it.get("sj_div") not in ("IS", "CIS", "BS"):
            continue
        nm = norm(it.get("account_nm", ""))
        amt = it.get("thstrm_amount")
        if amt is None or str(amt).strip() in ("", "-"):
            continue
        try:
            v = float(str(amt).replace(",", ""))
        except Exception:
            continue
        if nm not in byname:
            byname[nm] = v
        if nm == "매출원가" and cogs is None:
            cogs = v
        if nm == "매출총이익" and gp is None:
            gp = v
        if nm == "자산총계" and assets is None:
            assets = v
    rev = None
    for cand in REV_NAMES:               # 우선순위 매칭
        if cand in byname:
            rev = byname[cand]
            break
    if rev is None and cogs is not None and gp is not None:   # 원가법 폴백
        rev = abs(cogs) + gp
    return rev, assets

# 대상 수집
pg = psycopg.connect(url, autocommit=True, connect_timeout=30)
targets = pg.execute(
    "SELECT stock_code, fiscal_year, reprt_code FROM financials "
    "WHERE revenue IS NULL AND op_income IS NOT NULL ORDER BY fiscal_year DESC, stock_code"
).fetchall()
print(f"대상 {len(targets)}건 (매출null·영업익있음)")

corp = json.load(open(ROOT / "data" / "corp_code_map.json", encoding="utf-8")).get("by_stock_code", {})
sq = sqlite3.connect(str(ROOT / "data" / "filmn9.db"))

fixed = 0
t0 = time.time()
for i, (code, yr, rc) in enumerate(targets, 1):
    cc = corp.get(code, {}).get("corp_code")
    if not cc:
        continue
    lst = fetch(cc, str(yr), rc, "CFS") or fetch(cc, str(yr), rc, "OFS")
    if not lst:
        continue
    rev, assets = extract_rev_assets(lst)
    if rev is None:
        continue
    anchor = abs(assets or 0) or abs(rev or 0)
    div = 1_000_000 if anchor >= 1e9 else 1_000 if anchor >= 1e6 else 1
    rev_mil = round(rev / div)
    pg.execute("UPDATE financials SET revenue=%s WHERE stock_code=%s AND fiscal_year=%s AND reprt_code=%s",
               (rev_mil, code, yr, rc))
    sq.execute("UPDATE financials SET revenue=? WHERE stock_code=? AND fiscal_year=? AND reprt_code=?",
               (rev_mil, code, yr, rc))
    fixed += 1
    time.sleep(0.05)
    if i % 100 == 0:
        sq.commit()
        print(f"  {i}/{len(targets)} ... 보강 {fixed} ({time.time()-t0:.0f}s)")
sq.commit()

print(f"\n=== 완료: {fixed}건 매출 보강 ({time.time()-t0:.0f}s) ===")
chk = pg.execute("SELECT revenue,op_income,net_income FROM financials WHERE stock_code='051910' AND fiscal_year=2026 AND reprt_code='11013'").fetchone()
print(f"LG화학 2026 Q1: 매출={chk[0]} 영업익={chk[1]} 순익={chk[2]} (백만원)" if chk else "LG 없음")
rem = pg.execute("SELECT COUNT(*) FROM financials WHERE revenue IS NULL AND op_income IS NOT NULL").fetchone()[0]
print(f"남은 매출null(영업익있음): {rem}건")
sq.close(); pg.close()
