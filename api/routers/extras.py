"""
api/routers/extras.py
=====================
Tab1 화면 신규 데이터 엔드포인트
- 주주, 경영인, 공시, 재무상세(B/S, I/S), 기업 건전성, 실시간 주가, 뉴스

엔드포인트
----------
GET /api/shareholders/{stock_code}
GET /api/executives/{stock_code}
GET /api/disclosures/{stock_code}?limit=10
GET /api/financial_detail/{stock_code}/{statement_type}  (BS|IS)
GET /api/health/{stock_code}                              (기업 건전성)
GET /api/realtime/{stock_code}                            (실시간 주가·시총)
GET /api/news/{stock_code}?limit=5                        (최신 뉴스)
"""
from __future__ import annotations

import sqlite3
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import datetime
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

router = APIRouter()
_ROOT = Path(__file__).resolve().parent.parent.parent
_DB = _ROOT / "data" / "filmn9.db"


def _conn():
    if not _DB.exists():
        raise HTTPException(500, "filmn9.db 없음")
    c = sqlite3.connect(_DB)
    c.row_factory = sqlite3.Row
    return c


# ─── 주주 ─────────────────────────────────────────────────────────────────────

@router.get("/shareholders/{stock_code}")
def get_shareholders(stock_code: str):
    """주주 구성 (최신 회계연도 기준)."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT MAX(fiscal_year) FROM shareholders WHERE stock_code = ?",
            (stock_code,)).fetchone()
        if not row or row[0] is None:
            raise HTTPException(404, f"{stock_code} 주주 데이터 없음")
        latest_year = row[0]

        rows = conn.execute(
            "SELECT rank, name, relation, shares, ratio "
            "FROM shareholders WHERE stock_code = ? AND fiscal_year = ? "
            "ORDER BY rank",
            (stock_code, latest_year)).fetchall()

    return {
        "stock_code": stock_code,
        "fiscal_year": latest_year,
        "items": [dict(r) for r in rows],
        "total_ratio": round(sum(r["ratio"] or 0 for r in rows), 2),
    }


# ─── 경영인 ───────────────────────────────────────────────────────────────────

@router.get("/executives/{stock_code}")
def get_executives(stock_code: str):
    """경영인 리스트 (최신 회계연도)."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT MAX(fiscal_year) FROM executives WHERE stock_code = ?",
            (stock_code,)).fetchone()
        if not row or row[0] is None:
            raise HTTPException(404, f"{stock_code} 경영인 데이터 없음")
        latest_year = row[0]

        rows = conn.execute(
            "SELECT rank, name, position, role, birth_year, career, "
            "shares, appointed_at, term_end "
            "FROM executives WHERE stock_code = ? AND fiscal_year = ? "
            "ORDER BY rank",
            (stock_code, latest_year)).fetchall()

    return {
        "stock_code": stock_code,
        "fiscal_year": latest_year,
        "items": [dict(r) for r in rows],
    }


# ─── 공시 ─────────────────────────────────────────────────────────────────────

@router.get("/disclosures/{stock_code}")
def get_disclosures(stock_code: str,
                    limit: int = Query(10, ge=1, le=50)):
    """최근 공시 (날짜 내림차순)."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT rcept_no, report_nm, flr_nm, rcept_dt, rm, url "
            "FROM disclosures WHERE stock_code = ? "
            "ORDER BY rcept_dt DESC LIMIT ?",
            (stock_code, limit)).fetchall()

    if not rows:
        raise HTTPException(404, f"{stock_code} 공시 데이터 없음")

    return {
        "stock_code": stock_code,
        "items": [dict(r) for r in rows],
        "count": len(rows),
    }


# ─── 재무상세 ────────────────────────────────────────────────────────────────

@router.get("/financial_detail/{stock_code}/{statement_type}")
def get_financial_detail(stock_code: str, statement_type: str):
    """
    재무제표 상세 (B/S 또는 I/S).
    pivot: 행=account_nm, 열=fiscal_year
    """
    st = statement_type.upper()
    if st not in ("BS", "IS"):
        raise HTTPException(400, "statement_type은 BS 또는 IS")

    with _conn() as conn:
        rows = conn.execute(
            "SELECT fiscal_year, account_id, account_nm, amount, "
            "       statement_scope, display_order "
            "FROM financial_detail "
            "WHERE stock_code = ? AND statement_type = ? "
            "ORDER BY fiscal_year DESC, display_order",
            (stock_code, st)).fetchall()

    if not rows:
        raise HTTPException(404, f"{stock_code} {st} 데이터 없음")

    # pivot
    years = sorted({r["fiscal_year"] for r in rows}, reverse=True)
    accounts: dict[str, dict] = {}
    for r in rows:
        nm = r["account_nm"]
        if nm not in accounts:
            accounts[nm] = {
                "account_id": r["account_id"],
                "account_nm": nm,
                "display_order": r["display_order"],
                "scope": r["statement_scope"],
                "values": {},
            }
        accounts[nm]["values"][str(r["fiscal_year"])] = r["amount"]

    items = sorted(accounts.values(), key=lambda x: x["display_order"] or 0)

    return {
        "stock_code": stock_code,
        "statement_type": st,
        "fiscal_years": [str(y) for y in years],
        "unit": "백만원",
        "items": items,
    }


# ─── 기업 건전성 ─────────────────────────────────────────────────────────────

def _bs_get(bs_map: dict, *candidates) -> float | None:
    """여러 후보 계정명 중 첫 번째로 존재하는 값 반환 (DART 종목마다 계정명 상이)."""
    for key in candidates:
        v = bs_map.get(key)
        if v is not None:
            return float(v)
    return None


@router.get("/health/{stock_code}")
def get_health(stock_code: str):
    """
    기업 건전성 지표 (BS financial_detail 기반 직접 계산):
      - 부채비율  = 부채총계 / 자본총계 × 100
      - 유동비율  = 유동자산 / 유동부채 × 100
      - 영업이익률 = 영업이익 / 매출액 × 100
      - 종합 등급 (green/yellow/red/gray)
    계정명은 DART 종목별로 상이: '유동자산' vs '유동자산 합계' 등 복수 후보 시도
    """
    with _conn() as conn:
        fin = conn.execute(
            "SELECT * FROM financials WHERE stock_code = ? "
            "ORDER BY fiscal_year DESC LIMIT 1",
            (stock_code,)).fetchone()
        if not fin:
            raise HTTPException(404, f"{stock_code} 재무 없음")
        fin = dict(fin)
        year = fin["fiscal_year"]

        # BS는 financial_detail에서 가장 최근 연도 사용
        # (financials 테이블의 최신 연도와 일치하지 않을 수 있음)
        bs = conn.execute(
            "SELECT account_nm, amount FROM financial_detail "
            "WHERE stock_code = ? AND statement_type = 'BS' "
            "AND fiscal_year = ("
            "  SELECT MAX(fiscal_year) FROM financial_detail"
            "  WHERE stock_code = ? AND statement_type = 'BS'"
            ")",
            (stock_code, stock_code)).fetchall()

    bs_map = {r["account_nm"]: r["amount"] for r in bs}

    # ── 유동자산 / 유동부채 (계정명 후보 복수 시도) ──
    curr_assets = _bs_get(bs_map, "유동자산", "유동자산 합계", "I. 유동자산")
    curr_liab   = _bs_get(bs_map, "유동부채", "유동부채 합계", "I. 유동부채")
    current_ratio = round(curr_assets / curr_liab * 100, 1) \
        if curr_assets and curr_liab else None

    # ── 부채비율: financials 테이블 우선, 없으면 BS에서 직접 계산 ──
    debt_ratio_db = fin.get("debt_ratio")
    if debt_ratio_db is not None:
        debt_ratio = float(debt_ratio_db)
    else:
        total_liab   = _bs_get(bs_map, "부채총계", "부채 합계", "부채총계 합계")
        total_equity = _bs_get(bs_map, "자본총계", "자본 합계", "자본총계 합계",
                                "지배기업 소유주에게 귀속되는 자본")
        # 부채총계가 없으면 자산총계 - 자본총계로 역산
        if total_liab is None:
            total_assets = _bs_get(bs_map, "자산총계", "자산 합계")
            if total_assets and total_equity:
                total_liab = total_assets - total_equity
        debt_ratio = round(total_liab / total_equity * 100, 1) \
            if total_liab and total_equity else None

    # ── 영업이익률 ──
    op_margin = round(fin["op_income"] / fin["revenue"] * 100, 1) \
        if fin.get("op_income") and fin.get("revenue") else None

    # ── 등급 산정 ──
    def grade(metric: str, val: float | None) -> str:
        if val is None:
            return "gray"
        rules = {
            "debt_ratio":    [(100, "green"), (200, "yellow"), (1e9, "red")],
            "current_ratio": [(150, "red"),   (200, "yellow"), (1e9, "green")],
            "op_margin":     [(5,   "red"),   (10,  "yellow"), (1e9, "green")],
        }
        for thresh, color in rules.get(metric, []):
            if val <= thresh:
                return color
        return "gray"

    metrics = {
        "debt_ratio":    {"value": debt_ratio,    "grade": grade("debt_ratio",    debt_ratio)},
        "current_ratio": {"value": current_ratio, "grade": grade("current_ratio", current_ratio)},
        "op_margin":     {"value": op_margin,     "grade": grade("op_margin",     op_margin)},
    }

    grades = [m["grade"] for m in metrics.values() if m["grade"] != "gray"]
    if "red" in grades:
        overall = "red"
    elif grades.count("yellow") >= 2:
        overall = "yellow"
    elif grades:
        overall = "green"
    else:
        overall = "gray"

    return {
        "stock_code":   stock_code,
        "fiscal_year":  year,
        "metrics":      metrics,
        "overall_grade": overall,
    }


# ─── 실시간 주가 / 시총 (yfinance, ~15분 지연) ───────────────────────────────

# KRX → yfinance 티커 매핑 (필요 시 확장)
_YF_SUFFIX = ".KS"   # KOSPI; KOSDAQ은 ".KQ"

_MARKET_MAP: dict[str, str] = {}  # stock_code → 시장 (DB에서 읽어 KQ/KS 결정)


def _yf_ticker(stock_code: str) -> str:
    """종목코드 → yfinance 티커 (예: '090430' → '090430.KS')"""
    # 필요 시 KOSDAQ 종목은 .KQ 사용 (간단히 .KS 우선 시도)
    return f"{stock_code}{_YF_SUFFIX}"


@router.get("/realtime/{stock_code}")
def get_realtime(stock_code: str):
    """
    yfinance 기반 실시간(~15분 지연) 주가·시총 반환.
    장중에는 15~20분 지연된 최신 가격을 반환.
    장 마감 후에는 당일 종가를 반환.
    """
    try:
        import yfinance as yf
        ticker = _yf_ticker(stock_code)
        t = yf.Ticker(ticker)
        fi = t.fast_info

        price = fi.last_price
        market_cap = fi.market_cap

        # 최신 1분봉으로 타임스탬프 확인
        now_kst = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
        hist = t.history(period="1d", interval="1m")
        if not hist.empty:
            last_ts = hist.index[-1]
            # timezone-aware → KST
            if last_ts.tzinfo is not None:
                import pytz
                kst = pytz.timezone("Asia/Seoul")
                last_ts = last_ts.astimezone(kst)
            price_time = last_ts.strftime("%Y-%m-%d %H:%M")
        else:
            price_time = now_kst.strftime("%Y-%m-%d")

        # 장중 여부 (KST 09:00~15:30, 평일)
        is_market_open = (
            now_kst.weekday() < 5
            and datetime.time(9, 0) <= now_kst.time() <= datetime.time(15, 30)
        )

        return {
            "stock_code":     stock_code,
            "ticker":         ticker,
            "price":          round(price) if price else None,
            "market_cap":     round(market_cap) if market_cap else None,
            "price_time":     price_time,
            "is_market_open": is_market_open,
            "source":         "Yahoo Finance (KRX ~15분 지연)",
            "delay_min":      15,
        }
    except Exception as e:
        logging.warning(f"realtime {stock_code}: {e}")
        raise HTTPException(503, f"실시간 데이터 조회 실패: {e}")


# ─── 최신 뉴스 (Google News RSS, 한국어) ────────────────────────────────────

_CORP_NAME_MAP: dict[str, str] = {
    "090430": "아모레퍼시픽",
    "009150": "삼성전기",
    "035420": "NAVER",
}


@router.get("/news/{stock_code}")
def get_news(stock_code: str, limit: int = Query(5, ge=1, le=20)):
    """
    Google News RSS 기반 최신 뉴스 (한국어, 무료·API키 불필요).
    """
    corp = _CORP_NAME_MAP.get(stock_code, stock_code)
    query = f"{corp} 주식 주가"
    url = (
        "https://news.google.com/rss/search?"
        + urllib.parse.urlencode({"q": query, "hl": "ko", "gl": "KR", "ceid": "KR:ko"})
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = resp.read()
        root = ET.fromstring(data)
        items = root.findall(".//item")
        news = []
        for item in items[:limit]:
            title   = (item.findtext("title") or "").strip()
            link    = (item.findtext("link") or "").strip()
            pubdate = (item.findtext("pubDate") or "").strip()
            source_el = item.find("{http://purl.org/rss/1.0/modules/dc/}creator")
            source = source_el.text.strip() if source_el is not None else ""
            # Google News redirect URL → 그대로 사용 (클릭 시 실제 기사로 이동)
            news.append({
                "title":   title,
                "link":    link,
                "pubdate": pubdate[:16] if pubdate else "",
                "source":  source,
            })
        return {"stock_code": stock_code, "corp": corp, "items": news}
    except Exception as e:
        logging.warning(f"news {stock_code}: {e}")
        # 뉴스 실패는 빈 배열로 graceful 처리
        return {"stock_code": stock_code, "corp": corp, "items": [], "error": str(e)}


# ─── 신용등급 추이 (Task #13) ────────────────────────────────────────────────

# 신용등급 수동 입력 테이블 (credit_ratings)이 생기기 전까지 쓸 Mock 데이터
# 실제 데이터는 NICE/KIS 신용평가 사이트에서 수동 수집 후 DB 적재 예정
_CREDIT_MOCK: dict[str, list[dict]] = {
    "090430": [
        {"year": 2020, "grade": "AA", "agency": "NICE", "note": "Mock"},
        {"year": 2021, "grade": "AA", "agency": "NICE", "note": "Mock"},
        {"year": 2022, "grade": "AA", "agency": "NICE", "note": "Mock"},
        {"year": 2023, "grade": "AA-", "agency": "NICE", "note": "Mock"},
        {"year": 2024, "grade": "AA-", "agency": "NICE", "note": "Mock"},
    ],
    "009150": [
        {"year": 2020, "grade": "AA+", "agency": "KIS", "note": "Mock"},
        {"year": 2021, "grade": "AA+", "agency": "KIS", "note": "Mock"},
        {"year": 2022, "grade": "AA+", "agency": "KIS", "note": "Mock"},
        {"year": 2023, "grade": "AA",  "agency": "KIS", "note": "Mock"},
        {"year": 2024, "grade": "AA",  "agency": "KIS", "note": "Mock"},
    ],
    "035420": [
        {"year": 2020, "grade": "AA+", "agency": "NICE", "note": "Mock"},
        {"year": 2021, "grade": "AA+", "agency": "NICE", "note": "Mock"},
        {"year": 2022, "grade": "AA+", "agency": "NICE", "note": "Mock"},
        {"year": 2023, "grade": "AA+", "agency": "NICE", "note": "Mock"},
        {"year": 2024, "grade": "AA+", "agency": "NICE", "note": "Mock"},
    ],
}


@router.get("/credit/{stock_code}")
def get_credit_rating(stock_code: str):
    """
    신용등급 추이.
    credit_ratings 테이블이 없으면 Mock 데이터 반환 (is_mock=true).
    실 데이터: python db/load_credit.py 실행 후 자동 전환.
    """
    # 실 테이블 시도
    try:
        with _conn() as conn:
            rows = conn.execute(
                "SELECT year, grade, agency, note "
                "FROM credit_ratings WHERE stock_code = ? ORDER BY year",
                (stock_code,)
            ).fetchall()
        if rows:
            return {
                "stock_code": stock_code,
                "is_mock": False,
                "items": [dict(r) for r in rows],
            }
    except Exception:
        pass

    # Mock 폴백
    items = _CREDIT_MOCK.get(stock_code, [])
    return {
        "stock_code": stock_code,
        "is_mock": True,
        "items": items,
        "note": "Mock 데이터 — NICE/KIS 실데이터 수집 후 DB 적재 필요",
    }
