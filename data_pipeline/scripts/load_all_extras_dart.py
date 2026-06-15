# -*- coding: utf-8 -*-
"""
load_all_extras_dart.py
=======================
DART API 직접 → SQLite 일괄 적재 (3000 전수)
  - 주주구성   : hyslrSttus(최대주주현황) + mrhlSttus(최대주주변동) → shareholders
  - 경영인     : exctvSttus(임원현황) → executives
  - 기업개요   : company.json(기업개황) → company_info

사용:
  python load_all_extras_dart.py --what company   # 기업개요만
  python load_all_extras_dart.py --what all       # 전부
  python load_all_extras_dart.py --limit 50       # 테스트
"""
from __future__ import annotations
import argparse
import json
import os
import sqlite3
import time
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path

ROOT = Path(r"C:\Users\Admin\FILMN9")
DB   = ROOT / "data" / "filmn9.db"
ENV  = ROOT / ".env"
CORP_MAP = ROOT / "data" / "corp_code_map.json"

# .env 로드
for line in ENV.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

DART_KEY = os.environ.get("DART_API_KEY", "").strip()
NOW = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
THIS_YEAR = datetime.now().year


def dart_get(endpoint, params):
    params = {"crtfc_key": DART_KEY, **params}
    url = f"https://opendart.fss.or.kr/api/{endpoint}.json?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))
        if data.get("status") == "000":
            return data.get("list", [])
        return []
    except Exception:
        return []


def to_int(s):
    if s is None:
        return None
    t = str(s).replace(",", "").replace("주", "").strip()
    if t in ("", "-"):
        return None
    try:
        return int(float(t))
    except Exception:
        return None


def to_float(s):
    if s is None:
        return None
    t = str(s).replace(",", "").replace("%", "").strip()
    if t in ("", "-"):
        return None
    try:
        return float(t)
    except Exception:
        return None


# ─── 주주구성 ───────────────────────────────────────────────
def load_shareholders(conn, code, corp_code):
    rows = []
    # 최대주주 현황
    for it in dart_get("hyslrSttus", {"corp_code": corp_code,
                                       "bsns_year": str(THIS_YEAR - 1), "reprt_code": "11011"}):
        rows.append((code, THIS_YEAR - 1, None,
                     it.get("nm", ""), it.get("relate", ""),
                     to_int(it.get("trmend_posesn_stock_co")),
                     to_float(it.get("trmend_posesn_stock_qota_rt")),
                     "DART hyslrSttus", NOW))
    time.sleep(0.12)
    # 5% 이상 대량보유
    for it in dart_get("majorstock", {"corp_code": corp_code}):
        rows.append((code, THIS_YEAR - 1, None,
                     it.get("repror", ""), "5% 이상 보유",
                     to_int(it.get("stkqy")), to_float(it.get("stkrt")),
                     "DART majorstock", NOW))
    time.sleep(0.12)
    if not rows:
        return 0
    conn.execute("DELETE FROM shareholders WHERE stock_code=?", (code,))
    # rank 부여 (ratio 내림차순)
    rows.sort(key=lambda r: -(r[6] or 0))
    rows = [(r[0], r[1], i + 1, *r[3:]) for i, r in enumerate(rows)]
    conn.executemany("""INSERT INTO shareholders
        (stock_code,fiscal_year,rank,name,relation,shares,ratio,source,loaded_at)
        VALUES (?,?,?,?,?,?,?,?,?)""", rows)
    return len(rows)


# ─── 경영인 ─────────────────────────────────────────────────
def load_executives(conn, code, corp_code):
    rows = []
    for i, it in enumerate(dart_get("exctvSttus", {"corp_code": corp_code,
                                                    "bsns_year": str(THIS_YEAR - 1), "reprt_code": "11011"})):
        rows.append((code, THIS_YEAR - 1, i + 1,
                     it.get("nm", ""), it.get("ofcps", ""),
                     it.get("rgist_exctv_at", "") + " / " + it.get("fte_at", ""),
                     it.get("birth_ym", "")[:4] if it.get("birth_ym") else "",
                     it.get("main_career", ""), None,
                     it.get("hffc_pd", ""), it.get("tenure_end_on", ""),
                     "DART exctvSttus", NOW))
    time.sleep(0.12)
    if not rows:
        return 0
    conn.execute("DELETE FROM executives WHERE stock_code=?", (code,))
    conn.executemany("""INSERT INTO executives
        (stock_code,fiscal_year,rank,name,position,role,birth_year,career,shares,appointed_at,term_end,source,loaded_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
    return len(rows)


# ─── 기업개요 ───────────────────────────────────────────────
def load_company(conn, code, corp_code, fallback_name, market):
    url = f"https://opendart.fss.or.kr/api/company.json?" + urllib.parse.urlencode(
        {"crtfc_key": DART_KEY, "corp_code": corp_code})
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            d = json.loads(r.read().decode("utf-8"))
        if d.get("status") != "000":
            d = {}
    except Exception:
        d = {}
    time.sleep(0.12)
    conn.execute("""INSERT INTO company_info
        (stock_code,corp_name,market,sector,listing_date,ceo,employees,homepage,address,phone,fiscal_month,source,generated_at,loaded_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(stock_code) DO UPDATE SET
          corp_name=excluded.corp_name, market=excluded.market, ceo=excluded.ceo,
          homepage=excluded.homepage, address=excluded.address, phone=excluded.phone,
          listing_date=excluded.listing_date, loaded_at=excluded.loaded_at""",
        (code, d.get("corp_name", fallback_name), market, d.get("induty_code", ""),
         d.get("est_dt", ""), d.get("ceo_nm", ""), None,
         d.get("hm_url", ""), d.get("adres", ""), d.get("phn_no", ""),
         to_int(d.get("acc_mt")), "DART company.json", NOW, NOW))
    return 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--what", choices=["company", "shareholders", "executives", "all"], default="all")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--skip-existing", action="store_true", help="이미 적재된 종목 건너뛰기")
    args = ap.parse_args()

    corp_map = json.loads(CORP_MAP.read_text(encoding="utf-8")).get("by_stock_code", {})
    # 6자리 종목코드만
    targets = [(c, v) for c, v in corp_map.items()
               if len(c) == 6 and v.get("corp_code")]
    if args.limit:
        targets = targets[:args.limit]

    conn = sqlite3.connect(DB, timeout=120)
    conn.execute("PRAGMA busy_timeout=120000")   # 락 시 최대 120초 대기
    print(f"대상 종목: {len(targets)}개 / 작업: {args.what}")
    start = time.time()
    stat = {"sh": 0, "ex": 0, "co": 0, "err": 0}

    for i, (code, info) in enumerate(targets, 1):
        corp_code = info["corp_code"]
        name = info.get("corp_name", code)
        market = info.get("market", "")
        try:
            if args.what in ("company", "all"):
                stat["co"] += load_company(conn, code, corp_code, name, market)
            if args.what in ("shareholders", "all"):
                if load_shareholders(conn, code, corp_code) > 0:
                    stat["sh"] += 1
            if args.what in ("executives", "all"):
                if load_executives(conn, code, corp_code) > 0:
                    stat["ex"] += 1
        except Exception as e:
            stat["err"] += 1
        if i % 50 == 0 or i == len(targets):
            conn.commit()
            el = time.time() - start
            eta = (len(targets) - i) / (i / el) / 60 if el > 0 else 0
            print(f"  [{i}/{len(targets)}] 개요={stat['co']} 주주={stat['sh']} 경영인={stat['ex']} "
                  f"err={stat['err']} | ETA {eta:.0f}분")

    conn.commit()
    conn.close()
    print(f"\n완료 — {(time.time()-start)/60:.1f}분")
    print(f"기업개요 {stat['co']} / 주주 {stat['sh']} / 경영인 {stat['ex']} / 에러 {stat['err']}")


if __name__ == "__main__":
    main()
