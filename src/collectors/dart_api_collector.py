"""
collectors/dart_api_collector.py
──────────────────────────────────
DART Open API → 기업개요 / 주주구성 / 최근공시 수집.

제공 함수
─────────
get_company_info(corp_code)   → 기업 기본 정보
get_major_shareholders(corp_code) → 주요 주주 리스트
get_recent_disclosures(corp_code, n) → 최근 공시 n건
"""

from __future__ import annotations
import sys, json, time
from pathlib import Path
from urllib.request import urlopen
from urllib.parse import urlencode
from urllib.error import URLError

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.app_config import DART_API_KEY, DART_BASE_URL, SAMPLE

_HEADERS = {"User-Agent": "Mozilla/5.0"}

# ─────────────────────────────────────────────────────────────────────────────
# 내부 HTTP 유틸
# ─────────────────────────────────────────────────────────────────────────────

def _get_json(endpoint: str, params: dict, retries: int = 3) -> dict:
    params["crtfc_key"] = DART_API_KEY
    url = f"{DART_BASE_URL}/{endpoint}?{urlencode(params)}"
    for attempt in range(retries):
        try:
            from urllib.request import Request
            req = Request(url, headers=_HEADERS)
            with urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except URLError:
            if attempt < retries - 1:
                time.sleep(1)
    return {}


# ─────────────────────────────────────────────────────────────────────────────
# 1) 기업 기본 정보 (company.json)
# ─────────────────────────────────────────────────────────────────────────────

def get_company_info(corp_code: str = SAMPLE["corp_code"]) -> dict:
    """
    DART company.json → 기업개요 카드용 데이터.

    Returns
    -------
    {
      "corp_name": str, "stock_code": str, "ceo_nm": str,
      "corp_cls": str,  "induty_code": str, "est_dt": str,
      "phn_no": str,    "fax_no": str,      "hm_url": str,
      "adres": str,     "acc_mt": str,
    }
    """
    data = _get_json("company.json", {"corp_code": corp_code})
    if data.get("status") != "000":
        return {}

    return {
        "corp_name"  : data.get("corp_name", ""),
        "stock_code" : data.get("stock_code", ""),
        "ceo_nm"     : data.get("ceo_nm", ""),
        "corp_cls"   : {"Y": "유가증권", "K": "코스닥", "N": "코넥스", "E": "기타"}.get(
                           data.get("corp_cls", ""), data.get("corp_cls", "")),
        "jurir_no"   : data.get("jurir_no", ""),       # 법인등록번호
        "bizr_no"    : data.get("bizr_no", ""),        # 사업자번호
        "induty_code": data.get("induty_code", ""),
        "est_dt"     : _fmt_date(data.get("est_dt", "")),
        "phn_no"     : data.get("phn_no", ""),
        "fax_no"     : data.get("fax_no", ""),
        "hm_url"     : data.get("hm_url", ""),
        "adres"      : data.get("adres", ""),
        "acc_mt"     : data.get("acc_mt", ""),         # 결산월
    }


def _fmt_date(dt: str) -> str:
    """"20170403" → "2017년 04월 03일" """
    if len(dt) == 8:
        return f"{dt[:4]}년 {dt[4:6]}월 {dt[6:]}일"
    return dt


# ─────────────────────────────────────────────────────────────────────────────
# 2) 주요 주주 (majorstock.json)
# ─────────────────────────────────────────────────────────────────────────────

def get_major_shareholders(corp_code: str = SAMPLE["corp_code"]) -> list[dict]:
    """
    DART majorstock.json → 주주구성 도넛 차트용 데이터.

    실제 응답 필드: repror(주주명), stkqy(보유주식수), stkrt(지분율%)
    Returns
    -------
    [{"name": str, "ratio": float, "shares": int}, ...]
    """
    data = _get_json("majorstock.json", {"corp_code": corp_code})
    if data.get("status") != "000":
        return []

    seen, holders = set(), []
    for item in data.get("list", []):
        name = item.get("repror", "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        try:
            ratio  = float(str(item.get("stkrt", "0")).replace(",", "") or 0)
            shares = int(str(item.get("stkqy", "0")).replace(",", "") or 0)
        except (ValueError, TypeError):
            ratio, shares = 0.0, 0
        holders.append({"name": name, "ratio": ratio, "shares": shares})

    holders.sort(key=lambda x: x["ratio"], reverse=True)
    return holders


# ─────────────────────────────────────────────────────────────────────────────
# 3) 최근 공시 (list.json)
# ─────────────────────────────────────────────────────────────────────────────

def get_recent_disclosures(
    corp_code: str = SAMPLE["corp_code"],
    n: int = 10,
) -> list[dict]:
    """
    DART list.json → 최근 공시 목록.

    Returns
    -------
    [
      {
        "rcept_no": str,  "rcept_dt": str,
        "report_nm": str, "flr_nm": str,
        "dart_url": str,
      },
      ...
    ]
    """
    params = {
        "corp_code" : corp_code,
        "bgn_de"    : "20240101",   # 2024년 이후 공시
        "page_no"   : "1",
        "page_count": str(n),
    }
    data = _get_json("list.json", params)
    if data.get("status") != "000":
        return []

    result = []
    for item in data.get("list", [])[:n]:
        rcept_no = item.get("rcept_no", "")
        result.append({
            "rcept_no"  : rcept_no,
            "rcept_dt"  : _fmt_rcept_dt(item.get("rcept_dt", "")),
            "report_nm" : item.get("report_nm", ""),
            "flr_nm"    : item.get("flr_nm", ""),
            "dart_url"  : f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}",
        })
    return result


def _fmt_rcept_dt(dt: str) -> str:
    """"20260514" → "2026.05.14" """
    if len(dt) == 8:
        return f"{dt[:4]}.{dt[4:6]}.{dt[6:]}"
    return dt


# ─────────────────────────────────────────────────────────────────────────────
# 동작 확인
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    corp = SAMPLE["corp_code"]
    name = SAMPLE["name"]
    print("=" * 55)
    print(f"FILMN9 dart_api_collector — {name}({corp})")
    print("=" * 55)

    print("\n[기업 기본 정보]")
    info = get_company_info(corp)
    for k, v in info.items():
        print(f"  {k:12s}: {v}")

    print("\n[주요 주주]")
    holders = get_major_shareholders(corp)
    if holders:
        for h in holders[:6]:
            print(f"  {h['name']:20s}  {h['ratio']:6.2f}%  {h['shares']:>15,}주")
    else:
        print("  데이터 없음 (API 미지원 또는 비공개)")

    print("\n[최근 공시 5건]")
    disclosures = get_recent_disclosures(corp, 5)
    for d in disclosures:
        print(f"  [{d['rcept_dt']}] {d['report_nm'][:40]}")
        print(f"           → {d['dart_url']}")

    print("\n✅ dart_api_collector 검증 완료")
