"""FastAPI 백엔드.

엔드포인트:
  GET  /health            상태 + DB 청크 수 + 디바이스
  GET  /companies?q=...   회사 검색/해석 (자동완성·되묻기용)
  POST /chat              논스트리밍 답변 {answer, sources, meta}
  POST /chat/stream       SSE 스트리밍 (head 메타 → 토큰들)
  POST /session/reset     세션 초기화

실행:
  conda activate dart-rag
  uvicorn embedding.chatbot.api:app --host 0.0.0.0 --port 8000
  # 또는: python -m embedding.chatbot.api
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse
from pydantic import BaseModel

from . import pipeline, company_index
from .session import STORE


@asynccontextmanager
async def lifespan(app: "FastAPI"):
    """서버 부팅 시 무거운 모델을 미리 로드(워밍업)해 첫 질의 콜드스타트 제거."""
    try:
        from ..embedder import embed_texts
        from . import reranker, company_index as _ci
        print("[api] warming up models...", flush=True)
        embed_texts(["워밍업"], show_progress=False)   # BGE-M3 로드
        try:
            reranker._load()                            # reranker 로드
        except reranker.RerankUnavailable as e:
            print(f"[api] reranker unavailable: {e}", flush=True)
        _ci._ensure_loaded()                            # 회사 인덱스 로드
        print("[api] warmup done.", flush=True)
    except Exception as e:
        print(f"[api] warmup skipped: {e}", flush=True)
    yield


app = FastAPI(title="사업보고서 RAG 챗봇", version="1.0", lifespan=lifespan)

# CORS — 프론트(localhost:3000)에서 직접 호출 가능하도록
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_INDEX_HTML = Path(__file__).resolve().parent / "static" / "index.html"


@app.get("/", response_class=HTMLResponse)
def index():
    """단일 페이지 채팅 UI (SSE 스트리밍)."""
    try:
        return _INDEX_HTML.read_text(encoding="utf-8")
    except OSError:
        return HTMLResponse("<h1>index.html not found</h1>", status_code=500)


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    current_year: int = 2026
    ticker: Optional[str] = None     # 후보 칩 클릭 등으로 회사 강제 지정 시


class ResetRequest(BaseModel):
    session_id: str


@app.get("/health")
def health():
    info = {"status": "ok"}
    try:
        from ..vector_store import get_stats
        from ..embedder import get_device_info
        info["db"] = get_stats()
        info["device"] = get_device_info()
    except Exception as e:
        info["status"] = "degraded"
        info["error"] = str(e)
    return info


@app.get("/companies")
def companies(q: Optional[str] = None, limit: int = 20):
    """q 가 있으면 해석 결과(매칭/후보), 없으면 앞부분 목록."""
    if q:
        return company_index.resolve(q)
    return {"companies": company_index.list_companies()[:limit]}


@app.post("/chat")
def chat(req: ChatRequest):
    return pipeline.answer(req.message, session_id=req.session_id,
                           current_year=req.current_year, ticker=req.ticker)


@app.post("/chat/stream")
def chat_stream(req: ChatRequest):
    """단계별 SSE 스트림.

    이벤트 유형(pipeline.answer_stream 참고):
      stage   — 진행 상태(분석/검색/생성)
      head    — 메타/상태
      sources — 출처 카드(답변보다 먼저 도착해 사용자 미리 읽기)
      token   — LLM 토큰
      done    — 종료
    """
    events = pipeline.answer_stream(
        req.message, session_id=req.session_id,
        current_year=req.current_year, ticker=req.ticker)

    def _sse():
        for ev in events:
            etype = ev.pop("type", "message")
            yield f"event: {etype}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"

    return StreamingResponse(_sse(), media_type="text/event-stream")


@app.post("/session/reset")
def reset(req: ResetRequest):
    STORE.reset(req.session_id)
    return {"status": "ok", "session_id": req.session_id}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
