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

import base64
import io
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse
from pydantic import BaseModel

from . import pipeline, company_index, llm_client
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
        # 검색 경로 전체(ChromaDB coll.get + brute-force + 재랭킹)를 startup 으로 콜드로딩 당김.
        # chatbot search()는 종목필터 시 coll.get 기반(brute-force) — 이 경로의 대용량 인덱스
        # 콜드로딩이 첫 사용자 질의를 수분 멈추게 한다. dummy 질의로 그 비용을 startup 1회로 옮긴다.
        # (GPU 무관 — ChromaDB 는 CPU/RAM 전용. VRAM 8GB 엔 대용량 인덱스가 안 들어감)
        try:
            import time as _t
            from . import retriever as _rt
            _s = _t.time()
            print("[api] warming up retrieval path (ChromaDB 대용량 인덱스 — 1~3분 소요)...", flush=True)
            _rt.search(queries=["워밍업"], rerank_query="워밍업",
                       ticker="005930", year=2025, final_top_k=3)
            print(f"[api] retrieval path warm ({_t.time() - _s:.0f}s)", flush=True)
        except Exception as e:
            print(f"[api] retrieval warmup skipped: {e}", flush=True)
        print("[api] warmup done.", flush=True)
    except Exception as e:
        print(f"[api] warmup skipped: {e}", flush=True)
    yield


app = FastAPI(title="사업보고서 RAG 챗봇", version="1.0", lifespan=lifespan)

# 통합 프론트(Next.js localhost:3000 등)에서 직접 호출 가능하도록 CORS 허용.
# 데모/로컬 단계라 전체 허용. 배포 시 allow_origins 를 실제 도메인으로 제한 권장.
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


# ── 첨부파일(이미지 / PDF) 멀티모달 답변 (B 기본형 + 확장) ──
_ALLOWED_IMG_MIME = {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif"}
_MAX_ATTACH_MB = 20
_PDF_RAG_THRESHOLD = 8000     # 추출 텍스트가 이보다 길면 첨부-RAG로 관련부분만
_SCAN_MAX_PAGES = 6          # 스캔 PDF 비전 인식 최대 페이지
_COMPARE_HINTS = ("비교", "대조", "대비", "차이", "vs", "versus")


def _maybe_dart_context(message: str) -> Optional[str]:
    """메시지에 '비교' 의도 + 회사가 있으면 해당 회사 DART 청크 발췌를 반환(없으면 None).

    회사 추출은 query_analyzer(문장→회사명) 사용. 불안정한 chroma 노출을 줄이기 위해
    비교 의도가 명확할 때만 검색한다(graceful — 실패 시 None → 첨부만으로 답변).
    """
    if not message or not any(h in message for h in _COMPARE_HINTS):
        return None
    from . import query_analyzer, retriever
    from ..retrieval import format_chunks_for_llm
    names, queries = [], [message]
    try:
        a = query_analyzer.analyze(message, current_year=2026)
        names = [n for n in ([a.get("company")] + (a.get("company_aliases") or [])) if n]
        queries = list(a.get("queries") or [message])
    except Exception:
        pass
    res = company_index.resolve_any(names) if names else {"matched": False}
    if not res.get("matched"):
        return None
    sr = retriever.search(queries=queries, rerank_query=message,
                          ticker=res["ticker"], final_top_k=6)
    chunks = sr.get("chunks") or []
    return format_chunks_for_llm(chunks, max_chars=8000) if chunks else None


@app.post("/chat/attach")
async def chat_attach(message: str = Form(""), session_id: Optional[str] = Form(None),
                      file: UploadFile = File(...)):
    """이미지·PDF(텍스트/스캔)를 첨부받아 멀티모달 LLM으로 답변.

    확장: 대용량 PDF는 첨부-RAG(관련부분만), 스캔 PDF는 페이지 비전, '비교' 의도면 DART와 대조.
    """
    data = await file.read()
    if len(data) > _MAX_ATTACH_MB * 1024 * 1024:
        return {"status": "error", "answer": f"파일이 너무 큽니다(최대 {_MAX_ATTACH_MB}MB).",
                "sources": [], "meta": {"mode": "attachment"}}
    name = file.filename or "attachment"
    ctype = (file.content_type or "").lower()
    low = name.lower()
    from . import attach_utils
    pdf_text, images, note, kind = None, [], "", "이미지"

    if ctype == "application/pdf" or low.endswith(".pdf"):
        kind = "PDF"
        try:
            pdf_text = attach_utils.pdf_extract_text(data)
        except Exception as e:
            return {"status": "error", "answer": f"PDF를 읽지 못했습니다: {e}",
                    "sources": [], "meta": {"mode": "attachment", "filename": name}}
        if pdf_text:
            if len(pdf_text) > _PDF_RAG_THRESHOLD:        # 대용량 → 첨부-RAG
                pdf_text = attach_utils.ephemeral_pdf_rag(pdf_text, message, top_k=8)
                note = "대용량 PDF — 질문 관련 부분만 검색(첨부 RAG)"
        else:                                              # 스캔/이미지 PDF → 페이지 비전
            try:
                images = attach_utils.pdf_render_pages(data, max_pages=_SCAN_MAX_PAGES)
            except Exception as e:
                return {"status": "ok", "sources": [], "meta": {"mode": "attachment", "filename": name},
                        "answer": f"스캔 PDF를 이미지로 변환하지 못했습니다({e}). 텍스트 PDF나 이미지를 첨부해 주세요."}
            if not images:
                return {"status": "ok", "sources": [], "meta": {"mode": "attachment", "filename": name},
                        "answer": "이 PDF에서 페이지를 추출하지 못했습니다."}
            kind = "스캔PDF"
            note = f"스캔 PDF — 앞 {len(images)}페이지 비전 인식"
    elif ctype in _ALLOWED_IMG_MIME or low.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
        mime = ctype if ctype in _ALLOWED_IMG_MIME else "image/png"
        images.append((base64.b64encode(data).decode(), mime))
    else:
        return {"status": "error", "sources": [], "meta": {"mode": "attachment", "filename": name},
                "answer": f"지원하지 않는 형식입니다({ctype or low}). PDF 또는 이미지(PNG/JPG/WEBP)를 첨부해 주세요."}

    # 첨부 + DART 비교 (메시지에 비교 의도 + 회사가 있을 때만, graceful)
    dart_context = None
    try:
        dart_context = _maybe_dart_context(message)
        if dart_context:
            note = (note + " · " if note else "") + "DART 보고서와 비교"
    except Exception:
        dart_context = None

    try:
        ans = llm_client.generate_attachment_answer(message, pdf_text=pdf_text, images=images,
                                                    dart_context=dart_context)
    except Exception as e:
        return {"status": "error", "answer": f"첨부 분석 중 오류: {e}",
                "sources": [], "meta": {"mode": "attachment", "filename": name}}
    return {"status": "ok", "answer": ans, "sources": [],
            "meta": {"mode": "attachment", "filename": name, "attach_kind": kind,
                     "note": note, "dart_compared": bool(dart_context)}}


@app.post("/session/reset")
def reset(req: ResetRequest):
    STORE.reset(req.session_id)
    return {"status": "ok", "session_id": req.session_id}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
