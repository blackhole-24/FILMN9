"""
api/main.py
===========
FILMN9 FastAPI 서버 — 재무정보 파트

실행
----
  cd C:/Users/Admin/FILMN9
  uvicorn backend.main:app --reload --port 8000

엔드포인트
----------
  GET /api/company/{code}        기업 기본정보
  GET /api/financials/{code}     재무정보
  GET /api/overview/{code}       기업정보 + 재무 통합
  GET /api/ohlcv/{code}          OHLCV 전체 (기간 필터 가능)
  GET /api/ohlcv/{code}/latest   최신 가격 단일 레코드
  GET /api/search?q=삼성         기업 검색 (corp_code_map)
  GET /sankey/{code}             Sankey HTML 반환
  GET /docs                      Swagger UI (자동 생성)
  GET /health                    서버 상태 확인
"""

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import json
import os
import sys

# ─── 경로 설정 ────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent   # FILMN9/
_FIN  = _ROOT / "기업개요_파트" / "재무정보"
if str(_FIN) not in sys.path:
    sys.path.insert(0, str(_FIN))

# ─── .env 파일 수동 로드 (python-dotenv 없이) ──────────────────────────────────
def _load_env(env_path: Path = _ROOT / ".env") -> None:
    if not env_path.exists():
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            if key and key not in os.environ:
                os.environ[key] = val

_load_env()

# ─── 라우터 임포트 ─────────────────────────────────────────────────────────────
from backend.routers.company   import router as company_router
from backend.routers.ohlcv     import router as ohlcv_router
from backend.routers.overview  import router as overview_router
from backend.routers.extras    import router as extras_router
from backend.routers.valuation import router as valuation_router
from backend.routers.sectors   import router as sectors_router
from backend.routers.morning   import router as morning_router
from backend.routers.valuation_summary import router as valuation_summary_router
from backend.routers.affiliate  import router as affiliate_router
from backend.routers.admin      import router as admin_router
from backend.routers.valuation_admin import router as valuation_admin_router

# ─── 앱 생성 ──────────────────────────────────────────────────────────────────
app = FastAPI(
    title="FILMN9 API",
    description="FILMN9 기업분석 플랫폼 — 재무정보 파트",
    version="0.1.0",
)

# CORS — 로컬 HTML 파일에서 fetch() 가능하도록
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ─── 프론트엔드 정적 파일 서빙 ────────────────────────────────────────────────
_FRONTEND = _ROOT / "frontend"
if _FRONTEND.exists():
    app.mount("/app", StaticFiles(directory=str(_FRONTEND), html=True), name="frontend")

# ─── 라우터 등록 ───────────────────────────────────────────────────────────────
app.include_router(company_router,   prefix="/api")
app.include_router(ohlcv_router,     prefix="/api")
app.include_router(overview_router,  prefix="/api")
app.include_router(extras_router,    prefix="/api")
app.include_router(valuation_router, prefix="/api")
app.include_router(sectors_router,   prefix="/api")
app.include_router(morning_router,   prefix="/api")
app.include_router(valuation_summary_router, prefix="/api")
app.include_router(affiliate_router, prefix="/api")
app.include_router(admin_router,     prefix="/api")
app.include_router(valuation_admin_router, prefix="/api")


# ─── 기동 시 모닝 위젯 캐시 자동 갱신 시작 (콜드 스타트 영구 제거, 옵션 A+B) ──
@app.on_event("startup")
def _start_morning_auto_refresh():
    """서버 기동 직후 모닝 위젯 캐시를 prewarm하고, 이후 14분마다 백그라운드로
    자동 갱신한다(TTL 15분 직전 갱신). → 첫 사용자도, 15분 갱신 순간의 사용자도
    콜드 스타트(yfinance ~3.6초)를 절대 겪지 않는다. 기동 자체는 막지 않음."""
    from backend.routers.morning import start_auto_refresh
    start_auto_refresh()


# ─── 기업 검색 엔드포인트 (corp_code_map 활용) ────────────────────────────────
_MAP_PATH  = _ROOT / "data" / "corp_code_map.json"
_map_cache = None

def _load_map() -> dict:
    global _map_cache
    if _map_cache is None:
        if not _MAP_PATH.exists():
            return {}
        _map_cache = json.loads(_MAP_PATH.read_text(encoding="utf-8"))
    return _map_cache


# 음차(한글 발음) 별칭 — 영문 약칭 회사명을 한글로 쳐도 매칭되게 한다.
# 예) "에스케이" → "sk"  ⇒  "SK하이닉스"(소문자화 "sk하이닉스")에 매치.
_HANGUL_ALIASES = {
    "에스케이씨": "skc", "에이치디씨": "hdc", "에이치엠엠": "hmm",
    "케이씨씨": "kcc", "오씨아이": "oci", "비지에프": "bgf",
    "에스케이": "sk", "엘지": "lg", "케이티": "kt", "지에스": "gs",
    "케이비": "kb", "엔에이치": "nh", "씨제이": "cj", "디비": "db",
    "에이치디": "hd", "에이치엘": "hl", "디엘": "dl", "엘에스": "ls",
    "제이비": "jb", "디지비": "dgb", "비엔케이": "bnk", "케이지": "kg",
    "엘엑스": "lx", "에스엘": "sl", "포스코": "posco", "케이씨": "kc",
}


def _norm(s: str) -> str:
    return s.strip().lower()


def _query_forms(q: str) -> set:
    """정규화(소문자) + 음차 별칭 확장한 후보 질의 문자열 집합."""
    base = _norm(q)
    forms = {base}
    for ko, en in _HANGUL_ALIASES.items():
        if ko in base:
            forms.add(base.replace(ko, en))
    return {f for f in forms if f}


_search_rows = None


def _search_index_rows() -> list:
    """corp_name 을 미리 소문자화한 검색 인덱스(1회 캐시)."""
    global _search_rows
    if _search_rows is None:
        rows = []
        for it in _load_map().get("search_index", []):
            name = it.get("corp_name", "")
            rows.append({
                "stock_code": it.get("stock_code", ""),
                "corp_name":  name,
                "name_lower": name.lower(),
                "market":     it.get("market", ""),
                "has_data":   it.get("has_jsonl", False),
            })
        _search_rows = rows
    return _search_rows


_liquidity = None


def _liquidity_map() -> dict:
    """종목별 최근 거래대금(close×volume) — 대장주 우선 정렬용(1회 캐시).
    시가총액 컬럼이 없어, 인기·유동성을 반영하는 실데이터 거래대금으로 랭킹."""
    global _liquidity
    if _liquidity is None:
        _liquidity = {}
        # 공용 connect() — sqlite/postgres 둘 다 동작('?'→'%s' 자동변환, row["col"] 접근).
        try:
            from backend.db import connect
            con = connect()
            mx_row = con.execute("SELECT MAX(date) AS d FROM ohlcv").fetchone()
            mx = mx_row["d"] if mx_row else None
            if mx:
                for row in con.execute(
                    "SELECT stock_code, close, volume FROM ohlcv WHERE date = ?", (mx,)
                ).fetchall():
                    c, v = row["close"], row["volume"]
                    if c and v:
                        _liquidity[row["stock_code"]] = c * v
            con.close()
        except Exception:
            pass
    return _liquidity


def _match_score(row: dict, forms: set, raw_q: str) -> float:
    """매치 품질 점수(클수록 상위).
    티어(정확5000>접두4000>코드3500>부분3000)는 1000 간격으로 떨어져 있어,
    거래대금·데이터보유 가점(<수백)이 티어를 넘지 않고 '같은 티어 내 순서'만 정한다."""
    import math
    nl = row["name_lower"]
    best = 0.0
    for f in forms:
        if not f:
            continue
        if nl == f:
            best = max(best, 5000)
        elif nl.startswith(f):
            best = max(best, 4000)
        elif f in nl:
            best = max(best, 3000)
    if raw_q and row["stock_code"].startswith(raw_q):
        best = max(best, 3500)
    if best <= 0:
        return 0.0
    liq = _liquidity_map().get(row["stock_code"], 0)
    if liq > 0:
        best += math.log10(liq) * 15        # 거래대금 클수록 상위(대장주 먼저)
    if row["has_data"]:
        best += 50
    return best


@app.get("/api/search")
def search_company(
    q:     str = Query(..., description="종목코드 또는 기업명 (대소문자·음차 무관, 오타 허용)"),
    limit: int = Query(10,  description="최대 결과 수"),
):
    """
    기업명 또는 종목코드로 검색. 자동완성 드롭다운용.

    어떻게 입력해도 매칭:
      소문자 sk · 대문자 SK · 음차 에스케이 · 부분명 하이닉스 → 모두 SK하이닉스
    예: /api/search?q=sk  /api/search?q=에스케이  /api/search?q=005930
    """
    raw_q = q.strip()
    forms = _query_forms(raw_q)
    rows  = _search_index_rows()

    scored = []
    for row in rows:
        s = _match_score(row, forms, raw_q)
        if s > 0:
            scored.append((s, row))

    # 직접 매치가 부족하면 difflib(표준 라이브러리)로 오타 허용 보강
    base = _norm(raw_q)
    if len(scored) < 3 and len(base) >= 2:
        import difflib
        seen = {row["stock_code"] for _, row in scored}
        for row in rows:
            if row["stock_code"] in seen:
                continue
            ratio = difflib.SequenceMatcher(None, base, row["name_lower"]).ratio()
            if ratio >= 0.6:
                # 오타 매치는 부분일치(3000) 아래 티어. 그 안에서 유사도·거래대금 순.
                import math
                liq = _liquidity_map().get(row["stock_code"], 0)
                sc = ratio * 1000 + (math.log10(liq) * 15 if liq > 0 else 0)
                scored.append((sc, row))

    scored.sort(key=lambda x: x[0], reverse=True)
    results = [{
        "stock_code": r["stock_code"],
        "corp_name":  r["corp_name"],
        "market":     r["market"],
        "has_data":   r["has_data"],
    } for _, r in scored[:limit]]

    return {"query": raw_q, "count": len(results), "results": results}


# ─── 헬스체크 ─────────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    map_ok   = _MAP_PATH.exists()
    parsed   = _ROOT / "data" / "parsed"
    n_parsed = len(list(parsed.iterdir())) if parsed.exists() else 0
    return {
        "status"       : "ok",
        "corp_map"     : map_ok,
        "parsed_codes" : n_parsed,
    }


@app.get("/")
def root():
    return {
        "service": "FILMN9 API",
        "docs"   : "/docs",
        "health" : "/health",
        "endpoints": [
            "/api/company/{code}",
            "/api/financials/{code}",
            "/api/overview/{code}",
            "/api/ohlcv/{code}",
            "/api/ohlcv/{code}/latest",
            "/api/valuation/{code}",
            "/api/search?q=기업명",
            "/sankey/{code}",
        ]
    }


# ─── Sankey HTML 서빙 ─────────────────────────────────────────────────────────
_SANKEY_DIR = _ROOT / "outputs" / "sankey"

# S3 정적 파일 버킷 (환경변수로 켜짐). 설정 시 S3 우선, 실패 시 로컬 폴백.
# 로컬 개발에선 환경변수 미설정 → 기존처럼 로컬 파일만 사용(동작 변화 없음).
_S3_STATIC_BUCKET = os.getenv("S3_STATIC_BUCKET", "").strip()
_s3_client = None


def _s3():
    """boto3 S3 클라이언트(지연 생성). 자격증명은 EC2 IAM 역할에서 자동 획득."""
    global _s3_client
    if _s3_client is None:
        import boto3  # 지연 import: S3 미사용 환경에선 의존성 불필요
        _s3_client = boto3.client("s3", region_name=os.getenv("AWS_REGION", "ap-northeast-2"))
    return _s3_client


@app.get("/sankey/{stock_code}", response_class=HTMLResponse)
def get_sankey(stock_code: str):
    """
    사전 생성된 Plotly Sankey HTML 반환.
    우선순위: ① S3(sankey/{code}_sankey.html) → ② EC2 로컬 파일 → ③ 404.
    실행(로컬 생성): python db/build_sankey.py {code}
    """
    # ① S3 우선 (버킷 설정 시)
    if _S3_STATIC_BUCKET:
        try:
            obj = _s3().get_object(
                Bucket=_S3_STATIC_BUCKET, Key=f"sankey/{stock_code}_sankey.html"
            )
            return HTMLResponse(content=obj["Body"].read().decode("utf-8"))
        except Exception:
            pass  # S3 미스/오류 → 로컬 폴백 (데모 안정성)

    # ② 로컬 폴백
    html_path = _SANKEY_DIR / f"{stock_code}_sankey.html"
    if not html_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Sankey 미생성: {stock_code} — python db/build_sankey.py {stock_code} 실행 필요",
        )
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))
