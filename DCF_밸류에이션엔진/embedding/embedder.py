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
    # SDPA(scaled_dot_product_attention) 어텐션 — 긴 시퀀스(1024토큰 표) forward 가속
    # + 메모리 절감. FP16과 결합 시 flash/메모리효율 커널 동작. 미지원 transformers/모델이면
    # eager 로 graceful fallback.
    try:
        _MODEL = AutoModel.from_pretrained(
            EMBEDDING_MODEL,
            local_files_only=True,
            attn_implementation="sdpa",
        )
    except Exception:
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

    # ── 길이정렬 + 토큰버짓 적응형 배치 (패딩 낭비 제거, 결과/순서 불변) ──
    # 동적 패딩(padding=True)은 배치 내 최장 길이에 맞춰 패딩하므로, 길이가 섞이면
    # 짧은 청크가 긴 청크에 맞춰 헛계산된다. 길이순으로 정렬해 비슷한 길이끼리 묶고,
    # "개수 × 최장토큰 ≤ token_budget" 예산으로 배치를 구성하면 짧은 청크는 한 배치에
    # 수백 개까지 묶여 GPU 실효 처리량이 크게 오른다. (패딩은 attention mask로 무시되어
    # 각 청크의 CLS 임베딩은 배치 구성과 무관하게 동일 → 수치 동일, 마지막에 원순서 복원)
    n = len(texts)
    # 토큰 추정은 보수적으로 1토큰=1문자(한국어는 실제 ~0.5tok/char라 과대추정=안전).
    # → 배치 실제 토큰수 ≤ 예산이 되어 기존 batch_size×max_length 메모리 상한을 안 넘김.
    approx = [min(max_length, max(1, len(t))) for t in texts]
    order = sorted(range(n), key=lambda i: approx[i])

    token_budget = max(max_length, batch_size * max_length)  # 기존 상한과 동일
    max_count = batch_size * 16                               # 짧은 청크 묶음 개수 상한

    groups: list[list[int]] = []
    cur: list[int] = []
    cur_max = 0
    for idx in order:
        tok = approx[idx]
        new_max = cur_max if tok <= cur_max else tok
        if cur and ((len(cur) + 1) * new_max > token_budget or len(cur) + 1 > max_count):
            groups.append(cur)
            cur, cur_max = [idx], tok
        else:
            cur.append(idx)
            cur_max = new_max
    if cur:
        groups.append(cur)

    iterator = groups
    if show_progress:
        try:
            from tqdm.auto import tqdm

            iterator = tqdm(groups, desc="Embedding", unit="batch")
        except Exception:
            pass

    out = np.empty((n, EMBEDDING_DIM), dtype=np.float32)
    for grp in iterator:
        batch = [texts[i] for i in grp]
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
        emb = embeddings.detach().cpu().numpy().astype(np.float32)
        for j, i in enumerate(grp):
            out[i] = emb[j]

    return out


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
