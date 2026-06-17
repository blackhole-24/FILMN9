# -*- coding: utf-8 -*-
"""DAY2 D-6: RAG hybrid — BM25 + cross-encoder rerank 보조 채널.

배경:
  Phase 1 whitening(all-but-the-top)으로 임베딩 anisotropy 를 1차 해소했으나,
  dense cosine 단독은 (1) 도메인 고유 어휘 정확 일치(예: '이차전지' vs '배터리'
  표기 차이)를 놓치고, (2) 짧은 사업 텍스트에서 변별력이 떨어진다.

  → 3개 채널을 결합:
     · dense   : whitened centroid cosine        (기존, 의미)
     · sparse  : BM25 (어휘 정확 매칭)            (신규)
     · rerank  : cross-encoder bge-reranker-v2-m3 (신규, 쌍 관련도, GPU 유리)

통합 (기본 가중):
     final = 0.5 * dense + 0.3 * bm25_norm + 0.2 * rerank
  가용하지 않은 채널은 가중치를 제외하고 남은 채널로 재정규화 (graceful).
  → 의존성/모델이 전혀 없어도 dense 단독으로 동작 (기존 동작 보존).

의존성 (모두 선택적 — 없으면 해당 채널 자동 스킵):
  · rank_bm25         : BM25 채널
  · kiwipiepy         : 한국어 형태소 토큰화 (없으면 char n-gram fallback)
  · FlagEmbedding     : bge-reranker-v2-m3 (GPU 권장)

설계 원칙:
  · 모든 외부 import 는 함수 내부 lazy + try/except → 모듈 import 자체는 무비용.
  · reranker 모델은 1회 로드 후 프로세스 캐시 (_RERANKER_CACHE).
  · 실데이터 정책 — 텍스트 없으면 None 반환(임의값 금지).
"""
from __future__ import annotations

from typing import Optional

# 기본 결합 가중 (가용 채널만으로 재정규화됨)
HYBRID_WEIGHTS = {"dense": 0.50, "bm25": 0.30, "rerank": 0.20}

# reranker 프로세스 캐시 — (model_obj or False). False = 로드 실패(재시도 안 함).
_RERANKER_CACHE = None
_RERANKER_MODEL_NAME = "BAAI/bge-reranker-v2-m3"


# ─────────────────────────────────────────────────────────────
# 토큰화 (한국어)
# ─────────────────────────────────────────────────────────────
_KIWI = None


def _tokenize(text: str) -> list[str]:
    """한국어 토큰화.

    1순위: kiwipiepy 형태소 분석 (명사·동사·형용사·외국어·숫자 어간).
    fallback: 공백 분리 + char 2-gram (형태소 분석기 부재 시).

    BM25 의 어휘 매칭 품질은 토큰화에 좌우 — 조사·어미를 떼야 '배터리를'/'배터리'가
    같은 토큰이 된다. kiwipiepy 가 있으면 정확, 없으면 char-bigram 이 근사 대체.
    """
    global _KIWI
    if not text:
        return []
    text = text.strip()
    # 1순위: kiwipiepy
    if _KIWI is not False:
        try:
            if _KIWI is None:
                from kiwipiepy import Kiwi
                _KIWI = Kiwi()
            toks = []
            for tok in _KIWI.tokenize(text):
                # 의미 형태소만: 일반/고유명사, 동사, 형용사, 외국어, 숫자, 영어
                if tok.tag[:2] in ("NN", "VV", "VA", "SL", "SN", "XR") or tok.tag == "NNG":
                    toks.append(tok.form.lower())
            if toks:
                return toks
        except Exception:
            _KIWI = False   # 부재 — 재시도 안 함
    # fallback: 공백 분리 + char bigram (한글 연속 구간)
    out: list[str] = []
    for word in text.split():
        w = word.strip().lower()
        if len(w) <= 2:
            if w:
                out.append(w)
        else:
            # 2-gram 슬라이딩 (짧은 어휘 변별)
            out.extend(w[i:i + 2] for i in range(len(w) - 1))
    return out


# ─────────────────────────────────────────────────────────────
# BM25 (sparse 어휘 매칭)
# ─────────────────────────────────────────────────────────────
def compute_bm25_scores(query_text: str,
                        corpus_texts: list[str]) -> Optional[list[float]]:
    """query 1건 vs corpus N건 → 각 corpus 문서의 BM25 점수 (min-max 정규화 0~1).

    Args:
        query_text:   타깃 사업 텍스트.
        corpus_texts: 후보들 사업 텍스트 (순서 = 후보 순서).
    Returns:
        길이 N 리스트 (0~1 정규화) 또는 None (rank_bm25 부재 / 입력 부족).

    정규화: BM25 raw 점수는 코퍼스마다 스케일이 달라 절대값 비교 불가 →
    후보 집합 내 min-max 로 상대 순위만 0~1 에 매핑. 후보가 1개거나 전부 동일하면
    변별 불가 → 0.5(중립) 반환.
    """
    try:
        from rank_bm25 import BM25Okapi
    except ImportError:
        return None
    if not query_text or not corpus_texts:
        return None
    corpus_tokens = [_tokenize(t or "") for t in corpus_texts]
    # 빈 토큰 문서가 섞이면 BM25 가 0 처리 — 허용 (해당 후보 sparse=0)
    if not any(corpus_tokens):
        return None
    query_tokens = _tokenize(query_text)
    if not query_tokens:
        return None
    try:
        bm25 = BM25Okapi(corpus_tokens)
        raw = bm25.get_scores(query_tokens)
    except Exception:
        return None
    raw = [float(x) for x in raw]
    lo, hi = min(raw), max(raw)
    if hi - lo < 1e-12:
        # 전부 동일 → 변별 불가, 중립 0.5
        return [0.5] * len(raw)
    return [(x - lo) / (hi - lo) for x in raw]


# ─────────────────────────────────────────────────────────────
# Cross-encoder rerank (쌍 관련도)
# ─────────────────────────────────────────────────────────────
def _get_reranker():
    """bge-reranker-v2-m3 lazy 로드 + 프로세스 캐시.

    Returns: FlagReranker 객체 또는 None (부재/로드 실패).
    """
    global _RERANKER_CACHE
    if _RERANKER_CACHE is not None:
        return _RERANKER_CACHE or None
    try:
        from FlagEmbedding import FlagReranker
        # use_fp16: GPU 메모리 절약. CPU 면 자동 무시.
        model = FlagReranker(_RERANKER_MODEL_NAME, use_fp16=True)
        _RERANKER_CACHE = model
        return model
    except Exception:
        _RERANKER_CACHE = False
        return None


def rerank_scores(query_text: str,
                  candidate_texts: list[str]) -> Optional[list[float]]:
    """cross-encoder 로 query vs 각 candidate 쌍 관련도 → 0~1 (sigmoid).

    Returns: 길이 N 리스트 또는 None (모델 부재 / 입력 부족).
    GPU 가용 시 빠름. 비용 큼 — top-K 후보로 제한해 호출 권장.
    """
    model = _get_reranker()
    if model is None or not query_text or not candidate_texts:
        return None
    pairs = [[query_text, t or ""] for t in candidate_texts]
    try:
        # normalize=True → sigmoid 적용 0~1
        scores = model.compute_score(pairs, normalize=True)
    except Exception:
        return None
    if not isinstance(scores, (list, tuple)):
        scores = [scores]
    return [float(s) for s in scores]


# ─────────────────────────────────────────────────────────────
# 통합
# ─────────────────────────────────────────────────────────────
def combine_hybrid(dense: Optional[float],
                   bm25: Optional[float],
                   rerank: Optional[float],
                   weights: Optional[dict] = None) -> Optional[float]:
    """가용 채널만 가중 결합 (None 채널 제외 후 재정규화).

    Args:
        dense:  whitened cosine 0~1 (또는 None)
        bm25:   BM25 정규화 0~1 (또는 None)
        rerank: reranker 0~1 (또는 None)
    Returns:
        결합 점수 0~1, 또는 None (모든 채널 None).

    예) dense=0.6, bm25=0.8, rerank 부재 →
        (0.5*0.6 + 0.3*0.8) / (0.5+0.3) = 0.66/0.8 = 0.675
    """
    w = weights or HYBRID_WEIGHTS
    parts = [("dense", dense), ("bm25", bm25), ("rerank", rerank)]
    num = 0.0
    den = 0.0
    for key, val in parts:
        if val is None:
            continue
        wk = w.get(key, 0.0)
        num += wk * float(val)
        den += wk
    if den < 1e-12:
        return None
    return num / den
