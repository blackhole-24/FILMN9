# -*- coding: utf-8 -*-
"""
halt_sources.py
===============
거래정지 종목 공식 출처 수집 (build_stock_status.py 가 사용).

3순위 폴백 구조:
  1) KIND 공식 매매거래정지 현황 (로그인 불필요) — fetch_kind_halts()
     · KRX 전자공시(KIND)의 현재 정지 스냅샷. 종목명만 제공 → 유니버스로 코드 매핑.
  2) (추정은 build_stock_status.py 본체에서 OHLCV 정체로 판정)
  3) DART 거래소공시 '주권매매거래정지/해제' — fetch_dart_halts()
     · stock_code 직접 제공 + 정지/해제 이벤트 구분.

둘 다 실패해도 본체 추정(heuristic)으로 동작 → 무중단.
"""
from __future__ import annotations
import re
import json
import urllib.request
import urllib.parse
import http.cookiejar
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(r"C:\Users\Admin\FILMN9")
ENV = ROOT / ".env"

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"


def _dart_key():
    try:
        m = re.search(r"DART_API_KEY=(\S+)", ENV.read_text(encoding="utf-8"))
        return m.group(1) if m else ""
    except Exception:
        return ""


# ─── 1순위: KIND 공식 매매거래정지 현황 ────────────────────────────────
def fetch_kind_halts() -> list[dict]:
    """
    KIND 현재 매매거래정지 종목 스냅샷.
    반환: [{"name": 종목명, "reason": 사유, "market": 시장}, ...]
    실패 시 [] (폴백 가능하도록 예외 삼킴).
    """
    base = "https://kind.krx.co.kr/investwarn/tradinghaltissue.do"
    main = base + "?method=searchTradingHaltIssueMain"
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.addheaders = [("User-Agent", _UA), ("Referer", main),
                     ("X-Requested-With", "XMLHttpRequest")]
    try:
        op.open(main, timeout=20).read()   # 세션 쿠키 확보
        form = {
            "method": "searchTradingHaltIssueSub", "forward": "tradinghaltissue_sub",
            "currentPageSize": "500", "pageIndex": "1", "searchMode": "",
            "searchCodeType": "", "searchCorpName": "", "paxreq": "",
            "outsvcno": "", "marketType": "6", "repIsuSrtCd": "",
        }
        resp = op.open(urllib.request.Request(base, data=urllib.parse.urlencode(form).encode()),
                       timeout=20).read().decode("utf-8", "ignore")
    except Exception:
        return []
    tb = re.search(r"<tbody>(.*?)</tbody>", resp, re.S)
    if not tb:
        return []
    out = []
    for tr in re.findall(r"<tr[^>]*>.*?</tr>", tb.group(1), re.S):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if len(tds) < 2:
            continue
        mkt = re.search(r"alt='([^']+)'", tr)
        # 종목명: img/태그 제거 + </a> 잔여 제거
        name = re.sub(r"<[^>]+>", "", tds[1]).replace("</a>", "").strip()
        reason = re.sub(r"<[^>]+>", "", tds[2]).strip() if len(tds) > 2 else ""
        if name:
            out.append({"name": name, "reason": reason or "매매거래정지",
                        "market": mkt.group(1) if mkt else ""})
    return out


# ─── 3순위 보완: DART 거래소공시 매매거래정지/해제 ──────────────────────
def fetch_dart_halts(days: int = 30) -> dict:
    """
    최근 N일 DART 거래소공시에서 주권매매거래정지/해제 이벤트 수집.
    반환: {stock_code: {"state": "HALT"|"RESUMED", "report": 공시명, "date": rcept_dt}}
          (종목별 최신 이벤트만; 해제가 정지보다 나중이면 RESUMED → 정지 아님)
    실패 시 {}.
    """
    key = _dart_key()
    if not key:
        return {}
    end = datetime.now()
    bgn = end - timedelta(days=days)
    events = {}   # code -> (date, state, report)
    try:
        for pg in range(1, 30):   # 거래소공시만 → 페이지 적음
            p = {"crtfc_key": key, "bgn_de": bgn.strftime("%Y%m%d"),
                 "end_de": end.strftime("%Y%m%d"), "pblntf_ty": "I",
                 "page_no": str(pg), "page_count": "100"}
            url = "https://opendart.fss.or.kr/api/list.json?" + urllib.parse.urlencode(p)
            d = json.loads(urllib.request.urlopen(url, timeout=15).read().decode("utf-8"))
            if d.get("status") != "000":
                break
            for it in d.get("list", []):
                nm = it.get("report_nm", "")
                code = (it.get("stock_code") or "").strip()
                if not code or len(code) != 6:
                    continue
                if "매매거래정지" not in nm:
                    continue
                state = "RESUMED" if "정지해제" in nm else "HALT"
                dt = it.get("rcept_dt", "")
                prev = events.get(code)
                if (prev is None) or (dt >= prev[0]):
                    events[code] = (dt, state, nm.strip())
            if pg >= d.get("total_page", 1):
                break
    except Exception:
        pass
    return {c: {"state": s, "report": r, "date": dt} for c, (dt, s, r) in events.items()}


if __name__ == "__main__":
    print("=== KIND 현재 거래정지 ===")
    k = fetch_kind_halts()
    print(f"  {len(k)}종목")
    for x in k[:10]:
        print(f"   [{x['market']}] {x['name']} | {x['reason']}")
    print("=== DART 최근 30일 정지/해제 이벤트 ===")
    dd = fetch_dart_halts(30)
    print(f"  {len(dd)}종목")
    for c, v in list(dd.items())[:15]:
        print(f"   {c} {v['state']} ({v['date']}) {v['report']}")
