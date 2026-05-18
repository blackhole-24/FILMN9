"""
collectors/yfinance_collector.py
─────────────────────────────────
yfinance로 주가 실시간 + 히스토리 수집.
티커: 090430.KS (아모레퍼시픽 보통주)

제공 함수
─────────
get_price_info(ticker)      → 현재가·전일·고가·저가·거래량·시총·52주고저·EPS/BPS/PER/PBR
get_price_history(ticker, period_key) → OHLCV DataFrame (기간별)
get_all_price_data(ticker)  → 전체 묶음 dict
"""

from __future__ import annotations
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta, time as dtime

import pandas as pd
import yfinance as yf

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.app_config import SAMPLE, CHART_PERIODS, COLOR_UP, COLOR_DOWN, COLOR_FLAT


# ─────────────────────────────────────────────────────────────────────────────
# 숫자 포맷 유틸
# ─────────────────────────────────────────────────────────────────────────────

def _fmt_krw(val: float | None, unit: str = "원") -> str:
    """123456789 → '1,234억 5,678만' 또는 '1,234억'"""
    if val is None:
        return "-"
    val = int(val)
    억 = val // 100_000_000
    만 = (val % 100_000_000) // 10_000
    if 억 >= 10000:
        조 = 억 // 10000
        억r = 억 % 10000
        return f"{조:,}조 {억r:,}억"
    if 억 > 0:
        return f"{억:,}억 {만:,}만" if 만 else f"{억:,}억"
    return f"{만:,}만{unit}" if 만 else f"{val:,}{unit}"


def _change_color(change_pct: float | None) -> str:
    if change_pct is None:
        return COLOR_FLAT
    return COLOR_UP if change_pct > 0 else (COLOR_DOWN if change_pct < 0 else COLOR_FLAT)


# ─────────────────────────────────────────────────────────────────────────────
# 1) 현재가 + 주요 지표
# ─────────────────────────────────────────────────────────────────────────────

def get_price_info(ticker: str = SAMPLE["ticker_yf"]) -> dict:
    """
    yfinance Ticker.info → 주가 헤더 카드용 데이터.

    Returns
    -------
    {
      "현재가": int,  "전일종가": int,  "시가": int,
      "고가": int,    "저가": int,      "거래량": int,
      "거래대금": str, "시가총액": str,  "상장주수": int,
      "52주최고": int, "52주최저": int,
      "외국인보유": str,            ← yfinance 미지원 시 "-"
      "PER": float,  "EPS": float,
      "PBR": float,  "BPS": float,
      "변동": float,               ← 전일 대비 변동금액
      "변동률": float,             ← 전일 대비 %
      "색상": str,                 ← 한국식 색상 코드
      "기준시각": str,
    }
    """
    tk = yf.Ticker(ticker)
    info = tk.info

    현재가  = info.get("currentPrice") or info.get("regularMarketPrice")
    전일종가 = info.get("previousClose") or info.get("regularMarketPreviousClose")
    시가    = info.get("open") or info.get("regularMarketOpen")
    고가    = info.get("dayHigh") or info.get("regularMarketDayHigh")
    저가    = info.get("dayLow")  or info.get("regularMarketDayLow")
    거래량  = info.get("volume")  or info.get("regularMarketVolume") or 0
    시가총액 = info.get("marketCap")
    상장주수 = info.get("sharesOutstanding")
    고52   = info.get("fiftyTwoWeekHigh")
    저52   = info.get("fiftyTwoWeekLow")
    per    = info.get("trailingPE") or info.get("forwardPE")
    eps    = info.get("trailingEps")
    pbr    = info.get("priceToBook")
    bvps   = info.get("bookValue")

    # 변동 계산
    변동 = (현재가 - 전일종가) if (현재가 and 전일종가) else None
    변동률 = round(변동 / 전일종가 * 100, 2) if (변동 and 전일종가) else None

    # 거래대금 = 현재가 × 거래량
    거래대금_raw = (현재가 or 0) * 거래량
    거래대금 = _fmt_krw(거래대금_raw) if 거래대금_raw else "-"

    return {
        "현재가"   : int(현재가)   if 현재가   else None,
        "전일종가"  : int(전일종가) if 전일종가  else None,
        "시가"     : int(시가)    if 시가     else None,
        "고가"     : int(고가)    if 고가     else None,
        "저가"     : int(저가)    if 저가     else None,
        "거래량"   : int(거래량),
        "거래대금"  : 거래대금,
        "시가총액"  : _fmt_krw(시가총액) if 시가총액 else "-",
        "상장주수"  : int(상장주수) if 상장주수 else None,
        "52주최고"  : int(고52)   if 고52    else None,
        "52주최저"  : int(저52)   if 저52    else None,
        "외국인보유" : "-",         # naver_scraper 에서 보완
        "PER"      : round(per,  2) if per   else None,
        "EPS"      : round(eps,  0) if eps   else None,
        "PBR"      : round(pbr,  2) if pbr   else None,
        "BPS"      : round(bvps, 0) if bvps  else None,
        "변동"     : int(변동)    if 변동    else None,
        "변동률"   : 변동률,
        "색상"     : _change_color(변동률),
        "기준시각"  : _market_time_str(info),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 기준 시각 계산 유틸
# ─────────────────────────────────────────────────────────────────────────────

_KST = timezone(timedelta(hours=9))
_MARKET_OPEN  = dtime(9, 0)   # 장 시작
_MARKET_CLOSE = dtime(15, 30) # 장 마감 (KRX 정규장)
_YFINANCE_DELAY_MIN = 15       # yfinance 지연 분


def _market_time_str(info: dict) -> str:
    """
    주가 데이터의 기준 시각 문자열 반환.

    ┌─────────────────────────────────────────────────────────┐
    │ 장중 (평일 09:00 ~ 15:30 KST)                          │
    │   → yfinance 약 15분 지연                               │
    │   → "HH시 MM분 기준" (현재시각 - 15분)                  │
    │                                                         │
    │ 장 마감 후 / 주말                                       │
    │   → 당일(또는 최근 거래일) 종가                         │
    │   → "M월 D일 당일 종가"                                 │
    └─────────────────────────────────────────────────────────┘
    """
    now_kst = datetime.now(_KST)
    is_weekday    = now_kst.weekday() < 5          # 월~금
    is_market_hrs = _MARKET_OPEN <= now_kst.time() < _MARKET_CLOSE

    if is_weekday and is_market_hrs:
        # ── 장중: 현재시각 - 15분이 데이터 기준 시각
        data_time = now_kst - timedelta(minutes=_YFINANCE_DELAY_MIN)
        return f"{data_time.hour}시 {data_time.minute:02d}분 기준"
    else:
        # ── 장 마감 / 주말: regularMarketTime에서 거래일 추출
        ts = info.get("regularMarketTime")
        if ts:
            try:
                dt_kst = datetime.fromtimestamp(int(ts), tz=_KST)
                return f"{dt_kst.month}월 {dt_kst.day}일 당일 종가"
            except Exception:
                pass
        # fallback: 오늘 날짜 종가
        return f"{now_kst.month}월 {now_kst.day}일 당일 종가"


# ─────────────────────────────────────────────────────────────────────────────
# 2) 기간별 주가 히스토리
# ─────────────────────────────────────────────────────────────────────────────

def get_price_history(
    ticker: str = SAMPLE["ticker_yf"],
    period_key: str = "최근1년",
) -> pd.DataFrame:
    """
    yfinance history → OHLCV DataFrame.

    Parameters
    ----------
    period_key : app_config.CHART_PERIODS 의 키
                 "최근30분" | "최근1개월" | "최근3개월" | "최근1년" | "최근3년"

    Returns
    -------
    DataFrame(index=Datetime, columns=[Open, High, Low, Close, Volume])
    비어있으면 empty DataFrame 반환.
    """
    cfg = CHART_PERIODS.get(period_key, CHART_PERIODS["최근1년"])
    tk  = yf.Ticker(ticker)

    try:
        df = tk.history(period=cfg["period"], interval=cfg["interval"])
    except Exception:
        return pd.DataFrame()

    if df.empty:
        return df

    # 불필요 컬럼 제거
    keep = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
    df = df[keep].copy()

    # 인덱스 타임존 제거 (Streamlit plotly 호환)
    if hasattr(df.index, "tz") and df.index.tz is not None:
        df.index = df.index.tz_localize(None)

    return df


# ─────────────────────────────────────────────────────────────────────────────
# 3) 전체 묶음
# ─────────────────────────────────────────────────────────────────────────────

def get_all_price_data(ticker: str = SAMPLE["ticker_yf"]) -> dict:
    """
    주가 관련 모든 데이터를 한 번에 수집.

    Returns
    -------
    {
      "info"    : get_price_info() 결과,
      "history" : { "최근30분": df, "최근1개월": df, ... }
    }
    """
    info = get_price_info(ticker)
    history = {key: get_price_history(ticker, key) for key in CHART_PERIODS}
    return {"info": info, "history": history}


# ─────────────────────────────────────────────────────────────────────────────
# 동작 확인
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ticker = SAMPLE["ticker_yf"]
    print("=" * 55)
    print(f"FILMN9 yfinance_collector — {SAMPLE['name']}({ticker})")
    print("=" * 55)

    print("\n[현재가 정보]")
    info = get_price_info(ticker)
    for k, v in info.items():
        print(f"  {k:10s}: {v}")

    print("\n[히스토리 — 최근1년 일봉 (앞 3행)]")
    df = get_price_history(ticker, "최근1년")
    if not df.empty:
        print(f"  shape: {df.shape}")
        print(df.head(3).to_string())
    else:
        print("  데이터 없음")

    print("\n[히스토리 — 최근30분 (앞 3행)]")
    df30 = get_price_history(ticker, "최근30분")
    if not df30.empty:
        print(f"  shape: {df30.shape}")
        print(df30.head(3).to_string())
    else:
        print("  장 종료 or 데이터 없음")

    print("\n✅ yfinance_collector 검증 완료")
