"""
api/routers/morning.py
======================
모닝루틴 — 글로벌 야간시장 지표 + 한국장 영향 신호등.

GET /api/morning   23개 글로벌 지표(yfinance) + 상관관계 기반 신호등 + 종합판정

참고: blackhole-24/hipython llm/03_morning_checklist (검증된 로직 포팅)
- 데이터: yfinance 실시간(15분 지연). 임의 생성 없음(NO-MOCK).
- 상관계수(r)는 글로벌×KOSPI 도메인 상수(참고 라벨).
- 15분 캐시(yfinance 과호출 방지).
"""
from __future__ import annotations

import threading
import time
from datetime import datetime

from fastapi import APIRouter

router = APIRouter()

# ─── 티커 정의 (라벨·섹션) ────────────────────────────────────────────────
TICKERS = {
    "ES=F":     {"label": "S&P500 선물", "section": "futures",     "desc": "미국 대표 주가지수 선물. KOSPI와 가장 강하게 동행하는 선행지표."},
    "NQ=F":     {"label": "나스닥 선물",  "section": "futures",     "desc": "기술주 중심 선물. 반도체·IT주와 KOSDAQ에 직결."},
    "YM=F":     {"label": "다우 선물",    "section": "futures",     "desc": "전통 산업주 중심 선물. 미국 투자심리 가늠자."},
    # ─── 미국 3대 지수(현물·간밤 마감) ───
    "^GSPC":    {"label": "S&P500 지수",  "section": "us_index",    "desc": "미국 대표 주가지수(현물). 간밤 미국장 최종 마감 결과."},
    "^IXIC":    {"label": "나스닥 종합",  "section": "us_index",    "desc": "나스닥 종합지수(현물). 기술주 중심 미국장 마감."},
    "^DJI":     {"label": "다우존스 지수", "section": "us_index",    "desc": "다우존스 산업평균지수(현물). 전통 대형주 미국장 마감."},
    "^VIX":     {"label": "VIX 공포지수", "section": "futures",     "desc": "시장 불안 정도. 낮을수록 안전(외국인 매수), 20↑ 주의·30↑ 위험."},
    "DX-Y.NYB": {"label": "달러인덱스",   "section": "fx",          "desc": "달러 강세 정도. 오르면 원화 약세·외국인 이탈 압력."},
    "KRW=X":    {"label": "원/달러",      "section": "fx",          "desc": "환율. 오르면(원화 약세) 외국인 매도 압력이 커짐."},
    "JPY=X":    {"label": "달러/엔",      "section": "fx",          "desc": "엔 약세 시 한국 수출주(자동차·반도체) 경쟁 압박."},
    "^TNX":     {"label": "미 10년 금리", "section": "rates",       "desc": "장기 금리. 오르면 달러 강세→외국인 이탈 연쇄."},
    "^IRX":     {"label": "미 2년 금리",  "section": "rates",       "desc": "단기 금리. 미 연준(Fed) 금리 방향을 선행 반영."},
    "CL=F":     {"label": "WTI 원유",     "section": "commodities", "desc": "국제 유가. 한국 무역수지·물가에 직접 영향."},
    "GC=F":     {"label": "금",           "section": "commodities", "desc": "대표 안전자산. 불안할수록 오르는 경향."},
    "HG=F":     {"label": "구리",         "section": "commodities", "desc": "‘닥터 코퍼’. 글로벌 경기 선행 지표."},
    "NG=F":     {"label": "천연가스",     "section": "commodities", "desc": "LNG 수입비용·에너지 단가와 연동."},
    "^KS11":    {"label": "KOSPI",        "section": "asia",        "desc": "한국 대표 주가지수(15분 지연)."},
    "^KQ11":    {"label": "KOSDAQ",       "section": "asia",        "desc": "중소·성장주 중심 한국 지수."},
    "^N225":    {"label": "닛케이",       "section": "asia",        "desc": "일본 대표지수. 아시아 리스크온/오프 신호."},
    "^HSI":     {"label": "항셍",         "section": "asia",        "desc": "홍콩 지수. 중국 경기·대중 수출주 방향."},
    "000001.SS":{"label": "상해종합",     "section": "asia",        "desc": "중국 상해종합지수. 중국 본토 증시·대중 수출주 방향."},
    "EWY":      {"label": "EWY(야간한국)", "section": "asia",        "desc": "미국 상장 한국 ETF. 미국 야간장의 한국 전망 선행."},
    "XLK":      {"label": "IT",           "section": "sectors",     "desc": "미국 IT 섹터 ETF 등락률."},
    "XLF":      {"label": "금융",         "section": "sectors",     "desc": "미국 금융 섹터 ETF 등락률."},
    "XLV":      {"label": "헬스케어",     "section": "sectors",     "desc": "미국 헬스케어 섹터 ETF 등락률."},
    "XLE":      {"label": "에너지",       "section": "sectors",     "desc": "미국 에너지 섹터 ETF 등락률."},
    "XLY":      {"label": "소비재",       "section": "sectors",     "desc": "미국 임의소비재 섹터 ETF 등락률."},
    "XLI":      {"label": "산업재",       "section": "sectors",     "desc": "미국 산업재 섹터 ETF 등락률."},
    # ─── 추가 지표 (실시간 yfinance) ───
    "^SOX":     {"label": "필라델피아 반도체", "section": "extra", "desc": "미국 반도체 종합지수(SOX). 한국 반도체주를 하루 선행."},
    "NVDA":     {"label": "엔비디아",        "section": "extra", "desc": "AI 반도체 대장주. 한국 HBM(SK·삼성) 수요 선행."},
    "TSM":      {"label": "TSMC",           "section": "extra", "desc": "세계 1위 파운드리. 반도체 업황 바로미터."},
    "MU":       {"label": "마이크론",        "section": "extra", "desc": "미국 메모리 업체. DRAM/NAND 업황 선행."},
    "BZ=F":     {"label": "브렌트유",        "section": "extra", "desc": "북해산 원유. WTI와 함께 국제 유가 기준."},
    "SI=F":     {"label": "은(Silver)",      "section": "extra", "desc": "산업+안전자산. 태양광·전자 수요와 연동."},
    "LIT":      {"label": "리튬·배터리 ETF",  "section": "extra", "desc": "이차전지 밸류체인. LG엔솔·에코프로 연동."},
    "URA":      {"label": "우라늄 ETF",      "section": "extra", "desc": "원전 연료. 원전주(두산에너빌리티) 테마."},
    "ZW=F":     {"label": "밀(Wheat)",       "section": "extra", "desc": "곡물가. 식품·사료(농심·CJ) 원가."},
    "ZC=F":     {"label": "옥수수",          "section": "extra", "desc": "곡물가. 사료·식품 원가."},
    "ZS=F":     {"label": "대두(콩)",        "section": "extra", "desc": "곡물가. 식용유·사료 원가."},
    "TLT":      {"label": "미 장기국채 ETF",  "section": "extra", "desc": "미국 장기금리 반대 흐름. 금리 방향 시각화."},
    "EURUSD=X": {"label": "유로/달러",       "section": "extra", "desc": "달러 반대편 통화. 달러 강세/약세 확인."},
    "BTC-USD":  {"label": "비트코인",        "section": "extra", "desc": "위험선호 심리 지표(약한 상관)."},
    "BDRY":     {"label": "발틱운임 ETF(BDI)", "section": "extra", "desc": "건화물 해운운임(BDI) 추종 ETF. 수출 물동량·해운주(HMM)."},
    "SLX":      {"label": "철강 ETF",        "section": "extra", "desc": "글로벌 철강 ETF. 철광석·철강주(포스코·현대제철) 업황."},
    "ZQ=F":     {"label": "Fed 기준금리 선물", "section": "extra", "desc": "30일 연방기금 선물. 미 정책금리 기대를 반영."},
}

# ─── 글로벌 × 한국 신호등 (상관관계 기반) ─────────────────────────────────
SIGNALS = [
    {"ticker": "ES=F",  "label": "S&P500 선물", "r": "r=+0.87", "comment": "미국 선물 = KOSPI 가장 강한 선행지표", "mode": "change", "up": 0.3, "down": -0.3},
    {"ticker": "^VIX",  "label": "VIX 공포지수", "r": "r=-0.79", "comment": "VIX 낮을수록 외국인 매수 유입", "mode": "level", "good": 20, "bad": 25, "invert": True},
    {"ticker": "KRW=X", "label": "원/달러",      "r": "r=-0.68", "comment": "원화 약세(환율↑) = 외국인 매도 압력", "mode": "change", "up": 0.3, "down": -0.3, "invert": True},
    {"ticker": "^TNX",  "label": "미 10년 금리", "r": "r=-0.55", "comment": "금리 상승 = 달러 강세 → 외국인 이탈", "mode": "change", "up": 1.0, "down": -1.0, "invert": True},
    {"ticker": "^N225", "label": "닛케이 225",   "r": "r=+0.72", "comment": "닛케이 상승 = 아시아 리스크온", "mode": "change", "up": 0.3, "down": -0.3},
    {"ticker": "^HSI",  "label": "항셍",         "r": "r=+0.65", "comment": "항셍 상승 = 중국 수출주 수혜", "mode": "change", "up": 0.3, "down": -0.3},
]

# ─── 캐시 ─────────────────────────────────────────────────────────────────
_CACHE = {"ts": 0.0, "data": None}
_TTL = 900   # 15분


def _fmt_price(ticker: str, price) -> str:
    if price is None:
        return "N/A"
    if ticker in ("^TNX", "^IRX"):
        return f"{price:.2f}%"
    if ticker == "KRW=X":
        return f"₩{price:,.1f}"
    if ticker in ("^KS11", "^KQ11", "^N225", "^HSI", "000001.SS",
                  "^DJI", "^IXIC", "^GSPC"):
        return f"{price:,.0f}"
    if ticker == "HG=F":
        return f"${price:.3f}"
    return f"{price:,.2f}"


def _fmt_delta(pct) -> str:
    if pct is None:
        return ""
    return f"{'+' if pct >= 0 else ''}{pct:.2f}%"


def _summarize(closes_list: list) -> dict:
    """종가 시계열(list, 최신=마지막) → 가격·전일대비·1개월 저/고·추세."""
    out = {"price": None, "change_pct": None, "m1_low": None, "m1_high": None, "trend": None}
    if not closes_list:
        return out
    vals = [float(x) for x in closes_list]
    n = len(vals)
    out["price"] = vals[-1]
    out["change_pct"] = ((vals[-1] - vals[-2]) / vals[-2] * 100) if (n >= 2 and vals[-2]) else 0.0
    out["m1_low"], out["m1_high"] = min(vals), max(vals)
    first = vals[0]
    chg = ((vals[-1] - first) / first * 100) if first else 0.0
    out["trend"] = "오름세" if chg > 2 else ("내림세" if chg < -2 else "보합세")
    return out


def _fetch_one(ticker: str) -> dict:
    import yfinance as yf
    try:
        h = yf.Ticker(ticker).history(period="1mo", interval="1d")
        return _summarize(list(h["Close"].dropna()))
    except Exception:
        return _summarize([])


def _collect() -> dict:
    import yfinance as yf
    tickers = list(TICKERS.keys())
    try:
        raw = yf.download(tickers=tickers, period="1mo", interval="1d",
                          group_by="ticker", auto_adjust=True, progress=False, threads=True)
    except Exception:
        raw = None

    data = {}
    for tk, meta in TICKERS.items():
        try:
            if raw is not None and tk in raw.columns.get_level_values(0):
                s = _summarize(list(raw[tk]["Close"].dropna()))
                if s["price"] is None:
                    s = _fetch_one(tk)
            else:
                s = _fetch_one(tk)
        except Exception:
            s = _fetch_one(tk)

        entry = {"ticker": tk, "label": meta["label"], "section": meta["section"],
                 "desc": meta.get("desc", ""), **s}
        entry["price_str"]   = _fmt_price(tk, s["price"])
        entry["delta_str"]   = _fmt_delta(s["change_pct"])
        entry["m1_low_str"]  = _fmt_price(tk, s["m1_low"])
        entry["m1_high_str"] = _fmt_price(tk, s["m1_high"])
        if s["m1_low"] is not None:
            entry["range_str"] = f"지난 한 달간 {entry['m1_low_str']}~{entry['m1_high_str']} 사이 {s['trend']}"
        else:
            entry["range_str"] = "데이터 없음"
        data[tk] = entry
    return data


def _signal(cfg: dict, data: dict):
    d = data.get(cfg["ticker"], {})
    invert = cfg.get("invert", False)
    if cfg["mode"] == "change":
        v = d.get("change_pct")
        if v is None:
            return "⚪", "데이터 없음"
        if not invert:
            if v >= cfg["up"]:   return "🟢", f"{v:+.2f}% 상승 신호"
            if v <= cfg["down"]: return "🔴", f"{v:+.2f}% 하락 신호"
            return "🟡", f"{v:+.2f}% 중립"
        else:
            if v <= -cfg["up"]:  return "🟢", f"{v:+.2f}% 우호적"
            if v >= -cfg["down"]: return "🔴", f"{v:+.2f}% 주의"
            return "🟡", f"{v:+.2f}% 중립"
    else:  # level (VIX)
        v = d.get("price")
        if v is None:
            return "⚪", "데이터 없음"
        if v < cfg["good"]:  return "🟢", f"{v:.2f} 안전권"
        if v >= cfg["bad"]:  return "🔴", f"{v:.2f} 위험권"
        return "🟡", f"{v:.2f} 주의권"


def _krx_gold() -> dict | None:
    """KRX 국내 금시장 현물 시세(원/g) — 네이버금융(한국거래소 출처) 일별 시세 스크래핑."""
    import urllib.request, re
    hdr = {"User-Agent": "Mozilla/5.0"}
    try:
        vals = []
        for pg in (1, 2):
            url = f"https://finance.naver.com/marketindex/goldDailyQuote.naver?marketindexCd=CMDT_GD&page={pg}"
            html = urllib.request.urlopen(urllib.request.Request(url, headers=hdr), timeout=8).read().decode("euc-kr", "ignore")
            rows = re.findall(r'<td class="date">([\d\.]+)</td>\s*<td[^>]*>([\d,\.]+)</td>', html)
            vals += [float(p.replace(",", "")) for _, p in rows]
        if not vals:
            return None
        s = _summarize(list(reversed(vals)))   # 오래된→최신 순으로
        p = s["price"]
        return {
            "ticker": "KRX_GOLD", "label": "금(KRX 국내)", "section": "extra",
            "desc": "한국거래소 금시장 현물 시세(원/g). 출처: 네이버금융(KRX).",
            **s,
            "price_str":   f"₩{p:,.0f}/g" if p else "N/A",
            "delta_str":   _fmt_delta(s["change_pct"]),
            "m1_low_str":  f"₩{s['m1_low']:,.0f}" if s["m1_low"] else "",
            "m1_high_str": f"₩{s['m1_high']:,.0f}" if s["m1_high"] else "",
            "range_str":   (f"지난 한 달간 ₩{s['m1_low']:,.0f}~₩{s['m1_high']:,.0f} 사이 {s['trend']}"
                            if s["m1_low"] else "데이터 없음"),
        }
    except Exception:
        return None


def _fear_greed() -> dict | None:
    """미국 공포·탐욕지수(CNN Fear & Greed Index, 0~100) — CNN 공개 API.
    실패하면 None(미표시) — NO-MOCK상 임의값 만들지 않음."""
    import urllib.request, json
    hdr = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://edition.cnn.com/markets/fear-and-greed",
        "Origin": "https://edition.cnn.com",
    }
    try:
        url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        raw = urllib.request.urlopen(
            urllib.request.Request(url, headers=hdr), timeout=6).read()
        fg = json.loads(raw).get("fear_and_greed", {})
        score = fg.get("score")
        if score is None:
            return None
        score = round(float(score))
        rating = fg.get("rating", "")
        kor = {"extreme fear": "극단적 공포", "fear": "공포", "neutral": "중립",
               "greed": "탐욕", "extreme greed": "극단적 탐욕"}.get(rating, rating)
        prev = fg.get("previous_close")
        delta = (score - round(float(prev))) if prev is not None else None
        return {
            "ticker": "FEAR_GREED", "label": "공포·탐욕지수(CNN)", "section": "sentiment",
            "desc": "미국 시장 심리 0~100(0=극단적 공포·100=극단적 탐욕). 출처: CNN Fear & Greed Index.",
            "price": score, "change_pct": (delta or 0), "m1_low": None, "m1_high": None, "trend": None,
            "price_str": f"{score} {kor}".strip(),
            "delta_str": (f"{'+' if delta >= 0 else ''}{delta}" if delta is not None else ""),
            "m1_low_str": "", "m1_high_str": "",
            "range_str": f"현재 {score}/100 — {kor}" if kor else f"현재 {score}/100",
        }
    except Exception:
        return None


def _naver_bonds() -> dict:
    """한국 시중금리(국고채·회사채·CD) — 네이버금융 국내금리 스크래핑(현재 금리)."""
    import urllib.request, re
    hdr = {"User-Agent": "Mozilla/5.0"}
    specs = [
        ("IRR_GOVT03Y", "국고채 3년",     "한국 국고채 3년 금리. 국내 시중금리·채권 기준."),
        ("IRR_CORP03Y", "회사채 3년(AA-)", "우량 회사채 3년 금리. 기업 자금조달 비용."),
        ("IRR_CD91",    "CD 91일",        "양도성예금증서 금리. 단기 시중금리 지표."),
    ]
    out: dict = {}
    try:
        html = urllib.request.urlopen(
            urllib.request.Request("https://finance.naver.com/marketindex/?tabSel=interest", headers=hdr),
            timeout=8).read().decode("euc-kr", "ignore")
    except Exception:
        return out
    for code, label, desc in specs:
        m = re.search(re.escape(code) + r'[\s\S]{0,250}?<td>([\d.]+)</td>\s*<td>([\s\S]{0,120}?)</td>', html)
        if not m:
            continue
        rate = float(m.group(1)); cell = m.group(2)
        direction = "상승" if "상승" in cell else ("하락" if "하락" in cell else "보합")
        cell_text = re.sub(r'<[^>]+>', ' ', cell)          # img 태그 제거(파일명 . 오인 방지)
        cm = re.search(r'\d+\.\d+|\d+', cell_text)
        chg = float(cm.group()) if cm else 0.0
        sign = -1 if direction == "하락" else (1 if direction == "상승" else 0)
        out[code] = {
            "ticker": code, "label": label, "section": "extra", "desc": desc,
            "price": rate, "change_pct": sign * chg, "m1_low": None, "m1_high": None, "trend": None,
            "price_str": f"{rate:.2f}%",
            "delta_str": (f"{'+' if sign > 0 else '-'}{chg:.2f}%p" if (chg and sign) else "보합"),
            "m1_low_str": "", "m1_high_str": "",
            "range_str": f"현재 {rate:.2f}% ({direction})",
        }
    return out


def _build() -> dict:
    data = _collect()

    # KRX 국내 금가격 (네이버 한국거래소 출처)
    g = _krx_gold()
    if g:
        data["KRX_GOLD"] = g

    # 美 장단기 금리차 (10Y − 3M) — 마이너스(역전)면 경기침체 선행 신호
    tnx = data.get("^TNX", {}).get("price")
    irx = data.get("^IRX", {}).get("price")
    if tnx is not None and irx is not None:
        sp = tnx - irx
        data["US_10Y_3M"] = {
            "ticker": "US_10Y_3M", "label": "美 장단기금리차(10Y-3M)", "section": "extra",
            "desc": "미 10년물−3개월물 국채금리 차이. 마이너스(역전)면 경기침체 선행 신호.",
            "price": sp, "change_pct": sp, "m1_low": None, "m1_high": None, "trend": None,
            "price_str": f"{sp:+.2f}%p", "delta_str": "",
            "m1_low_str": "", "m1_high_str": "",
            "range_str": ("역전 — 침체 경계 신호" if sp < 0 else "정상(플러스)"),
        }

    # 한국 시중금리 (국고채·회사채·CD) — 네이버 스크래핑
    for k, v in _naver_bonds().items():
        data[k] = v

    # 미국 공포·탐욕지수 (CNN) — 실패 시 미표시(NO-MOCK)
    fg = _fear_greed()
    if fg:
        data["FEAR_GREED"] = fg

    signals, green, red, yellow = [], 0, 0, 0
    for cfg in SIGNALS:
        icon, status = _signal(cfg, data)
        signals.append({"ticker": cfg["ticker"], "label": cfg["label"], "r": cfg["r"],
                        "icon": icon, "status": status, "comment": cfg["comment"]})
        if icon == "🟢": green += 1
        elif icon == "🔴": red += 1
        else: yellow += 1

    if green >= 4:
        overall = {"icon": "🟢", "text": "오늘 한국장 상승 우호적 환경"}
    elif red >= 4:
        overall = {"icon": "🔴", "text": "오늘 한국장 하락 위험 신호"}
    elif green > red:
        overall = {"icon": "🟡", "text": "전반적으로 소폭 상승 가능성"}
    else:
        overall = {"icon": "🟡", "text": "혼조세 — 방향성 불분명"}
    overall.update({"green": green, "yellow": yellow, "red": red})

    sections: dict[str, list] = {}
    for tk, e in data.items():
        sections.setdefault(e["section"], []).append(e)

    return {
        "as_of": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "source": "yfinance (15분 지연)",
        "overall": overall,
        "signals": signals,
        "sections": sections,
    }


@router.get("/morning")
def morning():
    """글로벌 야간시장 지표 + 한국장 영향 신호등 (15분 캐시)."""
    now = time.time()
    if _CACHE["data"] is not None and (now - _CACHE["ts"]) < _TTL:
        return {**_CACHE["data"], "cached": True}
    data = _build()
    _CACHE["ts"] = now
    _CACHE["data"] = data
    return {**data, "cached": False}


def warm_cache() -> None:
    """서버 기동 시 캐시 prewarm — 콜드 스타트(yfinance ~3.6초)를 첫 사용자가
    겪지 않도록 미리 _build() 결과를 캐시에 채운다. 실패해도 서비스 영향 없음."""
    try:
        data = _build()
        _CACHE["ts"]   = time.time()
        _CACHE["data"] = data
        print("[morning] 캐시 prewarm 완료 (콜드 스타트 제거)")
    except Exception as e:
        print(f"[morning] prewarm 실패(무시): {e}")


_AUTO_REFRESH_STARTED = False

def start_auto_refresh(interval_sec: int = 840) -> None:
    """[옵션 B] 기동 직후 1회 prewarm + 이후 interval(기본 14분)마다 백그라운드 갱신.
    TTL(900초=15분)보다 짧은 주기로 미리 새로고침 → 캐시가 만료될 틈이 없어
    어떤 사용자도 콜드 스타트를 겪지 않는다(항상 따뜻한 캐시). daemon 스레드라
    서버 종료 시 함께 정리되고, 실패해도 서비스에 영향 없음."""
    global _AUTO_REFRESH_STARTED
    if _AUTO_REFRESH_STARTED:
        return
    _AUTO_REFRESH_STARTED = True

    def _loop():
        warm_cache()                 # 기동 직후 1회 (prewarm)
        while True:
            time.sleep(interval_sec)  # 14분 대기
            warm_cache()              # 만료 직전 미리 갱신

    threading.Thread(target=_loop, daemon=True, name="morning-auto-refresh").start()
    print(f"[morning] 자동 주기 갱신 시작 (매 {interval_sec//60}분, TTL 15분 직전 갱신)")
