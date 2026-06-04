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


@app.get("/api/search")
def search_company(
    q:     str = Query(..., description="종목코드 또는 기업명 (부분 일치)"),
    limit: int = Query(10,  description="최대 결과 수"),
):
    """
    기업명 또는 종목코드로 검색. 자동완성 드롭다운용.

    예: /api/search?q=삼성
        /api/search?q=005930
    """
    cmap  = _load_map()
    index = cmap.get("search_index", [])
    q     = q.strip()

    results = []
    for item in index:
        name_match = q in item.get("corp_name", "")
        code_match = item.get("stock_code", "").startswith(q)
        if name_match or code_match:
            results.append({
                "stock_code": item["stock_code"],
                "corp_name" : item["corp_name"],
                "market"    : item.get("market", ""),
                "has_data"  : item.get("has_jsonl", False),
            })
        if len(results) >= limit:
            break

    return {"query": q, "count": len(results), "results": results}


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

@app.get("/sankey/{stock_code}", response_class=HTMLResponse)
def get_sankey(stock_code: str):
    """
    사전 생성된 Plotly Sankey HTML 반환.
    파일 없으면 404.
    실행: python db/build_sankey.py {code}
    """
    html_path = _SANKEY_DIR / f"{stock_code}_sankey.html"
    if not html_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Sankey 미생성: {stock_code} — python db/build_sankey.py {stock_code} 실행 필요",
        )
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))
