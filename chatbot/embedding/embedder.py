"""BGE-M3 embedding helper.

This module uses transformers directly instead of sentence-transformers.
In the local Windows environment, importing sentence-transformers 5.x pulls in
datasets/aiohttp and can crash in native SSL certificate loading before any
Python exception is raised. BGE-M3's cached sentence-transformers config uses
CLS pooling followed by normalization, which is reproduced here.
"""
from __future__ import annotations

import numpy as np

from .config import BATCH_SIZE, EMBEDDING_DIM, EMBEDDING_MODEL, USE_GPU


_MODEL = None
_TOKENIZER = None
_DEVICE = None


def _get_device() -> str:
    """Return cuda when available and enabled, otherwise cpu."""
    global _DEVICE
    if _DEVICE is not None:
        return _DEVICE
    if not USE_GPU:
        _DEVICE = "cpu"
        return _DEVICE
    try:
        import torch

        _DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        _DEVICE = "cpu"
    return _DEVICE


def _load_model():
    """Load the BGE-M3 tokenizer and model once."""
    global _MODEL, _TOKENIZER
    if _MODEL is not None and _TOKENIZER is not None:
        return _MODEL, _TOKENIZER

    try:
        import torch
        from transformers import AutoModel, AutoTokenizer
    except ImportError as e:
        raise RuntimeError(
            "torch/transformers packages are required: "
            "pip install torch transformers"
        ) from e

    device = _get_device()
    print(f"[embedder] loading model: {EMBEDDING_MODEL} (device={device})", flush=True)
    _TOKENIZER = AutoTokenizer.from_pretrained(
        EMBEDDING_MODEL,
        local_files_only=True,
    )
    _MODEL = AutoModel.from_pretrained(
        EMBEDDING_MODEL,
        local_files_only=True,
    )
    _MODEL.to(torch.device(device))

    # GPU 에서는 FP16 으로 메모리 절반 + 속도 2배. BGE-M3 는 FP16 학습 호환 모델.
    precision = "FP32"
    if device == "cuda":
        _MODEL = _MODEL.half()
        precision = "FP16"

    _MODEL.eval()
    print(f"[embedder] loaded (dim={EMBEDDING_DIM}, precision={precision})", flush=True)
    return _MODEL, _TOKENIZER


def embed_texts(
    texts: list[str],
    batch_size: int = BATCH_SIZE,
    show_progress: bool = True,
    max_length: int = 1024,
) -> np.ndarray:
    """Embed texts into normalized dense vectors with shape N x 1024.

    max_length 기본 1024 — 한국 사업보고서의 긴 표(신용등급·자본·주식수 등)가
    512 토큰에서 잘리던 문제 해소 (실측: 청크의 ~15%가 512 초과, 1024 초과는 0.1%).
    BGE-M3 는 8192 토큰까지 지원.
    """
    if not texts:
        return np.zeros((0, EMBEDDING_DIM), dtype=np.float32)

    import torch

    model, tokenizer = _load_model()
    batch_size = max(1, int(batch_size))
    max_length = min(max_length, 8192)
    device = next(model.parameters()).device

    ranges = range(0, len(texts), batch_size)
    if show_progress:
        try:
            from tqdm.auto import tqdm

            ranges = tqdm(
                ranges,
                total=(len(texts) + batch_size - 1) // batch_size,
                desc="Embedding",
                unit="batch",
            )
        except Exception:
            pass

    batches = []
    for start in ranges:
        batch = texts[start:start + batch_size]
        encoded = tokenizer(
            batch,
            padding=True,
            truncation=True,
            max_length=max_length,
            return_tensors="pt",
        )
        encoded = {k: v.to(device) for k, v in encoded.items()}
        with torch.inference_mode():
            output = model(**encoded)
            # FP16 모델이면 hidden_state 도 FP16 — FP32 로 캐스팅 후 정규화 (정밀도 안정)
            embeddings = output.last_hidden_state[:, 0].float()
            embeddings = torch.nn.functional.normalize(embeddings, p=2, dim=1)
        batches.append(embeddings.detach().cpu().numpy().astype(np.float32))

    return np.vstack(batches)


def embed_query(query: str) -> np.ndarray:
    """Embed a single query into a 1D dense vector."""
    emb = embed_texts([query], show_progress=False)
    return emb[0]


def get_device_info() -> dict:
    """Return the device/model metadata used for embedding."""
    device = _get_device()
    info = {"device": device, "model": EMBEDDING_MODEL, "dim": EMBEDDING_DIM}
    if device == "cuda":
        try:
            import torch

            info["gpu_name"] = torch.cuda.get_device_name(0)
            info["gpu_mem_total_gb"] = (
                torch.cuda.get_device_properties(0).total_memory / 1e9
            )
        except Exception:
            pass
    return info
