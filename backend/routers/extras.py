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

import json
import os
import re
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
_CORP_MAP = _ROOT / "data" / "corp_code_map.json"

_log = logging.getLogger(__name__)


def _load_corp_code(stock_code: str) -> str | None:
    if not _CORP_MAP.exists():
        return None
    try:
        with open(_CORP_MAP, encoding="utf-8") as f:
            m = json.load(f).get("by_stock_code", {})
        return (m.get(stock_code) or {}).get("corp_code")
    except Exception:
        return None


def _conn():
    if not _DB.exists():
        raise HTTPException(500, "filmn9.db 없음")
    c = sqlite3.connect(_DB)
    c.row_factory = sqlite3.Row
    return c


@router.get("/stock_status/{stock_code}")
def stock_status(stock_code: str):
    """
    상장 상태 조회 — 상장폐지/거래정지/관리종목/정상.
    프론트는 status != NORMAL 일 때 주가차트·재무탭에 배너를 띄움.
    stock_status 테이블은 build_stock_status.py 가 하루 1회 갱신.
    """
    c = _conn()
    try:
        row = c.execute(
            "SELECT status,label,reason,ref_date,last_trade_date,checked_at "
            "FROM stock_status WHERE stock_code=?", (stock_code,)
        ).fetchone()
    except sqlite3.OperationalError:
        # 테이블 미생성 시 정상으로 간주 (배너 없음)
        return {"stock_code": stock_code, "status": "NORMAL", "label": "",
                "tradable": True}
    finally:
        c.close()
    if not row:
        return {"stock_code": stock_code, "status": "NORMAL", "label": "",
                "tradable": True}
    status = row["status"]
    return {
        "stock_code": stock_code,
        "status": status,                       # NORMAL/ADMIN/HALT/DELISTED
        "label": row["label"],                  # 화면 표기 한글
        "reason": row["reason"],
        "ref_date": row["ref_date"],            # 상폐일/지정일
        "last_trade_date": row["last_trade_date"],
        "checked_at": row["checked_at"],
        "tradable": status in ("NORMAL", "ADMIN"),
    }


# ─── 주주 관계 한자 → 한글 정규화 (DART relate 필드가 한자인 경우) ──────────────
_HANJA_REL = [
    ("配偶者", "배우자"), ("子女", "자녀"), ("叔父", "삼촌"), ("妹兄", "매형"),
    ("外叔", "외삼촌"), ("本人", "본인"),
    ("子", "자녀"), ("女", "딸"), ("父", "부"), ("母", "모"),
    ("兄", "형"), ("弟", "동생"), ("妹", "여동생"), ("姉", "누나"),
    ("妻", "배우자"), ("夫", "배우자"), ("孫", "손주"), ("姪", "조카"),
    ("叔", "삼촌"), ("婿", "사위"), ("媳", "며느리"), ("姑", "고모"),
    ("舅", "외삼촌"), ("甥", "생질"), ("姻", "인척"), ("族", "친족"), ("血", "혈"),
]


def _norm_relation(rel):
    """관계 문자열 내 한자를 한글로 치환 (한글 부분은 유지)."""
    if not rel:
        return rel
    s = str(rel)
    for h, k in _HANJA_REL:
        s = s.replace(h, k)
    return s


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
            "  AND name NOT IN ('계','합계','소계') "
            "  AND (shares IS NULL OR shares > 0) "
            "ORDER BY rank",
            (stock_code, latest_year)).fetchall()

        # 중복 (name, relation) 행 → ratio 최대값만 채택
        dedup: dict = {}
        for r in rows:
            key = (r["name"], r["relation"])
            cur = dedup.get(key)
            if cur is None or (r["ratio"] or 0) > (cur["ratio"] or 0):
                dedup[key] = dict(r)
        items = sorted(dedup.values(), key=lambda x: -(x["ratio"] or 0))

    # 관계 한자 → 한글 (전 종목 일괄 적용)
    for it in items:
        it["relation"] = _norm_relation(it.get("relation"))

    return {
        "stock_code": stock_code,
        "fiscal_year": latest_year,
        "items": items,
        "total_ratio": round(sum((r["ratio"] or 0) for r in items), 3),
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


# ─── WICS 산업·업종 검색 (유사어 사전 기반) ───────────────────────────────
@router.get("/sectors/search")
def search_sectors(q: str = Query(..., min_length=1, max_length=30)):
    """키워드(유사어)로 WICS 업종 찾기
    예: ?q=방산 → 우주항공과국방
    """
    q_norm = re.sub(r"\s+", "", q).lower()
    with _conn() as conn:
        rows = conn.execute("""
            SELECT DISTINCT wics_name FROM wics_keywords
            WHERE keyword_norm LIKE '%' || ? || '%'
            ORDER BY wics_name
        """, (q_norm,)).fetchall()
    return {
        "query": q,
        "matched_sectors": [r["wics_name"] for r in rows],
        "count": len(rows),
    }


@router.get("/sectors/all")
def list_all_sectors():
    """WICS 78개 업종 전체 목록 + 키워드 수"""
    with _conn() as conn:
        rows = conn.execute("""
            SELECT wics_name, COUNT(*) as kw_count
            FROM wics_keywords
            GROUP BY wics_name
            ORDER BY wics_name
        """).fetchall()
    return {
        "total": len(rows),
        "sectors": [dict(r) for r in rows],
    }


# ─── 고객사·경쟁사 (히스토리 브리핑 보강) ──────────────────────────────────
@router.get("/peers/{stock_code}")
def get_peers(stock_code: str):
    """경쟁사 (WICS 동종업계) + 고객사 (사업보고서 기반)"""
    with _conn() as conn:
        comp_rows = conn.execute("""
            SELECT competitor_code, competitor_name, rank, basis, wics
            FROM peer_competitors WHERE stock_code = ?
            ORDER BY rank
        """, (stock_code,)).fetchall()

        cust_row = conn.execute("""
            SELECT customer_type, customers, channels, source_grade, source_text
            FROM company_customers WHERE stock_code = ?
        """, (stock_code,)).fetchone()

    competitors = [
        {"code": r["competitor_code"], "name": r["competitor_name"], "rank": r["rank"]}
        for r in comp_rows
    ]
    wics = comp_rows[0]["wics"] if comp_rows else None

    customers = None
    if cust_row:
        grade_label = {"B": "사업보고서 매출처", "C": "소비자(B2C)", "M": "B2B+B2C"}.get(cust_row["source_grade"], "")
        customers = {
            "type": cust_row["customer_type"],          # B2B / B2C / MIXED
            "items": [c.strip() for c in (cust_row["customers"] or "").split(",") if c.strip()],
            "channels": cust_row["channels"] or "",     # 판매채널·지역 (빈도순)
            "grade": cust_row["source_grade"],
            "grade_label": grade_label,
            "source_text": cust_row["source_text"],
        }

    return {
        "stock_code": stock_code,
        "wics": wics,
        "competitors": competitors,
        "customers": customers,
    }


# ─── 전자공시 (DART list.json 실시간, 페이지네이션·필터) ─────────────────────
_DART_DISC_CACHE: dict = {}   # {(corp_code,bgn,end,types,page): (ts, data)}
_DART_DISC_TTL = 600          # 10분 캐시

# 화면 라벨 → DART pblntf_ty 코드 매핑
_DISCLOSURE_TYPES = {
    "A": "정기공시",
    "B": "주요사항보고",
    "C": "발행공시",
    "D": "지분공시",
    "E": "기타공시",
    "F": "외부감사관련",
    "G": "펀드공시",
    "H": "자산유동화",
    "I": "거래소공시",
    "J": "공정위공시",
}


def _infer_disclosure_type(report_nm: str) -> tuple[str, str]:
    """보고서명 패턴 → (코드, 라벨) 추정 (DART 응답엔 pblntf_ty가 없어서 별도 추정)"""
    nm = report_nm or ""
    n = nm.replace(" ", "")
    if any(k in n for k in ["사업보고서", "분기보고서", "반기보고서"]):
        return "A", "정기공시"
    if "주요사항보고" in n:
        return "B", "주요사항보고"
    if any(k in n for k in ["증권신고", "증권발행", "투자설명서", "일괄신고"]):
        return "C", "발행공시"
    if any(k in n for k in ["임원ㆍ주요주주", "임원·주요주주", "주식등의대량보유", "의결권대리행사권유"]):
        return "D", "지분공시"
    if any(k in n for k in ["감사보고서"]):
        return "F", "외부감사관련"
    if "펀드" in n or "투자회사" in n:
        return "G", "펀드공시"
    if "자산유동화" in n or "유동화증권" in n:
        return "H", "자산유동화"
    if any(k in n for k in ["대규모기업집단", "기업집단현황", "비상장회사중요사항", "동일인등출자계열"]):
        return "J", "공정위공시"
    if any(k in n for k in ["영업(잠정)실적", "단일판매ㆍ공급계약", "단일판매·공급계약",
                            "기업설명회", "투자판단", "거래정지", "지배구조보고서",
                            "기업지배구조", "주식분할", "주식병합", "공정공시"]):
        return "I", "거래소공시"
    return "E", "기타공시"


@router.get("/dart_disclosures/{stock_code}")
def get_dart_disclosures(
    stock_code: str,
    period: str = Query("1y", regex="^(1m|6m|1y|3y|5y|10y|custom)$"),
    bgn_de: str | None = Query(None, regex="^[0-9]{8}$"),
    end_de: str | None = Query(None, regex="^[0-9]{8}$"),
    types: str | None = Query(None, description="공시유형 다중 (A,B,C 콤마구분, 빈값=전체)"),
    page: int = Query(1, ge=1, le=100),
    page_count: int = Query(15, ge=5, le=100),
    final: bool = Query(True, description="최종보고서만"),
):
    """
    DART 전자공시 — 종목별 전체 공시 목록 (실시간)
    네이버 증권 전자공시 탭과 동일한 UX 지원
    """
    corp_code = _load_corp_code(stock_code)
    if not corp_code:
        raise HTTPException(404, f"{stock_code} corp_code 없음")

    api_key = os.environ.get("DART_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(500, "DART_API_KEY 환경변수 없음")

    # 기간 산출
    today = datetime.datetime.today()
    if period == "custom" and bgn_de and end_de:
        bgn, end = bgn_de, end_de
    else:
        period_map = {"1m": 30, "6m": 180, "1y": 365,
                      "3y": 365*3, "5y": 365*5, "10y": 365*10}
        days = period_map.get(period, 365)
        end = today.strftime("%Y%m%d")
        bgn = (today - datetime.timedelta(days=days)).strftime("%Y%m%d")

    cache_key = f"{corp_code}_{bgn}_{end}_{types or 'ALL'}_{page}_{page_count}_{final}"
    now_ts = datetime.datetime.now().timestamp()
    cached = _DART_DISC_CACHE.get(cache_key)
    if cached and now_ts - cached[0] < _DART_DISC_TTL:
        return cached[1]

    # DART API 파라미터
    params = {
        "crtfc_key": api_key,
        "corp_code": corp_code,
        "bgn_de": bgn,
        "end_de": end,
        "page_no": page,
        "page_count": page_count,
        "sort": "date",
        "sort_mth": "desc",
    }
    if final:
        params["last_reprt_at"] = "Y"

    # 공시유형은 단일만 지원 — 여러 개면 클라이언트 측에서 호출 분할하거나 전체 후 필터
    types_list = [t.strip() for t in (types or "").split(",") if t.strip()]
    if len(types_list) == 1:
        params["pblntf_ty"] = types_list[0]

    url = "https://opendart.fss.or.kr/api/list.json?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=8) as r:
            raw = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        raise HTTPException(502, f"DART API 호출 실패: {e}")

    status = raw.get("status")
    if status == "013":   # 데이터 없음
        result = {
            "stock_code": stock_code, "corp_code": corp_code,
            "items": [], "total_count": 0, "total_page": 0,
            "page_no": page, "page_count": page_count,
            "bgn_de": bgn, "end_de": end,
        }
        _DART_DISC_CACHE[cache_key] = (now_ts, result)
        return result
    if status not in ("000",):
        raise HTTPException(502, f"DART API: {raw.get('message')}")

    items = []
    for it in raw.get("list", []):
        report_nm = (it.get("report_nm", "") or "").strip()
        # 보고서명 패턴으로 유형 추정 (DART 응답엔 pblntf_ty 없음)
        ptype, plabel = _infer_disclosure_type(report_nm)
        # types 다중 필터 (클라이언트 측 필터링)
        if len(types_list) > 1 and ptype not in types_list:
            continue
        rcept_no = it.get("rcept_no", "")
        items.append({
            "rcept_no":     rcept_no,
            "rcept_dt":     it.get("rcept_dt", ""),
            "corp_name":    it.get("corp_name", ""),
            "corp_cls":     it.get("corp_cls", ""),    # Y=유가, K=코스닥, N=코넥스, E=기타
            "report_nm":    report_nm,
            "flr_nm":       it.get("flr_nm", ""),
            "rm":           it.get("rm", ""),
            "pblntf_ty":    ptype,
            "pblntf_label": plabel,
            "dart_url":     f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}",
        })

    result = {
        "stock_code": stock_code,
        "corp_code": corp_code,
        "items": items,
        "total_count": int(raw.get("total_count", 0)),
        "total_page": int(raw.get("total_page", 0)),
        "page_no": page,
        "page_count": page_count,
        "bgn_de": bgn,
        "end_de": end,
    }
    _DART_DISC_CACHE[cache_key] = (now_ts, result)
    return result


# ─── 단일판매·공급계약 공시 (DART list.json 실시간) ─────────────────────────
_SUPPLY_CACHE: dict = {}  # {corp_code: (timestamp, data)}
_SUPPLY_TTL = 3600  # 1시간 캐시


@router.get("/supply_contracts/{stock_code}")
def get_supply_contracts(stock_code: str, years: int = Query(5, ge=1, le=10)):
    """단일판매·공급계약 체결/해지 공시 목록 (DART list.json 실시간 호출)"""
    corp_code = _load_corp_code(stock_code)
    if not corp_code:
        raise HTTPException(404, f"{stock_code} corp_code 없음")

    api_key = os.environ.get("DART_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(500, "DART_API_KEY 환경변수 없음")

    # 캐시 확인
    now_ts = datetime.datetime.now().timestamp()
    cache_key = f"{corp_code}_{years}"
    cached = _SUPPLY_CACHE.get(cache_key)
    if cached and now_ts - cached[0] < _SUPPLY_TTL:
        return cached[1]

    today = datetime.datetime.today()
    end_de = today.strftime("%Y%m%d")
    bgn_de = today.replace(year=today.year - years).strftime("%Y%m%d")

    params = {
        "crtfc_key": api_key,
        "corp_code": corp_code,
        "bgn_de": bgn_de,
        "end_de": end_de,
        "pblntf_ty": "I",          # 거래소공시
        "pblntf_detail_ty": "I001",  # 수시공시
        "page_count": 100,
        "sort": "date",
        "sort_mth": "desc",
    }
    url = "https://opendart.fss.or.kr/api/list.json?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=8) as r:
            raw = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        raise HTTPException(502, f"DART API 호출 실패: {e}")

    if raw.get("status") not in ("000", "013"):
        # 013 = 데이터 없음
        if raw.get("status") == "013":
            result = {"stock_code": stock_code, "corp_code": corp_code,
                      "items": [], "count": 0, "years": years}
            _SUPPLY_CACHE[cache_key] = (now_ts, result)
            return result
        raise HTTPException(502, f"DART API: {raw.get('message')}")

    items = []
    for it in raw.get("list", []):
        nm = it.get("report_nm", "")
        norm = nm.replace("ㆍ", "").replace("·", "").replace(" ", "")
        if "단일판매공급계약체결" in norm:
            event = "체결"
        elif "단일판매공급계약해지" in norm:
            event = "해지"
        else:
            continue
        rcept_no = it.get("rcept_no", "")
        items.append({
            "rcept_no": rcept_no,
            "rcept_dt": it.get("rcept_dt", ""),
            "report_nm": nm,
            "event_type": event,
            "flr_nm": it.get("flr_nm", ""),
            "rm": it.get("rm", ""),
            "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}",
        })

    result = {
        "stock_code": stock_code, "corp_code": corp_code,
        "items": items, "count": len(items), "years": years,
    }
    _SUPPLY_CACHE[cache_key] = (now_ts, result)
    return result


# ─── 재무상세 ────────────────────────────────────────────────────────────────

def _detect_fd_unit(conn, stock_code: str) -> str:
    """
    financial_detail 금액의 단위(원/천원/백만원)를 종목별로 감지.
    DART financials.assets(백만원=진실값)를 기준으로 financial_detail 자산총계와 비교해 역산.
    DART 값이 없으면 자산총계 자릿수로 폴백.
    """
    fd = conn.execute(
        "SELECT amount FROM financial_detail "
        "WHERE stock_code=? AND statement_type='BS' AND account_nm LIKE '%자산총계%' AND amount>0 "
        "ORDER BY (statement_scope='연결') DESC, fiscal_year DESC LIMIT 1", (stock_code,)).fetchone()
    if not fd or not fd[0]:
        return "원"
    fdv = float(fd[0])
    fa = conn.execute(
        "SELECT assets FROM financials WHERE stock_code=? AND assets IS NOT NULL "
        "ORDER BY fiscal_year DESC LIMIT 1", (stock_code,)).fetchone()
    if fa and fa[0]:
        true_won = float(fa[0]) * 1e6          # DART assets(백만) → 원
        ratio = true_won / fdv                 # financial_detail × ratio ≈ 원
        for mult, label in ((1, "원"), (1e3, "천원"), (1e6, "백만원")):
            if 0.3 <= ratio / mult <= 3:       # 연도차 ±3배 허용
                return label
    # 폴백: 자산총계 자릿수 (상장사 자산 ≥ ~1000억 in 원)
    if fdv >= 1e11:
        return "원"
    if fdv >= 1e8:
        return "백만원"
    return "천원"


@router.get("/financial_detail/{stock_code}/{statement_type}")
def get_financial_detail(stock_code: str, statement_type: str, scope: str = "연결"):
    """
    재무제표 상세 (B/S, I/S, CIS).
    pivot: 행=account_nm, 열=fiscal_year

    [Query Parameter]
    - statement_type: BS (재무상태표), IS (손익계산서), CIS (포괄손익계산서)
                      ※ IS 호출 시 자동으로 IS+CIS 모두 검색 (사업보고서마다 다름)
    - scope: "연결" (기본값) | "별도"

    [수정 이력 2026-05-27]
    - CIS (포괄손익계산서) 지원 추가
    - statement_scope 필터 추가 (연결/별도)
    - 단위 '원' 명시
    - account_id 기준 중복 제거 (account_nm 중복 시 덮어씀 방지)
    """
    st = statement_type.upper()
    if st not in ("BS", "IS", "CIS"):
        raise HTTPException(400, "statement_type은 BS, IS, CIS 중 하나")

    if scope not in ("연결", "별도"):
        raise HTTPException(400, "scope는 '연결' 또는 '별도'")

    # IS 호출 시 IS 또는 CIS 모두 검색 (회사마다 다른 명칭 사용)
    if st == "IS":
        st_filter = ("IS", "CIS")
    elif st == "CIS":
        st_filter = ("CIS", "IS")
    else:
        st_filter = (st,)

    placeholders = ",".join("?" * len(st_filter))

    with _conn() as conn:
        rows = conn.execute(
            f"SELECT fiscal_year, account_id, account_nm, amount, "
            f"       statement_scope, statement_type, display_order "
            f"FROM financial_detail "
            f"WHERE stock_code = ? AND statement_type IN ({placeholders}) "
            f"  AND statement_scope = ? "
            f"ORDER BY fiscal_year DESC, display_order",
            (stock_code, *st_filter, scope)).fetchall()
        unit = _detect_fd_unit(conn, stock_code)   # 종목별 단위 감지

    if not rows:
        raise HTTPException(404,
            f"{stock_code} {st} ({scope}) 데이터 없음")

    # pivot — account_id 기준 (계정명이 같아도 ID 다르면 별개 행)
    years = sorted({r["fiscal_year"] for r in rows}, reverse=True)
    accounts: dict[str, dict] = {}
    for r in rows:
        key = r["account_id"]
        if key not in accounts:
            accounts[key] = {
                "account_id": key,
                "account_nm": r["account_nm"],
                "display_order": r["display_order"],
                "scope": r["statement_scope"],
                "statement_type": r["statement_type"],
                "values": {},
            }
        accounts[key]["values"][str(r["fiscal_year"])] = r["amount"]

    # ─── 핵심 항목 우선 정렬 (2026-05-27 추가) ───
    # 매출액/자산총계 등이 화면 맨 위로 오도록 우선순위 부여
    PRIORITY_KEYWORDS_BS = [
        "자산총계", "자산 총계", "유동자산", "비유동자산",
        "현금및현금성자산", "부채총계", "부채 총계", "유동부채",
        "비유동부채", "자본총계", "자본 총계", "자본금",
    ]
    PRIORITY_KEYWORDS_IS = [
        "매출액", "영업수익", "수익(매출액)", "매출",
        "영업비용", "매출원가", "매출총이익",
        "영업이익", "영업손실",
        "법인세비용차감전순이익", "당기순이익", "당기순손실",
        "지배기업", "비지배지분", "주당순이익", "총포괄이익",
    ]

    if st == "BS":
        keywords = PRIORITY_KEYWORDS_BS
    else:
        keywords = PRIORITY_KEYWORDS_IS

    def priority(item):
        nm = item["account_nm"] or ""
        for idx, kw in enumerate(keywords):
            if kw in nm:
                return (0, idx, item["display_order"] or 0)
        return (1, 999, item["display_order"] or 0)

    items = sorted(accounts.values(), key=priority)

    # ─── 음수 부호 처리 (XBRL ANEGATED 의미를 화면용 부호로) ───
    # DB에는 절댓값으로 저장되어 있지만, 비용·차감 항목은 음수로 표시
    NEGATIVE_KEYWORDS_IS = [
        "영업비용", "매출원가", "판매비", "관리비", "비용",
        "법인세비용", "감가상각", "차감",
    ]
    for item in items:
        nm = item["account_nm"] or ""
        # IS/CIS 에서 비용 키워드 포함된 계정명은 음수로 표시
        if st in ("IS", "CIS") and any(kw in nm for kw in NEGATIVE_KEYWORDS_IS):
            for yr, v in item["values"].items():
                if v is not None and v > 0:
                    item["values"][yr] = -abs(v)

    return {
        "stock_code": stock_code,
        "statement_type": st,
        "scope": scope,
        "fiscal_years": [str(y) for y in years],
        "unit": unit,
        "items": items,
        "count": len(items),
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
_YF_SUFFIX = ".KS"   # 기본값 (KOSPI)

_SUFFIX_MAP: dict[str, str] = {}   # stock_code → .KS/.KQ (ticker_suffix 테이블 캐시)
_SUFFIX_LOADED = False


def _load_suffix_map():
    """ticker_suffix 테이블 → 캐시 (KOSDAQ .KQ 정확 매핑). 1회 로드."""
    global _SUFFIX_LOADED
    if _SUFFIX_LOADED:
        return
    try:
        with _conn() as conn:
            for code, suf in conn.execute("SELECT stock_code, suffix FROM ticker_suffix").fetchall():
                _SUFFIX_MAP[code] = suf
    except Exception:
        pass
    _SUFFIX_LOADED = True


def _yf_ticker(stock_code: str) -> str:
    """종목코드 → yfinance 티커. KOSDAQ은 .KQ (ticker_suffix 기준)."""
    _load_suffix_map()
    return f"{stock_code}{_SUFFIX_MAP.get(stock_code, _YF_SUFFIX)}"


def _ohlcv_last_close(stock_code: str):
    """우리 DB 최신 종가 (가격 sanity 대조용)."""
    try:
        with _conn() as conn:
            r = conn.execute(
                "SELECT close FROM ohlcv WHERE stock_code=? ORDER BY date DESC LIMIT 1",
                (stock_code,)).fetchone()
        return float(r[0]) if r and r[0] else None
    except Exception:
        return None


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

        # ── 안전장치: 우리 ohlcv 최신 종가와 50%↑ 벗어나면 반대 접미사로 자동 교정 ──
        # (KOSDAQ 종목이 잘못된 .KS 유령 티커 값을 받는 경우 방지)
        ref = _ohlcv_last_close(stock_code)
        if ref and price and abs(price - ref) / ref > 0.5:
            alt_suffix = ".KQ" if ticker.endswith(".KS") else ".KS"
            alt_ticker = f"{stock_code}{alt_suffix}"
            try:
                t2 = yf.Ticker(alt_ticker)
                p2 = t2.fast_info.last_price
                if p2 and abs(p2 - ref) / ref < abs(price - ref) / ref:
                    t, fi, ticker = t2, t2.fast_info, alt_ticker
                    price, market_cap = p2, fi.market_cap
            except Exception:
                pass

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
    "035420": "네이버",   # 영문 'NAVER' 대신 한글 '네이버' 사용 (정확도 ↑)
}


_TICKER_NAME_CACHE: dict = {}  # ticker_universe.csv 캐시


def _load_ticker_universe():
    """ticker_universe.csv 한 번만 메모리에 로드"""
    global _TICKER_NAME_CACHE
    if _TICKER_NAME_CACHE:
        return
    csv_path = _ROOT / "data" / "ticker_universe.csv"
    if not csv_path.exists():
        return
    try:
        import csv
        with open(csv_path, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                code = (r.get("stock_code") or "").strip()
                name = (r.get("corp_name") or "").strip()
                if code and name:
                    _TICKER_NAME_CACHE[code] = name
    except Exception as e:
        logging.warning(f"ticker_universe.csv 로드 실패: {e}")


def _load_corp_name(stock_code: str) -> str:
    """1순위 매핑 테이블 → 2순위 ticker_universe.csv → 3순위 DB company_info → 4순위 stock_code"""
    if stock_code in _CORP_NAME_MAP:
        return _CORP_NAME_MAP[stock_code]
    _load_ticker_universe()
    if stock_code in _TICKER_NAME_CACHE:
        name = re.sub(r"[\(\)（）㈜]|주식회사", "", _TICKER_NAME_CACHE[stock_code]).strip()
        return name or stock_code
    try:
        with _conn() as conn:
            row = conn.execute(
                "SELECT corp_name FROM company_info WHERE stock_code = ?",
                (stock_code,)).fetchone()
            if row and row["corp_name"]:
                name = re.sub(r"[\(\)（）㈜]|주식회사", "", row["corp_name"]).strip()
                return name or stock_code
    except Exception:
        pass
    return stock_code


_NEWS_CACHE: dict = {}   # {stock_code: (timestamp, items)}
_NEWS_TTL = 300          # 5분 캐시


def _strip_html(text: str) -> str:
    """네이버 응답의 <b>·HTML 엔티티 제거"""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", text)
    text = (text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
                .replace("&quot;", '"').replace("&apos;", "'").replace("&#39;", "'"))
    return text.strip()


def _domain_from_url(url: str) -> str:
    """링크에서 매체명 추출 (예: https://www.hankyung.com/... → hankyung.com)"""
    if not url:
        return ""
    m = re.match(r"https?://(?:www\.)?([^/]+)", url)
    return m.group(1) if m else ""


@router.get("/news/{stock_code}")
def get_news(stock_code: str, limit: int = Query(5, ge=1, le=20)):
    """
    네이버 검색 API (뉴스) 기반 최신 뉴스 (한국어).
    - 일일 25,000건 한도 (무료)
    - 5분 메모리 캐시
    - 환경변수 NAVER_CLIENT_ID, NAVER_CLIENT_SECRET 필요
    - 키 없으면 Google News RSS 폴백
    """
    corp = _load_corp_name(stock_code)
    now_ts = datetime.datetime.now().timestamp()

    # 캐시 확인
    cache_key = f"{stock_code}_{limit}"
    cached = _NEWS_CACHE.get(cache_key)
    if cached and now_ts - cached[0] < _NEWS_TTL:
        return {"stock_code": stock_code, "corp": corp,
                "items": cached[1], "_cached": True, "_source": "Naver (cached)"}

    # Windows·Linux 호환 위해 여러 케이스 시도
    naver_id = (os.environ.get("NAVER_CLIENT_ID") or
                os.environ.get("Naver_Client_Id") or "").strip()
    naver_secret = (os.environ.get("NAVER_CLIENT_SECRET") or
                    os.environ.get("Naver_Client_Secret") or "").strip()

    # ── 1순위: 네이버 검색 API ─────────────────────────────────
    if naver_id and naver_secret:
        try:
            # 회사명 + 주식·종목 관련 키워드로 narrowing → 종목 관련 기사만
            # OR 검색이 안 되므로 가장 일반적인 "주가" 추가
            query = f"{corp} 주가"
            params = {"query": query, "display": 50,   # 넉넉히 받아 필터
                      "start": 1, "sort": "date"}
            url = "https://openapi.naver.com/v1/search/news.json?" + urllib.parse.urlencode(params)
            req = urllib.request.Request(url, headers={
                "X-Naver-Client-Id": naver_id,
                "X-Naver-Client-Secret": naver_secret,
                "User-Agent": "Mozilla/5.0",
            })
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            items_raw = data.get("items", [])
            # 회사명이 제목에 포함된 기사만 채택 (본문만 스치는 기사 제거)
            corp_norm = corp.replace(" ", "")
            news = []
            for it in items_raw:
                title_clean = _strip_html(it.get("title", ""))
                if not title_clean:
                    continue
                title_norm = title_clean.replace(" ", "")
                # 제목에 회사명 포함 필수
                if corp_norm not in title_norm:
                    continue
                pub = it.get("pubDate", "")
                try:
                    dt = datetime.datetime.strptime(pub[:25], "%a, %d %b %Y %H:%M:%S")
                    pub_fmt = dt.strftime("%Y-%m-%d %H:%M")
                except Exception:
                    pub_fmt = pub[:16]
                link = it.get("link") or it.get("originallink", "")
                news.append({
                    "title":   title_clean,
                    "link":    link,
                    "pubdate": pub_fmt,
                    "source":  _domain_from_url(it.get("originallink") or link),
                    "summary": _strip_html(it.get("description", ""))[:140],
                })
                if len(news) >= limit:
                    break

            if news:
                _NEWS_CACHE[cache_key] = (now_ts, news)
                return {"stock_code": stock_code, "corp": corp,
                        "items": news, "_source": "Naver Open API"}
            # 0건이면 폴백으로 진행 (return 안 함)
        except Exception as e:
            logging.warning(f"naver news {stock_code} 실패 → RSS 폴백: {e}")

    # ── 2순위 폴백: 파이낸셜뉴스(증권) + 한국경제 병렬 RSS ─────
    import ssl as _ssl
    from concurrent.futures import ThreadPoolExecutor

    _ctx = _ssl.create_default_context()
    _ctx.check_hostname = False
    _ctx.verify_mode = _ssl.CERT_NONE

    RSS_SOURCES = [
        ("파이낸셜뉴스",  "https://www.fnnews.com/rss/r20/fn_realnews_stock.xml"),
        ("한국경제",      "https://www.hankyung.com/feed/economy"),
    ]

    # 종목명 키워드 (회사명 + 약칭)
    keywords = {corp}
    short = re.sub(r"[\(\)（）주식회사주㈜]", "", corp).strip()
    if short and short != corp:
        keywords.add(short)
    if corp:
        parts = re.sub(r"[\(\)（）주식회사주㈜]", "", corp).split()
        if parts and len(parts[0]) >= 2:
            keywords.add(parts[0])
    keywords = {k for k in keywords if k}

    def _fetch_rss(src_url):
        src_name, url = src_url
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537.36",
                "Accept": "application/xml, text/xml, */*",
            })
            with urllib.request.urlopen(req, context=_ctx, timeout=3) as resp:
                body = resp.read()
            root = ET.fromstring(body)
            return src_name, root.findall(".//item")
        except Exception as e:
            logging.warning(f"RSS {src_name} 실패: {e}")
            return src_name, []

    try:
        # 병렬 호출
        with ThreadPoolExecutor(max_workers=2) as ex:
            results = list(ex.map(_fetch_rss, RSS_SOURCES))

        # 매체별 종목명 필터링·통합
        collected = []
        seen_titles = set()
        for src_name, items in results:
            for item in items:
                title = _strip_html((item.findtext("title") or "").strip())
                if not title or title in seen_titles:
                    continue
                desc = _strip_html((item.findtext("description") or "").strip())
                # 종목명 매칭 (제목+요약)
                if not any(k in (title + desc) for k in keywords):
                    continue
                seen_titles.add(title)
                link = (item.findtext("link") or "").strip()
                pubdate = (item.findtext("pubDate") or "").strip()
                try:
                    dt = datetime.datetime.strptime(pubdate[:25], "%a, %d %b %Y %H:%M:%S")
                    pub_fmt = dt.strftime("%Y-%m-%d %H:%M")
                except Exception:
                    pub_fmt = pubdate[:16]
                collected.append({
                    "title":   title,
                    "link":    link,
                    "pubdate": pub_fmt,
                    "source":  src_name,
                    "summary": desc[:140],
                    "_pub_raw": pubdate,
                })

        # 최신순 정렬 → 상위 limit개
        def _sort_key(x):
            try:
                return datetime.datetime.strptime(x["_pub_raw"][:25],
                                                  "%a, %d %b %Y %H:%M:%S")
            except Exception:
                return datetime.datetime.min
        collected.sort(key=_sort_key, reverse=True)
        news = [{k: v for k, v in it.items() if k != "_pub_raw"}
                for it in collected[:limit]]

        _NEWS_CACHE[cache_key] = (now_ts, news)
        src_label = ("파이낸셜뉴스+한국경제 RSS" if news
                     else "파이낸셜뉴스+한국경제 RSS (매칭 0건)")
        return {"stock_code": stock_code, "corp": corp,
                "items": news, "_source": src_label}
    except Exception as e:
        logging.warning(f"RSS fallback {stock_code}: {e}")
        return {"stock_code": stock_code, "corp": corp,
                "items": [], "_source": "전체 실패", "error": str(e)}


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
