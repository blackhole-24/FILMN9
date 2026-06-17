# -*- coding: utf-8 -*-
"""첨부파일 처리 유틸 (B 확장).

- pdf_extract_text : PDF 텍스트 추출(pypdf)
- pdf_render_pages : 스캔/이미지 PDF 페이지를 PNG로 렌더(PyMuPDF) → 비전 입력
- ephemeral_pdf_rag: 대용량 PDF를 청킹·임베딩해 질문 관련 상위 청크만 추출
                     (메인 ChromaDB를 건드리지 않는 인메모리 RAG)
"""
from __future__ import annotations

import base64
import io


def pdf_extract_text(data: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    return "\n".join((p.extract_text() or "") for p in reader.pages).strip()


def pdf_render_pages(data: bytes, max_pages: int = 6, dpi: int = 130) -> list:
    """스캔/이미지 PDF의 앞 max_pages 페이지를 PNG로 렌더 → [(base64, mime), ...].

    텍스트 추출이 안 되는 스캔본을 비전으로 읽기 위함. PyMuPDF(fitz) 필요.
    """
    import fitz  # PyMuPDF
    out: list = []
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            pix = page.get_pixmap(dpi=dpi)
            out.append((base64.b64encode(pix.tobytes("png")).decode(), "image/png"))
    finally:
        doc.close()
    return out


def ephemeral_pdf_rag(text: str, question: str, top_k: int = 8, chunk_chars: int = 1200) -> str:
    """대용량 PDF: 청킹 → 임베딩 → 질문 유사도 상위 top_k 청크만 묶어 반환.

    메인 ChromaDB에 저장하지 않는 1회성(인메모리) RAG — 토큰 한도 안에서 관련 부분만 LLM에 전달.
    임베딩 실패/소형 문서면 원문을 그대로 반환(graceful).
    """
    chunks = [text[i:i + chunk_chars] for i in range(0, len(text), chunk_chars)]
    if len(chunks) <= top_k:
        return text
    try:
        import numpy as np
        from ..embedder import embed_texts
        q = (question or "").strip() or "핵심 요약"
        embs = embed_texts(chunks + [q], show_progress=False)
        arr = np.asarray([np.asarray(e, dtype="float32") for e in embs])
        cv, qv = arr[:-1], arr[-1]
        sims = (cv @ qv) / (np.linalg.norm(cv, axis=1) * (np.linalg.norm(qv) + 1e-9) + 1e-9)
        idx = sorted(int(i) for i in sims.argsort()[::-1][:top_k])
        return "\n…\n".join(chunks[i] for i in idx)
    except Exception:
        # 임베딩 불가 시 앞부분 truncation 으로 폴백
        return text[:top_k * chunk_chars]
