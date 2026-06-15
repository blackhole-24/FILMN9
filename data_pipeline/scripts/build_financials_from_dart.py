# -*- coding: utf-8 -*-
"""
build_financials_from_dart.py
=============================
재무 하이라이트·건전성용 financials 테이블을 DART API(진실원천)에서 직접 재적재.
 - fnlttSinglAcntAll (연결 CFS, 직전 사업연도) → 매출/영익/순익/자산/부채/자본
 - 모두 원 단위 → /1e6 백만원 통일 (소스 단위 불일치 근본 해소)
"""
import re, json, sqlite3, urllib.request, urllib.parse, time
from datetime import datetime
from pathlib import Path

ROOT = Path(r"C:\Users\Admin\FILMN9")
DB = ROOT / "data" / "filmn9.db"
ENV = ROOT / ".env"
CORP = ROOT / "data" / "corp_code_map.json"
KEY = re.search(r"DART_API_KEY=(\S+)", ENV.read_text(encoding="utf-8")).group(1)
NOW = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
YEAR = "2024"   # 직전 완료 사업연도 (DART 확정치)


def norm(n): return re.sub(r"\(.*?\)", "", n or "").replace(" ", "").strip()


WANT = {
    "rev": ["매출액", "영업수익", "수익"], "op": ["영업이익"], "ni": ["당기순이익"],
    "assets": ["자산총계"], "liab": ["부채총계"], "equity": ["자본총계"],
}


def fetch(corp_code, fs):
    p = {"crtfc_key": KEY, "corp_code": corp_code, "bsns_year": YEAR,
         "reprt_code": "11011", "fs_div": fs}
    try:
        d = json.loads(urllib.request.urlopen(
            "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json?" + urllib.parse.urlencode(p),
            timeout=12).read().decode("utf-8"))
        return d.get("list", []) if d.get("status") == "000" else []
    except Exception:
        return []


def extract(lst):
    vals = {}
    for it in lst:
        nm = norm(it.get("account_nm", ""))
        amt = it.get("thstrm_amount")
        if not amt:
            continue
        try:
            v = float(str(amt).replace(",", ""))
        except Exception:
            continue
        for key, names in WANT.items():
            if key not in vals and nm in names:
                vals[key] = v
    return vals


def _norm(n): return re.sub(r"\(.*?\)", "", n or "").replace(" ", "").replace("(", "").replace(")", "").strip()


def fallback_from_detail(conn, done):
    """DART 미보유 종목 → financial_detail에서 adaptive 스케일로 보완 (fy=YEAR 통일)"""
    REV=("매출액","영업수익","수익","매출"); OP=("영업이익","영업이익손실"); NI=("당기순이익","당기순이익손실")
    AS=("자산총계",); LI=("부채총계",); EQ=("자본총계",)
    latest=dict(conn.execute("SELECT stock_code,MAX(fiscal_year) FROM financial_detail WHERE fiscal_year BETWEEN 2022 AND 2025 GROUP BY stock_code").fetchall())
    rows=conn.execute("SELECT stock_code,fiscal_year,statement_scope,account_nm,amount FROM financial_detail").fetchall()
    bag={}
    for c,fy,sc,acc,amt in rows:
        if latest.get(c)!=fy or amt is None: continue
        bag.setdefault(c,{}).setdefault((_norm(acc),sc or ""),amt)
    def pick(d,ks):
        for s in ("연결","별도",""):
            for k in ks:
                if (k,s) in d: return d[(k,s)]
        return None
    n=0
    for c,d in bag.items():
        if c in done: continue
        g=lambda ks: pick(d,ks)
        rev=g(REV); a=g(AS)
        anchor=abs(a or 0) or abs(rev or 0)
        div=1_000_000 if anchor>=1e9 else 1_000 if anchor>=1e6 else 1
        f=lambda x: round(x/div) if x is not None else None
        rv,op,ni=f(g(REV)),f(g(OP)),f(g(NI)); li,eq=f(g(LI)),f(g(EQ))
        dr=round((g(LI))/(g(EQ))*100,2) if (g(LI) and g(EQ)) else None
        if rv is not None or op is not None:
            conn.execute("""INSERT OR REPLACE INTO financials
                (stock_code,fiscal_year,revenue,op_income,net_income,assets,liabilities,equity,debt_ratio,unit,source,generated_at,loaded_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (c,int(YEAR),rv,op,ni,f(g(AS)),li,eq,dr,"백만원","financial_detail 추정(DART미보유)",NOW,NOW))
            n+=1
    conn.commit()
    return n


def main():
    corp = json.load(open(CORP, encoding="utf-8")).get("by_stock_code", {})
    conn = sqlite3.connect(DB, timeout=120)
    conn.execute("PRAGMA busy_timeout=120000")
    conn.execute("DELETE FROM financials")   # 전체 비우고 단일 기준(FY2024) 재구축
    conn.commit()
    done = set()
    targets = [c for c in corp if len(c) == 6 and corp[c].get("corp_code")]
    print(f"DART 재무 재적재 대상: {len(targets)}개 (FY{YEAR}, 연결우선)")
    ok = miss = 0
    t0 = time.time()
    for i, code in enumerate(targets, 1):
        cc = corp[code]["corp_code"]
        lst = fetch(cc, "CFS") or fetch(cc, "OFS")   # 연결 우선, 없으면 별도
        if not lst:
            miss += 1
        else:
            v = extract(lst)
            if v.get("rev") is not None or v.get("op") is not None:
                f = lambda x: round(v[x] / 1e6) if v.get(x) is not None else None
                liab, eq = v.get("liab"), v.get("equity")
                dr = round(liab / eq * 100, 2) if (liab and eq) else None
                conn.execute("""INSERT OR REPLACE INTO financials
                    (stock_code,fiscal_year,revenue,op_income,net_income,assets,liabilities,equity,
                     debt_ratio,unit,source,generated_at,loaded_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (code, int(YEAR), f("rev"), f("op"), f("ni"), f("assets"), f("liab"), f("equity"),
                     dr, "백만원", "DART API 직접(fnlttSinglAcntAll)", NOW, NOW))
                ok += 1
                done.add(code)
            else:
                miss += 1
        if i % 200 == 0:
            conn.commit()
            el = time.time() - t0
            print(f"  [{i}/{len(targets)}] ok={ok} miss={miss} ETA {(len(targets)-i)/(i/el)/60:.1f}분", flush=True)
        time.sleep(0.06)
    conn.commit()
    fb = fallback_from_detail(conn, done)
    total = conn.execute("SELECT COUNT(DISTINCT stock_code) FROM financials").fetchone()[0]
    conn.close()
    print(f"\n완료 {(time.time()-t0)/60:.1f}분 / DART {ok} / detail폴백 {fb} / 합계 {total} (누락대상 {miss})")


if __name__ == "__main__":
    main()
