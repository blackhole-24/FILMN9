# -*- coding: utf-8 -*-
"""Tier A/B/C 핵심 로직 단위 테스트 — 회귀 안전망.

stdlib unittest 기반(pytest 불필요).

실행:
  python -m unittest valuation_engine.tests.test_tier_logic
  또는
  python -m unittest discover -s valuation_engine/tests -v
"""
import unittest


# ── B2: winsorized_median ────────────────────────────────────────────
class TestWinsorizedMedian(unittest.TestCase):
    def setUp(self):
        from valuation_engine.dcf_engine import _winsorized_median
        self.fn = _winsorized_median

    def test_empty_returns_none(self):
        self.assertIsNone(self.fn([], k=1))

    def test_single_value(self):
        self.assertEqual(self.fn([0.05], k=1), 0.05)

    def test_n3_returns_middle(self):
        self.assertEqual(self.fn([0.02, 0.04, 0.06], k=1), 0.04)

    def test_n5_winsorize_trims_extremes(self):
        self.assertEqual(self.fn([-1.0, 0.05, 0.08, 0.10, 5.0], k=1), 0.08)

    def test_identical_values(self):
        self.assertEqual(self.fn([0.05] * 5, k=1), 0.05)

    def test_handles_none_values(self):
        self.assertEqual(self.fn([0.04, None, 0.06], k=1), 0.05)


# ── B1+: OPM pattern classifier ──────────────────────────────────────
class TestOpmPattern(unittest.TestCase):
    def setUp(self):
        from valuation_engine.dcf_engine import _classify_opm_pattern
        self.fn = _classify_opm_pattern

    def test_short_series_stable(self):
        pat, _ = self.fn([0.1, 0.12, 0.11])
        self.assertEqual(pat, "stable")

    def test_small_range_stable(self):
        pat, _ = self.fn([0.12, 0.13, 0.12, 0.11, 0.13, 0.12, 0.13, 0.12])
        self.assertEqual(pat, "stable")

    def test_monotonic_decline_evolution(self):
        pat, _ = self.fn([0.30, 0.28, 0.26, 0.24, 0.22, 0.20, 0.18, 0.15])
        self.assertEqual(pat, "evolution")

    def test_monotonic_rise_evolution(self):
        pat, _ = self.fn([0.007, 0.017, 0.019, 0.022, 0.027, 0.049, 0.051, 0.074])
        self.assertEqual(pat, "evolution")

    def test_oscillating_cyclical(self):
        pat, _ = self.fn([0.242, 0.121, 0.152, 0.185, 0.144, 0.025, 0.109, 0.131])
        self.assertEqual(pat, "cyclical")


# ── C1: 산업 분류 ────────────────────────────────────────────────────
class TestIndustryClassifier(unittest.TestCase):
    def setUp(self):
        from valuation_engine.industry_classifier import classify_ticker
        self.classify = classify_ticker

    def test_semiconductor_is_cyclical(self):
        r = self.classify("000660")
        self.assertEqual(r["category"], "cyclical")

    def test_naver_is_growth(self):
        r = self.classify("035420")
        self.assertEqual(r["category"], "growth")

    def test_telecom_is_mature(self):
        r = self.classify("030200")
        self.assertEqual(r["category"], "mature")

    def test_force_name_override_samsung_electronics(self):
        r = self.classify("005930")
        self.assertEqual(r["category"], "cyclical")
        self.assertEqual(r["source"], "name_force")


# ── retry decorator ─────────────────────────────────────────────────
class TestRetry(unittest.TestCase):
    def test_success_first_try(self):
        from valuation_engine._retry import with_retry
        calls = [0]
        @with_retry(max_tries=3, backoff=0.01)
        def f():
            calls[0] += 1
            return 42
        self.assertEqual(f(), 42)
        self.assertEqual(calls[0], 1)

    def test_retry_then_succeed(self):
        from valuation_engine._retry import with_retry
        calls = [0]
        @with_retry(max_tries=3, backoff=0.01, retry_on=(ValueError,))
        def f():
            calls[0] += 1
            if calls[0] < 3:
                raise ValueError("temporary")
            return "ok"
        self.assertEqual(f(), "ok")
        self.assertEqual(calls[0], 3)

    def test_max_tries_exhausted_raises(self):
        from valuation_engine._retry import with_retry
        @with_retry(max_tries=2, backoff=0.01, retry_on=(RuntimeError,))
        def f():
            raise RuntimeError("permanent")
        with self.assertRaises(RuntimeError):
            f()


# ── Phase 0: 피어 선정 컷 로직 수정 검증 ──────────────────────────────
class TestPeerCutLogic(unittest.TestCase):
    """MIN_SCORE 동어반복 제거 + XBRL factor 분리 검증."""

    def setUp(self):
        from valuation_engine.peer_selector import MIN_SCORE, WEIGHTS
        self.MIN_SCORE = MIN_SCORE
        self.WEIGHTS = WEIGHTS

    def test_min_score_no_longer_equals_sector_weight(self):
        # 동어반복 제거 — MIN_SCORE 가 sector_sim 가중과 같으면 안 됨
        self.assertNotEqual(self.MIN_SCORE, self.WEIGHTS["sector_sim"],
            "MIN_SCORE 가 sector_sim 가중과 같으면 '같은 소섹터면 무조건 통과' 동어반복")

    def test_min_score_strictly_above_sector_only(self):
        # 같은 소섹터만 만족(다른 차원 0)으로 컷 통과 불가
        sector_only_max = self.WEIGHTS["sector_sim"] * 1.0   # 같은 소섹터 만점
        self.assertGreater(self.MIN_SCORE, sector_only_max,
            "같은 소섹터(0.30)만으로 컷 통과 가능하면 변별 기능 없음")

    def test_compute_similarity_xbrl_factor_separated(self):
        # XBRL factor 가 score 에서 분리됐는지 — data_quality_factor 메타로만 반영
        from valuation_engine.peer_selector import compute_similarity
        target = {"ticker": "X", "sector": "S", "mid": "M",
                  "mktcap": 1e12, "revenue": 1e12, "de_ratio": 0.5,
                  "cycle_z": 0, "year": 2025}
        cand_5y = dict(target, ticker="A", xbrl_years_available=5)
        cand_3y = dict(target, ticker="B", xbrl_years_available=3)
        sim_5 = compute_similarity(target, cand_5y, set(), {}, use_rag=False)
        sim_3 = compute_similarity(target, cand_3y, set(), {}, use_rag=False)
        # 점수는 같아야 함 (data_quality 가 score 에 곱해지면 안 됨)
        self.assertAlmostEqual(sim_5["total_score"], sim_3["total_score"], places=5,
            msg="XBRL factor 가 score 에 영향 — 분리되지 않음")
        # data_quality_factor 는 다르게 노출돼야
        self.assertEqual(sim_5["data_quality_factor"], 1.0)
        self.assertEqual(sim_3["data_quality_factor"], 0.80)


# ── Phase 0: DCF 부적합 라우팅 (금융·지주) ──────────────────────────
class TestDcfUnsuitable(unittest.TestCase):
    def setUp(self):
        from valuation_engine.industry_classifier import is_dcf_unsuitable
        self.fn = is_dcf_unsuitable

    def test_bank_is_unsuitable(self):
        ok, reason = self.fn("055550")   # 신한지주? 우선 KB금융 같은 은행
        # 신한지주는 지주 → 어떤 식으로든 부적합
        # 은행 자체로 테스트: 055550 신한금융지주
        self.assertTrue(ok, "은행/금융지주는 DCF 부적합이어야 함")

    def test_insurance_is_unsuitable(self):
        # 삼성생명 032830 — 보험업
        ok, reason = self.fn("032830")
        self.assertTrue(ok, "보험사는 DCF 부적합이어야 함")

    def test_manufacturing_is_suitable(self):
        ok, reason = self.fn("009150")   # 삼성전기
        self.assertFalse(ok, "일반 제조업은 DCF 적합해야 함")

    def test_growth_company_is_suitable(self):
        ok, reason = self.fn("035420")   # NAVER
        self.assertFalse(ok, "IT/플랫폼은 DCF 적합해야 함")


# ── Phase 1: 가중치 합 + 신규 유사도 함수 + 신뢰도 점수 ────────────────
class TestPhase1Weights(unittest.TestCase):
    def test_weights_sum_to_one(self):
        from valuation_engine.peer_selector import WEIGHTS
        self.assertAlmostEqual(sum(WEIGHTS.values()), 1.0, places=6,
            msg="가중치 합이 1.0이 아님")

    def test_weights_include_new_dimensions(self):
        from valuation_engine.peer_selector import WEIGHTS
        for k in ("opm_sim", "growth_sim", "roic_sim"):
            self.assertIn(k, WEIGHTS, f"Phase 1 신규 차원 {k} 누락")

    def test_size_weights_reduced(self):
        from valuation_engine.peer_selector import WEIGHTS
        # 시총·매출 가중이 0.20+0.15 = 0.35 에서 축소됐는지
        self.assertLess(WEIGHTS["mktcap_sim"] + WEIGHTS["revenue_sim"], 0.30,
            "규모 가중치(시총+매출)가 충분히 축소되지 않음")


class TestPhase1SimFunctions(unittest.TestCase):
    def test_opm_sim_within_5pp_returns_1(self):
        from valuation_engine.peer_selector import _opm_sim
        self.assertEqual(_opm_sim(0.10, 0.13), 1.0)   # 3%p 차이

    def test_opm_sim_over_20pp_returns_0(self):
        from valuation_engine.peer_selector import _opm_sim
        self.assertEqual(_opm_sim(0.10, -0.15), 0.0)   # 25%p

    def test_growth_sim_wider_tolerance(self):
        from valuation_engine.peer_selector import _growth_sim, _opm_sim
        # 같은 차이라도 growth는 더 관대 (분모 넓음)
        diff_15pp = 0.15
        self.assertGreater(_growth_sim(0.10, 0.10 + diff_15pp),
                           _opm_sim(0.10, 0.10 + diff_15pp))

    def test_roic_sim_strict(self):
        from valuation_engine.peer_selector import _roic_sim
        self.assertEqual(_roic_sim(0.12, 0.13), 1.0)   # 1%p 차이
        self.assertEqual(_roic_sim(0.12, -0.05), 0.0)   # 17%p

    def test_sim_handles_none(self):
        from valuation_engine.peer_selector import _opm_sim, _growth_sim, _roic_sim
        self.assertEqual(_opm_sim(None, 0.10), 0.0)
        self.assertEqual(_growth_sim(0.05, None), 0.0)
        self.assertEqual(_roic_sim(None, None), 0.0)


class TestPeerConfidence(unittest.TestCase):
    def setUp(self):
        from valuation_engine.peer_selector import compute_peer_confidence
        self.fn = compute_peer_confidence

    def test_empty_peers_returns_E(self):
        r = self.fn([], {"sector": "S", "mktcap": 1e12})
        self.assertEqual(r["grade"], "E")
        self.assertEqual(r["score"], 0)

    def test_three_good_peers_returns_high_grade(self):
        # 3사 모두 같은 소섹터, 적당한 시총·OPM
        target = {"sector": "S", "mktcap": 1e12, "revenue": 1e12,
                  "ebit": 1e11, "opm": 0.10}
        peers = [
            {"name": f"P{i}", "sector": "S", "mktcap": 1.5e12,
             "revenue": 1.2e12, "opm": 0.11,
             "components": {"rag_sim": 0.80},
             "data_completeness": "full"}
            for i in range(3)
        ]
        r = self.fn(peers, target)
        self.assertIn(r["grade"], ("A", "B"), f"3사 양호인데 grade={r['grade']}")

    def test_below_min_peers_deducted(self):
        target = {"sector": "S", "mktcap": 1e12}
        peers = [
            {"name": "P1", "sector": "S", "mktcap": 1e12, "below_min_score": True},
            {"name": "P2", "sector": "S", "mktcap": 1e12, "below_min_score": True},
            {"name": "P3", "sector": "S", "mktcap": 1e12},
        ]
        r = self.fn(peers, target)
        # below_min 2사 × −10 = −20
        deduction_reasons = " | ".join(d["reason"] for d in r["deductions"])
        self.assertIn("보충", deduction_reasons)   # Phase 9: "점수미달 보충"→"유사도 낮아 보충한 피어"

    def test_partial_peers_deducted(self):
        target = {"sector": "S", "mktcap": 1e12}
        peers = [
            {"name": "P1", "sector": "S", "mktcap": 1e12,
             "data_completeness": "partial_krx_only"}
            for _ in range(3)
        ]
        r = self.fn(peers, target)
        self.assertEqual(r["n_partial"], 3)

    def test_few_same_sector_deducted(self):
        target = {"sector": "S", "mktcap": 1e12}
        # 다른 소섹터 피어들
        peers = [{"name": "P1", "sector": "OTHER", "mktcap": 1e12} for _ in range(3)]
        r = self.fn(peers, target)
        reasons = " | ".join(d["reason"] for d in r["deductions"])
        self.assertIn("업종", reasons)   # Phase 9: "같은 소섹터 N사"→"같은 업종(세부 분류) N사"


# ── Phase 1: Whitening (anisotropy 보정) ──────────────────────────
class TestWhitening(unittest.TestCase):
    def test_get_params_returns_dict_or_none(self):
        # corpus < 20 면 None, ≥ 20 이면 dict
        from valuation_engine.embedding_whitening import get_params, _MIN_CORPUS
        p = get_params()
        if p is not None:
            self.assertIn("mu", p)
            self.assertIn("top_pcs", p)
            self.assertGreaterEqual(p["n_corpus"], _MIN_CORPUS)

    def test_whiten_vector_normalized(self):
        import numpy as np
        from valuation_engine.embedding_whitening import whiten_vector
        # params=None 시 정규화만
        v = np.array([1.0, 2.0, 3.0, 4.0])
        w = whiten_vector(v, None)
        self.assertAlmostEqual(float(np.linalg.norm(w)), 1.0, places=5)

    def test_whiten_with_params_normalized(self):
        # corpus 있어서 fit 됐을 때 — 결과 정규화 보장
        import numpy as np
        from valuation_engine.embedding_whitening import get_params, whiten_vector
        params = get_params()
        if params is None:
            self.skipTest("whitening corpus 부족")
        # mu 와 같은 차원의 임의 벡터
        v = np.random.randn(params["mu"].size).astype(float)
        v = v / np.linalg.norm(v)
        w = whiten_vector(v, params)
        self.assertAlmostEqual(float(np.linalg.norm(w)), 1.0, places=5)


# ── D-8: 재무구조 기반 holding 판정 ──────────────────────────────
class TestD8HoldingFinancial(unittest.TestCase):
    """D-8: 지분법투자/자본총계 비율 기반 holding 판정.

    임계 (peer_selector.INV_ASSOC_RATIO_HOLDING_*):
      · 40~70%  → 지주의심
      · 70%+    → 순수지주
      · 그 외   → operating 회사 (피어 적격)
    """

    def test_operating_company_low_ratio_pass(self):
        """삼성전기 — 지분법투자 0.6% → 정상 operating."""
        from valuation_engine.peer_selector import _is_holding_by_financials
        is_h, reason = _is_holding_by_financials({"inv_assoc_ratio": 0.006})
        self.assertFalse(is_h)
        self.assertIsNone(reason)

    def test_pure_holding_high_ratio(self):
        """LG·SK 류 순수지주 — 80% → 명확히 holding."""
        from valuation_engine.peer_selector import _is_holding_by_financials
        is_h, reason = _is_holding_by_financials({"inv_assoc_ratio": 0.80})
        self.assertTrue(is_h)
        self.assertIn("순수지주", reason)

    def test_suspected_holding_mid_ratio(self):
        """40~70% — 지주 의심 강한 신호."""
        from valuation_engine.peer_selector import _is_holding_by_financials
        is_h, reason = _is_holding_by_financials({"inv_assoc_ratio": 0.50})
        self.assertTrue(is_h)
        self.assertIn("지주의심", reason)

    def test_missing_data_graceful_pass(self):
        """데이터 부재(None) — 통과 (graceful)."""
        from valuation_engine.peer_selector import _is_holding_by_financials
        is_h, reason = _is_holding_by_financials({"inv_assoc_ratio": None})
        self.assertFalse(is_h)
        self.assertIsNone(reason)

    def test_threshold_boundary_just_below(self):
        """39.9% — 임계 직전 통과."""
        from valuation_engine.peer_selector import _is_holding_by_financials
        is_h, _ = _is_holding_by_financials({"inv_assoc_ratio": 0.399})
        self.assertFalse(is_h)

    def test_threshold_boundary_just_above(self):
        """40.1% — 임계 직후 차단."""
        from valuation_engine.peer_selector import _is_holding_by_financials
        is_h, _ = _is_holding_by_financials({"inv_assoc_ratio": 0.401})
        self.assertTrue(is_h)

    def test_extract_equity_method_from_noa_items(self):
        """v3 캐시 noa_items 에서 InvestmentAccountedForUsingEquityMethod 추출."""
        from valuation_engine.peer_selector import _extract_equity_method_investment
        fin = {
            "noa_items": [
                {"tag": "CashAndCashEquivalents", "val": 1_000_000},
                {"tag": "InvestmentAccountedForUsingEquityMethod", "val": 62_167_547_879},
                {"tag": "NoncurrentRecognisedAssetsDefinedBenefitPlan", "val": 280_753_879_535},
            ]
        }
        self.assertEqual(_extract_equity_method_investment(fin), 62_167_547_879.0)

    def test_extract_equity_method_missing_returns_zero(self):
        """noa_items 없거나 태그 없으면 0 (operating 신호와 동치)."""
        from valuation_engine.peer_selector import _extract_equity_method_investment
        self.assertEqual(_extract_equity_method_investment({}), 0.0)
        self.assertEqual(_extract_equity_method_investment({"noa_items": []}), 0.0)
        self.assertEqual(_extract_equity_method_investment({"noa_items": [
            {"tag": "CashAndCashEquivalents", "val": 1_000_000}]}), 0.0)

    def test_is_dcf_unsuitable_with_financials_signals(self):
        """is_dcf_unsuitable 시그니처 확장 — financials_signals 인자 동작."""
        from valuation_engine.industry_classifier import is_dcf_unsuitable
        # 키워드는 정상이지만 재무구조가 holding 인 경우 → 차단
        is_u, reason = is_dcf_unsuitable(
            "000001", name="가상회사", industry="전자부품", products="반도체",
            financials_signals={"inv_assoc_ratio": 0.85}
        )
        self.assertTrue(is_u)
        self.assertIn("순수지주", reason or "")

    def test_is_dcf_unsuitable_without_financials_signals(self):
        """financials_signals 미전달 시 기존 동작 그대로 (regression 가드)."""
        from valuation_engine.industry_classifier import is_dcf_unsuitable
        is_u, _ = is_dcf_unsuitable(
            "000001", name="가상회사", industry="전자부품", products="반도체"
        )
        self.assertFalse(is_u)

    # ── D-8 2차 신호 ②: 지분법손익 / |영업이익| ──────────────────────
    def test_high_equity_method_income_flagged(self):
        """신호 ② — |지분법손익|/|영업이익| > 50% → operating peer 부적합.

        시나리오: 영업회사처럼 보이지만 자회사 지분법손익이 영업이익을 압도.
        신호 ①(inv_assoc_ratio) 임계 미만이라도 ② 단독으로 차단되는지 확인.
        """
        from valuation_engine.peer_selector import _is_holding_by_financials
        is_h, reason = _is_holding_by_financials({
            "inv_assoc_ratio": 0.15,    # ① 30% 미만 → 단독으론 통과
            "em_income_ratio": 0.65,    # ② 50% 초과 → 차단
        })
        self.assertTrue(is_h)
        self.assertIn("지분법손익", reason)

    def test_equity_method_income_below_threshold_pass(self):
        """신호 ② — 50% 이하면 통과 (정상 operating).

        예: 두산(2025) em_income_ratio = 2.5% → operating 으로 분류.
        """
        from valuation_engine.peer_selector import _is_holding_by_financials
        is_h, _ = _is_holding_by_financials({
            "inv_assoc_ratio": 0.05,
            "em_income_ratio": 0.025,
        })
        self.assertFalse(is_h)

    def test_equity_method_income_boundary_just_above(self):
        """신호 ② — 50.1% → 임계 직후 차단."""
        from valuation_engine.peer_selector import _is_holding_by_financials
        is_h, _ = _is_holding_by_financials({"em_income_ratio": 0.501})
        self.assertTrue(is_h)

    # ── D-8 2차 신호 ③: 세그먼트 HHI ─────────────────────────────────
    def test_diversified_segments_flagged(self):
        """신호 ③ — 1위 < 60% AND 부문 ≥ 3 → 복합기업.

        시나리오: 두산형 (1위 44.9%, 5부문, HHI ≈ 0.38).
        HHI < 0.36 ≈ 1위 60% 미만 동치 — 본 케이스는 HHI 0.385 로 약간 위지만
        '1위 < 60% AND ≥ 3' 조건 만족 → 트리거.
        """
        from valuation_engine.peer_selector import _is_holding_by_financials
        is_h, reason = _is_holding_by_financials({
            "segment_top_share":  0.449,
            "segment_n_segments": 5,
            "segment_hhi":        0.385,
        })
        self.assertTrue(is_h)
        self.assertIn("복합기업", reason)
        self.assertIn("5부문", reason)

    def test_diversified_3segments_hhi_below_036_flagged(self):
        """신호 ③ — HHI < 0.36 케이스 (1위 40%, 3부문 균등 가까움)."""
        from valuation_engine.peer_selector import _is_holding_by_financials
        is_h, reason = _is_holding_by_financials({
            "segment_top_share":  0.40,
            "segment_n_segments": 3,
            "segment_hhi":        0.34,
        })
        self.assertTrue(is_h)
        self.assertIn("복합기업", reason)

    def test_concentrated_segments_pass(self):
        """신호 ③ — 1위 ≥ 60% → 지배사업, 부문 수 무관하게 통과."""
        from valuation_engine.peer_selector import _is_holding_by_financials
        is_h, _ = _is_holding_by_financials({
            "segment_top_share":  0.85,
            "segment_n_segments": 3,
            "segment_hhi":        0.74,
        })
        self.assertFalse(is_h)

    def test_few_segments_pass_even_if_below_60(self):
        """신호 ③ — 부문 < 3 이면 1위 비중 낮아도 통과 (단일 사업 + 부수)."""
        from valuation_engine.peer_selector import _is_holding_by_financials
        is_h, _ = _is_holding_by_financials({
            "segment_top_share":  0.55,
            "segment_n_segments": 2,
        })
        self.assertFalse(is_h)

    def test_segment_boundary_top_share_exact_60_pass(self):
        """신호 ③ — 1위 = 60% (경계, 미만 아님) → 통과."""
        from valuation_engine.peer_selector import _is_holding_by_financials
        is_h, _ = _is_holding_by_financials({
            "segment_top_share":  0.60,
            "segment_n_segments": 5,
        })
        self.assertFalse(is_h)

    # ── D-8 2차: ② ③ graceful (XBRL 부재 캐시 보호) ───────────────────
    def test_signal_2_3_missing_data_graceful(self):
        """신호 ② ③ 모두 부재 → 통과 (graceful — XBRL 미수집/구 캐시)."""
        from valuation_engine.peer_selector import _is_holding_by_financials
        is_h, _ = _is_holding_by_financials({
            "inv_assoc_ratio": 0.10,    # ① 통과
            "em_income_ratio": None,    # ② 부재
            "segment_top_share": None,  # ③ 부재
            "segment_n_segments": None,
        })
        self.assertFalse(is_h)


if __name__ == "__main__":
    unittest.main()
