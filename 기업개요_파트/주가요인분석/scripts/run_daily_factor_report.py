"""Run daily stock factor reports for selected Korean stocks.

Prototype scope:
- Price: pykrx OHLCV for individual stocks
- Market index: FinanceDataReader KS11/KQ11
- Evidence: Naver News Search API, OpenDART disclosures
- LLM: OpenAI gpt-5.4-mini

Examples
--------
  python scripts/run_daily_factor_report.py
  python scripts/run_daily_factor_report.py --codes 009150
  python scripts/run_daily_factor_report.py --codes 009150,035420
  python scripts/run_daily_factor_report.py --all
  python scripts/run_daily_factor_report.py --all --no-llm
"""

from __future__ import annotations

import argparse
import email.utils
import html
import io
import json
import os
import re
import sys
import time
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from typing import Any

import FinanceDataReader as fdr
import pandas as pd
import requests
from dotenv import load_dotenv
from openai import OpenAI
from pykrx import stock as krx


sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
DEFAULT_OUTPUT_DIR = BASE_DIR / "output" / "daily_factor_reports"
KST = timezone(timedelta(hours=9))

LLM_MODEL = "gpt-5.4-mini"
PRICE_INPUT_USD_PER_1M = 0.75
PRICE_OUTPUT_USD_PER_1M = 4.50
USD_KRW_ESTIMATE = 1350

NOISE_KEYWORDS = [
    "성과급",
    "임금",
    "노조",
    "채용",
    "복지",
    "갈등",
    "파업",
    "인사",
    "임직원",
]

FACTOR_KEYWORDS = [
    "MLCC",
    "적층세라믹",
    "카메라모듈",
    "패키지기판",
    "FC-BGA",
    "전장",
    "AI",
    "서버",
    "스마트폰",
    "아이폰",
    "중국",
    "실적",
    "매출",
    "영업이익",
    "이익",
    "목표가",
    "투자의견",
    "수주",
    "공급",
    "증설",
    "투자",
    "환율",
    "HBM",
    "전기차",
    "양극재",
    "임상",
    "기술이전",
    "신작",
]

IMPORTANT_DISCLOSURE_KEYWORDS = [
    "실적",
    "매출",
    "영업",
    "손익",
    "단일판매",
    "공급계약",
    "투자판단",
    "유상증자",
    "전환사채",
    "신주인수권",
    "소송",
    "자기주식",
    "배당",
]


@dataclass(frozen=True)
class Target:
    stock_code: str
    corp_name: str
    market: str
    sector: str
    topics: tuple[str, ...]
    peers: dict[str, str]


TARGETS: dict[str, Target] = {
    "000660": Target(
        "000660",
        "SK하이닉스",
        "KOSPI",
        "반도체",
        ("HBM", "AI", "메모리", "실적", "목표가"),
        {"삼성전자": "005930", "한미반도체": "042700", "ISC": "095340"},
    ),
    "005380": Target(
        "005380",
        "현대차",
        "KOSPI",
        "자동차",
        ("판매", "관세", "환율", "전기차", "실적"),
        {"기아": "000270", "현대모비스": "012330", "HL만도": "204320"},
    ),
    "247540": Target(
        "247540",
        "에코프로비엠",
        "KOSDAQ",
        "2차전지",
        ("양극재", "전기차", "수주", "리튬", "실적"),
        {"에코프로": "086520", "엘앤에프": "066970", "포스코퓨처엠": "003670"},
    ),
    "009150": Target(
        "009150",
        "삼성전기",
        "KOSPI",
        "전자부품",
        ("MLCC", "FC-BGA", "AI", "전장", "실적"),
        {"삼성전자": "005930", "LG이노텍": "011070", "대덕전자": "353200"},
    ),
    "035420": Target(
        "035420",
        "NAVER",
        "KOSPI",
        "인터넷/플랫폼",
        ("AI", "광고", "커머스", "웹툰", "클라우드"),
        {"카카오": "035720", "크래프톤": "259960", "더존비즈온": "012510"},
    ),
    "005490": Target(
        "005490",
        "POSCO홀딩스",
        "KOSPI",
        "철강/소재",
        ("철강", "리튬", "중국", "원자재", "2차전지"),
        {"현대제철": "004020", "포스코퓨처엠": "003670", "고려아연": "010130"},
    ),
    "196170": Target(
        "196170",
        "알테오젠",
        "KOSDAQ",
        "바이오",
        ("기술이전", "임상", "특허", "SC제형", "마일스톤"),
        {"리가켐바이오": "141080", "유한양행": "000100", "HLB": "028300"},
    ),
    "009450": Target(
        "009450",
        "경동나비엔",
        "KOSPI",
        "생활가전/에너지기기",
        ("보일러", "수출", "북미", "실적", "환율"),
        {"코웨이": "021240", "쿠쿠홈시스": "284740", "파세코": "037070"},
    ),
    "214450": Target(
        "214450",
        "파마리서치",
        "KOSDAQ",
        "헬스케어/미용의료",
        ("리쥬란", "의료기기", "화장품", "실적", "수출"),
        {"휴젤": "145020", "메디톡스": "086900", "클래시스": "214150"},
    ),
    "069080": Target(
        "069080",
        "웹젠",
        "KOSDAQ",
        "게임",
        ("신작", "게임", "매출", "MMORPG", "실적"),
        {"크래프톤": "259960", "엔씨소프트": "036570", "펄어비스": "263750"},
    ),
}


def load_env() -> tuple[OpenAI | None, dict[str, str]]:
    load_dotenv(dotenv_path=ENV_PATH)
    keys = {
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", ""),
        "DART_API_KEY": os.getenv("DART_API_KEY", ""),
        "NAVER_CLIENT_ID": os.getenv("NAVER_CLIENT_ID", ""),
        "NAVER_CLIENT_SECRET": os.getenv("NAVER_CLIENT_SECRET", ""),
    }
    missing = [name for name, value in keys.items() if not value]
    if missing:
        raise RuntimeError(f".env에 필요한 키가 없습니다: {', '.join(missing)}")
    return OpenAI(api_key=keys["OPENAI_API_KEY"]), keys


def yyyymmdd(value: datetime | str) -> str:
    if isinstance(value, str):
        return value.replace("-", "")
    return value.strftime("%Y%m%d")


def clean_text(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", "", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    col_map = {
        "시가": "open",
        "고가": "high",
        "저가": "low",
        "종가": "close",
        "거래량": "volume",
        "거래대금": "value",
        "등락률": "change_rate",
    }
    out = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns}).copy()
    out.index = pd.to_datetime(out.index)
    out = out.sort_index()
    for col in ["open", "high", "low", "close", "volume"]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def fetch_stock_ohlcv(stock_code: str, end_date: str | None = None, lookback_days: int = 90) -> pd.DataFrame:
    end_dt = datetime.strptime(end_date, "%Y%m%d") if end_date else datetime.now(KST)
    start_dt = end_dt - timedelta(days=lookback_days)
    raw = krx.get_market_ohlcv(yyyymmdd(start_dt), yyyymmdd(end_dt), stock_code)
    return normalize_ohlcv(raw)


def latest_two_rows(df: pd.DataFrame, report_date: str | None = None) -> tuple[pd.Series, pd.Series]:
    if df.empty or len(df) < 2:
        raise RuntimeError("최근 2거래일 가격 데이터가 부족합니다.")
    if report_date:
        cutoff = pd.Timestamp(datetime.strptime(report_date, "%Y%m%d"))
        df = df[df.index <= cutoff]
        if len(df) < 2:
            raise RuntimeError(f"{report_date} 기준 최근 2거래일 데이터가 부족합니다.")
    return df.iloc[-2], df.iloc[-1]


def classify_price_pattern(recent_returns: list[float], return_5d: float | None, volume_ratio_20d: float | None) -> dict:
    if not recent_returns:
        return {"code": "unknown", "label": "판단 보류", "reason": "최근 수익률 데이터가 부족합니다."}
    today_ret = recent_returns[-1]
    prev_ret = recent_returns[-2] if len(recent_returns) >= 2 else None
    same_direction_count = sum(1 for value in recent_returns if abs(value) >= 0.3 and value * today_ret > 0)

    if prev_ret is not None and today_ret * prev_ret < 0 and abs(prev_ret) >= 1.0:
        return {
            "code": "reversal",
            "label": "반등/되돌림형",
            "reason": "직전 거래일과 반대 방향으로 움직여 단기 반등 또는 되돌림 가능성을 함께 봐야 합니다.",
        }
    if return_5d is not None and same_direction_count >= 3 and abs(return_5d) >= 3:
        return {
            "code": "trend_continuation",
            "label": "추세 지속형",
            "reason": "최근 5거래일 중 같은 방향의 움직임이 반복되어 오늘 하루보다 최근 흐름을 함께 해석해야 합니다.",
        }
    if abs(today_ret) >= 3 and (volume_ratio_20d or 0) >= 1.5:
        return {
            "code": "event_shock",
            "label": "이벤트 반응형",
            "reason": "당일 수익률과 거래량이 함께 커져 당일 이벤트 반응 가능성이 상대적으로 큽니다.",
        }
    if abs(today_ret) < 1 and (return_5d is None or abs(return_5d) < 2):
        return {
            "code": "limited_move",
            "label": "제한적 변동형",
            "reason": "당일 및 최근 누적 변동폭이 크지 않아 원인 단정보다 참고 요인 중심 해석이 적절합니다.",
        }
    return {
        "code": "mixed",
        "label": "혼합형",
        "reason": "추세, 되돌림, 이벤트 중 하나로 단정하기 어려워 뉴스·수급·시장 데이터를 함께 봐야 합니다.",
    }


def calc_return_snapshot(target: Target, report_date: str | None = None) -> dict:
    df = fetch_stock_ohlcv(target.stock_code, report_date)
    prev, today = latest_two_rows(df, report_date)

    prev_close = float(prev["close"])
    close = float(today["close"])
    return_1d = (close - prev_close) / prev_close * 100

    prev_20 = df[df.index < today.name].tail(20)
    avg_volume_20d = float(prev_20["volume"].mean()) if len(prev_20) else None
    volume_ratio_20d = float(today["volume"] / avg_volume_20d) if avg_volume_20d else None

    df_to_today = df[df.index <= today.name].copy()
    returns = (df_to_today["close"].pct_change() * 100).dropna().tail(5)
    recent_returns_5d = [
        {"date": idx.strftime("%Y-%m-%d"), "return": round(float(value), 2)}
        for idx, value in returns.items()
    ]
    if len(df_to_today) >= 6:
        base_close = float(df_to_today.iloc[-6]["close"])
        return_5d = (close - base_close) / base_close * 100
    else:
        return_5d = None
    pattern = classify_price_pattern(
        [item["return"] for item in recent_returns_5d],
        round(return_5d, 2) if return_5d is not None else None,
        volume_ratio_20d,
    )

    return {
        "stock_code": target.stock_code,
        "corp_name": target.corp_name,
        "market": target.market,
        "sector": target.sector,
        "prev_trade_date": prev.name.strftime("%Y-%m-%d"),
        "trade_date": today.name.strftime("%Y-%m-%d"),
        "prev_close": int(prev_close),
        "open": int(today["open"]),
        "high": int(today["high"]),
        "low": int(today["low"]),
        "close": int(close),
        "volume": int(today["volume"]),
        "return_1d": round(return_1d, 2),
        "recent_returns_5d": recent_returns_5d,
        "return_5d": round(return_5d, 2) if return_5d is not None else None,
        "pattern": pattern,
        "avg_volume_20d": int(avg_volume_20d) if avg_volume_20d else None,
        "volume_ratio_20d": round(volume_ratio_20d, 2) if volume_ratio_20d else None,
    }


def calc_simple_return(stock_code: str, report_date: str | None = None) -> float | None:
    try:
        df = fetch_stock_ohlcv(stock_code, report_date, lookback_days=30)
        prev, today = latest_two_rows(df, report_date)
        return round((float(today["close"]) - float(prev["close"])) / float(prev["close"]) * 100, 2)
    except Exception:
        return None


def calc_market_index_return(market: str, report_date: str | None = None) -> dict | None:
    symbol = "KQ11" if market.upper() == "KOSDAQ" else "KS11"
    name = "KOSDAQ" if symbol == "KQ11" else "KOSPI"
    try:
        end_dt = datetime.strptime(report_date, "%Y%m%d") if report_date else datetime.now(KST)
        start_dt = end_dt - timedelta(days=30)
        df = fdr.DataReader(symbol, start_dt.strftime("%Y-%m-%d"), (end_dt + timedelta(days=1)).strftime("%Y-%m-%d"))
        if df.empty or "Close" not in df.columns:
            return None
        df.index = pd.to_datetime(df.index).tz_localize(None)
        df = df.sort_index()
        if report_date:
            cutoff = pd.Timestamp(datetime.strptime(report_date, "%Y%m%d"))
            df = df[df.index <= cutoff]
        if len(df) < 2:
            return None
        prev = df.iloc[-2]
        today = df.iloc[-1]
        ret = (float(today["Close"]) - float(prev["Close"])) / float(prev["Close"]) * 100
        return {
            "name": name,
            "symbol": symbol,
            "source": "FinanceDataReader",
            "prev_trade_date": df.index[-2].strftime("%Y-%m-%d"),
            "trade_date": df.index[-1].strftime("%Y-%m-%d"),
            "return_1d": round(ret, 2),
        }
    except Exception as e:
        print(f"  [WARN] FDR {name} 수익률 조회 실패: {e}")
        return None


def safe_number(value: Any) -> int:
    try:
        if pd.isna(value):
            return 0
        return int(value)
    except Exception:
        return 0


def summarize_investor_row(row: pd.Series) -> dict:
    individual = safe_number(row.get("개인", 0))
    foreign = safe_number(row.get("외국인", 0)) + safe_number(row.get("기타외국인", 0))
    excluded = {"개인", "외국인", "기타외국인", "기타법인", "전체"}
    institution_cols = [col for col in row.index if col not in excluded]
    institution = sum(safe_number(row.get(col, 0)) for col in institution_cols)
    return {
        "individual": individual,
        "foreign": foreign,
        "institution": institution,
        "institution_columns": institution_cols,
    }


def collect_investor_flow(stock_code: str, price: dict) -> dict | None:
    try:
        trade_date = price["trade_date"]
        recent = price.get("recent_returns_5d", [])
        start_date = recent[0]["date"] if recent else price["prev_trade_date"]
        df = krx.get_market_trading_value_by_date(
            start_date.replace("-", ""),
            trade_date.replace("-", ""),
            stock_code,
            on="순매수",
        )
        if df is None or df.empty:
            return None
        df.index = pd.to_datetime(df.index)
        df = df.sort_index()
        df = df[df.index <= pd.Timestamp(datetime.strptime(trade_date, "%Y-%m-%d"))]
        if df.empty:
            return None
        daily = summarize_investor_row(df.iloc[-1])
        recent_5d = summarize_investor_row(df.tail(5).sum(numeric_only=True))
        return {
            "source": "pykrx.get_market_trading_value_by_date(on='순매수')",
            "unit": "KRW",
            "trade_date": df.index[-1].strftime("%Y-%m-%d"),
            "period_start": df.tail(5).index[0].strftime("%Y-%m-%d"),
            "period_end": df.tail(5).index[-1].strftime("%Y-%m-%d"),
            "daily_net_buy_value": {
                "individual": daily["individual"],
                "foreign": daily["foreign"],
                "institution": daily["institution"],
            },
            "recent_5d_net_buy_value": {
                "individual": recent_5d["individual"],
                "foreign": recent_5d["foreign"],
                "institution": recent_5d["institution"],
            },
            "institution_columns": daily["institution_columns"],
        }
    except Exception as e:
        print(f"  [WARN] 투자자별 순매수대금 조회 실패: {e}")
        return None


def parse_naver_pubdate(pub_date: str) -> datetime | None:
    try:
        return email.utils.parsedate_to_datetime(pub_date).astimezone(KST)
    except Exception:
        return None


def news_window_from_price(price: dict) -> tuple[datetime, datetime]:
    prev_date = datetime.strptime(price["prev_trade_date"], "%Y-%m-%d").date()
    trade_date = datetime.strptime(price["trade_date"], "%Y-%m-%d").date()
    start_dt = datetime.combine(prev_date, dt_time(15, 30), tzinfo=KST)
    end_dt = datetime.combine(trade_date, dt_time(23, 59), tzinfo=KST)
    return start_dt, end_dt


def collect_naver_news(target: Target, start_dt: datetime, end_dt: datetime, keys: dict[str, str], display: int = 50) -> list[dict]:
    headers = {
        "X-Naver-Client-Id": keys["NAVER_CLIENT_ID"],
        "X-Naver-Client-Secret": keys["NAVER_CLIENT_SECRET"],
    }
    queries = [target.corp_name, f"{target.corp_name} 주가"]
    queries.extend(f"{target.corp_name} {topic}" for topic in target.topics)

    seen: set[str] = set()
    items: list[dict] = []
    for query in dict.fromkeys(queries):
        resp = requests.get(
            "https://openapi.naver.com/v1/search/news.json",
            headers=headers,
            params={"query": query, "display": display, "sort": "date"},
            timeout=15,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"네이버 뉴스 API 실패: HTTP {resp.status_code} / {resp.text[:200]}")
        for raw in resp.json().get("items", []):
            published_at = parse_naver_pubdate(raw.get("pubDate", ""))
            if not published_at or not (start_dt <= published_at <= end_dt):
                continue
            title = clean_text(raw.get("title", ""))
            description = clean_text(raw.get("description", ""))
            url = raw.get("originallink") or raw.get("link") or ""
            key = url or title
            if key in seen:
                continue
            seen.add(key)
            items.append({
                "id": f"N{len(items) + 1}",
                "query": query,
                "title": title,
                "description": description,
                "published_at": published_at.strftime("%Y-%m-%d %H:%M"),
                "url": url,
            })
        time.sleep(0.15)
    items.sort(key=lambda x: x["published_at"], reverse=True)
    return items


_CORP_CODE_MAP: dict[str, str] | None = None


def load_corp_code_map(keys: dict[str, str]) -> dict[str, str]:
    global _CORP_CODE_MAP
    if _CORP_CODE_MAP is not None:
        return _CORP_CODE_MAP
    resp = requests.get(
        "https://opendart.fss.or.kr/api/corpCode.xml",
        params={"crtfc_key": keys["DART_API_KEY"]},
        timeout=30,
    )
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        root = ET.fromstring(zf.read("CORPCODE.xml"))
    mapping = {}
    for item in root.findall("list"):
        stock_code = item.findtext("stock_code", "").strip()
        corp_code = item.findtext("corp_code", "").strip()
        if stock_code:
            mapping[stock_code] = corp_code
    _CORP_CODE_MAP = mapping
    return mapping


def collect_dart_disclosures(target: Target, start_dt: datetime, end_dt: datetime, keys: dict[str, str]) -> list[dict]:
    corp_code = load_corp_code_map(keys).get(target.stock_code)
    if not corp_code:
        return []
    resp = requests.get(
        "https://opendart.fss.or.kr/api/list.json",
        params={
            "crtfc_key": keys["DART_API_KEY"],
            "corp_code": corp_code,
            "bgn_de": start_dt.strftime("%Y%m%d"),
            "end_de": end_dt.strftime("%Y%m%d"),
            "last_reprt_at": "N",
            "page_count": 100,
        },
        timeout=15,
    )
    data = resp.json()
    if data.get("status") not in {"000", "013"}:
        raise RuntimeError(f"DART API 실패: {data.get('status')} / {data.get('message')}")
    rows = []
    for raw in data.get("list", []):
        rows.append({
            "id": f"D{len(rows) + 1}",
            "rcept_dt": raw.get("rcept_dt"),
            "report_nm": raw.get("report_nm"),
            "corp_name": raw.get("corp_name"),
            "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={raw.get('rcept_no')}",
        })
    return rows


def score_news(item: dict, target: Target) -> int:
    text = f"{item.get('title', '')} {item.get('description', '')}"
    score = 0
    if target.corp_name in item.get("title", ""):
        score += 5
    elif target.corp_name in text:
        score += 3
    score += sum(1 for kw in FACTOR_KEYWORDS if kw.lower() in text.lower())
    score += sum(2 for topic in target.topics if topic.lower() in text.lower())
    if "주가" in text:
        score += 1
    score -= sum(8 for kw in NOISE_KEYWORDS if kw in text)
    return score


def score_disclosure(item: dict) -> int:
    title = item.get("report_nm", "")
    score = 4
    score += sum(3 for kw in IMPORTANT_DISCLOSURE_KEYWORDS if kw in title)
    if "정정" in title:
        score -= 2
    return max(score, 1)


def build_interpretation_notes(price: dict, market: dict | None, peers: dict, flow: dict | None, disclosures: list[dict]) -> list[str]:
    notes = []
    volume_ratio = price.get("volume_ratio_20d")
    if volume_ratio is not None and volume_ratio < 0.7:
        notes.append(f"거래량은 20일 평균 대비 {volume_ratio}배로 낮아, 강한 수급 유입을 단정하기 어렵습니다.")
    elif volume_ratio is not None and volume_ratio >= 1.5:
        notes.append(f"거래량은 20일 평균 대비 {volume_ratio}배로 높아, 당일 이슈 반응 여부를 함께 봐야 합니다.")
    if not disclosures:
        notes.append("최근 수집 기간 내 DART 주요 공시는 확인되지 않았습니다.")
    if market and abs(market.get("return_1d", 0)) < 0.3:
        notes.append(f"{market.get('name', '시장')}은 {market.get('return_1d')}%로 보합권이어서 시장 전체보다 개별/업종 요인 점검이 중요합니다.")
    if flow:
        daily = flow.get("daily_net_buy_value", {})
        smart_net = daily.get("foreign", 0) + daily.get("institution", 0)
        if price.get("return_1d", 0) * smart_net > 0:
            notes.append("당일 외국인+기관 순매수 방향이 주가 방향과 일치해 수급 보강 여부를 볼 수 있습니다.")
        elif smart_net:
            notes.append("당일 외국인+기관 순매수 방향은 주가 방향과 엇갈려 수급만으로 설명하기는 제한적입니다.")
    positive_peers = [name for name, ret in peers.items() if ret is not None and ret > 0]
    negative_peers = [name for name, ret in peers.items() if ret is not None and ret < 0]
    if positive_peers and negative_peers:
        notes.append("비교 종목의 방향이 엇갈려 업종 전체 강세보다는 일부 종목/테마 선호로 해석하는 편이 안전합니다.")
    return notes


def build_ranked_evidence(news: list[dict], disclosures: list[dict], price: dict, market: dict | None, flow: dict | None) -> list[dict]:
    evidence = []
    for item in news:
        if item.get("score", 0) <= 0:
            continue
        evidence.append({
            "id": item["id"],
            "source_type": "news",
            "title": item["title"],
            "published_at": item["published_at"],
            "score": item.get("score", 0),
            "evidence_ids": [item["id"]],
        })
    for item in disclosures:
        evidence.append({
            "id": item["id"],
            "source_type": "disclosure",
            "title": item.get("report_nm", ""),
            "published_at": item.get("rcept_dt", ""),
            "score": score_disclosure(item),
            "evidence_ids": [item["id"]],
        })
    pattern = price.get("pattern", {})
    evidence.append({
        "id": "PRICE",
        "source_type": "price",
        "title": f"1D {price.get('return_1d')}%, 5D {price.get('return_5d')}%, {pattern.get('label', '패턴 미분류')}",
        "score": 5 + (2 if abs(price.get("return_1d", 0)) >= 2 else 0),
        "evidence_ids": ["PRICE"],
    })
    if market:
        target_ret = price.get("return_1d", 0)
        market_ret = market.get("return_1d", 0)
        evidence.append({
            "id": "MARKET",
            "source_type": "market",
            "title": f"{market.get('name')} {market_ret}%, 종목 초과수익률 {round(target_ret - market_ret, 2)}%p",
            "score": 4 + (2 if abs(target_ret - market_ret) >= 1.5 else 0),
            "evidence_ids": ["MARKET"],
        })
    if flow:
        daily = flow.get("daily_net_buy_value", {})
        foreign_inst = daily.get("foreign", 0) + daily.get("institution", 0)
        evidence.append({
            "id": "FLOW",
            "source_type": "investor_flow",
            "title": f"외국인+기관 당일 순매수대금 {foreign_inst:,}원",
            "score": 5 + (2 if price.get("return_1d", 0) * foreign_inst > 0 else 0),
            "evidence_ids": ["FLOW"],
        })
    return sorted(evidence, key=lambda x: x["score"], reverse=True)[:15]


def build_evidence_pack(target: Target, keys: dict[str, str], report_date: str | None = None) -> dict:
    price = calc_return_snapshot(target, report_date)
    market = calc_market_index_return(target.market, report_date)
    peers = {name: calc_simple_return(code, report_date) for name, code in target.peers.items()}
    investor_flow = collect_investor_flow(target.stock_code, price)
    news_start, news_end = news_window_from_price(price)
    news_items = collect_naver_news(target, news_start, news_end, keys)
    dart_items = collect_dart_disclosures(target, news_start, news_end, keys)
    ranked_news = sorted(
        [{**item, "score": score_news(item, target)} for item in news_items],
        key=lambda x: (x["score"], x["published_at"]),
        reverse=True,
    )
    selected_news = [item for item in ranked_news if item.get("score", 0) > 0][:12]
    notes = build_interpretation_notes(price, market, peers, investor_flow, dart_items)
    ranked_evidence = build_ranked_evidence(selected_news, dart_items, price, market, investor_flow)
    return {
        "price": price,
        "market": market,
        "peers": peers,
        "investor_flow": investor_flow,
        "interpretation_notes": notes,
        "ranked_evidence": ranked_evidence,
        "news_window": {
            "start": news_start.strftime("%Y-%m-%d %H:%M"),
            "end": news_end.strftime("%Y-%m-%d %H:%M"),
        },
        "news": selected_news,
        "disclosures": dart_items,
    }


SYSTEM_PROMPT = """당신은 한국 주식 장마감 리포트를 작성하는 금융 데이터 애널리스트입니다.
주가 변동의 원인을 단정하지 말고, 제공된 뉴스/공시/가격 데이터에 근거해 '관련 요인'으로 설명하세요.
제공된 근거에 없는 사실, 숫자, 기사, 공시는 만들지 마세요.
반드시 JSON 객체 하나만 출력하세요."""


def build_user_prompt(target: Target, pack: dict) -> str:
    return f"""
아래 데이터만 근거로 {target.corp_name} 1D 수익률 설명 요인 3개를 작성하세요.

[가격 데이터]
{json.dumps(pack["price"], ensure_ascii=False, indent=2)}

[시장/비교 종목]
시장: {json.dumps(pack["market"], ensure_ascii=False)}
비교 종목 1D 수익률: {json.dumps(pack["peers"], ensure_ascii=False)}

[투자자별 순매수대금]
{json.dumps(pack["investor_flow"], ensure_ascii=False, indent=2)}

[해석상 주의점]
{json.dumps(pack["interpretation_notes"], ensure_ascii=False, indent=2)}

[랭킹된 근거 후보]
{json.dumps(pack["ranked_evidence"], ensure_ascii=False, indent=2)}

[뉴스 수집 기간]
{json.dumps(pack["news_window"], ensure_ascii=False)}

[뉴스 후보]
{json.dumps(pack["news"], ensure_ascii=False, indent=2)}

[DART 공시]
{json.dumps(pack["disclosures"], ensure_ascii=False, indent=2)}

작성 규칙:
1. factors는 정확히 3개입니다.
2. 각 요인은 title, type, scope, summary, evidence_ids, confidence를 포함합니다.
3. evidence_ids에는 위 뉴스 id(N1...), 공시 id(D1...), 또는 PRICE, MARKET, FLOW만 넣으세요.
4. 랭킹된 근거 후보를 우선하되, 점수가 낮은 근거를 억지로 요인에 넣지 마세요.
5. 거래량 부족, DART 공시 없음, 시장 보합처럼 원인이라기보다 제한 조건에 가까운 내용은 interpretation_notes로 분리하세요.
6. 개별 기업 뉴스/공시가 부족하면, 억지로 원인을 만들지 말고 "직접적인 개별 이슈는 제한적"이라고 쓰세요.
7. "영향을 미쳤다"보다 "영향을 줬을 가능성이 있다", "관련 요인으로 해석된다"처럼 단정도를 낮추세요.
8. 한국어로 짧고 명확하게 작성하세요.

출력 JSON 형식:
{{
  "stock_code": "{target.stock_code}",
  "corp_name": "{target.corp_name}",
  "period": "직전 거래일 종가 대비 금일 종가",
  "return_1d": 0.0,
  "recent_pattern": "패턴명",
  "headline": "한 문장 요약",
  "factors": [
    {{
      "rank": 1,
      "type": "company_news|disclosure|sector_market|investor_flow|price_pattern|limited_evidence",
      "scope": "today|recent_5d|market|flow",
      "title": "요인 제목",
      "summary": "근거 기반 설명",
      "evidence_ids": ["N1"],
      "confidence": "high|medium|low"
    }}
  ],
  "interpretation_notes": ["해석상 주의점"],
  "caution": "뉴스와 공시 기반의 해석이며 주가 변동 원인을 확정하지 않습니다."
}}
"""


def extract_json_object(text: str) -> dict:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"JSON 객체를 찾지 못했습니다: {text[:300]}")
    return json.loads(match.group())


def summarize_factors(client: OpenAI, target: Target, pack: dict) -> dict:
    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(target, pack)},
        ],
        max_completion_tokens=2000,
    )
    content = response.choices[0].message.content or ""
    result = extract_json_object(content)
    usage = response.usage
    if usage:
        reasoning_tokens = getattr(getattr(usage, "completion_tokens_details", None), "reasoning_tokens", 0) or 0
        result["_usage"] = {
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "reasoning_tokens": reasoning_tokens,
            "output_tokens": usage.completion_tokens - reasoning_tokens,
        }
    result["_llm_model"] = LLM_MODEL
    result["_generated_at"] = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    return result


def estimate_openai_cost(usage: dict) -> dict:
    input_tokens = usage.get("prompt_tokens", 0) or 0
    output_tokens = usage.get("completion_tokens", 0) or 0
    reasoning_tokens = usage.get("reasoning_tokens", 0) or 0
    visible_output_tokens = usage.get("output_tokens", output_tokens - reasoning_tokens) or 0
    cost_usd = (
        input_tokens / 1_000_000 * PRICE_INPUT_USD_PER_1M
        + output_tokens / 1_000_000 * PRICE_OUTPUT_USD_PER_1M
    )
    return {
        "input_tokens": input_tokens,
        "output_tokens_billed": output_tokens,
        "visible_output_tokens": visible_output_tokens,
        "reasoning_tokens": reasoning_tokens,
        "estimated_cost_usd": round(cost_usd, 6),
        "estimated_cost_krw": round(cost_usd * USD_KRW_ESTIMATE, 2),
        "price_input_usd_per_1m": PRICE_INPUT_USD_PER_1M,
        "price_output_usd_per_1m": PRICE_OUTPUT_USD_PER_1M,
        "usd_krw_estimate": USD_KRW_ESTIMATE,
    }


def save_payload(output_dir: Path, target: Target, report: dict | None, pack: dict, error: str | None = None) -> Path:
    trade_date = pack.get("price", {}).get("trade_date", datetime.now(KST).strftime("%Y-%m-%d"))
    save_dir = output_dir / trade_date
    save_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r'[\\/:*?"<>|]', "_", target.corp_name)
    path = save_dir / f"{target.stock_code}_{safe_name}_daily_factor_report.json"
    payload = {
        "report": report,
        "evidence_pack": pack,
        "error": error,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def select_targets(args: argparse.Namespace) -> list[Target]:
    if args.all:
        return list(TARGETS.values())
    codes = args.codes or "009150"
    selected = []
    for code in re.split(r"[,\s]+", codes.strip()):
        if not code:
            continue
        if code not in TARGETS:
            known = ", ".join(TARGETS)
            raise ValueError(f"알 수 없는 종목코드: {code}. 현재 등록된 코드: {known}")
        selected.append(TARGETS[code])
    return selected


def run_one(target: Target, client: OpenAI | None, keys: dict[str, str], args: argparse.Namespace) -> dict:
    print(f"\n[{target.stock_code}] {target.corp_name} ({target.market}/{target.sector})")
    pack = build_evidence_pack(target, keys, args.report_date)
    print(
        f"  가격: 1D {pack['price'].get('return_1d')}% / "
        f"5D {pack['price'].get('return_5d')}% / "
        f"{pack['price'].get('pattern', {}).get('label')}"
    )
    print(
        f"  근거: 뉴스 {len(pack.get('news', []))}건 / "
        f"공시 {len(pack.get('disclosures', []))}건 / "
        f"수급 {'있음' if pack.get('investor_flow') else '없음'}"
    )

    if args.no_llm:
        path = save_payload(args.output_dir, target, None, pack)
        print(f"  저장: {path}")
        return {"target": target, "path": path, "usage": {}, "cost": {}, "ok": True}

    assert client is not None
    report = summarize_factors(client, target, pack)
    cost = estimate_openai_cost(report.get("_usage", {}))
    path = save_payload(args.output_dir, target, report, pack)
    print(f"  요약: {report.get('headline', '')}")
    print(
        f"  토큰: input {cost['input_tokens']:,} / "
        f"output {cost['output_tokens_billed']:,} / "
        f"비용 ${cost['estimated_cost_usd']:.6f}"
    )
    print(f"  저장: {path}")
    return {"target": target, "path": path, "usage": report.get("_usage", {}), "cost": cost, "ok": True}


def write_summary(output_dir: Path, results: list[dict], no_llm: bool) -> Path:
    stamp = datetime.now(KST).strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"_summary_{stamp}.json"
    output_dir.mkdir(parents=True, exist_ok=True)
    total_input = sum(r.get("cost", {}).get("input_tokens", 0) for r in results)
    total_output = sum(r.get("cost", {}).get("output_tokens_billed", 0) for r in results)
    total_cost = sum(r.get("cost", {}).get("estimated_cost_usd", 0) for r in results)
    payload = {
        "generated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
        "model": None if no_llm else LLM_MODEL,
        "count": len(results),
        "success_count": sum(1 for r in results if r.get("ok")),
        "total_tokens": {
            "input": total_input,
            "output_billed": total_output,
        },
        "estimated_cost": {
            "usd": round(total_cost, 6),
            "krw": round(total_cost * USD_KRW_ESTIMATE, 2),
        },
        "results": [
            {
                "stock_code": r["target"].stock_code,
                "corp_name": r["target"].corp_name,
                "ok": r.get("ok"),
                "path": str(r.get("path")) if r.get("path") else None,
                "error": r.get("error"),
                "cost": r.get("cost", {}),
            }
            for r in results
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="국내 주식 1D 수익률 요인 요약 배치 실행")
    parser.add_argument("--all", action="store_true", help="등록된 10종목 전체 실행")
    parser.add_argument("--codes", type=str, default=None, help="쉼표/공백 구분 종목코드. 예: 009150,035420")
    parser.add_argument("--report-date", type=str, default=None, help="기준일 YYYYMMDD. 생략 시 조회 가능한 최신 거래일")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="결과 저장 폴더")
    parser.add_argument("--no-llm", action="store_true", help="OpenAI 호출 없이 근거 패키지만 저장")
    parser.add_argument("--sleep", type=float, default=0.8, help="종목 간 대기 시간(초)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_dir = args.output_dir.resolve()
    client, keys = load_env()
    if args.no_llm:
        client = None

    targets = select_targets(args)
    mode = "근거 수집만" if args.no_llm else f"LLM 요약({LLM_MODEL})"
    print(f"실행 대상: {len(targets)}종목 / 모드: {mode}")
    print(f"저장 폴더: {args.output_dir}")

    results = []
    for i, target in enumerate(targets, 1):
        try:
            print(f"\n=== {i}/{len(targets)} ===")
            results.append(run_one(target, client, keys, args))
        except Exception as e:
            print(f"  [ERROR] {target.stock_code} {target.corp_name}: {e}")
            results.append({"target": target, "ok": False, "error": str(e), "cost": {}, "usage": {}})
        if i < len(targets):
            time.sleep(args.sleep)

    summary_path = write_summary(args.output_dir, results, args.no_llm)
    total_cost = sum(r.get("cost", {}).get("estimated_cost_usd", 0) for r in results)
    print("\n완료")
    print(f"성공: {sum(1 for r in results if r.get('ok'))}/{len(results)}")
    print(f"예상 비용: ${total_cost:.6f} (~{total_cost * USD_KRW_ESTIMATE:.2f}원)")
    print(f"요약 저장: {summary_path}")


if __name__ == "__main__":
    main()
