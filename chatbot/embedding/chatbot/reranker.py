"""Cross-encoder 재랭킹 (BAAI/bge-reranker-v2-m3).

bi-encoder(임베딩)는 질문·청크를 따로 벡터화해 거리만 재지만, cross-encoder 는
(질문, 청크) 쌍을 함께 보고 관련성을 직접 채점한다. 1단계에서 넓게 가져온 후보를
2단계에서 정밀 재정렬해 정확도를 끌어올린다.

embedder.py 와 동일하게 transformers 를 직접 사용한다 (Windows 에서 sentence-transformers
import 시 네이티브 SSL 로딩 크래시 회피). 재임베딩이 전혀 필요 없고 질의 시에만 동작.

최초 1회 모델 로드(미캐시면 다운로드 ~2.2GB). 로드 실패 시 None 을 반환하는 대신
호출부에서 graceful degrade 하도록 RerankUnavailable 를 던진다.
"""
from __future__ import annotations

from .config import RERANKER_MODEL, RERANKER_MAX_LEN, RERANKER_LOCAL_ONLY

_MODEL = None
_TOKENIZER = None
_DEVICE = None


class RerankUnavailable(RuntimeError):
    """재랭커 로드 불가 (미설치/미다운로드 등) — 호출부에서 스킵."""


def _load():
    global _MODEL, _TOKENIZER, _DEVICE
    if _MODEL is not None:
        return _MODEL, _TOKENIZER, _DEVICE
    try:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
    except ImportError as e:
        raise RerankUnavailable("torch/transformers 필요") from e

    _DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
    try:
        _TOKENIZER = AutoTokenizer.from_pretrained(
            RERANKER_MODEL, local_files_only=RERANKER_LOCAL_ONLY)
        _MODEL = AutoModelForSequenceClassification.from_pretrained(
            RERANKER_MODEL, local_files_only=RERANKER_LOCAL_ONLY)
    except Exception as e:
        raise RerankUnavailable(f"재랭커 모델 로드 실패: {e}") from e

    _MODEL.to(torch.device(_DEVICE))
    if _DEVICE == "cuda":
        _MODEL = _MODEL.half()   # FP16: 메모리 절반 + 속도 ↑
    _MODEL.eval()
    print(f"[reranker] loaded {RERANKER_MODEL} (device={_DEVICE})", flush=True)
    return _MODEL, _TOKENIZER, _DEVICE


def rerank(query, candidates: list[dict], top_k: int,
           batch_size: int = 16) -> list[dict]:
    """(query, candidate['text']) 쌍을 채점해 상위 top_k 반환.

    query 는 str 또는 list[str]. 리스트면 각 질의로 채점한 뒤 청크별 **최고점(max)**을
    쓴다(확장 인지 재랭킹): "우발부채" 질문이 끌어온 "지급보증" 청크가 "지급보증" 질의에서
    높은 점수를 받아 최종에 살아남게 한다.

    각 candidate 에 'rerank_score'(=max)와 'rerank_matched_query'(최고점 질의)를 추가한다.
    모델 로드 불가 시 RerankUnavailable 를 던진다.
    """
    if not candidates:
        return []
    queries = [query] if isinstance(query, str) else list(query)
    queries = [q for q in queries if q and q.strip()] or [""]

    import torch

    model, tokenizer, device = _load()
    texts = [c.get("text", "") for c in candidates]
    n = len(texts)
    max_scores = [float("-inf")] * n
    best_q: list = [None] * n

    for q in queries:
        for start in range(0, n, batch_size):
            batch = texts[start:start + batch_size]
            pairs = [[q, t] for t in batch]
            enc = tokenizer(pairs, padding=True, truncation=True,
                            max_length=RERANKER_MAX_LEN, return_tensors="pt")
            enc = {k: v.to(device) for k, v in enc.items()}
            with torch.inference_mode():
                logits = model(**enc).logits.view(-1).float()
            for i, sc in enumerate(logits.detach().cpu().tolist()):
                idx = start + i
                if sc > max_scores[idx]:
                    max_scores[idx] = sc
                    best_q[idx] = q

    for i, c in enumerate(candidates):
        c["rerank_score"] = float(max_scores[i])
        c["rerank_matched_query"] = best_q[i]
    ranked = sorted(candidates, key=lambda c: c["rerank_score"], reverse=True)
    return ranked[:top_k]
