"""Phase 1 — BGE-M3 사업 centroid 의 anisotropy 보정 (all-but-the-top).

배경:
  BGE-M3 같은 sentence embedding 은 anisotropic — 모든 벡터가 고차원 공간의 좁은
  cone 에 몰림. → 무관한 회사끼리도 cosine 이 0.78~0.93 에 압축돼 변별력 저하.

방법 (Mu & Viswanath 2018, "All-But-The-Top"):
  1) corpus centroid 모음에서 평균 μ 차감 (centering)
  2) SVD 로 상위 k 개 PC (anisotropic component) 제거
  3) 결과 정규화 → cosine 분포가 [-1, +1] 전체로 펴짐

전제:
  · 저장된 centroid_*.npy 가 충분히(≥20개) 있어야 fit 가능.
  · 부족하면 graceful skip (whitening 미적용, 기존 raw cosine 그대로).
  · GPU 불필요 — numpy CPU SVD.

사용:
  from .embedding_whitening import get_params, whiten_vector
  params = get_params()
  if params is not None:
      v1 = whiten_vector(raw_v1, params)
      v2 = whiten_vector(raw_v2, params)
  cosine = np.dot(v1, v2)
"""
from __future__ import annotations
import glob
from pathlib import Path
from typing import Optional

import numpy as np


_VAR_ROOT = Path(__file__).resolve().parent.parent
_CENTROID_DIR = _VAR_ROOT / "data" / "rag_cache"
_WHITENING_CACHE = _CENTROID_DIR / "whitening_params.npz"
_CENTROID_DIR.mkdir(parents=True, exist_ok=True)

# 상위 PC 제거 개수 — 8 (1024-dim 임베딩의 상위 약 0.8% 주성분 제거)
_DEFAULT_K = 8
# 학습 최소 표본
_MIN_CORPUS = 20

_PARAMS_CACHE: Optional[dict] = None


def _load_corpus_centroids() -> Optional[np.ndarray]:
    """저장된 centroid_*.npy → 행렬 (N, D). 표본 부족 시 None."""
    files = sorted(glob.glob(str(_CENTROID_DIR / "centroid_*.npy")))
    vecs = []
    expected_dim = None
    for f in files:
        try:
            v = np.load(f)
            if v.ndim != 1 or v.size == 0:
                continue
            if expected_dim is None:
                expected_dim = v.size
            elif v.size != expected_dim:
                continue   # 차원 다른 벡터 스킵
            vecs.append(v)
        except Exception:
            continue
    if len(vecs) < _MIN_CORPUS:
        return None
    return np.stack(vecs)


def fit_whitening(corpus: np.ndarray, k: int = _DEFAULT_K) -> dict:
    """all-but-the-top: μ + 상위 k 개 주성분 학습.

    Args:
        corpus: (N, D) 정규화된 centroid 행렬
        k:      제거할 상위 주성분 개수
    Returns:
        {"mu": (D,), "top_pcs": (k, D), "n_corpus": N, "k": k}
    """
    mu = corpus.mean(axis=0)
    X = corpus - mu
    # SVD: X = U S Vt — 상위 k 개 PC = Vt[:k]
    _, _, Vt = np.linalg.svd(X, full_matrices=False)
    top_pcs = Vt[: min(k, Vt.shape[0])]
    params = {"mu": mu, "top_pcs": top_pcs,
              "n_corpus": int(corpus.shape[0]), "k": int(top_pcs.shape[0])}
    # Phase 5: whitened pairwise cosine 분포 → [0,1] percentile 정규화 기준.
    #   whitening(anisotropy 제거) 후 cosine 은 0 근처로 압축해제돼 raw 임계(0.55·0.7)
    #   와 스케일이 안 맞는다. corpus centroid 간 cosine 분포의 percentile rank 로 매핑해
    #   '동종=높은 유사도' 의미를 복원하고 임계 호환성을 확보한다(아래 normalize 사용).
    W = np.stack([whiten_vector(c, params) for c in corpus])
    sims = []
    n = len(W)
    for i in range(n):
        for j in range(i + 1, n):
            sims.append(float(np.dot(W[i], W[j])))
    if sims:
        params["cos_percentiles"] = np.percentile(np.asarray(sims), np.arange(0, 101))
    return params


def save_params(params: dict, path: Path = _WHITENING_CACHE) -> None:
    kw = dict(mu=params["mu"], top_pcs=params["top_pcs"],
              n_corpus=params.get("n_corpus", 0), k=params.get("k", 0))
    if params.get("cos_percentiles") is not None:
        kw["cos_percentiles"] = params["cos_percentiles"]   # Phase 5
    np.savez(path, **kw)


def load_params(path: Path = _WHITENING_CACHE) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        npz = np.load(path)
        p = {"mu": npz["mu"], "top_pcs": npz["top_pcs"],
             "n_corpus": int(npz.get("n_corpus", np.array(0))),
             "k": int(npz.get("k", np.array(0)))}
        if "cos_percentiles" in npz.files:
            p["cos_percentiles"] = npz["cos_percentiles"]    # Phase 5
        return p
    except Exception:
        return None


def normalize_whitened_cosine(cos: float, params: Optional[dict]) -> float:
    """Phase 5: whitened cosine → [0,1] (corpus 분포 percentile rank).

    whitening 후 cosine 은 0 근처로 압축해제돼 절대값이 작다(동종도 0.05~0.3).
    corpus centroid 간 cosine 분포에서 이 값이 상위 몇 %인지(rank)로 매핑해
    '동종=높은 유사도(0.7~0.9)'·'무관=낮음(0.1~0.3)' 의미를 복원한다 → 임계(0.55) 호환.
    cos_percentiles 부재(구 캐시) 시 raw rescale 폴백.
    """
    if params is None:
        return max(0.0, min(1.0, (cos - 0.7) / 0.3))    # raw cosine 폴백
    cp = params.get("cos_percentiles")
    if cp is None:
        return max(0.0, min(1.0, (cos - 0.7) / 0.3))
    rank = float(np.searchsorted(cp, cos)) / (len(cp) - 1)
    return max(0.0, min(1.0, rank))


def whiten_vector(v: np.ndarray, params: Optional[dict]) -> np.ndarray:
    """단일 벡터에 whitening 적용. 결과는 L2 정규화.

    params=None 시 단순 정규화만 (graceful fallback).
    """
    if params is None:
        return v / (np.linalg.norm(v) + 1e-12)
    x = v - params["mu"]
    # 상위 PC 방향 성분 제거
    for pc in params["top_pcs"]:
        x = x - float(np.dot(x, pc)) * pc
    n = float(np.linalg.norm(x)) + 1e-12
    return x / n


def get_params(force_refit: bool = False, k: int = _DEFAULT_K,
               verbose: bool = False) -> Optional[dict]:
    """프로세스 단위 메모이즈된 whitening 파라미터.

    캐시 hit: 메모리 → 디스크. miss: corpus 로드 + fit + 저장.
    표본 부족(<_MIN_CORPUS) 시 None — 호출자가 whitening 미적용.
    """
    global _PARAMS_CACHE
    if _PARAMS_CACHE is not None and not force_refit:
        return _PARAMS_CACHE
    if not force_refit:
        p = load_params()
        if p is not None:
            _PARAMS_CACHE = p
            if verbose:
                print(f"  [whitening] 캐시 hit: n_corpus={p['n_corpus']}, k={p['k']}")
            return _PARAMS_CACHE
    corpus = _load_corpus_centroids()
    if corpus is None:
        if verbose:
            print(f"  [whitening] corpus < {_MIN_CORPUS} — 미적용")
        return None
    params = fit_whitening(corpus, k=k)
    save_params(params)
    _PARAMS_CACHE = params
    if verbose:
        print(f"  [whitening] fit: n_corpus={params['n_corpus']}, k={params['k']}")
    return params


def whitened_cosine(v1: np.ndarray, v2: np.ndarray,
                    params: Optional[dict] = None) -> float:
    """두 raw centroid → whitening cosine (params None 면 raw cosine)."""
    if params is None:
        params = get_params()
    w1 = whiten_vector(v1, params)
    w2 = whiten_vector(v2, params)
    return float(np.dot(w1, w2))


if __name__ == "__main__":
    p = get_params(verbose=True)
    if p:
        print(f"  μ norm: {np.linalg.norm(p['mu']):.4f}")
        print(f"  상위 PC 분산 비율 (PC1~k):")
        # 분산 비율 출력 — corpus 재로드 후
        corpus = _load_corpus_centroids()
        if corpus is not None:
            X = corpus - p["mu"]
            _, S, _ = np.linalg.svd(X, full_matrices=False)
            total = float(np.sum(S ** 2))
            for i, s in enumerate(S[:p["k"]]):
                ratio = (s ** 2) / total * 100
                print(f"    PC{i+1}: {ratio:.2f}%")
