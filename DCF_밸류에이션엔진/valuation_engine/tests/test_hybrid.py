# -*- coding: utf-8 -*-
"""DAY2 D-6: RAG hybrid (BM25 + reranker) 단위 테스트.

torch/모델 의존성 없이 검증 가능한 순수 로직만:
  · combine_hybrid 가용 채널 재정규화
  · _tokenize fallback (kiwipiepy 부재 시 char n-gram)
  · compute_bm25_scores (rank_bm25 가용 시) / None (부재 시)

reranker(GPU 모델)는 환경 의존이라 통합 평가에서 검증.

실행:
  python -m unittest valuation_engine.tests.test_hybrid -v
"""
from __future__ import annotations

import unittest


class TestCombineHybrid(unittest.TestCase):
    """가용 채널만 가중 결합 + 재정규화."""

    def test_all_three_channels(self):
        from valuation_engine.embedding_hybrid import combine_hybrid
        # 0.5*0.6 + 0.3*0.8 + 0.2*1.0 = 0.30+0.24+0.20 = 0.74 (den=1.0)
        r = combine_hybrid(0.6, 0.8, 1.0)
        self.assertAlmostEqual(r, 0.74, places=4)

    def test_dense_only_passthrough(self):
        """bm25·rerank 부재 → dense 그대로 (재정규화로 가중 상쇄)."""
        from valuation_engine.embedding_hybrid import combine_hybrid
        r = combine_hybrid(0.62, None, None)
        self.assertAlmostEqual(r, 0.62, places=4)

    def test_dense_plus_bm25_renormalized(self):
        """rerank 부재 → (0.5*dense + 0.3*bm25) / 0.8."""
        from valuation_engine.embedding_hybrid import combine_hybrid
        # (0.5*0.6 + 0.3*0.8) / (0.5+0.3) = 0.54/0.8 = 0.675
        r = combine_hybrid(0.6, 0.8, None)
        self.assertAlmostEqual(r, 0.675, places=4)

    def test_all_none_returns_none(self):
        from valuation_engine.embedding_hybrid import combine_hybrid
        self.assertIsNone(combine_hybrid(None, None, None))

    def test_rerank_only(self):
        from valuation_engine.embedding_hybrid import combine_hybrid
        r = combine_hybrid(None, None, 0.9)
        self.assertAlmostEqual(r, 0.9, places=4)

    def test_custom_weights(self):
        from valuation_engine.embedding_hybrid import combine_hybrid
        # 동일 가중 → 단순 평균
        w = {"dense": 1.0, "bm25": 1.0, "rerank": 1.0}
        r = combine_hybrid(0.3, 0.6, 0.9, weights=w)
        self.assertAlmostEqual(r, 0.6, places=4)

    def test_weights_sum_default(self):
        """기본 가중 합 1.0 (문서화된 0.5/0.3/0.2)."""
        from valuation_engine.embedding_hybrid import HYBRID_WEIGHTS
        self.assertAlmostEqual(sum(HYBRID_WEIGHTS.values()), 1.0, places=6)


class TestTokenize(unittest.TestCase):
    """한국어 토큰화 — kiwipiepy 가용/부재 양쪽에서 비어있지 않아야."""

    def test_nonempty_for_korean(self):
        from valuation_engine.embedding_hybrid import _tokenize
        toks = _tokenize("이차전지 양극재 및 음극재 제조 사업")
        self.assertGreater(len(toks), 0)

    def test_empty_string(self):
        from valuation_engine.embedding_hybrid import _tokenize
        self.assertEqual(_tokenize(""), [])
        self.assertEqual(_tokenize("   "), [])

    def test_overlap_detectable(self):
        """유사 사업 텍스트는 공통 토큰 ≥ 1 (BM25 매칭 전제)."""
        from valuation_engine.embedding_hybrid import _tokenize
        a = set(_tokenize("반도체 메모리 D램 낸드 제조"))
        b = set(_tokenize("반도체 메모리 양산 D램 설계"))
        self.assertGreater(len(a & b), 0)


class TestBM25(unittest.TestCase):
    """BM25 — rank_bm25 가용 시 동작, 부재 시 None (graceful)."""

    def setUp(self):
        try:
            import rank_bm25  # noqa
            self.has_bm25 = True
        except ImportError:
            self.has_bm25 = False

    def test_returns_none_without_lib_or_scores_with(self):
        from valuation_engine.embedding_hybrid import compute_bm25_scores
        query = "반도체 메모리 D램 제조 양산"
        corpus = [
            "반도체 메모리 D램 낸드 양산 제조",   # 유사
            "화장품 색조 기초 스킨케어 제조 판매",  # 무관
            "반도체 D램 메모리 설계 제조",          # 유사
        ]
        scores = compute_bm25_scores(query, corpus)
        if not self.has_bm25:
            self.assertIsNone(scores)
            self.skipTest("rank_bm25 부재 — graceful None 확인")
        self.assertEqual(len(scores), 3)
        # 반도체 문서(0,2)가 화장품(1)보다 높아야
        self.assertGreater(scores[0], scores[1])
        self.assertGreater(scores[2], scores[1])
        # 정규화 0~1
        for s in scores:
            self.assertGreaterEqual(s, 0.0)
            self.assertLessEqual(s, 1.0)

    def test_empty_inputs_return_none(self):
        from valuation_engine.embedding_hybrid import compute_bm25_scores
        self.assertIsNone(compute_bm25_scores("", ["a"]))
        self.assertIsNone(compute_bm25_scores("q", []))


if __name__ == "__main__":
    unittest.main()
