# -*- coding: utf-8 -*-
"""
build_analyst_targets.py
========================
애널리스트 리포트(FCFF) 수동 다운로드 타깃 리스트 생성.

기준:
  · 시가총액 3천억원 이상 (5천억+ 는 tier 표시)
  · 제외: 금융(은행·증권·보험·캐피탈), 지주사, REIT, 스팩, 우선주
    → FCFF DCF 부적합 섹터
정렬: 시가총액 내림차순 (커버리지 두터운 순)
출력: analyst_report_targets.csv (다운로드 체크리스트)
"""
import csv
import re
from pathlib import Path
import FinanceDataReader as fdr

OUT = Path(r"C:\Users\Admin\FILMN9\analyst_report_targets.csv")
TH_BROAD = 3e11     # 3천억
TH_CORE = 5e11      # 5천억

FIN_KW = ["은행", "증권", "보험", "캐피탈", "금융지주", "저축은행", "신용", "카드",
          "선물", "자산운용", "금융"]
HOLDING_KW = ["홀딩스", "지주", "Holdings", "홀딩"]
REIT_KW = ["리츠", "REIT", "위탁관리부동산투자", "기업구조조정부동산투자"]
SPAC_KW = ["스팩", "기업인수목적"]


def is_pref(name, code):
    # 우선주: 이름 끝 '우'/'우B'/'(전환)' 또는 코드 끝자리 5/7/9
    if re.search(r"우[A-Z]?$", name) or "우선주" in name:
        return True
    if code[-1] in "5790" and code[-1] != "0":   # 5/7/9 끝 = 우선주 관행
        return True
    return False


def main():
    krx = fdr.StockListing("KRX")           # Marcap 포함
    desc = fdr.StockListing("KRX-DESC")     # Industry/Sector
    ind = {}
    for c, i, s in zip(desc["Code"], desc.get("Industry", [""]*len(desc)), desc.get("Sector", [""]*len(desc))):
        ind[str(c).zfill(6)] = f"{i or ''} {s or ''}".strip()

    rows = []
    excluded = {"금융": 0, "지주": 0, "REIT": 0, "스팩": 0, "우선주": 0}
    for _, r in krx.iterrows():
        code = str(r["Code"]).zfill(6)
        name = str(r["Name"])
        mc = r.get("Marcap") or 0
        if not mc or mc < TH_BROAD:
            continue
        industry = ind.get(code, "")
        blob = name + " " + industry
        if is_pref(name, code):
            excluded["우선주"] += 1; continue
        if any(k in name for k in SPAC_KW):
            excluded["스팩"] += 1; continue
        if any(k in name for k in REIT_KW) or "부동산투자회사" in industry:
            excluded["REIT"] += 1; continue
        if any(k in name for k in HOLDING_KW):
            excluded["지주"] += 1; continue
        if any(k in blob for k in FIN_KW):
            excluded["금융"] += 1; continue
        rows.append({
            "code": code, "name": name, "market": r.get("Market", ""),
            "marcap_억원": round(mc / 1e8), "marcap_raw": int(mc),
            "tier": "코어(5천억+)" if mc >= TH_CORE else "확장(3천억+)",
            "industry": industry,
        })

    rows.sort(key=lambda x: -x["marcap_raw"])
    for i, x in enumerate(rows, 1):
        x["우선순위"] = i

    with open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["우선순위", "종목코드", "종목명", "시장", "시총(억원)", "티어", "업종", "다운로드완료(O/X)"])
        for x in rows:
            w.writerow([x["우선순위"], x["code"], x["name"], x["market"],
                        f'{x["marcap_억원"]:,}', x["tier"], x["industry"], ""])

    core = sum(1 for x in rows if x["tier"].startswith("코어"))
    print(f"타깃 리스트 생성: {len(rows)}개")
    print(f"  코어(5천억+): {core}  /  확장(3천억~5천억): {len(rows)-core}")
    print(f"  제외: {excluded}")
    print(f"  저장: {OUT}")
    print("\n상위 15개:")
    for x in rows[:15]:
        print(f'  {x["우선순위"]:>3}. {x["code"]} {x["name"][:14]:14s} {x["marcap_억원"]:>9,}억 [{x["tier"]}]')


if __name__ == "__main__":
    main()
