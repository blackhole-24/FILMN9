"""임베딩 파이프라인 설정.

모델·DB·전처리 정책 한 곳에서 관리.
"""
from __future__ import annotations
from pathlib import Path

# ─────────────────────────────────────────────────────────────
# 경로
# ─────────────────────────────────────────────────────────────
VAR_ROOT = Path(__file__).resolve().parent.parent
KOSPI_DIR  = VAR_ROOT / "KOSPI"
KOSDAQ_DIR = VAR_ROOT / "KOSDAQ"

EMBEDDING_DIR = VAR_ROOT / "embedding"
CHROMA_DB_DIR = EMBEDDING_DIR / "chroma_db"   # ChromaDB 영구 저장
CHROMA_DB_DIR.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────────────────────────
# 임베딩 모델
# ─────────────────────────────────────────────────────────────
# BGE-M3 (BAAI) — 한국어 retrieval 최상위, 1024 차원, 8K context, Apache 2.0
EMBEDDING_MODEL = "BAAI/bge-m3"
EMBEDDING_DIM   = 1024

# GPU 자동 감지 (CUDA 사용 가능 시 GPU, 아니면 CPU)
USE_GPU = True   # False 면 강제 CPU

# 배치 크기 (GPU 메모리 따라 조정)
# - max_length=512 + FP16 + transformers AutoModel 기준 활성화 메모리 ~2GB
# - RTX 4060 Laptop 8GB VRAM 에서 batch 64 안전 (FP16 으로 메모리 절반)
# - OOM 시 32 또는 16으로 줄임
BATCH_SIZE = 64

# ─────────────────────────────────────────────────────────────
# 컬렉션 이름 (ChromaDB)
# ─────────────────────────────────────────────────────────────
COLLECTION_NAME = "annual_reports"

# ─────────────────────────────────────────────────────────────
# 청크 필터링 정책
# ─────────────────────────────────────────────────────────────
MIN_CHAR_LEN = 30        # 이보다 짧은 청크는 임베딩 제외 (의미 없음)
SKIP_SECTIONS = {        # 이런 섹션은 임베딩 제외 (cover page 등)
    "(문서 본문)",
}

# ─────────────────────────────────────────────────────────────
# 진행 표시
# ─────────────────────────────────────────────────────────────
VERBOSE = True
