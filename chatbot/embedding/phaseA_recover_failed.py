# -*- coding: utf-8 -*-
"""Phase A 실패 건 복구 — [첨부정정]으로 골라진 rcept 대신 원본(비정정) rcept 재시도.

원인: report_detector가 같은 period의 최신 rcept_dt를 채택하는데, 그게 [첨부정정]이면
DART에 document.xml이 없어 'File is not a zip file'로 실패한다 (status 014).
같은 period의 원본(정정 아닌) rcept_no를 우선 시도해 본문이 있는 쪽으로 복구한다.

실행:  python embedding/phaseA_recover_failed.py
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

VAR = Path(r"C:\Users\Admin\Desktop\VAR")
sys.path.insert(0, str(VAR))
from dotenv import load_dotenv

load_dotenv(VAR / ".env")
KEY = os.getenv("DART_API_KEY")
assert KEY

from valuation_engine.report_ingest import download_document
from embedding.dc_xml_cleaner import clean_xml, parse_with_fallback
from embedding.dc_chunker import build_chunks

# 로그에 찍힌 실패 (stock, period). 추가되면 여기에 더하면 됨.
FAILS = [("012450", "2026.03"), ("288180", "2025.12"), ("023760", "2026.03")]

_PERIOD = {"12": ("annual", "annual", "사업보고서"), "03": ("q1", "quarterly", "분기보고서"),
           "06": ("semiannual", "semiannual", "반기보고서"), "09": ("q3", "quarterly", "분기보고서")}


def load_corp():
    xmlb = (VAR / "embedding" / "corpcode.xml").read_bytes()
    m = {}
    for el in ET.fromstring(xmlb).iter("list"):
        sc = (el.findtext("stock_code") or "").strip()
        cc = (el.findtext("corp_code") or "").strip()
        cn = (el.findtext("corp_name") or "").strip()
        if sc and cc:
            m[sc.zfill(6)] = {"corp_code": cc.zfill(8), "corp_name": cn}
    return m


def load_market():
    out = {}
    for path, mk in [(r"C:\Users\Admin\Downloads\data_1426_20260527.csv", "KOSPI"),
                     (r"C:\Users\Admin\Downloads\data_1439_20260527.csv", "KOSDAQ")]:
        with open(path, encoding="cp949", newline="") as f:
            for r in csv.DictReader(f):
                c = (r.get("단축코드") or "").strip().zfill(6)
                if c:
                    out[c] = mk
    return out


def jsonl_path(market, stock, corp_name, year, plabel):
    safe = re.sub(r'[\\/:*?"<>|]+', "", corp_name).strip() or stock
    d = VAR / "KOSPI" if market == "KOSPI" else VAR / "KOSDAQ"
    return d / f"{stock}_{safe}_{year}_{plabel}_chunks.jsonl"


def recover(stock, period, CORP, MARKET):
    info = CORP.get(stock)
    if not info:
        return f"{stock}: corp_code 없음"
    cc, cn = info["corp_code"], info["corp_name"]
    market = MARKET.get(stock, "KOSPI")
    # 같은 period 후보 rcept 모두
    r = requests.get("https://opendart.fss.or.kr/api/list.json",
                     params={"crtfc_key": KEY, "corp_code": cc, "pblntf_ty": "A",
                             "bgn_de": "20260101", "end_de": "20260531", "page_count": "50"},
                     timeout=30)
    cands = [it for it in (r.json().get("list") or [])
             if period in (it.get("report_nm", "") or "")]
    if not cands:
        return f"{stock} {period}: 후보 없음"
    # 정렬: 정정 아닌 것 우선(False<True), 그 안에서 rcept_dt 최신 우선
    cands.sort(key=lambda it: ("정정" in (it.get("report_nm") or ""),
                               -int(it["rcept_dt"])))
    yr, mm = period.split(".")
    plabel, rtype, prefix = _PERIOD[mm]
    rkind = f"{yr}-{plabel}"
    rnm = f"{prefix} ({period})"

    for c in cands:
        rc = c["rcept_no"]
        try:
            xml = download_document(rc)
        except Exception as e:
            print(f"  {stock} {period} rcept {rc}: {str(e)[:80]} → 다음 후보", flush=True)
            time.sleep(0.2)
            continue
        root, mode = parse_with_fallback(clean_xml(xml))
        meta = {
            "group": market, "stock_code": stock, "corp_code": cc, "corp_name": cn,
            "report_nm": rnm, "report_kind": rkind, "report_type": rtype,
            "rcept_no": rc, "rcept_dt": c["rcept_dt"], "fiscal_period": rkind,
            "source_url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rc}",
            "parse_mode": mode,
        }
        recs = build_chunks(root, meta)
        path = jsonl_path(market, stock, cn, int(yr), plabel)
        tmp = path.with_suffix(".jsonl.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            for rr in recs:
                f.write(json.dumps(rr, ensure_ascii=False) + "\n")
        tmp.replace(path)
        # progress 업데이트
        pp = VAR / "embedding" / "collect_progress.json"
        prog = json.loads(pp.read_text(encoding="utf-8")) if pp.exists() else {}
        prog[f"{stock}:{yr}-{plabel}"] = "done"
        pp.write_text(json.dumps(prog, ensure_ascii=False), encoding="utf-8")
        return f"{stock} {period} ✅ 복구: rcept {rc} | {len(recs)}청크"
    return f"{stock} {period} ❌ 모든 후보 실패(DART 자체 누락)"


def main():
    print("=== Phase A 실패 건 복구 ===", flush=True)
    CORP = load_corp()
    MARKET = load_market()
    ok = bad = 0
    for stock, period in FAILS:
        r = recover(stock, period, CORP, MARKET)
        print(r, flush=True)
        if "✅" in r:
            ok += 1
        else:
            bad += 1
    print(f"=== 결과: 복구 {ok} · 실패 {bad} ===", flush=True)


if __name__ == "__main__":
    main()
