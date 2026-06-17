"""자동 피어 산정 모듈.

사용자 입력 종목 → 자동으로 가치평가용 피어 4사 선정.

설계 — peer_group_finder_v7 의 알고리즘 + 우리 서비스 차별점 결합:

  점수 = 0.30 · 사업유사도   (WICS 소섹터 + 사업보고서 RAG 임베딩)
       + 0.15 · BIZ_TAG 일치도
       + 0.20 · 시총 유사도   (log scale)
       + 0.15 · 매출 유사도   (log scale)
       + 0.10 · 자본구조 D/E 유사도
       + 0.10 · 사이클 z-score 유사도 (산업 국면 정합)

필터 (제외 조건):
  - 동일 회사
  - 상장 < 2년 (β 회귀 표본 부족)
  - XBRL 데이터 부족
  - NOPAT 5년 중위값 ≤ 0 (만성 적자, 피어 멀티플 무의미)

차용 (peer_group_finder_v7):
  - WICS_SECTOR_MAP, BIZ_TAG, _CROSS_SECTOR_WHITELIST, MONOPOLY_SET
  - _mktcap_sim_log (로그 시총 유사도)

확장 (본 시스템 신규):
  - BGE-M3 임베딩 사업유사도 (사업보고서 RAG)
  - 재무 정합성 (매출·D/E)
  - 가치평가 적합성 (적자 회사 제외)

사용:
    from valuation_engine.peer_selector import select_peers

    peers = select_peers(ticker="000720", top_n=3)
    # → [{"ticker": "047040", "name": "대우건설", "score": 0.85, "reasons": {...}}, ...]
"""
from __future__ import annotations

import math
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

# 후보 XBRL 보강 동시 호출 워커 수 (DART 분당 한도 내 보수적)
_ENRICH_MAX_WORKERS = 5

_VAR_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_VAR_ROOT))


# ─────────────────────────────────────────────────────────────
# 가중치 (학술 기준 — Damodaran 피어 선정 + 본 시스템 목적)
# ─────────────────────────────────────────────────────────────
# Phase 1(2026-05-28) — 성장·마진·ROIC 차원 추가, 규모 가중치 축소.
#   목적: PER ≈ f(성장률, 위험, 배당), EV/EBITDA ≈ f(성장률, ROIC, 세율) — 멀티플을
#         결정하는 변수가 비슷한 회사를 골라야 멀티플 역산이 의미 있음.
#   변경 요지:
#     · 시총·매출 가중치 ↓ (사업 본질이 아닌 규모만 비슷한 회사 매칭 방지)
#     · OPM·growth·ROIC 신규 도입 (멀티플 결정 변수)
#     · sector·biz_tag 가중치 소폭 ↓ (전체 합 1.0 보존)
# Phase 5(2026-05-29) — RAG 사업유사도를 독립 가중 차원으로 승격.
#   기존: RAG 가 sec_score<0.5 일 때만 sector_sim 가중치(0.25)를 재사용해 보강
#         → ① 동종·인접 피어엔 RAG 미적용(게이트), ② 보강 시 가중치 합 1.0 런타임 위반.
#   변경: rag_sim 독립 차원(0.10) — '항상' 계산(게이트 제거). 사업유사도 관련 가중
#         (sector 0.25 + biz_tag 0.10 = 0.35)을 0.18+0.07+0.10 으로 재배분 → 총 0.35
#         유지, 합 1.0 보존. RAG 데이터 부재 시 sec_score 프록시로 차원 유지.
WEIGHTS = {
    "sector_sim":     0.18,    # ↓ 0.25  (WICS 소섹터 — RAG 독립화로 일부 이관)
    "biz_tag":        0.07,    # ↓ 0.10  (사업모델 태그)
    "rag_sim":        0.10,    # 신규    (사업보고서 임베딩+BM25+reranker hybrid)
    "mktcap_sim":     0.15,    # 시총 log
    "revenue_sim":    0.10,    # 매출 log
    "leverage_sim":   0.08,    # D/E
    "cycle_sim":      0.07,    # 산업 사이클
    "opm_sim":        0.10,    # 영업이익률 (멀티플 결정 변수)
    "growth_sim":     0.10,    # 매출 3년 CAGR
    "roic_sim":       0.05,    # 자본수익성
}
assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-6

# 최소 점수 — Phase 0 수정(2026-05-28):
#   이전 MIN_SCORE = 0.30 은 sector_sim 가중치(0.30)와 정확히 동일 → 동어반복.
#   같은 소섹터(sec_score=1.0) 후보가 다른 5개 차원 0점이어도 1.0×0.30 = 0.30 으로
#   자동 통과 → "같은 소섹터면 무조건 컷 통과", 변별 기능 상실.
#   0.40 으로 상향 → 같은 소섹터 + 다른 차원 일부 충족(시총 sim≥0.50, 매출 sim≥0.67 등)
#   필요 → MIN_SCORE 가 진짜 변별 임계로 작동.
MIN_SCORE = 0.40

# 최소 피어 수 — 중위값 통계 의미 확보 (이하면 backup 후보로 보충)
MIN_PEERS = 3

# ─────────────────────────────────────────────────────────────
# WICS 섹터 매핑 — peer_group_finder_v7 의 WICS_SECTOR_MAP 차용
# (실제 사용 시 동 파일에서 import 또는 dict 통째 복사)
# ─────────────────────────────────────────────────────────────
# 본 모듈은 외부에서 매핑을 받도록 설계 — 통합 시점에 peer_group_finder_v7 모듈
# 로부터 WICS_SECTOR_MAP, BIZ_TAG, _CROSS_SECTOR_WHITELIST, MONOPOLY_SET 를
# import 해서 주입.

def _load_wics_map():
    """peer_universe_data wrapper 에서 WICS 매핑 + BIZ_TAG + 화이트리스트 + 독점 set.

    내부적으로 peer_group_finder_v7.py (VAR 루트) 의 데이터를 import 시도.
    외부 파일 미존재 시 fallback (운영 종목 9개) 사용.
    """
    from .peer_universe_data import (
        WICS_SECTOR_MAP,
        BIZ_TAG,
        _CROSS_SECTOR_WHITELIST,
        MONOPOLY_SET,
    )
    return WICS_SECTOR_MAP, BIZ_TAG, _CROSS_SECTOR_WHITELIST, MONOPOLY_SET


# ─────────────────────────────────────────────────────────────
# 유사도 산출 (peer_group_finder_v7 차용 + 신규)
# ─────────────────────────────────────────────────────────────
def _mktcap_sim_log(cap_a: float, cap_b: float) -> float:
    """시가총액 로그 유사도 (peer_group_finder_v7 차용).

    log10 스케일 차이 → 0 (동일 규모) ~ 1 (규모 매우 다름) → 1.0 ~ 0.0 점수.
    """
    if cap_a <= 0 or cap_b <= 0:
        return 0.0
    log_diff = abs(math.log10(cap_a) - math.log10(cap_b))
    # 1 자리수 차이 (10배) → 점수 0.5, 2 자리 (100배) → 0.0
    return max(0.0, min(1.0, 1.0 - log_diff / 2.0))


def _revenue_sim_log(rev_a: float, rev_b: float) -> float:
    """매출 로그 유사도 (시총과 동일 로직)."""
    return _mktcap_sim_log(rev_a, rev_b)


def _leverage_sim(de_a: float, de_b: float) -> float:
    """D/E 유사도 — 자본구조 정합성.

    abs 차이 → 0 (동일) ~ 큰 차이 → 점수 감소.
    반환 범위: [0.0, 1.0] 보장 (음수 침범 방지)
    """
    diff = abs(float(de_a or 0) - float(de_b or 0))
    # D/E 1.0 차이까지는 점수, 그 이상이면 0
    score = 1.0 - diff
    return max(0.0, min(1.0, score))   # ★ [0, 1] clamp


def _bounded_diff_sim(a, b, full_score_pp: float, zero_score_pp: float) -> float:
    """절대 차이가 full_score_pp 이내 → 1.0, zero_score_pp 이상 → 0.0, 선형 보간.

    Phase 1 OPM·growth·ROIC 유사도 공통 산식.
    full_score_pp/zero_score_pp 단위: 분수(0.05 = 5%p).
    """
    if a is None or b is None:
        return 0.0
    diff = abs(float(a) - float(b))
    if diff <= full_score_pp:
        return 1.0
    if diff >= zero_score_pp:
        return 0.0
    return max(0.0, min(1.0,
        (zero_score_pp - diff) / (zero_score_pp - full_score_pp)))


def _opm_sim(opm_a, opm_b) -> float:
    """영업이익률 유사도 — 5%p 이내 1.0, 20%p 이상 0.0."""
    return _bounded_diff_sim(opm_a, opm_b, 0.05, 0.20)


def _growth_sim(g_a, g_b) -> float:
    """매출 3년 CAGR 유사도 — 5%p 이내 1.0, 30%p 이상 0.0 (성장률 변동성 큼 → 넓게)."""
    return _bounded_diff_sim(g_a, g_b, 0.05, 0.30)


def _roic_sim(r_a, r_b) -> float:
    """ROIC 유사도 — 3%p 이내 1.0, 15%p 이상 0.0."""
    return _bounded_diff_sim(r_a, r_b, 0.03, 0.15)


def _sector_score(target_sec: str, target_mid: str,
                  cand_sec: str,   cand_mid: str,
                  whitelist: set) -> float:
    """소섹터·중섹터 매칭 점수 (peer_group_finder_v7 로직 단순화).

    - 소섹터 일치       → 1.0
    - 화이트리스트 인접 → 0.5
    - 중섹터만 일치     → 0.3
    - 무관              → 0.0
    """
    if target_sec == cand_sec:
        return 1.0
    pair = frozenset({target_sec, cand_sec})
    if pair in whitelist:
        return 0.5
    if target_mid == cand_mid:
        return 0.3
    return 0.0


def _biz_tag_match(target_tag: Optional[str], cand_tag: Optional[str]) -> float:
    """BIZ_TAG 일치도.
    - 둘 다 없음: 1.0 (정보 부족, 패널티 안 줌)
    - 같음: 1.0
    - 다름: 0.4 (큰 패널티 — 같은 섹터 내 사업모델 차이)
    """
    if not target_tag or not cand_tag:
        return 1.0
    return 1.0 if target_tag == cand_tag else 0.4


# 사업 centroid 메모리 캐시 (세션 내 — target 1회 계산 후 모든 cand 비교에 재사용)
_BIZ_CENTROID_MEM: dict[str, "object"] = {}


def _get_business_centroid(ticker: str, year: int):
    """회사의 '사업의 내용' 청크 임베딩 centroid(정규화) — 메모리+디스크 캐시.

    사업보고서 단위(ticker+year)로 불변 → 한 번 계산하면 영구 재사용.
    Returns: 1024-d numpy 벡터 (정규화) 또는 None (청크/임베딩 부재).
    """
    import numpy as np
    key = f"{ticker}_{year}"
    if key in _BIZ_CENTROID_MEM:
        return _BIZ_CENTROID_MEM[key]

    cache_dir = _VAR_ROOT / "data" / "rag_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"centroid_{ticker}_{year}.npy"
    if cache_path.exists():
        try:
            v = np.load(cache_path)
            _BIZ_CENTROID_MEM[key] = v
            return v
        except Exception:
            pass   # 손상 → 재계산

    try:
        from embedding.retrieval import retrieve_business_segments
        from embedding.vector_store import get_embeddings_by_ids
    except ImportError:
        return None

    chunks = retrieve_business_segments(ticker, year, top_k=10)
    if not chunks:
        return None
    embs = get_embeddings_by_ids([c["id"] for c in chunks])
    if not embs:
        return None
    v = np.mean(np.asarray(embs, dtype=float), axis=0)
    v = v / (np.linalg.norm(v) + 1e-12)   # 정규화 centroid
    try:
        np.save(cache_path, v)
    except Exception:
        pass
    _BIZ_CENTROID_MEM[key] = v
    return v


def _rag_business_similarity(target_ticker: str, target_year: int,
                              cand_ticker: str, cand_year: int) -> Optional[float]:
    """사업보고서 RAG 임베딩 유사도 — 정규화 centroid 코사인 (캐시 활용).

    각 회사의 '사업의 내용' 청크 임베딩 평균(centroid)을 _get_business_centroid 가
    캐시 제공. target centroid 는 메모리 캐시로 모든 cand 비교에 1회만 계산.
    Returns: 0.0~1.0 사업 유사도 / 데이터 부족 시 None.
    """
    try:
        import numpy as np
        v1 = _get_business_centroid(target_ticker, target_year)
        v2 = _get_business_centroid(cand_ticker, cand_year)
        if v1 is None or v2 is None:
            return None
        # Phase 1: all-but-the-top whitening (anisotropy 보정)
        #   corpus(centroid_*.npy) ≥ 20개 있으면 학습된 μ + 상위 PC 제거 후 cosine.
        #   부족 시 graceful — 기존 raw cosine + rescale 사용.
        try:
            from .embedding_whitening import get_params, whiten_vector
            params = get_params()
        except Exception:
            params = None
        if params is not None:
            v1 = whiten_vector(v1, params)
            v2 = whiten_vector(v2, params)
            sim = float(np.dot(v1, v2))
            # Phase 5: whitening 후 cosine 은 0 근처로 압축해제돼 절대값이 작다.
            #   corpus 분포 percentile rank 로 [0,1] 정규화 → '동종=높음' 의미 복원,
            #   임계(0.55 등)와 스케일 호환. (이전엔 max(0,min(1,sim)) 라 동종도 0.04~0.18
            #   로 나와 신뢰도 RAG 감점이 항상 발동하던 버그.)
            from .embedding_whitening import normalize_whitened_cosine
            return normalize_whitened_cosine(sim, params)
        # graceful: whitening 미가용 → 기존 rescale 그대로
        sim = float(np.dot(v1, v2))
        return max(0.0, min(1.0, (sim - 0.7) / 0.3))
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────
# D-6: RAG hybrid — 사업 텍스트 캐시 + BM25/reranker 사전계산
# ─────────────────────────────────────────────────────────────
_BIZ_TEXT_MEM: dict[str, Optional[str]] = {}


def _get_business_text(ticker: str, year: int) -> Optional[str]:
    """회사 '사업의 내용' 청크 원문 결합 — BM25/reranker 입력 (메모리+디스크 캐시).

    centroid(임베딩)와 별개로 '원문 텍스트'가 필요한 sparse/cross-encoder 채널용.
    사업보고서 단위(ticker+year) 불변 → 1회 추출 후 영구 재사용.
    Returns: 결합 텍스트 또는 None (청크 부재).
    """
    key = f"{ticker}_{year}"
    if key in _BIZ_TEXT_MEM:
        return _BIZ_TEXT_MEM[key]
    cache_dir = _VAR_ROOT / "data" / "rag_cache"
    cache_path = cache_dir / f"biztext_{ticker}_{year}.txt"
    if cache_path.exists():
        try:
            txt = cache_path.read_text(encoding="utf-8")
            _BIZ_TEXT_MEM[key] = txt
            return txt
        except Exception:
            pass
    try:
        from embedding.retrieval import retrieve_business_segments
    except ImportError:
        return None
    chunks = retrieve_business_segments(ticker, year, top_k=10)
    if not chunks:
        return None
    txt = "\n".join(c.get("text", "") for c in chunks if c.get("text"))
    if not txt.strip():
        return None
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(txt, encoding="utf-8")
    except Exception:
        pass
    _BIZ_TEXT_MEM[key] = txt
    return txt


def _precompute_hybrid_channels(target_ticker: str, target_year: int,
                                 candidates: list[dict],
                                 verbose: bool = True) -> None:
    """D-6: 후보 집합 단위로 BM25 + reranker 사전계산 → 각 cand 에 첨부.

    · BM25 는 IDF 가 코퍼스(후보 전체) 통계에 의존 → 일괄 계산이 정석 (1:1 부적합).
    · reranker(cross-encoder)도 동일 모델 1회 로드로 배치 처리가 효율적.
    각 cand 에 cand["_bm25_sim"], cand["_rerank_sim"] (0~1) 첨부.
    의존성/텍스트 부재 시 graceful — 아무 키도 안 붙고 dense 단독으로 동작.
    """
    try:
        from .embedding_hybrid import compute_bm25_scores, rerank_scores
    except Exception:
        return
    target_text = _get_business_text(target_ticker, target_year)
    if not target_text:
        return
    texts: list[str] = []
    idxs: list[int] = []
    for i, c in enumerate(candidates):
        t = _get_business_text(c.get("ticker", ""), c.get("year", target_year))
        if t:
            texts.append(t)
            idxs.append(i)
    if not texts:
        return
    bm25 = compute_bm25_scores(target_text, texts)
    rerank = rerank_scores(target_text, texts)
    for j, i in enumerate(idxs):
        if bm25 is not None:
            candidates[i]["_bm25_sim"] = bm25[j]
        if rerank is not None:
            candidates[i]["_rerank_sim"] = rerank[j]
    if verbose:
        ch = []
        if bm25 is not None:
            ch.append("BM25")
        if rerank is not None:
            ch.append("rerank")
        if ch:
            print(f"  [D-6 hybrid] {'+'.join(ch)} 채널 {len(texts)}사 사전계산 "
                  f"(dense 와 결합)")


# ─────────────────────────────────────────────────────────────
# 후보 통합 점수
# ─────────────────────────────────────────────────────────────
# ═════════════════════════════════════════════════════════════
# Phase 1(2026-05-28) — 신뢰도 100점 감점 공식
#   "이 피어셋이 얼마나 신뢰할 만한가" 를 사용자에게 직접 노출.
#   학술적 정답 없음 — 휴리스틱 감점 폭 (백테스트 인프라 갖추기 전 잠정치).
#   등급: A(90+) / B(75+) / C(60+) / D(40+) / E(40-)
# ═════════════════════════════════════════════════════════════
# 마지막 select_peers_for_target 호출의 confidence 메타 — UI 노출용
_LAST_CONFIDENCE: Optional[dict] = None


def get_last_peer_confidence() -> Optional[dict]:
    """직전 select_peers_for_target 호출의 신뢰도 메타 (deductions 포함).

    Returns: {score, grade, deductions, n_peers, n_same_sector, ...} 또는 None.
    """
    return _LAST_CONFIDENCE


def compute_peer_confidence(peers: list[dict], target_data: dict) -> dict:
    """선정된 피어셋의 신뢰도 점수(0~100) 및 등급 산출.

    감점 항목:
      ① 유효 피어 < 3        → −25
      ② below_min_score 피어 → −10/사 (보충된 점수미달 피어)
      ③ PARTIAL 피어         → −10/사
      ④ 같은 소섹터 < 2개    → −15
      ⑤ 평균 RAG 사업유사도 < 0.55 → −15 (RAG 미가용 시 스킵)
      ⑥ 시총 차이 10배(log10≥1) 초과 피어 > 0 → −10
      ⑦ OPM 차이 10%p 초과 피어 > 0          → −10
      ⑧ 매출 차이 10배 초과 피어 > 0          → −5  (시총보다 약함)
    """
    score = 100
    deductions: list[dict] = []
    n = len(peers)
    if n == 0:
        return {"score": 0, "grade": "E", "deductions": [
            {"reason": "유효 피어 0개", "delta": -100}], "n_peers": 0}

    # ① 유효 피어 < 3
    if n < 3:
        score -= 25
        deductions.append({"reason": f"유효 피어 {n}개 (<3)", "delta": -25})

    # ② below_min_score 보충 피어
    n_below = sum(1 for p in peers if p.get("below_min_score"))
    if n_below:
        d = -10 * n_below
        score += d
        deductions.append({"reason": f"유사도 낮아 보충한 피어 {n_below}사", "delta": d})

    # ③ PARTIAL 피어
    n_partial = sum(1 for p in peers
                    if p.get("data_completeness") == "partial_krx_only")
    if n_partial:
        d = -10 * n_partial
        score += d
        deductions.append({"reason": f"재무데이터 일부 부족 {n_partial}사", "delta": d})

    # ④ 같은 소섹터 < 2
    target_sec = target_data.get("sector", "")
    n_same_sec = sum(1 for p in peers if p.get("sector") == target_sec)
    if n_same_sec < 2:
        score -= 15
        deductions.append({
            "reason": f"같은 업종(세부 분류) {n_same_sec}사 (2개 미만)", "delta": -15})

    # ⑤ 평균 RAG 사업유사도 < 0.55 (RAG 가용 시)
    rag_vals = [p["components"].get("rag_sim") for p in peers
                if isinstance(p.get("components"), dict)
                and p["components"].get("rag_sim") is not None]
    if rag_vals:
        avg_rag = sum(rag_vals) / len(rag_vals)
        if avg_rag < 0.55:
            score -= 15
            deductions.append({
                "reason": f"평균 사업 유사도 {avg_rag:.2f} (기준 0.55 미만)",
                "delta": -15})

    # ⑥ 시총 차이 10배 초과 (log10 ≥ 1) 피어 존재
    import math as _m
    t_cap = target_data.get("mktcap") or 0
    n_cap_far = 0
    if t_cap > 0:
        for p in peers:
            c = p.get("mktcap") or 0
            if c > 0 and abs(_m.log10(t_cap) - _m.log10(c)) > 1.0:
                n_cap_far += 1
    if n_cap_far:
        score -= 10
        deductions.append({
            "reason": f"시총 10배+ 차이 {n_cap_far}사", "delta": -10})

    # ⑦ OPM 차이 10%p 초과 피어 존재
    t_opm = None
    if target_data.get("revenue") and target_data.get("revenue") > 0:
        # target_data 에 ebit 또는 opm 가 있으면 사용. revenue 만 있고 opm 직접 없으면 스킵.
        if target_data.get("opm") is not None:
            t_opm = target_data["opm"]
        elif target_data.get("ebit") is not None:
            t_opm = target_data["ebit"] / target_data["revenue"]
    if t_opm is not None:
        n_opm_far = 0
        for p in peers:
            p_opm = None
            if p.get("opm") is not None:
                p_opm = p["opm"]
            elif p.get("ebit") and p.get("revenue") and p["revenue"] > 0:
                p_opm = p["ebit"] / p["revenue"]
            if p_opm is not None and abs(t_opm - p_opm) > 0.10:
                n_opm_far += 1
        if n_opm_far:
            score -= 10
            deductions.append({
                "reason": f"영업이익률 10%p+ 차이 {n_opm_far}사", "delta": -10})

    # ⑧ 매출 차이 10배 초과
    t_rev = target_data.get("revenue") or 0
    n_rev_far = 0
    if t_rev > 0:
        for p in peers:
            c = p.get("revenue") or 0
            if c > 0 and abs(_m.log10(t_rev) - _m.log10(c)) > 1.0:
                n_rev_far += 1
    if n_rev_far:
        score -= 5
        deductions.append({
            "reason": f"매출 10배+ 차이 {n_rev_far}사", "delta": -5})

    # 클램프 [0, 100]
    score = max(0, min(100, score))
    if   score >= 90: grade = "A"
    elif score >= 75: grade = "B"
    elif score >= 60: grade = "C"
    elif score >= 40: grade = "D"
    else:             grade = "E"

    return {
        "score": score, "grade": grade,
        "deductions": deductions, "n_peers": n,
        "n_same_sector": n_same_sec, "n_partial": n_partial,
        "n_below_min": n_below,
    }


def _xbrl_years_factor(years_available: int) -> float:
    """XBRL 가용 연수 → 점수 가중 계수.

    - 5년: 1.00 (full quality)
    - 4년: 0.92
    - 3년: 0.80 (최소 기준 통과)
    - 2년 이하: 호출되지 않음 (_is_eligible 에서 제외)
    """
    if years_available >= 5:
        return 1.0
    if years_available == 4:
        return 0.92
    if years_available == 3:
        return 0.80
    return 0.0   # 안전망 — 실제로는 _is_eligible 에서 차단됨


def compute_similarity(target: dict, cand: dict,
                       whitelist: set, biz_tag_map: dict,
                       use_rag: bool = True) -> dict:
    """타깃 vs 후보 회사 종합 유사도 산출.

    Args:
        target/cand: {
            "ticker", "name", "sector", "mid",
            "mktcap", "revenue", "de_ratio", "cycle_z",
            "year"  # 최신 회계연도
        }
        whitelist:   _CROSS_SECTOR_WHITELIST
        biz_tag_map: BIZ_TAG dict
        use_rag:     사업보고서 RAG 유사도 사용 여부 (느림)

    Returns:
        {
            "total_score": ...,
            "components": {
                "sector_sim":   ...,
                "biz_tag":      ...,
                "mktcap_sim":   ...,
                "revenue_sim":  ...,
                "leverage_sim": ...,
                "cycle_sim":    ...,
                "rag_sim":      ...,  # use_rag 시
            },
            "reasons": [...]  # 사람이 읽기 좋은 근거
        }
    """
    # 1) WICS 섹터
    sec_score = _sector_score(
        target.get("sector", ""), target.get("mid", ""),
        cand.get("sector", ""),   cand.get("mid", ""),
        whitelist,
    )

    # 2) BIZ_TAG
    biz_score = _biz_tag_match(
        biz_tag_map.get(target["ticker"]),
        biz_tag_map.get(cand["ticker"]),
    )

    # 3) 시총 (None 안전 — PARTIAL 모드 후보 대비)
    cap_score = _mktcap_sim_log(
        target.get("mktcap") or 0, cand.get("mktcap") or 0)

    # 4) 매출 (PARTIAL 모드면 None → 점수 0 으로 자동 처리)
    rev_score = _revenue_sim_log(
        target.get("revenue") or 0, cand.get("revenue") or 0)

    # 5) D/E — None(데이터 부재) 시 0점(중립). 0(무차입)은 정상 비교(무차입끼리 유사).
    #   Phase 6: enrich 가 부재(ibd 추출실패)는 None, 무차입(ibd=0)은 0.0 으로 구분 전달.
    t_de = target.get("de_ratio")
    c_de = cand.get("de_ratio")
    if t_de is None or c_de is None:
        lev_score = 0.0   # 데이터 부재 → 0 (가중치 효과 제거)
    else:
        lev_score = _leverage_sim(t_de, c_de)

    # 6) 사이클 z-score
    t_cz = target.get("cycle_z")
    c_cz = cand.get("cycle_z")
    if t_cz is None or c_cz is None:
        cycle_score = 0.0   # 데이터 없으면 0
    else:
        z_diff = abs(t_cz - c_cz)
        cycle_score = max(0.0, 1.0 - z_diff / 2.0)

    # 7) Phase 1 신규 — OPM·growth·ROIC (멀티플 결정 변수)
    #    데이터 None 이면 유사도 0 (가중치 효과 자동 제거)
    opm_score    = _opm_sim(target.get("opm"),    cand.get("opm"))
    growth_score = _growth_sim(target.get("growth_3yr"), cand.get("growth_3yr"))
    roic_score   = _roic_sim(target.get("roic"),  cand.get("roic"))

    # 가중 합산
    # 7) RAG 사업유사도 (Phase 5: 독립 차원, '항상' 계산 — sec_score<0.5 게이트 제거).
    #   dense(whitened centroid cosine) + BM25 + reranker 를 combine_hybrid 로 결합.
    #   데이터 부재(centroid/임베딩 없음) 시 sec_score 프록시로 차원을 유지해 가중치
    #   합 1.0 을 보존한다. → 동종·인접 피어에도 사업모델 차이가 반영(H7 해소),
    #   sector 가중치 재사용으로 합이 깨지던 문제도 제거(H9 해소).
    rag_score = sec_score   # 기본 프록시 (WICS 섹터 일치도)
    rag_dense = rag_bm25 = rag_rerank = None
    if use_rag:
        rag_dense  = _rag_business_similarity(
            target["ticker"], target.get("year", 2025),
            cand["ticker"],   cand.get("year", 2025))
        rag_bm25   = cand.get("_bm25_sim")
        rag_rerank = cand.get("_rerank_sim")
        try:
            from .embedding_hybrid import combine_hybrid
            _h = combine_hybrid(rag_dense, rag_bm25, rag_rerank)
        except Exception:
            _h = rag_dense
        if _h is not None:
            rag_score = _h

    total = (
        WEIGHTS["sector_sim"]   * sec_score
        + WEIGHTS["biz_tag"]    * biz_score
        + WEIGHTS["rag_sim"]    * rag_score
        + WEIGHTS["mktcap_sim"] * cap_score
        + WEIGHTS["revenue_sim"]* rev_score
        + WEIGHTS["leverage_sim"]* lev_score
        + WEIGHTS["cycle_sim"]  * cycle_score
        + WEIGHTS["opm_sim"]    * opm_score
        + WEIGHTS["growth_sim"] * growth_score
        + WEIGHTS["roic_sim"]   * roic_score
    )

    # ★ Phase 0 수정(2026-05-28) — XBRL 가용 연수 factor 를 score 에서 분리.
    #   이전: total *= _xbrl_years_factor(xbrl_yrs)
    #     · 같은 소섹터·동종 사업인데 데이터 가용성만 차이 나는 회사가 컷에서 갈리는 버그
    #     · 예: 같은 소섹터(sec=1.0, 다른차원 0) × 5년(1.00)=0.30 통과 / × 3년(0.80)=0.24 탈락
    #     · 사업 유사성과 무관한 기준이 피어 자격을 결정 → 비논리적
    #   변경: data_quality_factor 메타 필드로 노출 — 신뢰도 표시·UI 에만 사용, 컷 영향 X.
    #   PARTIAL(KRX 시총만) 은 비교 데이터 자체가 부분이라 점수 할인 ×0.7 유지.
    xbrl_yrs = cand.get("xbrl_years_available", 0)
    if cand.get("data_completeness") == "partial_krx_only":
        total *= 0.7
        data_quality_factor = 0.7
    elif xbrl_yrs > 0 and xbrl_yrs < 999:
        data_quality_factor = _xbrl_years_factor(xbrl_yrs)
    else:
        data_quality_factor = 1.0

    components = {
        "sector_sim":   sec_score,
        "biz_tag":      biz_score,
        "rag_sim":      rag_score,        # Phase 5: 독립 차원 (hybrid 또는 sec 프록시)
        "mktcap_sim":   cap_score,
        "revenue_sim":  rev_score,
        "leverage_sim": lev_score,
        "cycle_sim":    cycle_score,
        "opm_sim":      opm_score,        # Phase 1
        "growth_sim":   growth_score,     # Phase 1
        "roic_sim":     roic_score,       # Phase 1
    }
    # Phase 5: hybrid 채널 분해값 노출 (디버깅·신뢰도용 — None 이면 생략)
    if rag_dense is not None:
        components["rag_dense"] = rag_dense
    if rag_bm25 is not None:
        components["rag_bm25"] = rag_bm25
    if rag_rerank is not None:
        components["rag_rerank"] = rag_rerank

    reasons = _build_reasons(target, cand, components)
    return {
        "total_score": total,
        "components":  components,
        "reasons":     reasons,
        "data_quality_factor": data_quality_factor,   # P0: 신뢰도 표시용 (컷 영향 X)
    }


def _build_reasons(target: dict, cand: dict, comp: dict) -> list[str]:
    reasons = []
    if comp["sector_sim"] >= 1.0:
        reasons.append(f"동일 소섹터 ({cand.get('sector','')})")
    elif comp["sector_sim"] >= 0.5:
        reasons.append(f"인접 섹터 (화이트리스트)")
    if comp.get("rag_sim") and comp["rag_sim"] >= 0.7:
        reasons.append(f"사업모델 유사 (RAG {comp['rag_sim']:.2f})")
    if comp["mktcap_sim"] >= 0.7:
        reasons.append(f"시총 유사 ({cand.get('mktcap',0)/1e12:.1f}조)")
    if comp["revenue_sim"] >= 0.7:
        reasons.append(f"매출 유사 ({cand.get('revenue',0)/1e12:.1f}조)")
    if comp["leverage_sim"] >= 0.7:
        reasons.append(f"자본구조 유사 (D/E {cand.get('de_ratio',0):.2f})")
    if comp["cycle_sim"] >= 0.7:
        reasons.append(f"사이클 국면 유사")
    return reasons


# ─────────────────────────────────────────────────────────────
# 필터
# ─────────────────────────────────────────────────────────────
def _is_eligible(cand: dict) -> tuple[bool, Optional[str]]:
    """피어 자격 검증. (True, None) 또는 (False, 사유).

    PARTIAL 모드 (data_completeness='partial_krx_only') 는 XBRL 부재로
    NOPAT/listing_years 검증 우회. 점수 단계에서 별도 처리.
    """
    is_partial = cand.get("data_completeness") == "partial_krx_only"

    # 1) 상장 기간 (β 회귀) — PARTIAL 모드도 검증 (KRX 캐시에서 산출 가능)
    listing_years = cand.get("listing_years", 999)
    if listing_years < 2:
        return False, f"상장 {listing_years}년 - β 회귀 불가"

    # PARTIAL 모드는 나머지 XBRL 기반 검증 우회 (data_completeness 표시로 사용자에게 알림)
    if is_partial:
        return True, None

    # 2) NOPAT 만성 적자 (5년 중위값 <= 0) — 정상 모드만
    nopat_5yr_med = cand.get("nopat_5yr_median")
    if nopat_5yr_med is None:
        return False, "NOPAT 데이터 부재"
    if nopat_5yr_med <= 0:
        return False, "NOPAT 5년 중위값 <= 0 - 가치평가 피어 부적합"

    # 3) XBRL 데이터 충분성 (3년 최소)
    if cand.get("xbrl_years_available", 0) < 3:
        return False, "XBRL 3년 미만"

    return True, None


# ─────────────────────────────────────────────────────────────
# 메인 진입점
# ─────────────────────────────────────────────────────────────
def select_peers(target_ticker: str,
                 target_data: dict,
                 universe: list[dict],
                 top_n: int = 3,
                 use_rag: bool = True,
                 verbose: bool = True) -> list[dict]:
    """타깃 ticker → 피어 Top N 자동 선정.

    Args:
        target_ticker:  타깃 종목코드
        target_data:    타깃 회사 정보 dict (sector, mid, mktcap, revenue, de_ratio, cycle_z, year)
        universe:       후보 회사 리스트 (각 dict 가 target_data 와 같은 필드)
        top_n:          피어 개수 (기본 3)
        use_rag:        RAG 임베딩 유사도 사용 (느림 — 첫 호출 ~수초)
        verbose:        진행 상황 출력

    Returns:
        피어 dict 리스트 — [{ticker, name, total_score, components, reasons}, ...]
    """
    wics_map, biz_tag, whitelist, monopoly = _load_wics_map()

    is_monopoly = target_ticker in monopoly
    if verbose:
        print(f"\n[피어 산정] 타깃 {target_data.get('name','?')} ({target_ticker})")
        print(f"  섹터: {target_data.get('sector','?')} / {target_data.get('mid','?')}")
        print(f"  시총: {target_data.get('mktcap',0)/1e12:.2f}조  "
              f"매출: {target_data.get('revenue',0)/1e12:.2f}조  "
              f"D/E: {target_data.get('de_ratio',0):.2f}")
        if is_monopoly:
            print("  ⚠ 독점/초대형 — 동일 섹터 피어 부족 → 화이트리스트 확장")
        print()

    # D-6: RAG hybrid 사전계산 — 후보 집합 단위 BM25 + reranker (있으면 각 cand 에 첨부).
    #   compute_similarity 의 RAG 보강(sec_score<0.5)에서 dense 와 결합. graceful.
    if use_rag:
        try:
            _precompute_hybrid_channels(
                target_ticker, target_data.get("year", 2025), universe, verbose=verbose)
        except Exception as _e:
            if verbose:
                print(f"  [D-6 hybrid] 사전계산 스킵: {str(_e)[:80]}")

    candidates = []
    backup = []   # MIN_SCORE 미달이지만 eligible — 최소 피어수 보충용
    for cand in universe:
        if cand["ticker"] == target_ticker:
            continue
        eligible, reason = _is_eligible(cand)
        if not eligible:
            if verbose and cand.get("ticker") in target_data.get("known_peers", []):
                print(f"  ✗ {cand.get('name','?')} ({cand['ticker']}) 제외 — {reason}")
            continue

        sim = compute_similarity(target_data, cand, whitelist, biz_tag, use_rag=use_rag)
        entry = {
            **cand,
            "total_score":         sim["total_score"],
            "components":          sim["components"],
            "reasons":             sim["reasons"],
            "data_quality_factor": sim.get("data_quality_factor", 1.0),
        }
        if sim["total_score"] < MIN_SCORE and not is_monopoly:
            backup.append(entry)   # 점수 미달 — 보충 후보로만 보관
            continue
        candidates.append(entry)

    candidates.sort(key=lambda x: -x["total_score"])
    peers = candidates[:top_n]

    # ★ 최소 피어수 보장 — MIN_SCORE 통과 후보가 부족하면 backup(점수순)으로 보충
    #   중위값 통계가 1~2사로 산출되는 것을 방지 (피어 1사면 중위값 = 그 회사값)
    if len(peers) < MIN_PEERS and backup:
        backup.sort(key=lambda x: -x["total_score"])
        for b in backup:
            if len(peers) >= MIN_PEERS:
                break
            b["below_min_score"] = True   # 신뢰도 낮음 — 점수 미달 보충 명시
            peers.append(b)
        if verbose:
            n_filled = sum(1 for p in peers if p.get("below_min_score"))
            if n_filled:
                print(f"  ⚠ MIN_SCORE({MIN_SCORE}) 통과 피어 부족 → "
                      f"점수 미달 {n_filled}사 보충 (최소 {MIN_PEERS}사 확보, 신뢰도 낮음)")

    if verbose:
        partial_count = sum(1 for p in peers if p.get("data_completeness") == "partial_krx_only")
        print(f"  ┌─ 피어 Top {top_n} ─────────────────────────────────")
        for i, p in enumerate(peers, 1):
            tag = " [PARTIAL]" if p.get("data_completeness") == "partial_krx_only" else ""
            if p.get("below_min_score"):
                tag += " [점수미달보충]"
            print(f"  │ {i}. [{p['ticker']}] {p['name']:<12s}  "
                  f"점수 {p['total_score']:.3f}{tag}")
            print(f"  │      {' / '.join(p['reasons'][:3]) if p['reasons'] else '근거 부족'}")
        print(f"  └────────────────────────────────────────────────")
        if partial_count > 0:
            print(f"  ⚠ {partial_count}사 PARTIAL 모드 (XBRL 부재, KRX 시총만 — 신뢰도 낮음)")
        print()

    return peers


# ═════════════════════════════════════════════════════════════
# Universe 자동 구축 — peer_group_finder_v7 의 WICS_SECTOR_MAP 활용
# ═════════════════════════════════════════════════════════════
def build_universe_from_wics(target_ticker: str,
                              include_adjacent: bool = True,
                              max_candidates: int = 30) -> list[dict]:
    """타깃과 같은 mid 섹터 + 인접(화이트리스트) 회사를 후보 풀로 구성.

    Args:
        target_ticker:    타깃 종목코드 (필수)
        include_adjacent: 화이트리스트 인접 섹터 포함 여부
        max_candidates:   최대 후보 수 (시총 유사 Top N 으로 1차 필터)

    Returns:
        [{"ticker", "name", "sector", "mid", ...}, ...]
        시총·재무 정보는 후속 단계에서 추가 (현재는 sector 매핑만).
    """
    wics_map, biz_tag, whitelist, _ = _load_wics_map()
    target_info = wics_map.get(target_ticker)
    if not target_info:
        # ★ 하드코드 WICS 맵에 없으면 krx_desc 기반 자동 매핑으로 fallback.
        #   (과거: 즉시 return [] → 맵 미등록 종목 전부 피어 0개. 중소형 대부분 해당.)
        #   이렇게 해야 아래 krx_industry_peers(동종 보강) 로직까지 도달한다.
        target_info = resolve_wics_from_krx(target_ticker)
    if not target_info:
        return []
    target_sec = target_info["sector"]
    target_mid = target_info["mid"]

    # Phase 1 Day1-패치: WICS map(팀원 peer_group_finder_v7)의 name 일부 오류 발견
    #   예: 066970 이 'LG이노텍'으로 잘못 등록 → 실제는 엘앤에프(이차전지)
    #   해법: name 만 krx_desc.csv(KRX 공식) 권위소스로 덮어쓰기. sector·mid 는 그대로.
    krx_name_map = _get_krx_name_map()
    def _wics_entry(t, info, group):
        canonical_name = krx_name_map.get(t)
        out = {"ticker": t, **info, "group": group}
        if canonical_name:           # krx_desc 에 있으면 권위소스 우선
            out["name"] = canonical_name
        return out

    # 1) 같은 소섹터 — 1차 후보 (Phase 1: group 태깅)
    same_sec = [
        _wics_entry(t, info, "same_sec")
        for t, info in wics_map.items()
        if t != target_ticker and info["sector"] == target_sec
    ]
    # 2) 같은 mid 섹터 (소섹터 다름) — 2차 후보
    same_mid = [
        _wics_entry(t, info, "same_mid")
        for t, info in wics_map.items()
        if t != target_ticker
           and info["sector"] != target_sec
           and info["mid"] == target_mid
    ]
    # 3) 화이트리스트 인접 (다른 mid 도 가능) — 3차 후보
    adjacent = []
    if include_adjacent:
        for t, info in wics_map.items():
            if t == target_ticker:
                continue
            pair = frozenset({target_sec, info["sector"]})
            if pair in whitelist:
                adjacent.append(_wics_entry(t, info, "adjacent"))

    # 4) KRX 같은 업종 (krx_desc.csv) — WICS 맵 누락 동종 보강
    #    WICS_SECTOR_MAP 이 소섹터당 소수만 등록되어(예: '전자장비와기기' 4사)
    #    같은 mid 의 이질 소섹터(반도체 등)로 후보가 채워지는 문제 해결.
    #    같은 KRX 표준산업분류 = 사실상 동종 → 타깃 소섹터로 태깅해 1순위 후보화.
    krx_industry_peers = []
    krx_ind_map = _get_krx_industry_map()
    krx_name_map = _get_krx_name_map()
    target_krx_ind = krx_ind_map.get(target_ticker)
    if target_krx_ind:
        for t, ind in krx_ind_map.items():
            if t == target_ticker or ind != target_krx_ind:
                continue
            krx_industry_peers.append({
                "ticker": t,
                "name":   krx_name_map.get(t, t),
                "sector": target_sec,   # 같은 KRX 업종 → 동종 취급 (WICS 소섹터 차용)
                "mid":    target_mid,
                "source": "krx_industry",
                "group":  "krx_same_industry",   # Phase 1: same_sec 와 함께 1순위
            })

    # 우선순위: WICS 동종 + KRX 동종 > 같은 mid(이질 소섹터) > 화이트리스트 인접
    candidates = same_sec + krx_industry_peers + same_mid + adjacent
    # 중복 제거 (앞선 항목 우선 — 동종이 mid/adjacent 보다 먼저 보존됨)
    seen = set()
    unique = []
    for c in candidates:
        if c["ticker"] not in seen:
            seen.add(c["ticker"])
            unique.append(c)

    # 동종(same_sec+KRX)이 많을 수 있으므로 컷을 넉넉히 — 시총 Top N 필터는 후속 단계.
    return unique[:max(max_candidates, 80)]


# ═════════════════════════════════════════════════════════════
# KRX 캐시에서 시총·상장주식수 (외부 의존 0)
# ═════════════════════════════════════════════════════════════
_KRX_CACHE_DIR = _VAR_ROOT / "peer_beta" / "data" / "raw"

# KRX 응답 필드 (peer_beta/krx_client.py 동일):
#   MKTCAP, LIST_SHRS, TDD_CLSPRC, ISU_SRT_CD, ISU_CD, LIST_DD


# ─────────────────────────────────────────────────────────────
# KRX 표준산업분류 → WICS 자동 매핑 (krx_desc.csv 있으면 활용)
# ─────────────────────────────────────────────────────────────
_KRX_DESC_CSV_CANDIDATES = [
    _VAR_ROOT / "krx_desc.csv",
    _VAR_ROOT / "data" / "krx_desc.csv",
]


def _load_krx_industry_map() -> dict[str, str]:
    """krx_desc.csv (있으면) 파싱 → {ticker: KRX 업종명}.

    팀원 fullkrx_A 가 사용하는 KRX 표준산업분류 데이터.
    파일 미존재 시 빈 dict 반환 (graceful — 시스템 정지 안 됨).

    파일 컬럼 가정: Code (6자리), Name, Industry
    """
    for csv_path in _KRX_DESC_CSV_CANDIDATES:
        if csv_path.exists():
            try:
                import pandas as pd
                df = pd.read_csv(csv_path, encoding="utf-8-sig")
                if "Code" in df.columns and "Industry" in df.columns:
                    df["Code"] = df["Code"].astype(str).str.zfill(6)
                    return {
                        str(r["Code"]): str(r["Industry"])
                        for _, r in df.iterrows()
                        if str(r["Industry"]) not in ("", "nan", "None")
                    }
            except Exception as e:
                print(f"  [WARN] krx_desc.csv 파싱 실패: {e}")
    return {}


# 단일 인스턴스 (한 번만 로드)
_KRX_INDUSTRY_MAP_CACHE: dict[str, str] | None = None


def _get_krx_industry_map() -> dict[str, str]:
    """lazy load — 첫 호출 시만 파일 읽음."""
    global _KRX_INDUSTRY_MAP_CACHE
    if _KRX_INDUSTRY_MAP_CACHE is None:
        _KRX_INDUSTRY_MAP_CACHE = _load_krx_industry_map()
    return _KRX_INDUSTRY_MAP_CACHE


def _load_krx_name_map() -> dict[str, str]:
    """krx_desc.csv 의 (ticker → Name) 매핑."""
    for csv_path in _KRX_DESC_CSV_CANDIDATES:
        if csv_path.exists():
            try:
                import pandas as pd
                df = pd.read_csv(csv_path, encoding="utf-8-sig")
                if "Code" in df.columns and "Name" in df.columns:
                    df["Code"] = df["Code"].astype(str).str.zfill(6)
                    return {
                        str(r["Code"]): str(r["Name"])
                        for _, r in df.iterrows()
                        if str(r["Name"]) not in ("", "nan", "None")
                    }
            except Exception:
                continue
    return {}


_KRX_NAME_MAP_CACHE: dict[str, str] | None = None


def _get_krx_name_map() -> dict[str, str]:
    global _KRX_NAME_MAP_CACHE
    if _KRX_NAME_MAP_CACHE is None:
        _KRX_NAME_MAP_CACHE = _load_krx_name_map()
    return _KRX_NAME_MAP_CACHE


# ─────────────────────────────────────────────────────────────
# 사업 다각화(지주·복합기업) 판정 — krx_desc.csv 의 Products 열 활용
# ─────────────────────────────────────────────────────────────
# 문제: 두산(000150) 같은 복합기업이 krx_desc 상 '전자부품 제조업'으로 분류되고
#       규모(시총·매출)가 유사해 삼성전기 피어로 혼입됨.
#       BGE-M3 사업유사도(centroid cosine)는 변별력이 낮아(두산 0.870 > 리노공업 0.850)
#       업종·규모 점수를 못 이김 → 의미검색으로는 거를 수 없음.
# 해법: Products(주요 제품/서비스) 텍스트에서 '서로 다른 산업 도메인' 개수를 세어
#       일정 수(>=3) 이상이면 복합기업으로 보고 피어에서 제외.
#       단일 업종 기업(대덕전자=PCB 5종, 삼성전기=전자부품)은 도메인 1개로 안전.

def _load_krx_products_map() -> dict[str, str]:
    """krx_desc.csv 의 (ticker → Products) 매핑."""
    for csv_path in _KRX_DESC_CSV_CANDIDATES:
        if csv_path.exists():
            try:
                import pandas as pd
                df = pd.read_csv(csv_path, encoding="utf-8-sig")
                if "Code" in df.columns and "Products" in df.columns:
                    df["Code"] = df["Code"].astype(str).str.zfill(6)
                    return {
                        str(r["Code"]): str(r["Products"])
                        for _, r in df.iterrows()
                        if str(r["Products"]) not in ("", "nan", "None")
                    }
            except Exception:
                continue
    return {}


_KRX_PRODUCTS_MAP_CACHE: dict[str, str] | None = None


def _get_krx_products_map() -> dict[str, str]:
    global _KRX_PRODUCTS_MAP_CACHE
    if _KRX_PRODUCTS_MAP_CACHE is None:
        _KRX_PRODUCTS_MAP_CACHE = _load_krx_products_map()
    return _KRX_PRODUCTS_MAP_CACHE


# 산업 도메인 키워드 그룹 — Products 텍스트에 등장하는 '이종 산업'을 도메인 단위로 집계.
# 같은 도메인 내 다양한 제품(예: PCB 5종)은 1개 도메인으로 묶여 단일사업으로 인정됨.
_BUSINESS_DOMAINS: dict[str, tuple[str, ...]] = {
    "전자/부품":   ("적층판", "기판", "인쇄회로", "회로기판", "소자", "mlcc", "콘덴서",
                  "카메라모듈", "모듈", "반도체", "소켓", "리노핀", "전자부품", "디스플레이",
                  "led", "센서", "수동소자", "패키지"),
    "기계/중공업": ("유압", "지게차", "건설기계", "공작기계", "엔진", "터빈", "발전설비",
                  "플랜트", "중장비", "산업차량", "방산", "기계"),
    "IT/SW/서비스": ("it 시스템", "소프트웨어", "솔루션", "시스템 개발", "시스템개발",
                  "운영 서비스", "정보기술", "플랫폼", "클라우드", "si "),
    "에너지/전지": ("연료전지", "2차전지", "이차전지", "배터리", "태양광", "발전", "수소",
                  "에너지저장", "ess"),
    "화학/소재":   ("석유화학", "합성수지", "화학", "비료", "도료", "필름소재", "첨가제",
                  "케미칼"),
    "건설/건자재": ("건설", "토목", "시멘트", "콘크리트", "건자재", "주택"),
    "유통/소비재": ("유통", "식품", "화장품", "의류", "패션", "리테일", "음료", "급식"),
    "바이오/제약": ("제약", "바이오", "의약품", "백신", "진단"),
    "금융":        ("금융", "보험", "증권", "캐피탈", "리스"),
}


def _count_business_domains(products: str) -> tuple[int, list[str]]:
    """Products 텍스트에서 서로 다른 산업 도메인 개수 집계.

    Returns: (도메인 개수, 매칭된 도메인명 리스트)

    예)
      두산   "동박적층판…, 유압기기…, 지게차…, IT 시스템…, 연료전지…"
             → {전자/부품, 기계/중공업, IT/SW/서비스, 에너지/전지} = 4
      대덕전자 "인쇄회로기판,…기판,…기판 제조" → {전자/부품} = 1
      삼성전기 "수동소자, 모듈, 반도체패키지 기판" → {전자/부품} = 1
    """
    if not products:
        return 0, []
    low = products.lower()
    hit = []
    for domain, kws in _BUSINESS_DOMAINS.items():
        if any(kw in low for kw in kws):
            hit.append(domain)
    return len(hit), hit


# 복합기업 판정 임계 — 서로 다른 산업 도메인이 이 수 이상이면 피어 제외.
# 2 도메인까지는 정상적 인접 다각화(예: 전자+IT)로 보고 허용, 3 이상이면 지주·복합기업.
DIVERSIFICATION_MAX_DOMAINS = 3


def _is_holding_company(name: str, products: str, industry: str = "") -> bool:
    """순수 투자지주회사(operating 사업 없음) 판정 — 키워드 신호.

    두산(복합 사업회사)은 사업 도메인이 많아 _count_business_domains 로 잡히지만,
    SK스퀘어·LG·SK 같은 '순수 지주회사'는 제품이 '지주회사'(=자회사 지분 보유) 하나뿐이라
    도메인 수가 0~1 → 다각화 페널티로 안 잡힘. 별도 신호로 판정해 피어에서 제외한다.
    (지주회사는 자체 영업이 없어 매출·OPM·멀티플이 사업회사와 본질적으로 다름.)

    신호 (KRX 분류 기준):
      - Products 가 '지주회사' 를 핵심 기재 (예: SK스퀘어=Products '지주회사')
      - 상호에 '지주' 포함 또는 '홀딩스' 로 끝남
      - Industry '기타 금융업' + Products 에 '지주' (지주회사가 편입되는 업종)

    한계: 이름·제품에 '지주' 키워드가 없는 holding(예: 일부 위장 holding)은 못 잡음.
    재무구조 신호(_is_holding_by_financials)와 OR 결합해서 사용 — D-8 보강.
    """
    nm = (name or "").strip()
    pr = (products or "").strip()
    ind = (industry or "").strip()
    if "지주회사" in pr:
        return True
    if nm.endswith("홀딩스") or "지주" in nm:
        return True
    if ind == "기타 금융업" and "지주" in pr:
        return True
    return False


# ─────────────────────────────────────────────────────────────
# D-8: 재무구조 기반 holding/operating peer 부적합 판정
# ─────────────────────────────────────────────────────────────
#   키워드(_is_holding_company)에 잡히지 않는 위장 holding/복합기업 보강.
#   세 신호 OR 결합 — 하나라도 해당하면 피어 제외.
#
#   ① 지분법투자(InvestmentAccountedForUsingEquityMethod) / 자본총계
#      · 40%+ → '지주의심', 70%+ → '순수지주'
#      예: GS 9.0조/19.2조 = 47% → 트리거 ✓
#
#   ② |지분법손익| / |영업이익| > 50%
#      자체 영업이 작고 자회사 손익이 영업이익 절반 이상 → 사실상 holding 성격.
#      ifrs-full:ShareOfProfitLossOfAssociatesAndJointVenturesAccountedForUsingEquityMethod
#      예: 영업이익 100억 + 지분법손익 80억 → 80% → operating peer 부적합
#
#   ③ 세그먼트 매출: 1위 < 60% AND 부문 ≥ 3 → 복합기업 (사업 분산)
#      OperatingSegments 차원 매출 매트릭스 → HHI ≈ Σ share_i²
#      예: 두산 1위 44.9%, 5부문, HHI 0.385 → 복합 ✓
#         CJ제일제당 1위 46.5%, 3부문(식품/물류/바이오) → 복합 ✓
#
#   데이터 부재(None) 시 통과 — graceful (XBRL 미수집/오래된 캐시 보호).
INV_ASSOC_RATIO_HOLDING_SUSPECTED = 0.40
INV_ASSOC_RATIO_HOLDING_PURE      = 0.70
EQUITY_METHOD_INCOME_RATIO_LIMIT  = 0.50    # |지분법손익|/|영업이익|
SEGMENT_TOP_SHARE_DIVERSIFIED     = 0.60    # 1위 < 60% AND
SEGMENT_MIN_COUNT_DIVERSIFIED     = 3       # ≥ 3 부문
# Phase 6: 세그먼트 HHI 임계 — HHI=Σshare² 가 이 값 이하면 '분산'(복합기업).
#   1위 60% 단일집중이면 HHI ≥ 0.36 → 0.36 이하는 부문 매출이 고르게 퍼진 상태.
#   기존엔 HHI 를 텍스트 표기로만 썼으나, 1위비중·부문수를 한 지표로 통합하므로
#   판정에도 OR 로 반영(예: 1위 62%·3부문이라 top_share 컷은 비껴가도 HHI 로 포착).
SEGMENT_HHI_DIVERSIFIED           = 0.36


def _is_holding_by_financials(financials_signals: dict) -> tuple[bool, Optional[str]]:
    """재무구조 기반 holding/복합기업 판정 — 세 신호 OR.

    Args:
        financials_signals: candidate dict (또는 동등 모양).
            인식 키:
              · inv_assoc_ratio          — 신호 ① 지분법투자/자본총계
              · em_income_ratio          — 신호 ② |지분법손익|/|영업이익|
              · segment_top_share        — 신호 ③ 1위 부문 매출 비중
              · segment_n_segments       — 신호 ③ 부문 수
            None / 누락 키는 통과 (graceful).
    Returns:
        (부적합 여부, 사람이 읽는 사유 또는 None)
    """
    if not isinstance(financials_signals, dict):
        return False, None

    def _to_float(v):
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    # 신호 ① 지분법투자/자본
    ratio = _to_float(financials_signals.get("inv_assoc_ratio"))
    if ratio is not None:
        if ratio >= INV_ASSOC_RATIO_HOLDING_PURE:
            return True, f"순수지주(지분법투자/자본 {ratio*100:.0f}%)"
        if ratio >= INV_ASSOC_RATIO_HOLDING_SUSPECTED:
            return True, f"지주의심(지분법투자/자본 {ratio*100:.0f}%)"

    # 신호 ② |지분법손익| / |영업이익|
    em_ratio = _to_float(financials_signals.get("em_income_ratio"))
    if em_ratio is not None and em_ratio > EQUITY_METHOD_INCOME_RATIO_LIMIT:
        return True, f"지분법손익 지배(|지분법손익|/|영업이익| {em_ratio*100:.0f}%)"

    # 신호 ③ 세그먼트 다각화 — Phase 6: HHI 를 판정에 반영(기존엔 텍스트 표기만).
    #   ⓐ 1위 < 60% AND 부문 ≥ 3  (이산 임계)  또는
    #   ⓑ HHI ≤ 0.36 (전체 매출 분포가 고르게 분산 — 1위비중·부문수 통합 지표)
    top_share = _to_float(financials_signals.get("segment_top_share"))
    n_seg     = financials_signals.get("segment_n_segments")
    try:
        n_seg = int(n_seg) if n_seg is not None else None
    except (TypeError, ValueError):
        n_seg = None
    hhi = _to_float(financials_signals.get("segment_hhi"))
    cond_a = (top_share is not None and n_seg is not None
              and top_share < SEGMENT_TOP_SHARE_DIVERSIFIED
              and n_seg >= SEGMENT_MIN_COUNT_DIVERSIFIED)
    cond_b = (hhi is not None and hhi <= SEGMENT_HHI_DIVERSIFIED)
    if cond_a or cond_b:
        _ts = f"1위 {top_share*100:.0f}%, " if top_share is not None else ""
        _ns = f"{n_seg}부문" if n_seg is not None else "다부문"
        _hh = f", HHI {hhi:.2f}" if hhi is not None else ""
        return True, f"복합기업({_ts}{_ns}{_hh})"

    return False, None


def _extract_equity_method_investment(financials: dict) -> float:
    """v3 통합 JSON 의 noa_items 에서 InvestmentAccountedForUsingEquityMethod 추출.

    캐시 형태 (extract_company_v3):
      financials["noa_items"] = [{"tag": "...", "kor": "...", "val": int}, ...]

    매칭 실패 시 0 반환 (없으면 0 이라는 의미 — 비 holding 신호와 동치).
    """
    if not isinstance(financials, dict):
        return 0.0
    for n in financials.get("noa_items") or []:
        if not isinstance(n, dict):
            continue
        if n.get("tag") == "InvestmentAccountedForUsingEquityMethod":
            try:
                return float(n.get("val") or 0)
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def resolve_wics_from_krx(ticker: str) -> dict | None:
    """ticker → KRX 업종 + Name → WICS 자동 매핑.

    krx_desc.csv 가 있을 때만 작동. 없으면 None.
    실데이터 정책 — Name 은 krx_desc.csv 에서 직접 추출 (임의값 안 함).
    """
    krx_map = _get_krx_industry_map()
    name_map = _get_krx_name_map()
    if not krx_map:
        return None
    industry = krx_map.get(ticker)
    if not industry:
        return None
    from .peer_universe_data import lookup_wics_by_krx_industry
    wics = lookup_wics_by_krx_industry(industry)
    if wics is None:
        return None
    real_name = name_map.get(ticker)
    if not real_name:
        return None    # 실데이터 정책 — 회사명 모르면 매핑 거부
    return {
        "name":         real_name,    # ★ krx_desc.csv 의 실제 Name
        "sector":       wics[0],
        "mid":          wics[1],
        "source":       "krx_industry_auto",
        "krx_industry": industry,
    }


def _trigger_krx_refresh(verbose: bool = True) -> bool:
    """KRX 전종목 시세 자동 갱신 — peer_beta 가 캐시에 저장하도록.

    peer_beta.fetch_stock_weekly 가 호출되면 그 일자의 KOSPI/KOSDAQ 전종목
    응답이 캐시 (stock_KOSPI_<date>.json) 로 저장됨. 임의의 ticker 호출이라도
    같은 일자 전종목이 함께 캐시되므로 효율적.
    """
    try:
        import sys as _sys
        if str(_VAR_ROOT) not in _sys.path:
            _sys.path.insert(0, str(_VAR_ROOT))
        # KRX 키(krxdata) 보장 — 단독 호출 경로에서도 .env 로드
        try:
            from dotenv import load_dotenv
            load_dotenv(_VAR_ROOT / ".env", override=False)
        except Exception:
            pass
        from peer_beta.krx_client import fetch_stock_weekly
        from peer_beta.calendar_utils import weekly_friday_dates
        from datetime import date

        # 직전 금요일 1개만 — 그 일자의 전종목 응답을 받아 캐시
        fridays = weekly_friday_dates(date.today(), lookback_years=0)[-1:]
        if not fridays:
            return False
        # 삼성전자 (005930, KOSPI) 한 종목만 트리거해도 전종목 응답 캐시됨
        fetch_stock_weekly("005930", "KOSPI", fridays)
        # KOSDAQ 도 갱신 — 현존 대형 KOSDAQ 종목으로 트리거 (전종목 응답 캐시).
        # 주의: 폐지 종목(예: 091990 셀트리온헬스케어 합병폐지)을 쓰면 빈 응답 → 캐시 실패.
        try:
            fetch_stock_weekly("247540", "KOSDAQ", fridays)   # 에코프로비엠 (현존 대형주)
        except Exception:
            pass
        if verbose:
            print(f"  [KRX] 전종목 시세 자동 갱신 완료 ({fridays[0]})")
        return True
    except Exception as e:
        if verbose:
            print(f"  [KRX] 자동 갱신 실패: {str(e)[:100]}")
        return False


def _load_krx_market_cache(auto_refresh_if_stale_days: int = 14,
                            verbose: bool = False) -> dict[str, dict]:
    """peer_beta 가 받은 KRX 전종목 시세 캐시 → {ticker: {mktcap, list_shrs, close, list_dd}}.

    캐시 정책:
      - 가장 최근 stock_KOSPI_<date>.json + stock_KOSDAQ_<date>.json 사용
      - 캐시가 N일 이상 오래되면 자동 갱신 (auto_refresh_if_stale_days)
      - 캐시 자체가 없으면 자동 호출로 신규 생성
    """
    import json
    from datetime import date, datetime, timedelta

    # ── 캐시 신선도 점검 ──
    def _latest_age(market: str) -> Optional[int]:
        files = sorted(_KRX_CACHE_DIR.glob(f"stock_{market}_*.json"))
        if not files:
            return None
        latest_stem = files[-1].stem
        try:
            yyyymmdd = latest_stem.split("_")[-1]
            d = datetime.strptime(yyyymmdd, "%Y%m%d").date()
            return (date.today() - d).days
        except Exception:
            return None

    kospi_age  = _latest_age("KOSPI")
    kosdaq_age = _latest_age("KOSDAQ")

    # 캐시 없거나 너무 오래되면 자동 갱신 — KOSPI·KOSDAQ 둘 다 점검
    # (KOSDAQ 캐시가 없으면 KOSDAQ 동종 피어가 통째로 누락되므로 반드시 포함)
    stale = auto_refresh_if_stale_days
    needs_refresh = (
        kospi_age is None or kosdaq_age is None or
        (stale is not None and ((kospi_age > stale) or (kosdaq_age > stale)))
    )
    if needs_refresh:
        _trigger_krx_refresh(verbose=True)

    # ── 로드 ──
    result: dict[str, dict] = {}
    for market in ("KOSPI", "KOSDAQ"):
        files = sorted(_KRX_CACHE_DIR.glob(f"stock_{market}_*.json"))
        if not files:
            continue
        latest = files[-1]
        with latest.open("r", encoding="utf-8") as f:
            data = json.load(f)
        for row in data.get("OutBlock_1", []):
            code = (row.get("ISU_SRT_CD") or row.get("ISU_CD") or "")
            if len(code) == 12 and code.upper().startswith("KR"):
                code = code[3:9]
            code = code.zfill(6)
            if not code:
                continue
            try:
                mktcap = float(str(row.get("MKTCAP", "0")).replace(",", "") or 0)
                list_shrs = float(str(row.get("LIST_SHRS", "0")).replace(",", "") or 0)
                close = float(str(row.get("TDD_CLSPRC", "0")).replace(",", "") or 0)
                acc_trdval = float(str(row.get("ACC_TRDVAL", "0")).replace(",", "") or 0)
            except (ValueError, TypeError):
                continue
            result[code] = {
                "mktcap":   mktcap,
                "list_shrs": list_shrs,
                "close":    close,
                "acc_trdval": acc_trdval,    # 거래대금 (유동성 필터용 — 2순위)
                "list_dd":  row.get("LIST_DD", ""),   # 일별매매엔 보통 빈값 → 아래 종목기본정보로 보강
                "secugrp":  "",
                "stkcert_tp": "",
                "market":   market,
            }

    # ── 종목기본정보 병합 (Spec 7/8) — 상장일·증권구분·주식종류 (1순위) ──
    # 일별매매정보엔 LIST_DD/SECUGRP_NM/주식종류가 없어 종목기본정보 API 로 보강.
    try:
        import sys as _sys
        if str(_VAR_ROOT) not in _sys.path:
            _sys.path.insert(0, str(_VAR_ROOT))
        try:
            from dotenv import load_dotenv
            load_dotenv(_VAR_ROOT / ".env", override=False)
        except Exception:
            pass
        from peer_beta.krx_client import fetch_isu_base_info
        from datetime import date as _date
        for mkt in ("KOSPI", "KOSDAQ"):
            for info in fetch_isu_base_info(mkt, _date.today()):
                tk = info["ticker"]
                if tk in result:
                    if info.get("list_dd"):
                        result[tk]["list_dd"] = info["list_dd"]
                    result[tk]["secugrp"]    = info.get("secugrp", "")
                    result[tk]["stkcert_tp"] = info.get("stkcert_tp", "")
    except Exception as e:
        if verbose:
            print(f"  [WARN] 종목기본정보 병합 실패: {str(e)[:100]} — 일별매매만 사용")
    return result


def _listing_years(list_dd: str) -> float:
    """상장일 YYYYMMDD → 현재까지 연수."""
    if not list_dd or len(list_dd) < 8:
        return 999.0   # 정보 부재 시 무시 (필터 통과)
    try:
        from datetime import date
        ly, lm, ld = int(list_dd[:4]), int(list_dd[4:6]), int(list_dd[6:8])
        listing = date(ly, lm, ld)
        return (date.today() - listing).days / 365.25
    except (ValueError, TypeError):
        return 999.0


def _enrich_with_market_data(candidates: list[dict],
                              krx_cache: dict[str, dict]) -> list[dict]:
    """1차 보강 — KRX 캐시 (시총·상장주식수·상장일) 만으로.

    XBRL 호출 없음 — 빠름. Top 15 정도로 줄이는 1차 필터.
    """
    for c in candidates:
        info = krx_cache.get(c["ticker"], {})
        c["mktcap"]        = info.get("mktcap", 0)
        c["list_shrs"]     = info.get("list_shrs", 0)
        c["close_price"]   = info.get("close", 0)
        c["acc_trdval"]    = info.get("acc_trdval", 0)      # 거래대금 (유동성)
        c["secugrp"]       = info.get("secugrp", "")        # 증권구분 (주권/ETF/...)
        c["stkcert_tp"]    = info.get("stkcert_tp", "")     # 주식종류 (보통주/우선주)
        # ★ market 정확화 (KOSPI/KOSDAQ) — 종가·지수 조회 시장 결정.
        #   krx_industry 후보는 market 미설정이라 KRX 캐시에서 채워야 KOSDAQ 종목
        #   종가를 올바른 시장에서 조회한다 (누락 시 KOSPI 고정 → 종가 조회 실패).
        if info.get("market"):
            c["market"] = info["market"]
        c.setdefault("market", "KOSPI")
        c["listing_years"] = _listing_years(info.get("list_dd", ""))
        # 복합기업 판정용 — krx_desc Products 텍스트 부착 (없으면 빈 문자열)
        c.setdefault("products", _get_krx_products_map().get(c["ticker"], ""))
    return candidates


# ─────────────────────────────────────────────────────────────
# 증권 적격성 필터 (종목기본정보 기반) + 유동성 하한
# ─────────────────────────────────────────────────────────────
# 일 거래대금 하한 (원) — 이하면 유동성 부족 → 베타/멀티플 신뢰도 낮아 피어 제외.
# 일반투자자 관점: 거래가 거의 없는 종목은 비교 기준으로 부적합.
MIN_DAILY_TRADING_VALUE = 100_000_000   # 1억원


def _is_eligible_security(cand: dict) -> tuple[bool, Optional[str]]:
    """종목기본정보 기반 증권 적격성 + 유동성 점검.

    - 증권구분(secugrp): '주권'만 허용. ETF·리츠·스팩·외국주 등 비주권 제외.
      (정보 부재=빈값이면 graceful 통과 — 종목기본정보 미수집 종목 보호)
    - 주식종류(stkcert_tp): 우선주류 제외 (보통주만).
    - 유동성: 일 거래대금 < MIN_DAILY_TRADING_VALUE 제외.
    """
    secugrp = cand.get("secugrp", "") or ""
    stkcert = cand.get("stkcert_tp", "") or ""
    trdval  = cand.get("acc_trdval", 0) or 0

    if secugrp and secugrp != "주권":
        return False, f"비주권({secugrp})"
    if stkcert and ("우선주" in stkcert or stkcert.endswith("우")):
        return False, f"우선주({stkcert})"
    if trdval and trdval < MIN_DAILY_TRADING_VALUE:
        return False, f"저유동성(거래대금 {trdval/1e8:.2f}억)"
    products = cand.get("products", "") or ""
    industry = _get_krx_industry_map().get(cand.get("ticker", ""), "")
    # 순수 투자지주회사 제외 — 자체 영업 없어 사업회사와 멀티플·재무구조가 본질적으로 다름
    # (예: SK스퀘어·LG·SK·*홀딩스). 정보 부재 시 통과.
    if _is_holding_company(cand.get("name", ""), products, industry):
        return False, "투자지주회사(지주회사)"
    # 복합기업(다각화 사업회사) 제외 — Products 가 3개 이상 이종 산업 도메인에 걸치면
    # 단일 사업 비교가 무의미 (예: 두산=전자/기계/IT/에너지 4도메인). 정보 부재 시 통과.
    n_dom, domains = _count_business_domains(products)
    if n_dom >= DIVERSIFICATION_MAX_DOMAINS:
        return False, f"복합기업({n_dom}개 산업: {'·'.join(domains)})"
    return True, None


# ═════════════════════════════════════════════════════════════
# XBRL 재무 보강 (Top N 후보만 — 호출 비용)
# ═════════════════════════════════════════════════════════════
def _enrich_with_xbrl(candidates: list[dict], year: int = 2025,
                       verbose: bool = True) -> list[dict]:
    """후보들에 XBRL 재무 보강 — 매출·D/E·NOPAT 5년 중위값·cycle_z.

    각 회사마다 팀원 XBRL 모듈 호출 (DART API). 비용 큼 → Top N 후 호출 권장.
    """
    import statistics
    from .extract_balance_sheet import extract_for_company

    # 팀원 XBRL 모듈 임시 import (per-company 호출용)
    try:
        sys.path.insert(0, str(_VAR_ROOT / "XBRL"))
        from xbrl_financials_v4 import extract_company    # noqa
    except ImportError:
        if verbose:
            print("  [WARN] 팀원 XBRL 모듈 import 실패 — XBRL 보강 스킵")
        return candidates

    from .config import FISCAL_YEARS
    from .xbrl_collector import load_cached, extract_company_v3

    def _one(c: dict):
        """후보 1개 XBRL 보강 (DART). 성공 시 갱신된 c, 데이터 부재 시 None."""
        ticker = c["ticker"]
        name = c["name"]
        # 1) 자본·NCI·EPS (피어 선정엔 선택적)
        bs = extract_for_company(ticker, name, year=year)
        if bs is None:
            bs = {}
        # 2) XBRL 시계열 — 캐시 우선, 누락 연도만 DART
        try:
            by_year = {}
            missing_years = []
            for y in FISCAL_YEARS:
                cached = load_cached(name, y)
                if cached:
                    by_year[y] = cached
                else:
                    missing_years.append(y)
            for y in missing_years:
                try:
                    by_year[y] = extract_company_v3(name_or_code=name, year=y,
                                                    save=True, verbose=False)
                except Exception:
                    pass
        except Exception as e:
            if verbose:
                print(f"  [skip] {name} XBRL 호출 실패: {e}")
            return None
        # 3) 핵심 지표
        years_sorted = sorted(by_year.keys(), key=int)
        if not years_sorted:
            if verbose:
                print(f"  [skip] {name} ({ticker}) — XBRL 재무 시계열 부재")
            return None
        latest = by_year[years_sorted[-1]]["financials"]
        revenue = latest.get("매출액", 0) or 0
        ebit    = latest.get("영업이익", 0) or 0
        ibd_raw = latest.get("ibd")          # Phase 6: None(추출실패) vs 0(무차입) 구분
        ibd     = ibd_raw or 0
        nopats = [by_year[y]["financials"].get("nopat", 0) or 0 for y in years_sorted]
        nopats_valid = [n for n in nopats if n is not None]
        nopat_med = statistics.median(nopats_valid) if nopats_valid else None
        opms = []
        for y in years_sorted:
            f = by_year[y]["financials"]
            r = f.get("매출액", 0) or 0
            e = f.get("영업이익", 0) or 0
            if r > 0:
                opms.append(e / r)
        if len(opms) >= 2:
            import numpy as np
            mean_opm = np.mean(opms)
            std_opm  = np.std(opms, ddof=1)
            # 주의(Phase 6): FISCAL_YEARS(3년) 표본의 z-score 는 자유도가 낮아
            #   ±1.0~1.4σ 에 갇혀 변별력이 제한적이다. cycle_sim 가중(0.07)이 작아
            #   영향은 제한적이나, 산업 패널 cross-sectional z 로의 개선은 별도 과제.
            cycle_z  = (opms[-1] - mean_opm) / std_opm if std_opm > 0 else 0
        else:
            cycle_z = 0
        E = c.get("mktcap", 0)
        # Phase 6: ibd 추출 실패(None) 또는 시총 부재면 de_ratio=None → leverage 0점(중립).
        #   ibd=0(무차입, 값 존재)은 0/E=0 으로 정상 산정 → 무차입 회사끼리 유사 반영.
        #   (기존: 부재·무차입을 모두 0 으로 합쳐 데이터부재를 무차입으로 오인했음.)
        de_ratio = (ibd / E) if (ibd_raw is not None and E > 0) else None
        # Phase 1: opm·growth·roic 산출 — 신규 유사도 차원
        opm_latest = (ebit / revenue) if (revenue and revenue > 0) else None
        # 매출 3년 CAGR (가용 시) — revs[0] > 0 인 경우만
        rev_series = []
        for y in years_sorted:
            r = by_year[y]["financials"].get("매출액", 0) or 0
            rev_series.append(r)
        growth_3yr = None
        if len(rev_series) >= 2 and rev_series[0] > 0:
            n_period = len(rev_series) - 1
            growth_3yr = (rev_series[-1] / rev_series[0]) ** (1.0 / n_period) - 1
        # ROIC = NOPAT_latest / IC. IC = equity_parent + IBD − NOA (latest)
        roic = None
        try:
            ic = (bs.get("equity_parent") or 0) + (ibd or 0) - (latest.get("noa") or 0)
            nopat_latest = latest.get("nopat")
            if nopat_latest is None and ebit:
                import statistics as _stat_m
                # nopat 없으면 ebit × (1−25%) 근사 (한계세율 추정)
                nopat_latest = ebit * 0.75
            if ic > 0 and nopat_latest:
                roic = nopat_latest / ic
        except Exception:
            roic = None
        # D-8 신호 ①: 지분법투자(InvestmentAccountedForUsingEquityMethod)/자본 → holding
        equity_method_inv = _extract_equity_method_investment(latest)
        equity_total_val  = (bs.get("equity_total") if bs else None) or 0
        if equity_total_val > 0:
            inv_assoc_ratio = equity_method_inv / equity_total_val
        else:
            inv_assoc_ratio = None    # 자본 미수집 → graceful

        # D-8 신호 ②: |지분법손익|/|영업이익|. v3 캐시(latest)에서 추출.
        em_income = latest.get("equity_method_income")
        if em_income is None or not ebit:
            em_income_ratio = None     # 부재 → graceful
        else:
            try:
                em_income_ratio = abs(float(em_income)) / abs(float(ebit))
            except (TypeError, ValueError, ZeroDivisionError):
                em_income_ratio = None

        # D-8 신호 ③: 세그먼트 매출 — top_share/n_segments/hhi. 부재 → None.
        seg_info = latest.get("segment_revenues") or {}
        segment_top_share  = seg_info.get("top_share")
        segment_n_segments = seg_info.get("n_segments")
        segment_hhi        = seg_info.get("hhi")

        c["equity_parent"]        = bs.get("equity_parent")
        c["minority_interest"]    = bs.get("minority_interest")
        c["revenue"]              = revenue
        c["ebit"]                 = ebit
        c["ibd"]                  = ibd
        c["de_ratio"]             = de_ratio
        c["nopat_5yr_median"]     = nopat_med
        c["cycle_z"]              = cycle_z
        c["opm"]                  = opm_latest      # Phase 1
        c["growth_3yr"]           = growth_3yr      # Phase 1
        c["roic"]                 = roic            # Phase 1
        c["equity_method_inv"]    = equity_method_inv   # D-8 ①: 지분법 투자(원)
        c["inv_assoc_ratio"]      = inv_assoc_ratio     # D-8 ①: 지분법/자본총계
        c["equity_method_income"] = em_income           # D-8 ②: 지분법손익(원)
        c["em_income_ratio"]      = em_income_ratio     # D-8 ②: |지분법손익|/|영업이익|
        c["segment_top_share"]    = segment_top_share   # D-8 ③: 1위 부문 비중
        c["segment_n_segments"]   = segment_n_segments  # D-8 ③: 부문 수
        c["segment_hhi"]          = segment_hhi         # D-8 ③: HHI (참조)
        c["xbrl_years_available"] = len(years_sorted)
        c["year"]                 = year
        return c

    # ★ 후보 단위 병렬 (속도): 각 후보의 DART 호출은 서로 독립.
    workers = max(1, min(_ENRICH_MAX_WORKERS, len(candidates)))
    results: dict[int, dict] = {}
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="enrich") as ex:
        futs = {ex.submit(_one, c): i for i, c in enumerate(candidates)}
        for fut, idx in futs.items():
            r = fut.result()
            if r is not None:
                results[idx] = r
    # 입력 순서 보존
    return [results[i] for i in sorted(results.keys())]


# ═════════════════════════════════════════════════════════════
# 통합 진입점 — 사용자 ticker → 자동 피어 Top N
# ═════════════════════════════════════════════════════════════
def select_peers_for_target(target_ticker: str,
                             target_data: Optional[dict] = None,
                             year: int = 2025,
                             top_n: int = 3,
                             use_rag: bool = True,
                             verbose: bool = True) -> list[dict]:
    """통합 진입점 — 타깃 ticker 입력만으로 자동 피어 Top N.

    흐름:
      1. WICS 매핑에서 sector/mid 조회
      2. 같은 sector + mid + 인접 회사를 1차 후보 풀로 (~30개)
      3. XBRL raw 가용 회사만 필터링 + 재무 보강
      4. compute_similarity 로 점수 산출 + Top N 선정

    Args:
        target_ticker: 타깃 종목코드
        target_data:   타깃 회사 정보. None 이면 WICS 매핑 + XBRL 에서 자동 추출.
        year:          기준 회계연도
        top_n:         피어 개수
        use_rag:       BGE-M3 RAG 사업유사도 사용 여부

    Returns:
        피어 dict 리스트 (점수·근거 포함)
    """
    wics_map, biz_tag, whitelist, monopoly = _load_wics_map()

    # 1) target_data 자동 구성
    if target_data is None:
        info = wics_map.get(target_ticker)

        # ★ primary 미등록 → KRX_TO_WICS 자동 매핑 시도 (krx_desc.csv 있으면)
        if not info:
            auto = resolve_wics_from_krx(target_ticker)
            if auto is not None:
                if verbose:
                    print(f"  [auto] {target_ticker} → KRX 업종 \"{auto['krx_industry']}\" "
                          f"→ WICS \"{auto['sector']}\" / \"{auto['mid']}\"")
                info = auto

        if not info:
            print(f"[오류] {target_ticker} WICS 매핑 없음 (krx_desc.csv 추가 시 자동 매핑 가능)")
            return []
        # ★ KRX 캐시에서 mktcap·listing_years 자동 채움 (시총 1차 필터용)
        _krx_cache = _load_krx_market_cache()
        _krx_info  = _krx_cache.get(target_ticker, {})
        _t_mktcap  = _krx_info.get("mktcap", 0)
        _t_listing = _listing_years(_krx_info.get("list_dd", ""))

        # ★ XBRL 통합 캐시에서 revenue/de_ratio/cycle_z 자동 보강 (H-6)
        equity_parent_val = 0
        target_revenue    = 0
        target_ibd        = 0
        target_cycle_z    = 0
        target_nopat_med  = None
        target_xbrl_yrs   = 0
        target_opm        = None    # Phase 1
        target_growth     = None
        target_roic       = None
        try:
            from .extract_balance_sheet import extract_for_company
            bs = extract_for_company(target_ticker, info["name"], year=year)
            if bs:
                equity_parent_val = bs.get("equity_parent", 0) or 0

            # XBRL 5년 시계열 캐시에서 매출·NOPAT·OPM cycle_z 산출
            from .xbrl_collector import load_cached
            from .config import FISCAL_YEARS
            by_year = {}
            for y in FISCAL_YEARS:
                c = load_cached(info["name"], y)
                if c:
                    by_year[y] = c
            if by_year:
                years_sorted = sorted(by_year.keys(), key=int)
                latest = by_year[years_sorted[-1]]["financials"]
                target_revenue = latest.get("매출액", 0) or 0
                target_ibd     = latest.get("ibd", 0) or 0
                target_xbrl_yrs = len(years_sorted)

                # NOPAT 5년 중위값
                import statistics as _stat
                nopats = [(by_year[y]["financials"].get("nopat") or 0)
                          for y in years_sorted]
                nopats = [n for n in nopats if n is not None]
                target_nopat_med = _stat.median(nopats) if nopats else None

                # OPM 시계열 → cycle_z (단일 회사 변동성)
                opms = []
                for y in years_sorted:
                    fy = by_year[y]["financials"]
                    r = fy.get("매출액", 0) or 0
                    e = fy.get("영업이익", 0) or 0
                    if r > 0:
                        opms.append(e / r)
                if len(opms) >= 2:
                    import numpy as _np
                    mu = _np.mean(opms)
                    sd = _np.std(opms, ddof=1) if len(opms) >= 2 else 0
                    target_cycle_z = (opms[-1] - mu) / sd if sd > 0 else 0

                # Phase 1: 타깃 opm·growth_3yr·roic 산출 (피어와 동일 산식)
                target_opm = (latest.get("영업이익", 0) / target_revenue
                              if target_revenue > 0 else None)
                rev_series = [(by_year[y]["financials"].get("매출액", 0) or 0)
                              for y in years_sorted]
                target_growth = None
                if len(rev_series) >= 2 and rev_series[0] > 0:
                    target_growth = (rev_series[-1] / rev_series[0]) ** (
                        1.0 / (len(rev_series) - 1)) - 1
                # ROIC 산출
                target_roic = None
                try:
                    _ep = equity_parent_val or 0
                    _noa = latest.get("noa") or 0
                    _ic = _ep + target_ibd - _noa
                    _nopat = latest.get("nopat")
                    if _nopat is None and latest.get("영업이익"):
                        _nopat = latest["영업이익"] * 0.75
                    if _ic > 0 and _nopat:
                        target_roic = _nopat / _ic
                except Exception:
                    pass
        except Exception as e:
            if verbose:
                print(f"  [WARN] {target_ticker} XBRL 보강 실패: {e} — 부분값으로 진행")

        # D/E = IBD / mktcap (KRX 시총 기반)
        target_de_ratio = (target_ibd / _t_mktcap) if _t_mktcap > 0 else 0

        target_data = {
            "ticker":   target_ticker,
            "name":     info["name"],
            "sector":   info["sector"],
            "mid":      info["mid"],
            "equity_parent": equity_parent_val,
            "mktcap":   _t_mktcap,           # KRX 캐시 자동
            "revenue":  target_revenue,      # ★ XBRL 자동 (H-6)
            "de_ratio": target_de_ratio,     # ★ XBRL 자동 (H-6)
            "cycle_z":  target_cycle_z,      # ★ XBRL 자동 (H-6)
            # Phase 1: 멀티플 결정 변수 — opm·growth·roic
            "opm":      target_opm,
            "growth_3yr": target_growth,
            "roic":     target_roic,
            "listing_years":     _t_listing,
            "nopat_5yr_median":  target_nopat_med,
            "xbrl_years_available": target_xbrl_yrs,
            "year":     year,
        }
        if verbose and target_revenue > 0:
            print(f"  [target보강] 매출 {target_revenue/1e12:.2f}조  "
                  f"D/E {target_de_ratio*100:.1f}%  "
                  f"cycle_z {target_cycle_z:+.2f}σ  "
                  f"NOPAT중위 {(target_nopat_med or 0)/1e8:.0f}억")

    if verbose:
        print(f"\n[1/4] WICS 후보 풀 구성 — {target_data['name']} ({target_ticker})")
        print(f"      섹터: {target_data['sector']} / {target_data['mid']}")

    # 2) WICS 후보 풀 (~30개)
    candidates_raw = build_universe_from_wics(target_ticker)
    if verbose:
        print(f"      1차 후보 (WICS): {len(candidates_raw)}사")

    # 3) KRX 캐시 보강 — 시총·상장연수·종가 (외부 호출 0, 즉시)
    if verbose:
        print(f"\n[2/4] KRX 캐시 보강 (시총·상장연수·종가)")
    krx_cache = _load_krx_market_cache()
    if not krx_cache:
        if verbose:
            print(f"      [WARN] KRX 캐시 없음 → peer_beta.run_beta 먼저 실행 필요")
        return []

    candidates_market = _enrich_with_market_data(candidates_raw, krx_cache)
    # KRX 캐시에 없는 후보 제외 (상장 폐지 등)
    candidates_market = [c for c in candidates_market if c["mktcap"] > 0]
    # 증권 적격성 필터 (종목기본정보) — 우선주·ETF·리츠·스팩·저유동성 제외 (1·2순위)
    n_before = len(candidates_market)
    _excluded = []
    _kept = []
    for c in candidates_market:
        ok, reason = _is_eligible_security(c)
        (_kept if ok else _excluded).append((c, reason))
    candidates_market = [c for c, _ in _kept]
    if verbose:
        n_drop = n_before - len(candidates_market)
        msg = f"      2차 후보 (KRX 보강): {len(candidates_market)}사"
        if n_drop:
            msg += f"  (적격성/유동성 제외 {n_drop}사)"
        print(msg)
        for c, reason in _excluded[:5]:
            print(f"        ✗ {c.get('name', c['ticker'])} — {reason}")

    # 4) 1차 필터링 — Phase 1: 섹터 quota + 시총 정렬 (시총만 컷 X)
    # 이전: 시총 차이만으로 컷 → 사업유사 매우 높은 중소형 same_sec 피어가 큰 시총
    #       same_mid·adjacent 에 의해 밀려나는 함정 발생.
    # 변경: 그룹별 quota (same_sec 15 + krx_industry 10 + same_mid 5 + adjacent 3)
    #       후보군 자체를 보존 후, 그룹 내에서 시총 유사도 정렬.
    target_mcap = target_data.get("mktcap", 0)

    SHORTLIST_QUOTAS = {
        "same_sec":           15,   # WICS 동일 소섹터
        "krx_same_industry":  10,   # KRX 표준산업분류 동종 (WICS 마스터 누락 보완)
        "same_mid":            5,   # 같은 중섹터, 다른 소섹터
        "adjacent":            3,   # 화이트리스트 인접
    }
    DEFAULT_QUOTA = 5              # group 미지정 후보 폴백

    # 그룹별 시총 유사도 정렬
    by_group: dict[str, list] = {}
    for c in candidates_market:
        grp = c.get("group", "unknown")
        by_group.setdefault(grp, []).append(c)
    for grp, lst in by_group.items():
        if target_mcap > 0:
            lst.sort(key=lambda c: -_mktcap_sim_log(target_mcap, c.get("mktcap") or 0))
    # quota 적용 → 합집합 (그룹 우선순위 유지)
    quotaed: list[dict] = []
    seen_t: set[str] = set()
    for grp in ("same_sec", "krx_same_industry", "same_mid", "adjacent", "unknown"):
        for c in by_group.get(grp, [])[:SHORTLIST_QUOTAS.get(grp, DEFAULT_QUOTA)]:
            if c["ticker"] not in seen_t:
                seen_t.add(c["ticker"])
                quotaed.append(c)
    candidates_market = quotaed
    if verbose:
        _summary = ", ".join(
            f"{g}={min(len(by_group.get(g, [])), SHORTLIST_QUOTAS.get(g, DEFAULT_QUOTA))}"
            for g in ("same_sec", "krx_same_industry", "same_mid", "adjacent")
            if by_group.get(g)
        )
        print(f"      1차 필터 (섹터 quota): 총 {len(candidates_market)}사  [{_summary}]")

    # 5) XBRL 재무 보강 — 캐시 우선, 미존재 시 DART 자동 호출
    if verbose:
        print(f"\n[3/4] XBRL 재무 보강 — 캐시 우선, 미존재 시 DART 호출")
    candidates_full = _enrich_with_xbrl(candidates_market, year=year, verbose=verbose)
    if verbose:
        print(f"      3차 후보 (XBRL 보강): {len(candidates_full)}사")

    # D-8: 재무구조 기반 holding 추가 필터 — XBRL 보강 결과(inv_assoc_ratio) 활용.
    #   키워드(_is_holding_company)에 잡히지 않은 위장 holding 보강. 데이터 부재 시 통과.
    filtered_full = []
    removed_holding: list[tuple[str, str]] = []
    for c in candidates_full:
        is_h, reason = _is_holding_by_financials(c)
        if is_h:
            removed_holding.append((c.get("name", ""), reason or "지주의심"))
        else:
            filtered_full.append(c)
    if removed_holding and verbose:
        print(f"      D-8 재무구조 지주 제외: {len(removed_holding)}사")
        for nm, r in removed_holding:
            print(f"        ✗ {nm} — {r}")
    candidates_full = filtered_full

    # ★ PARTIAL 모드 — XBRL 수집 불가 시 KRX 시총·섹터만으로 점수 산출 (신뢰도 낮음 명시)
    # candidates_market 자체가 비어 있으면 진짜 데이터 부재 → 빈 결과
    if not candidates_full:
        if not candidates_market:
            if verbose:
                print(f"      [중단] KRX 데이터 부재 — 피어 산정 불가")
            return []
        if verbose:
            print(f"      [PARTIAL] XBRL 보강 불가 → KRX 시총만으로 점수 산출 (신뢰도 낮음)")
        for c in candidates_market:
            # XBRL 필드 없음 명시 (임의값 0 으로 채우지 않고 None 유지)
            c.setdefault("revenue", None)
            c.setdefault("de_ratio", None)
            c.setdefault("cycle_z", None)
            c.setdefault("nopat_5yr_median", None)
            c["xbrl_years_available"] = 999   # _is_eligible 필터 우회 sentinel
            c["data_completeness"] = "partial_krx_only"
        candidates_full = candidates_market

    # 6) 종합 유사도 + Top N
    if verbose:
        print(f"\n[4/4] 종합 유사도 산출 + Top {top_n} 선정 (RAG={use_rag})")
    peers = select_peers(target_ticker, target_data, candidates_full,
                          top_n=top_n, use_rag=use_rag, verbose=verbose)

    # Phase 1 (H8): target 자체가 holding/금융이면 사업회사 피어 비교가 무의미.
    #   DCF 는 dcf_engine 의 is_dcf_unsuitable 로 이미 차단되나, 멀티플은 사업회사
    #   피어로 산출돼 오도 가능 → 경고 + 신뢰도 메타에 플래그(점수 감점은 Phase 6).
    _target_unsuitable, _target_unsuit_reason = False, None
    try:
        from .industry_classifier import is_dcf_unsuitable
        _target_unsuitable, _target_unsuit_reason = is_dcf_unsuitable(target_ticker)
        if _target_unsuitable and verbose:
            print(f"\n  ⚠ [target 부적합] {_target_unsuit_reason}")
            print(f"     → 사업회사 피어 멀티플 비교는 한계 (NAV/SOTP·DDM 등 대체모형 권장)")
    except Exception:
        pass

    # Phase 1: 피어셋 신뢰도 점수 산출
    #   · 각 피어 dict 에 grade/score 값만 첨부 (slim)
    #   · 전체 메타(deductions 등)는 _LAST_CONFIDENCE 모듈 변수에 저장 →
    #     caller 가 get_last_peer_confidence() 로 접근
    confidence = compute_peer_confidence(peers, target_data)
    if _target_unsuitable:
        confidence["target_unsuitable"] = True
        confidence["target_unsuitable_reason"] = _target_unsuit_reason
    for p in peers:
        p["peer_confidence_grade"] = confidence["grade"]
        p["peer_confidence_score"] = confidence["score"]
    global _LAST_CONFIDENCE
    _LAST_CONFIDENCE = confidence

    if verbose:
        print(f"\n  ┌─ 피어셋 신뢰도 ─────────────────")
        print(f"  │ 점수 {confidence['score']}/100  등급 {confidence['grade']}")
        for d in confidence['deductions']:
            print(f"  │   {d['delta']:+d}  {d['reason']}")
        print(f"  └──────────────────────────────────")

    return peers


# ─────────────────────────────────────────────────────────────
# 테스트
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # 예시 — 현대건설 + 건설 피어 우주
    target = {
        "ticker":     "000720",  "name": "현대건설",
        "sector":     "건설과엔지니어링", "mid": "자본재",
        "mktcap":     5_000_000_000_000,    # 5조
        "revenue":    30_000_000_000_000,   # 30조
        "de_ratio":   0.30,
        "cycle_z":    -1.2,    # 침체기
        "listing_years": 30,
        "nopat_5yr_median": 500_000_000_000,  # 5천억
        "xbrl_years_available": 5,
        "year": 2025,
    }

    # smoke test 생략 — 실 사용 시 select_peers_for_target 사용
