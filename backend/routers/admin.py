"""
backend/routers/admin.py
========================
관리자 페이지 백엔드 — 설계서(통합산출물/PM_산출물/01_관리자페이지_요구사항_설계서.md) 구현.

[탭1] 운영 모니터링 (읽기 전용)
  GET  /api/admin/health      서버 3종(백엔드/프론트3000/챗봇8800) UP·응답시간
  GET  /api/admin/db-stats    SQLite 테이블별 행수 + 빈 테이블 경고
  GET  /api/admin/freshness   배치별 최신 동기화 시각(주가/적재/Sankey/밸류)
  GET  /api/admin/coverage    기준 종목수 대비 파트별 보유율(%)
  GET  /api/admin/smoke       샘플 종목 핵심 데이터 핑(작동 확인)
  POST /api/admin/cache/refresh   모닝 위젯 캐시 강제 갱신(확인 필요)

[탭2] 신뢰도 검증 (NO-MOCK 정합성)
  POST /api/admin/verify/sample   파트·N개 샘플 검증(숫자 매칭·완전성·항등식)
  GET  /api/admin/verify/report   최근 샘플 검증 결과

※ 모두 읽기 전용 또는 멱등. .env/키 노출 없음. 데이터 없으면 정직하게 0/none.
"""
from __future__ import annotations

import socket
import sqlite3
import time
from pathlib import Path

import os
from fastapi import APIRouter, Body, Header, HTTPException, Depends


def verify_admin(x_admin_token: str = Header(default="")):
    """관리자 인증 — .env의 ADMIN_TOKEN과 X-Admin-Token 헤더 일치 시에만 통과.
    ADMIN_TOKEN 미설정이면 전부 401(안전 기본값). 값은 코드/Git에 두지 않고 .env에서만 읽음."""
    expected = os.getenv("ADMIN_TOKEN", "")
    if not expected or x_admin_token != expected:
        raise HTTPException(status_code=401, detail="관리자 인증이 필요합니다")


# 모든 /admin/* 라우트에 인증 의존성 적용
router = APIRouter(dependencies=[Depends(verify_admin)])

_ROOT = Path(__file__).resolve().parent.parent.parent
_DB = _ROOT / "data" / "filmn9.db"
_SANKEY = _ROOT / "outputs" / "sankey"
_AFFIL = _ROOT / "기업개요_파트" / "계열회사시각화"

# 기준 종목수(동결 기준 = 산업분류 활성 종목)
_BASE_UNIVERSE = 2580


def _conn():
    from backend.db import connect
    return connect()


def _tables(cur):
    # SQLite=sqlite_master / PostgreSQL=pg_tables (DB_BACKEND 분기)
    from backend.db import DB_BACKEND
    if DB_BACKEND == "postgres":
        sql = "SELECT tablename AS name FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
    else:
        sql = "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    return [r["name"] for r in cur.execute(sql)]


def _port_up(host: str, port: int, timeout: float = 0.6):
    """TCP 연결로 포트 생존 + 응답시간(ms) 측정."""
    t0 = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, round((time.perf_counter() - t0) * 1000, 1)
    except OSError:
        return False, None


# ───────────────────────── 탭1 · 모니터링 ─────────────────────────

@router.get("/admin/health")
def admin_health():
    """서버 3종 상태(백엔드=self ok, 프론트 3000, 챗봇 8800)."""
    front_up, front_ms = _port_up("127.0.0.1", 3000)
    chat_up, chat_ms = _port_up("127.0.0.1", 8800)
    return {
        "servers": [
            {"name": "백엔드 (FastAPI)", "port": 8090, "up": True, "ms": 0,
             "note": "self"},
            {"name": "프론트엔드 (Next.js)", "port": 3000, "up": front_up, "ms": front_ms},
            {"name": "AI 챗봇 (RAG)", "port": 8800, "up": chat_up, "ms": chat_ms},
        ],
        "db_exists": _DB.exists(),
    }


@router.get("/admin/db-stats")
def admin_db_stats():
    """SQLite 테이블별 행수 + 빈 테이블."""
    if not _DB.exists():
        return {"tables": [], "total_rows": 0, "empty": [], "error": "DB 없음"}
    con = _conn()
    cur = con.cursor()
    out = []
    total = 0
    empty = []
    for t in _tables(cur):
        try:
            n = cur.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        except Exception:
            n = -1
        out.append({"table": t, "rows": n})
        if n == 0:
            empty.append(t)
        if n > 0:
            total += n
    con.close()
    return {"tables": out, "total_rows": total, "empty": empty,
            "table_count": len(out)}


@router.get("/admin/freshness")
def admin_freshness():
    """배치별 최신 동기화 시각."""
    items = []
    if _DB.exists():
        con = _conn(); cur = con.cursor()

        def q1(sql):
            try:
                v = cur.execute(sql).fetchone()[0]
                return v
            except Exception:
                return None

        items.append({"source": "주가 OHLCV (일배치 16:00)",
                      "latest": q1("SELECT MAX(date) FROM ohlcv"),
                      "kind": "일배치"})
        items.append({"source": "재무 적재 (financials)",
                      "latest": q1("SELECT MAX(loaded_at) FROM financials"),
                      "kind": "시즌배치"})
        items.append({"source": "공시 적재 (disclosures)",
                      "latest": q1("SELECT MAX(loaded_at) FROM disclosures"),
                      "kind": "시즌배치"})
        items.append({"source": "밸류 요약 (valuation_summary)",
                      "latest": q1("SELECT MAX(as_of_date) FROM valuation_summary"),
                      "kind": "사전배치"})
        con.close()

    # Sankey 사전생성 파일
    if _SANKEY.exists():
        files = list(_SANKEY.glob("*_sankey.html"))
        newest = max((f.stat().st_mtime for f in files), default=None)
        items.append({
            "source": f"손익흐름도 Sankey (사전생성 {len(files)}개)",
            "latest": time.strftime("%Y-%m-%d %H:%M", time.localtime(newest)) if newest else None,
            "kind": "사전배치"})
    return {"items": items}


@router.get("/admin/coverage")
def admin_coverage():
    """기준 종목수 대비 파트별 보유율."""
    base = _BASE_UNIVERSE
    rows = []
    if _DB.exists():
        con = _conn(); cur = con.cursor()

        def cnt(sql):
            try:
                return cur.execute(sql).fetchone()[0]
            except Exception:
                return 0

        company = cnt("SELECT COUNT(*) FROM company_info")
        rows = [
            {"part": "기업개요 (company_info)", "count": company},
            {"part": "재무 (financials)",
             "count": cnt("SELECT COUNT(DISTINCT stock_code) FROM financials")},
            {"part": "주가 (ohlcv)",
             "count": cnt("SELECT COUNT(DISTINCT stock_code) FROM ohlcv")},
            {"part": "주주 (shareholders)",
             "count": cnt("SELECT COUNT(DISTINCT stock_code) FROM shareholders")},
            {"part": "경영인 (executives)",
             "count": cnt("SELECT COUNT(DISTINCT stock_code) FROM executives")},
            {"part": "밸류 요약 (valuation_summary)",
             "count": cnt("SELECT COUNT(*) FROM valuation_summary")},
            {"part": "재무제표 연결 (financial_detail·BS)",
             "count": cnt("SELECT COUNT(DISTINCT stock_code) FROM financial_detail WHERE statement_type='BS' AND statement_scope='연결'")},
        ]
        # Sankey 완전도(영업이익까지 매칭 가능) — LIKE % 는 con.execute 로(db.py %% 이스케이프)
        try:
            sk = con.execute("SELECT COUNT(DISTINCT stock_code) FROM financial_detail "
                             "WHERE statement_type='CIS' AND statement_scope='연결' "
                             "AND account_nm LIKE '%영업이익%'").fetchone()[0]
            rows.append({"part": "Sankey 완전도 (영업이익 매칭)", "count": sk})
        except Exception:
            pass
        con.close()
    # 파일 기반 자산
    if _SANKEY.exists():
        rows.append({"part": "손익흐름도 Sankey (파일)",
                     "count": len(list(_SANKEY.glob("*_sankey.html")))})
    aff = 0
    for sub in ("samples_structure_diagrams", "samples", "samples_graphviz_style"):
        d = _AFFIL / sub
        if d.exists():
            aff += len([p for p in d.glob("*") if p.is_dir() or p.suffix == ".svg"])
    rows.append({"part": "계열사 시각화 (샘플)", "count": aff})

    for r in rows:
        r["base"] = base
        r["pct"] = round(min(r["count"], base) / base * 100, 1) if base else 0
    return {
        "base_universe": base, "rows": rows,
        "sankey_meta": {
            "원천": "financial_detail (DART 파싱 손익계산서 CIS/IS) 10계정",
            "추출값": "매출액·매출원가·매출총이익·판관비·영업이익·영업외수익/비용·세전이익·법인세·당기순이익",
            "생성방식": "build_sankey_v3.py 로 사전생성(그때그때 X)",
            "저장위치": "outputs/sankey/{종목코드}_sankey.html (파일·DB 아님, 화면은 불러오기만)",
            "비고": "계정명 정규화(로마숫자 접두사 제거) 적용 시 완전도 대폭 향상",
        },
        "재무하이라이트_원천": "financials 테이블(요약) · /api/overview tab1.financials · DART API→DB 저장값 조회(실시간 아님)",
    }


_SMOKE_CODES = ["005930", "000720", "028260", "035420"]


@router.get("/admin/smoke")
def admin_smoke():
    """샘플 종목 핵심 데이터 작동 확인(읽기)."""
    checks = []
    if not _DB.exists():
        return {"checks": [], "ok": 0, "fail": 1, "error": "DB 없음"}
    con = _conn(); cur = con.cursor()
    for code in _SMOKE_CODES:
        t0 = time.perf_counter()
        res = {}
        try:
            res["company_info"] = bool(cur.execute(
                "SELECT 1 FROM company_info WHERE stock_code=?", (code,)).fetchone())
            res["financials"] = bool(cur.execute(
                "SELECT 1 FROM financials WHERE stock_code=? LIMIT 1", (code,)).fetchone())
            res["ohlcv"] = bool(cur.execute(
                "SELECT 1 FROM ohlcv WHERE stock_code=? LIMIT 1", (code,)).fetchone())
            res["sankey_file"] = (_SANKEY / f"{code}_sankey.html").exists()
            ms = round((time.perf_counter() - t0) * 1000, 1)
            ok = all([res["company_info"], res["financials"], res["ohlcv"]])
            checks.append({"code": code, "ok": ok, "ms": ms, "detail": res})
        except Exception as e:
            checks.append({"code": code, "ok": False, "error": str(e)[:80]})
    con.close()
    return {"checks": checks,
            "ok": sum(1 for c in checks if c.get("ok")),
            "fail": sum(1 for c in checks if not c.get("ok"))}


@router.post("/admin/cache/refresh")
def admin_cache_refresh():
    """모닝 위젯 캐시 강제 갱신(멱등)."""
    try:
        from backend.routers.morning import warm_cache
        warm_cache()
        return {"ok": True, "msg": "모닝 캐시 prewarm 완료"}
    except Exception as e:
        return {"ok": False, "msg": f"실패: {str(e)[:120]}"}


# ───────────────────────── 탭2 · 신뢰도 검증 ─────────────────────────
# 마지막 샘플 결과(메모리 보관 — 리포트 탭에서 재조회)
_LAST_REPORT: dict = {}


def _rand_codes(cur, table: str, n: int):
    try:
        rows = cur.execute(
            f'SELECT DISTINCT stock_code FROM "{table}" '
            f'ORDER BY RANDOM() LIMIT ?', (n,)).fetchall()
        return [r[0] for r in rows]
    except Exception:
        return []


@router.post("/admin/verify/sample")
def admin_verify_sample(payload: dict = Body(...)):
    """
    파트·N개 샘플 신뢰도 검증(NO-MOCK 숫자/완전성 검사).
    payload: {"part": "financials|ohlcv|company_info|valuation", "n": 10}
    """
    part = (payload or {}).get("part", "financials")
    n = int((payload or {}).get("n", 10))
    n = max(1, min(n, 50))
    if not _DB.exists():
        return {"part": part, "error": "DB 없음"}

    con = _conn(); cur = con.cursor()
    checked = 0
    failures = []
    method = ""

    if part == "financials":
        method = "회계 항등식: 자산총계 ≈ 부채총계 + 자본총계 (허용오차 0.5%)"
        for code in _rand_codes(cur, "financials", n):
            row = cur.execute(
                "SELECT fiscal_year,assets,liabilities,equity FROM financials "
                "WHERE stock_code=? ORDER BY fiscal_year DESC LIMIT 1", (code,)).fetchone()
            if not row:
                continue
            checked += 1
            a, l, e = row["assets"], row["liabilities"], row["equity"]
            if a and l is not None and e is not None:
                diff = abs(a - (l + e))
                if a != 0 and diff / abs(a) > 0.005:
                    failures.append({"code": code, "field": "assets=liab+equity",
                                     "db": a, "expected": (l + e),
                                     "diff_pct": round(diff / abs(a) * 100, 2)})

    elif part == "ohlcv":
        method = "주가 OHLC 유효성: low ≤ open,close ≤ high, high ≥ low, volume ≥ 0"
        for code in _rand_codes(cur, "ohlcv", n):
            row = cur.execute(
                "SELECT date,open,high,low,close,volume FROM ohlcv "
                "WHERE stock_code=? ORDER BY date DESC LIMIT 1", (code,)).fetchone()
            if not row:
                continue
            checked += 1
            o, h, l, c, v = row["open"], row["high"], row["low"], row["close"], row["volume"]
            bad = []
            if None not in (o, h, l, c):
                if not (l <= o <= h): bad.append("open 범위")
                if not (l <= c <= h): bad.append("close 범위")
                if h < l: bad.append("high<low")
            if v is not None and v < 0: bad.append("volume<0")
            if bad:
                failures.append({"code": code, "field": ",".join(bad),
                                 "db": dict(row)})

    elif part == "company_info":
        method = "핵심필드 완전성: corp_name·market·sector 비어있지 않음"
        for code in _rand_codes(cur, "company_info", n):
            row = cur.execute(
                "SELECT corp_name,market,sector FROM company_info "
                "WHERE stock_code=?", (code,)).fetchone()
            if not row:
                continue
            checked += 1
            miss = [k for k in ("corp_name", "market", "sector")
                    if not (row[k] and str(row[k]).strip())]
            if miss:
                failures.append({"code": code, "field": "결측: " + ",".join(miss)})

    elif part == "valuation":
        method = "밸류 정합성: upside_pct ≈ (fair_price−current_price)/current_price×100 (±1%p)"
        rows = cur.execute(
            "SELECT stock_code,fair_price,current_price,upside_pct "
            "FROM valuation_summary").fetchall()
        for row in rows[:n]:
            fp, cp, up = row["fair_price"], row["current_price"], row["upside_pct"]
            if fp is None or cp in (None, 0) or up is None:
                continue
            checked += 1
            exp = (fp - cp) / cp * 100
            if abs(exp - up) > 1.0:
                failures.append({"code": row["stock_code"], "field": "upside_pct",
                                 "db": round(up, 2), "expected": round(exp, 2)})
    else:
        con.close()
        return {"part": part, "error": "알 수 없는 파트"}

    con.close()
    fail = len(failures)
    rate = round(fail / checked * 100, 1) if checked else 0.0
    result = {
        "part": part, "method": method, "requested": n, "checked": checked,
        "pass": checked - fail, "fail": fail, "error_rate": rate,
        "failures": failures[:20],
        "verdict": "정상(NO-MOCK 일치)" if fail == 0 else f"불일치 {fail}건 발견",
    }
    _LAST_REPORT[part] = result
    return result


@router.get("/admin/verify/report")
def admin_verify_report():
    """최근 샘플 검증 결과(파트별)."""
    return {"reports": _LAST_REPORT}


# ───────────────────── [1] 전수 검증 (배치) ─────────────────────
@router.post("/admin/verify/full")
def admin_verify_full(payload: dict = Body(...)):
    """샘플이 아닌 전 종목 대상 내부 정합성 검증(배치)."""
    part = (payload or {}).get("part", "financials")
    if not _DB.exists():
        return {"part": part, "error": "DB 없음"}
    con = _conn(); cur = con.cursor()
    checked = 0; failures = []; method = ""

    if part == "financials":
        method = "전수: 자산총계 ≈ 부채총계 + 자본총계 (±0.5%) — 각 종목 최신연도"
        rows = cur.execute(
            "SELECT f.stock_code,f.assets,f.liabilities,f.equity FROM financials f "
            "JOIN (SELECT stock_code,MAX(fiscal_year) my FROM financials GROUP BY stock_code) m "
            "ON f.stock_code=m.stock_code AND f.fiscal_year=m.my").fetchall()
        for r in rows:
            a, l, e = r["assets"], r["liabilities"], r["equity"]
            if a and l is not None and e is not None:
                checked += 1
                if a != 0 and abs(a - (l + e)) / abs(a) > 0.005:
                    failures.append({"code": r["stock_code"], "field": "assets=liab+equity",
                                     "db": a, "expected": l + e})
    elif part == "ohlcv":
        method = "전수: 각 종목 최신 일봉 low≤open,close≤high, high≥low, volume≥0"
        rows = cur.execute(
            "SELECT o.stock_code,o.open,o.high,o.low,o.close,o.volume FROM ohlcv o "
            "JOIN (SELECT stock_code,MAX(date) md FROM ohlcv GROUP BY stock_code) m "
            "ON o.stock_code=m.stock_code AND o.date=m.md").fetchall()
        for r in rows:
            o, h, l, c, v = r["open"], r["high"], r["low"], r["close"], r["volume"]
            checked += 1
            bad = []
            if None not in (o, h, l, c):
                if not (l <= o <= h): bad.append("open")
                if not (l <= c <= h): bad.append("close")
                if h < l: bad.append("high<low")
            if v is not None and v < 0: bad.append("volume<0")
            if bad:
                failures.append({"code": r["stock_code"], "field": ",".join(bad)})
    elif part == "company_info":
        method = "전수: corp_name·market·sector 결측 없음"
        for r in cur.execute("SELECT stock_code,corp_name,market,sector FROM company_info").fetchall():
            checked += 1
            miss = [k for k in ("corp_name", "market", "sector") if not (r[k] and str(r[k]).strip())]
            if miss:
                failures.append({"code": r["stock_code"], "field": "결측:" + ",".join(miss)})
    elif part == "valuation":
        method = "전수: upside_pct ≈ (fair−current)/current×100 (±1%p)"
        for r in cur.execute("SELECT stock_code,fair_price,current_price,upside_pct FROM valuation_summary").fetchall():
            fp, cp, up = r["fair_price"], r["current_price"], r["upside_pct"]
            if fp is None or cp in (None, 0) or up is None:
                continue
            checked += 1
            exp = (fp - cp) / cp * 100
            if abs(exp - up) > 1.0:
                failures.append({"code": r["stock_code"], "field": "upside_pct",
                                 "db": round(up, 2), "expected": round(exp, 2)})
    else:
        con.close(); return {"part": part, "error": "알 수 없는 파트"}
    con.close()
    fail = len(failures)
    rate = round(fail / checked * 100, 2) if checked else 0.0
    res = {"part": part, "scope": "full", "method": method, "checked": checked,
           "pass": checked - fail, "fail": fail, "error_rate": rate,
           "failures": failures[:30],
           "verdict": "전수 정상(NO-MOCK 일치)" if fail == 0 else f"전수 불일치 {fail}건"}
    _LAST_REPORT["full_" + part] = res
    return res


# ───────────────────── [2] 히스토리브리핑 신뢰도 연동 ─────────────────────
_REPORT_MD_CANDIDATES = [
    _ROOT / "통합산출물" / "result_report.md",
    _ROOT / "브리핑정리" / "result_report.md",
]

@router.get("/admin/verify/briefing")
def admin_verify_briefing():
    """히스토리브리핑 evaluate.py(4-Phase) 평가 결과 요약 연동."""
    import re
    p = next((c for c in _REPORT_MD_CANDIDATES if c.exists()), None)
    if not p:
        return {"available": False, "msg": "브리핑 평가 리포트(result_report.md) 없음"}
    txt = p.read_text(encoding="utf-8", errors="ignore")

    def g(pat):
        m = re.search(pat, txt)
        return m.group(1) if m else None

    avg = g(r"평균 품질 점수[^\d]*([\d.]+)")
    return {
        "available": True,
        "source": "히스토리브리핑 evaluate.py 4-Phase 채점 → result_report.md",
        "count": g(r"생성 종목 수[^\d]*([\d,]+)"),
        "avg_score": avg,
        "grades": {"high": g(r"high[^%]*?([0-9]+)\s*%"),
                   "medium": g(r"medium[^%]*?([0-9]+)\s*%"),
                   "low": g(r"low[^%]*?([0-9]+)\s*%")},
        "method": "①수치 정확성 ②인용 정합 ③RAGAS ④LLM Judge → overall_score(100점)",
        "pass": (float(avg) >= 75) if avg else None,
        "threshold": "평균 75점 이상 목표(현재 기준)",
        "note": "기존 배치 평가 결과를 연동 표시. 실시간 재평가(유료 LLM)는 별도.",
    }


# ───────────────────── [3] DART 원문 대조 (요약 ↔ XBRL 상세) ─────────────────────
def _detail_pick(cur, code, fy):
    """financial_detail에서 핵심 계정값을 {field:{scope:amount}}로 수집."""
    rows = cur.execute(
        "SELECT statement_scope,account_id,account_nm,amount "
        "FROM financial_detail WHERE stock_code=? AND fiscal_year=?", (code, fy)).fetchall()
    d: dict = {}
    for r in rows:
        sc, aid, anm, amt = r["statement_scope"], r["account_id"], r["account_nm"] or "", r["amount"]
        if amt is None:
            continue
        f = None
        if aid == "ifrs-full_Assets" or anm == "자산총계": f = "assets"
        elif aid == "ifrs-full_Liabilities" or anm == "부채총계": f = "liabilities"
        elif aid == "ifrs-full_Equity" or anm == "자본총계": f = "equity"
        elif anm in ("매출액", "수익(매출액)"): f = "revenue"
        elif anm in ("영업이익", "영업이익(손실)"): f = "op_income"
        elif anm in ("당기순이익", "당기순이익(손실)"): f = "net_income"
        if f:
            d.setdefault(f, {}).setdefault(sc, amt)
    return d


def _pick_scope(m):
    for sc in ("연결", "별도"):
        if sc in m:
            return m[sc], sc
    for sc, v in m.items():
        return v, sc
    return None, None


_DART_FIELDS = [("assets", "자산총계"), ("liabilities", "부채총계"), ("equity", "자본총계"),
                ("revenue", "매출액"), ("op_income", "영업이익"), ("net_income", "당기순이익")]


def _scale_match(fin, det, tol=0.01):
    """단위 차이(원/천원/백만원/십억 등) 무관 일치 판정.
    fin 에 10의 거듭제곱 배율을 곱해 det 와 ±1% 이내면 일치(같은 유효숫자 = 단위만 다름)."""
    if det is None or fin is None:
        return False
    if abs(det) < 1:
        return abs(fin) < 1
    for scale in (1, 1e3, 1e6, 1e9, 1e12, 1e-3, 1e-6):
        if abs(fin * scale - det) / abs(det) <= tol:
            return True
    return False


@router.post("/admin/verify/dart")
def admin_verify_dart(payload: dict = Body(...)):
    """요약 재무(financials) ↔ DART XBRL 상세(financial_detail) 대조.
    payload: {"n": 20, "full": false}"""
    full = bool((payload or {}).get("full", False))
    n = int((payload or {}).get("n", 20))
    n = max(1, min(n, 100))
    if not _DB.exists():
        return {"error": "DB 없음"}
    con = _conn(); cur = con.cursor()
    base = ("SELECT f.stock_code,f.fiscal_year,f.revenue,f.op_income,f.net_income,"
            "f.assets,f.liabilities,f.equity FROM financials f "
            "JOIN (SELECT stock_code,MAX(fiscal_year) my FROM financials GROUP BY stock_code) m "
            "ON f.stock_code=m.stock_code AND f.fiscal_year=m.my")
    if not full:
        base += " ORDER BY RANDOM() LIMIT ?"
        srows = cur.execute(base, (n,)).fetchall()
    else:
        srows = cur.execute(base).fetchall()

    field_stat = {f: {"match": 0, "mismatch": 0, "no_src": 0} for f, _ in _DART_FIELDS}
    compared = matched = 0
    mism = []
    stocks = 0
    for s in srows:
        code, fy = s["stock_code"], s["fiscal_year"]
        d = _detail_pick(cur, code, fy)
        if not d:
            continue
        stocks += 1
        for field, _ in _DART_FIELDS:
            sv = s[field]
            if sv is None:
                continue
            if field not in d:
                field_stat[field]["no_src"] += 1
                continue
            dv, sc = _pick_scope(d[field])
            if dv is None:
                field_stat[field]["no_src"] += 1
                continue
            compared += 1
            if _scale_match(sv, dv):
                matched += 1
                field_stat[field]["match"] += 1
            else:
                field_stat[field]["mismatch"] += 1
                if len(mism) < 30:
                    mism.append({"code": code, "field": field,
                                 "summary": sv, "dart": dv, "scope": sc})
    con.close()
    rate = round((compared - matched) / compared * 100, 2) if compared else 0.0
    res = {
        "scope": "full" if full else "sample",
        "method": "요약 재무(financials) 값이 DART XBRL 상세(financial_detail, 연결 우선)와 일치하는지 ±1% 대조",
        "stocks": stocks, "compared": compared, "matched": matched,
        "mismatch": compared - matched, "match_rate": round(matched / compared * 100, 2) if compared else 0.0,
        "error_rate": rate, "field_stat": field_stat, "mismatches": mism,
        "verdict": "원문 일치(파싱 정상)" if compared == matched else f"원문 불일치 {compared - matched}건 — 파싱 점검 필요",
    }
    _LAST_REPORT["dart"] = res
    return res


# ───────────────────── [4] AI 챗봇 검증 (지식베이스·서버, 비용 0) ─────────────────────
@router.get("/admin/verify/chatbot")
def admin_verify_chatbot():
    """AI 챗봇(RAG) 준비상태 점검 — 8800 생존 + ChromaDB 청크 수(질의 안 함=무료)."""
    import urllib.request
    import json as _json
    up, _ = _port_up("127.0.0.1", 8800)
    if not up:
        return {"available": False, "server_up": False,
                "msg": "AI 챗봇 서버(8800) DOWN — 켜야 검증 가능",
                "method": "RAG 지식베이스(ChromaDB) 적재 상태 + 서버 생존 점검"}
    try:
        t0 = time.perf_counter()
        with urllib.request.urlopen("http://127.0.0.1:8800/health", timeout=30) as r:
            h = _json.loads(r.read().decode("utf-8"))
        ms = round((time.perf_counter() - t0) * 1000, 0)
        db = h.get("db") or {}
        chunks = None
        if isinstance(db, dict):
            for k in ("count", "n_chunks", "chunks", "total", "num_chunks", "n"):
                v = db.get(k)
                if isinstance(v, (int, float)):
                    chunks = int(v); break
            if chunks is None:
                for v in db.values():
                    if isinstance(v, (int, float)) and v > 1000:
                        chunks = int(v); break
        elif isinstance(db, (int, float)):
            chunks = int(db)
        return {"available": True, "server_up": True, "status": h.get("status"),
                "ms": ms, "chunks": chunks, "db": db, "device": h.get("device"),
                "method": "RAG 지식베이스 적재 상태(ChromaDB 임베딩 청크 수)·디바이스 점검. 질의 안 함=무료.",
                "ragas_note": "라이브 RAGAS(faithfulness·answer relevancy)는 질의당 유료 LLM(gpt-5-mini) 필요 → 사전승인 후 별도 배치.",
                "pass": bool(chunks and chunks > 0)}
    except Exception as e:
        return {"available": True, "server_up": True,
                "msg": "health 조회 실패(모델 로딩중일 수 있음): " + str(e)[:100]}


# ───────────────────── [5] 계열사 검증 (커버리지·무결성) ─────────────────────
@router.get("/admin/verify/affiliate")
def admin_verify_affiliate():
    """계열회사 시각화 파일 커버리지 + 무결성(크기>0, SVG 루트태그)."""
    import re
    base = _AFFIL
    found: dict = {}
    if base.exists():
        st = base / "samples_structure_diagrams"
        if st.exists():
            for d in sorted(st.glob("*")):
                if d.is_dir():
                    m = re.match(r"(\d{6})", d.name)
                    if m:
                        for f in d.glob("*_affiliate_structure.svg"):
                            found.setdefault(m.group(1), f); break
        gv = base / "samples_graphviz_style"
        if gv.exists():
            for f in sorted(gv.glob("*_graphviz_style.svg")):
                m = re.match(r"(\d{6})", f.name)
                if m:
                    found.setdefault(m.group(1), f)
        sm = base / "samples"
        if sm.exists():
            for d in sorted(sm.glob("*")):
                if d.is_dir():
                    m = re.match(r"(\d{6})", d.name)
                    if m:
                        for f in (list(d.glob("original_affiliate_diagram.*"))
                                  + list(d.glob("affiliate_*.svg"))):
                            found.setdefault(m.group(1), f); break
    broken = []
    for code, f in found.items():
        try:
            sz = f.stat().st_size
            ok = sz > 100
            if ok and f.suffix.lower() == ".svg":
                head = f.read_text(encoding="utf-8", errors="ignore")[:300]
                ok = "<svg" in head
            if not ok:
                broken.append({"code": code, "file": f.name, "size": sz})
        except Exception as e:
            broken.append({"code": code, "file": f.name, "err": str(e)[:40]})
    avail = len(found)
    return {
        "method": "계열회사 시각화 파일 커버리지 + 무결성(크기>0·SVG 루트태그) 점검. 원천=DART 사업보고서 계열회사.",
        "available_count": avail, "valid": avail - len(broken), "broken": broken,
        "base_universe": _BASE_UNIVERSE,
        "coverage_pct": round(avail / _BASE_UNIVERSE * 100, 2) if _BASE_UNIVERSE else 0,
        "samples": sorted(found.keys()),
        "verdict": "샘플 무결성 정상" if not broken else f"손상 {len(broken)}건",
        "note": "현재 GitHub 샘플만 적재(전종목은 output/affiliate_visualization 드라이브 수령 후). 낮은 커버리지는 정상.",
    }


# ═════════════ [밸류·챗봇 관리자/QA 콘솔 메타] — 밸류에이션 파트 파트 통합 ═════════════
# 출처: feat/admin-qa-console 브랜치 (커밋 8918cac) backend/routers/admin.py
# 평가 기준일·모델버전·데이터 출처 일자·규모를 valuation.db / filmn9.db 에서 집계.
import json as _vjson
import os as _vos
from datetime import datetime as _vdt

_VAL_DB = Path(_vos.getenv("VALUATION_DB_PATH", str(_ROOT / "data" / "valuation.db")))


def _vq1(db: Path, sql: str, params: tuple = ()):
    """단일행 조회(없으면/에러면 None) — graceful."""
    if not db.exists():
        return None
    try:
        conn = sqlite3.connect(str(db), timeout=10.0)
        conn.row_factory = sqlite3.Row
        row = conn.execute(sql, params).fetchone()
        conn.close()
        return dict(row) if row else None
    except sqlite3.Error:
        return None


def _vg(r, k, default=None):
    return r.get(k) if r else default


@router.get("/admin/meta")
def admin_meta():
    """평가에 사용된 데이터 기준일·규모·출처 일자 요약 (실데이터 · 밸류에이션 파트 파트)."""
    # ── 밸류에이션 (valuation.db) ──
    v: dict = {"db_exists": _VAL_DB.exists()}
    cnt = _vq1(_VAL_DB, "SELECT COUNT(DISTINCT stock_code) AS n, COUNT(*) AS runs, "
                        "COUNT(DISTINCT eval_date) AS dates, MAX(eval_date) AS latest "
                        "FROM valuation_runs")
    v["n_stocks"] = _vg(cnt, "n")
    v["n_runs"] = _vg(cnt, "runs")
    v["n_eval_dates"] = _vg(cnt, "dates")
    v["latest_eval_date"] = _vg(cnt, "latest")
    v["rf"] = _vq1(_VAL_DB, "SELECT rate_date, rf, source FROM rf_rates ORDER BY rate_date DESC LIMIT 1")
    v["kofia_latest"] = _vg(_vq1(_VAL_DB, "SELECT MAX(yield_date) AS d FROM kofia_bond_yields"), "d")
    v["market_snapshot_latest"] = _vg(_vq1(_VAL_DB, "SELECT MAX(snap_date) AS d FROM market_snapshot"), "d")
    v["xbrl_years"] = [
        _vg(_vq1(_VAL_DB, "SELECT MIN(fiscal_year) AS y FROM financials"), "y"),
        _vg(_vq1(_VAL_DB, "SELECT MAX(fiscal_year) AS y FROM financials"), "y"),
    ]
    mv = _vq1(_VAL_DB, "SELECT doc FROM mongo_docs WHERE collection='valuation_results' "
                       "ORDER BY updated_at DESC LIMIT 1")
    try:
        v["model_version"] = _vjson.loads(mv["doc"]).get("model_version") if mv else None
    except Exception:
        v["model_version"] = None

    # ── 기업개요 (filmn9.db) ──
    co: dict = {"db_exists": _DB.exists()}
    co["company_info"] = _vg(_vq1(_DB, "SELECT COUNT(*) AS n FROM company_info"), "n")
    co["ohlcv_latest"] = _vg(_vq1(_DB, "SELECT MAX(date) AS d FROM ohlcv"), "d")
    co["ohlcv_rows"] = _vg(_vq1(_DB, "SELECT COUNT(*) AS n FROM ohlcv"), "n")
    fy = _vq1(_DB, "SELECT MIN(fiscal_year) AS mn, MAX(fiscal_year) AS mx FROM financials")
    co["fiscal_years"] = [_vg(fy, "mn"), _vg(fy, "mx")]
    co["financial_detail_rows"] = _vg(_vq1(_DB, "SELECT COUNT(*) AS n FROM financial_detail"), "n")
    co["financial_detail_stocks"] = _vg(
        _vq1(_DB, "SELECT COUNT(DISTINCT stock_code) AS n FROM financial_detail"), "n")

    return {
        "generated_at": _vdt.now().strftime("%Y-%m-%d %H:%M:%S"),
        "valuation": v,
        "company": co,
        "ports": {"frontend": 3000, "backend": 8090, "chatbot": 8800},
        "policy": {"no_mock": True, "note": "실데이터 100% — 데이터 없으면 가짜 숫자 대신 '미평가/준비중' 표시"},
    }


# ───────────────────────── 기능 모듈 운영 현황 (2026-06-14 고도화) ─────────────────────────
# 각 기능 모듈이 어느 원천(DB/파일)에서 → 어떻게 화면까지 오는지 + 실시간 상태(데이터 보유수).
# ID = 데이터 원천 지도 번호. UI는 서비스(메인/기업개요/밸류) 그룹 순서로 배치.
def _cnt(sql: str) -> int:
    try:
        con = _conn(); cur = con.cursor()
        n = cur.execute(sql).fetchone()[0]
        con.close()
        return int(n)
    except Exception:
        return -1


@router.get("/admin/modules")
def admin_modules():
    """기능 모듈별 원천→흐름→자동화→실시간 상태. 운영 대시보드용."""
    sankey_n = len(list(_SANKEY.glob("*_sankey.html"))) if _SANKEY.exists() else 0
    vres = _ROOT / "data" / "valuation_results"
    vres_n = len([d for d in vres.iterdir() if d.is_dir()]) if vres.exists() else 0
    affil_n = 0
    for sub in ("samples", "samples_structure_diagrams", "samples_graphviz_style"):
        p = _AFFIL / sub
        if p.exists():
            affil_n += len(list(p.glob("*")))

    def card(idn, group, name, source, store, api, auto, status, count, unit="종"):
        return {"id": idn, "group": group, "name": name, "source": source, "store": store,
                "api": api, "auto": auto, "status": status, "count": count, "unit": unit}

    def st(n, warn=1, good=2000):
        if n < 0: return "down"
        if n == 0: return "down"
        if n < good: return "warn"
        return "ok"

    mods = []
    # 메인
    mods.append(card("3", "메인", "글로벌 마켓 시그널", "yfinance 41지표+네이버(금/금리)", "DB 미적재(메모리 캐시)",
                     "GET /api/morning", "실시간 호출·15분 캐시·자동 갱신", "realtime", "실시간", ""))
    mods.append(card("2", "메인", "산업 탐색(WICS)", "KRX WICS 분류", "RDS/SQLite company_info.sector + wics_keywords",
                     "GET /api/sectors", "사전 적재", st(_cnt("SELECT COUNT(*) FROM company_info")), _cnt("SELECT COUNT(*) FROM company_info")))
    mods.append(card("5A", "메인", "밸류 요약 랭킹", "DCF 엔진 v8 산출", "RDS/SQLite valuation_summary",
                     "GET /api/valuation-summary", "summary.csv→적재", st(_cnt("SELECT COUNT(*) FROM valuation_summary")), _cnt("SELECT COUNT(*) FROM valuation_summary")))
    # 기업개요
    mods.append(card("6", "기업개요", "히스토리 브리핑", "DART 사업보고서+LLM", "MongoDB Atlas filmn9.histories",
                     "GET /api/overview(brief)", "8단계 LLM 파이프라인 사전생성", "ok", "Atlas", ""))
    mods.append(card("7", "기업개요", "주가차트(OHLCV)", "KRX(yfinance/pykrx)", "RDS/SQLite ohlcv",
                     "GET /api/ohlcv/{code}", "매 거래일 16:00 스케줄러 자동", st(_cnt("SELECT COUNT(DISTINCT stock_code) FROM ohlcv")), _cnt("SELECT COUNT(DISTINCT stock_code) FROM ohlcv")))
    mods.append(card("8", "기업개요", "손익흐름도(Sankey)", "DART 재무(IS/CIS)", "파일 outputs/sankey/*.html",
                     "GET /sankey/{code}", "build_sankey_v3 전수 사전생성", st(sankey_n), sankey_n, "개"))
    mods.append(card("9", "기업개요", "재무제표 BS/IS(3년)", "DART API fnlttSinglAcntAll", "RDS/SQLite financial_detail",
                     "GET /api/financial_detail/{code}/{BS|IS}", "DART 3년치 직접 재구축", st(_cnt("SELECT COUNT(DISTINCT stock_code) FROM financial_detail")), _cnt("SELECT COUNT(DISTINCT stock_code) FROM financial_detail")))
    mods.append(card("12", "기업개요", "재무 하이라이트/건전성", "DART API 재무", "RDS/SQLite financials",
                     "GET /api/overview", "2026 1분기·YoY 수집", st(_cnt("SELECT COUNT(DISTINCT stock_code) FROM financials")), _cnt("SELECT COUNT(DISTINCT stock_code) FROM financials")))
    mods.append(card("11", "기업개요", "주주 구성", "DART 최대주주·5%이상", "RDS/SQLite shareholders",
                     "GET /api/shareholders/{code}", "사전 적재", st(_cnt("SELECT COUNT(DISTINCT stock_code) FROM shareholders")), _cnt("SELECT COUNT(DISTINCT stock_code) FROM shareholders")))
    mods.append(card("10", "기업개요", "경영인", "DART 임원현황", "RDS/SQLite executives",
                     "GET /api/executives/{code}", "사전 적재", st(_cnt("SELECT COUNT(DISTINCT stock_code) FROM executives")), _cnt("SELECT COUNT(DISTINCT stock_code) FROM executives")))
    mods.append(card("13", "기업개요", "최근 공시", "DART list.json", "RDS/SQLite disclosures + 실시간",
                     "GET /api/disclosures/{code}", "일부 적재+실시간", st(_cnt("SELECT COUNT(*) FROM disclosures"), good=50), _cnt("SELECT COUNT(*) FROM disclosures"), "건"))
    mods.append(card("15A", "기업개요", "계열회사 구조", "DART 소유지분도", "파일(SVG/이미지)",
                     "GET /api/affiliate/{code}", "사전 생성(현재 샘플)", st(affil_n, good=5), affil_n, "파일"))
    # 밸류
    mods.append(card("16", "밸류에이션", "밸류 대시보드(DCF)", "DCF 엔진 v8(밸류에이션 파트)", "파일 valuation_results/*.json",
                     "GET /api/valuation-full/{code}", "엔진 산출 합본JSON", st(vres_n), vres_n))
    # 챗봇
    mods.append(card("18", "AI챗봇", "RAG 챗봇", "DART 사업보고서 임베딩", "ChromaDB(별도 :8800)",
                     "POST :8800/chat/stream", "BGE-M3+리랭커 GPU+LLM", "ok" if _port_up("127.0.0.1", 8800) else "down", "8800", ""))
    groups = ["메인", "기업개요", "밸류에이션", "AI챗봇"]
    return {"generated_at": _vdt.now().strftime("%Y-%m-%d %H:%M:%S"), "groups": groups, "modules": mods}


@router.get("/admin/qa/run")
def admin_qa_run():
    """QA 테스트 — 핵심 기능 모듈의 데이터 보유를 정량 테스트하고 통과/실패 집계."""
    tests = []
    def t(name, ok, detail=""):
        tests.append({"test": name, "pass": bool(ok), "detail": detail})
    n_an = _cnt("SELECT COUNT(*) FROM company_info ci WHERE EXISTS(SELECT 1 FROM financials f WHERE f.stock_code=ci.stock_code AND f.revenue IS NOT NULL) AND EXISTS(SELECT 1 FROM ohlcv o WHERE o.stock_code=ci.stock_code)")
    t("분석가능 종목 ≥ 2,500 (재무+주가)", n_an >= 2500, f"{n_an}종")
    n_fd3 = _cnt("SELECT COUNT(*) FROM (SELECT stock_code FROM financial_detail GROUP BY stock_code HAVING COUNT(DISTINCT fiscal_year)>=3)")
    t("재무제표 3년치 ≥ 2,500종", n_fd3 >= 2500, f"{n_fd3}종")
    n_sk = len(list(_SANKEY.glob("*_sankey.html"))) if _SANKEY.exists() else 0
    t("손익흐름도 파일 ≥ 2,500개", n_sk >= 2500, f"{n_sk}개")
    n_sh = _cnt("SELECT COUNT(DISTINCT stock_code) FROM shareholders")
    t("주주구성 ≥ 2,500종", n_sh >= 2500, f"{n_sh}종")
    n_val = _cnt("SELECT COUNT(*) FROM valuation_summary")
    t("밸류 요약 ≥ 2,000종", n_val >= 2000, f"{n_val}종")
    n_q1 = _cnt("SELECT COUNT(*) FROM financials WHERE reprt_code='11013' AND fiscal_year=2026")
    t("2026 1분기 재무 ≥ 2,500종", n_q1 >= 2500, f"{n_q1}종")
    n_neg = _cnt("SELECT COUNT(*) FROM financials WHERE revenue<0")
    t("매출 음수(이상치) = 0", n_neg == 0, f"{n_neg}건")
    passed = sum(1 for x in tests if x["pass"])
    return {"generated_at": _vdt.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total": len(tests), "passed": passed, "failed": len(tests) - passed, "tests": tests}


@router.get("/admin/data-management")
def admin_data_management():
    """데이터 관리 — 각 데이터의 최신 기준시점·적재출처·갱신 자동화 여부(#17·#25)."""
    def one(sql):
        try:
            con = _conn(); v = con.cursor().execute(sql).fetchone(); con.close()
            return v[0] if v else None
        except Exception:
            return None
    fy_max = one("SELECT MAX(fiscal_year) FROM financials")
    ohlcv_max = one("SELECT MAX(date) FROM ohlcv")
    items = [
        {"name": "재무 하이라이트(financials)", "기준": f"최신 {fy_max}년 / 분기보고서 포함",
         "출처": "DART fnlttSinglAcntAll", "자동화": "수동(분기·연간 보고서 공시 시 재수집)", "갱신주기": "분기"},
        {"name": "재무제표 3개년(financial_detail)", "기준": "2025·2024·2023 (사업보고서 당기/전기/전전기)",
         "출처": "DART API 직접 재구축", "자동화": "수동(사업보고서 갱신 시)", "갱신주기": "연 1회(3월 전후)"},
        {"name": "주가(ohlcv)", "기준": f"최신 거래일 {ohlcv_max}",
         "출처": "yfinance/pykrx (KRX)", "자동화": "✅ 매 거래일 16:00 작업스케줄러 자동", "갱신주기": "매일"},
        {"name": "주주·경영인·공시", "기준": "최신 사업보고서 기준",
         "출처": "DART OpenAPI", "자동화": "수동", "갱신주기": "연 1회"},
        {"name": "히스토리 브리핑", "기준": "2025 사업보고서",
         "출처": "DART RAG + LLM", "자동화": "수동(LLM 파이프라인 실행)", "갱신주기": "연 1회"},
        {"name": "밸류에이션", "기준": "엔진 v8 산출분",
         "출처": "DCF 엔진(export_poc)", "자동화": "수동(엔진 배치)", "갱신주기": "분기/수시"},
    ]
    return {"generated_at": _vdt.now().strftime("%Y-%m-%d %H:%M:%S"),
            "items": items,
            "note": "사업보고서 갱신 자동화(예: 신규 공시 감지→재수집)는 향후 과제(#25). 현재 주가만 완전 자동."}


@router.get("/admin/aws-cost")
def admin_aws_cost():
    """AWS 비용·리소스 스냅샷(#17). 로컬 _aws_cost_snapshot.py가 생성한 data/aws_snapshot.json 표시."""
    import json as _json
    f = _ROOT / "data" / "aws_snapshot.json"
    if not f.exists():
        return {"available": False, "note": "스냅샷 없음. 로컬에서 _aws_cost_snapshot.py 실행 후 data/aws_snapshot.json 생성/업로드 필요."}
    try:
        snap = _json.loads(f.read_text(encoding="utf-8"))
        snap["available"] = True
        return snap
    except Exception as e:
        return {"available": False, "note": f"스냅샷 읽기 실패: {e}"}
