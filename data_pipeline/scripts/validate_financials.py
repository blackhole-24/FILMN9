# -*- coding: utf-8 -*-
"""
validate_financials.py
======================
① 내부 일관성·계산 검증 (전 종목, 외부호출 0)
② DART 표본 대조 (파싱본 정확도)
결과: 룰별 통과/실패 집계 + DART 일치율
"""
import re, sqlite3, json, urllib.request, urllib.parse, random
from pathlib import Path

DB = Path(r"C:\Users\Admin\FILMN9\data\filmn9.db")
ENV = Path(r"C:\Users\Admin\FILMN9\.env")


def norm(nm):
    return re.sub(r"\(.*?\)", "", nm or "").replace(" ", "").replace("(", "").replace(")", "").strip()


def load_fd():
    """종목별 최신연도 손익/재무 계정 (연결 우선) → dict"""
    conn = sqlite3.connect(DB)
    latest = dict(conn.execute("""SELECT stock_code, MAX(fiscal_year) FROM financial_detail
        WHERE fiscal_year BETWEEN 2022 AND 2025 GROUP BY stock_code""").fetchall())
    rows = conn.execute("SELECT stock_code,fiscal_year,statement_scope,account_nm,amount FROM financial_detail").fetchall()
    fin = {r[0]: r[1:] for r in conn.execute("SELECT stock_code,revenue,op_income,net_income,debt_ratio FROM financials").fetchall()}
    src = {}
    for code, s in conn.execute("SELECT stock_code, source FROM financial_detail GROUP BY stock_code").fetchall():
        src[code] = s
    conn.close()
    bag = {}
    for code, fy, scope, acc, amt in rows:
        if latest.get(code) != fy or amt is None:
            continue
        bag.setdefault(code, {}).setdefault((norm(acc), scope or ""), amt)
    return bag, fin, latest, src


def pick(d, keys):
    for sc in ("연결", "별도", ""):
        for k in keys:
            if (k, sc) in d:
                return d[(k, sc)]
    return None


ACC = {
    "rev": ["매출액", "영업수익", "수익", "매출"], "cogs": ["매출원가"], "gp": ["매출총이익"],
    "sga": ["판매비와관리비"], "op": ["영업이익", "영업이익손실"],
    "assets": ["자산총계"], "liab": ["부채총계"], "equity": ["자본총계"],
    "ca": ["유동자산"], "cl": ["유동부채"], "ni": ["당기순이익", "당기순이익손실"],
}


def close(a, b, tol=0.01):
    if a is None or b is None or b == 0:
        return None
    return abs(a - b) / abs(b) <= tol


def run_internal():
    bag, fin, latest, src = load_fd()
    codes = set(bag) | set(fin)
    R = {}
    def rec(name, ok):
        d = R.setdefault(name, [0, 0, 0])  # pass, fail, na
        d[0 if ok is True else 1 if ok is False else 2] += 1

    fails = {}
    for c in codes:
        d = bag.get(c, {})
        g = lambda k: pick(d, ACC[k])
        rev, cogs, gp, sga, op = g("rev"), g("cogs"), g("gp"), g("sga"), g("op")
        assets, liab, eq, ca, cl, ni = g("assets"), g("liab"), g("equity"), g("ca"), g("cl"), g("ni")
        # R1 자산=부채+자본
        r = close(assets, (liab or 0) + (eq or 0)) if (assets and (liab or eq)) else None
        rec("R1 자산총계=부채+자본", r); _flag(fails, "R1", c, r)
        # R2 매출총이익=매출-매출원가
        r = close(gp, rev - cogs) if (gp is not None and rev and cogs is not None) else None
        rec("R2 매출총이익=매출-매출원가", r)
        # R3 영업이익=매출총이익-판관비
        r = close(op, gp - sga) if (op is not None and gp is not None and sga is not None) else None
        rec("R3 영업이익=매출총이익-판관비", r)
        # R4 하이라이트 ↔ detail 매출 일치 (financials는 백만원, detail은 원→/1e6 가정 비교는 비율로)
        fr = (fin.get(c) or [None])[0] if c in fin else None
        # financials.revenue(백만) vs detail rev → 비율 1:1 (스케일 약분 위해 op/rev 비교 대신 매출 직접: detail/1e6)
        r = close(fr, rev/1e6) if (fr and rev) else None
        rec("R4 하이라이트매출 ↔ 사업보고서매출", r); _flag(fails, "R4", c, r)
        # R5 부채비율 재계산
        dr = fin.get(c)[3] if (c in fin and fin[c][3] is not None) else None
        calc = (liab/eq*100) if (liab and eq and eq != 0) else None
        r = close(dr, calc) if (dr is not None and calc is not None) else None
        rec("R5 부채비율 계산일치", r)
        # R6 결측 (하이라이트 매출 없음)
        rec("R6 매출 결측 없음", (fr is not None and fr != 0))
        # R7 이상치 (자산<=0, 부채비율 음수/과대)
        bad = (assets is not None and assets <= 0) or (dr is not None and (dr < 0 or dr > 10000))
        rec("R7 이상치(음수자산·극단부채비율) 없음", (not bad) if (assets is not None or dr is not None) else None)
    return R, fails


def _flag(fails, rule, code, r):
    if r is False:
        fails.setdefault(rule, []).append(code)


def run_dart_sample(n=120):
    key = re.search(r"DART_API_KEY=(\S+)", ENV.read_text(encoding="utf-8")).group(1)
    corp = json.load(open(r"C:\Users\Admin\FILMN9\data\corp_code_map.json", encoding="utf-8")).get("by_stock_code", {})
    bag, fin, latest, src = load_fd()
    # 파싱본(XML/JSONL)만 표본
    parsed = [c for c in bag if src.get(c) and ("XML" in src[c] or "JSONL" in src[c])]
    random.seed(42)
    sample = random.sample(parsed, min(n, len(parsed)))
    match = mismatch = noref = 0
    samples_bad = []
    for c in sample:
        cc = (corp.get(c) or {}).get("corp_code")
        if not cc:
            noref += 1; continue
        try:
            p = {"crtfc_key": key, "corp_code": cc, "bsns_year": "2024", "reprt_code": "11011", "fs_div": "CFS"}
            d = json.loads(urllib.request.urlopen("https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json?" + urllib.parse.urlencode(p), timeout=12).read().decode("utf-8"))
            lst = d.get("list", [])
        except Exception:
            noref += 1; continue
        if not lst:
            noref += 1; continue
        # DART 매출액(당기) 추출
        dart_rev = None
        for it in lst:
            if norm(it.get("account_nm", "")) in ("매출액", "영업수익", "수익") and it.get("thstrm_amount"):
                try:
                    dart_rev = float(str(it["thstrm_amount"]).replace(",", "")); break
                except: pass
        our_rev = pick(bag[c], ACC["rev"])
        if dart_rev and our_rev:
            if close(our_rev, dart_rev, 0.02):
                match += 1
            else:
                mismatch += 1
                if len(samples_bad) < 10:
                    samples_bad.append((c, our_rev, dart_rev))
        else:
            noref += 1
    return len(sample), match, mismatch, noref, samples_bad


if __name__ == "__main__":
    import sys
    if "--dart" in sys.argv:
        tot, m, mm, nr, bad = run_dart_sample(120)
        print(f"DART 표본 대조: 표본 {tot} / 일치 {m} / 불일치 {mm} / 대조불가 {nr}")
        print(f"일치율(대조가능분): {m*100//max(m+mm,1)}%")
        for c, o, d in bad: print(f"  불일치 {c}: 우리={o:,.0f} DART={d:,.0f}")
    else:
        R, fails = run_internal()
        print("=== 내부 일관성 검증 (pass/fail/na) ===")
        for k, v in R.items():
            tot = v[0] + v[1]
            rate = v[0]*100//max(tot, 1)
            print(f"  {k}: 통과 {v[0]} / 실패 {v[1]} / 해당없음 {v[2]}  → 통과율 {rate}%")
        print("\nR4(하이라이트↔매출) 실패 샘플:", (fails.get("R4") or [])[:10])
        print("R1(항등식) 실패 샘플:", (fails.get("R1") or [])[:10])
