# -*- coding: utf-8 -*-
"""DAY2 A-3: 골든 케이스 통합 회귀 테스트.

목적:
  단위 테스트 51개는 OK이나 end-to-end 회귀 안전망 없음. 미래 리팩토링·
  데이터 갱신 시 silent 변경(예: fair_price 가 의도 없이 30% 이동) 자동 감지.

대상:
  golden_cases/{ticker}_{date}.json 에 저장된 기대값 vs results/{...}.json 실측값.

비교 정책:
  · fair_price       : ±5%      (스냅숏 시점 대비 — 환율·시총 변동 흡수)
  · wacc             : ±0.5%p
  · peer_confidence  : ±10점     (점수)  / grade 는 정확 일치
  · dcf_grade        : 정확 일치
  · industry_category: 정확 일치
  · n_peers          : 정확 일치 (≥ 3)

snapshot 갱신:
  의도된 변경(모델 개선 등)으로 기대값이 바뀌면 snapshot 도 같은 PR 에서 갱신.
  무지성 갱신 금지 — 변경 사유를 PR 설명에 남길 것.

실행:
  python -m unittest valuation_engine.tests.test_golden_cases -v
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

_VAR_ROOT = Path(__file__).resolve().parent.parent.parent
GOLDEN_DIR = _VAR_ROOT / "valuation_engine" / "tests" / "golden_cases"
RESULTS_DIR = _VAR_ROOT / "valuation_engine" / "results"


def _load_snapshot(ticker: str, date: str) -> dict:
    # snapshot 파일명 컨벤션: {ticker}_{YYYYMMDD}.json (results 와 동일)
    p = GOLDEN_DIR / f"{ticker}_{date.replace('-', '')}.json"
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def _load_actual(ticker: str, date: str) -> dict:
    p = RESULTS_DIR / f"valuation_{ticker}_{date.replace('-', '')}.json"
    if not p.exists():
        return None
    with p.open("r", encoding="utf-8") as f:
        d = json.load(f)
    s = d.get("summary", {}) or {}
    pc = d.get("peer_confidence", {}) or {}
    vd = d.get("valuation_diagnostics", {}) or {}
    return {
        "fair_price": s.get("fair_price"),
        "wacc": s.get("wacc"),
        "dcf_grade": s.get("dcf_grade"),
        "peer_confidence_grade": s.get("peer_confidence_grade"),
        "peer_confidence_score": s.get("peer_confidence_score"),
        "industry_category": s.get("industry_category") or vd.get("industry_category"),
        "n_peers": pc.get("n_peers"),
        "fair_price_low": s.get("fair_price_low"),
        "fair_price_high": s.get("fair_price_high"),
    }


class _GoldenCaseBase(unittest.TestCase):
    """공통 비교 로직 — 자식 TestCase 가 ticker / date 만 지정."""
    ticker = None
    date = None

    @classmethod
    def setUpClass(cls):
        if cls.ticker is None:
            raise unittest.SkipTest("base — no ticker")
        cls.snap = _load_snapshot(cls.ticker, cls.date)
        cls.actual = _load_actual(cls.ticker, cls.date)
        if cls.actual is None:
            raise unittest.SkipTest(
                f"results/valuation_{cls.ticker}_{cls.date.replace('-','')}.json 없음 — "
                f"평가 실행 후 회귀 검증 가능."
            )

    def test_fair_price_within_tolerance(self):
        tol_pct = self.snap["meta"]["tolerance"]["fair_price_pct"]
        expect = self.snap["fair_price"]
        actual = self.actual["fair_price"]
        self.assertIsNotNone(actual, "fair_price 누락")
        rel = abs(actual - expect) / abs(expect) if expect else 0
        self.assertLessEqual(
            rel, tol_pct,
            f"[{self.ticker}] fair_price drift {rel*100:.2f}% > {tol_pct*100:.1f}% "
            f"(expect {expect:,.0f} → actual {actual:,.0f})"
        )

    def test_wacc_within_tolerance(self):
        tol_pp = self.snap["meta"]["tolerance"]["wacc_pp"]
        expect = self.snap["wacc"]
        actual = self.actual["wacc"]
        self.assertIsNotNone(actual, "wacc 누락")
        self.assertLessEqual(
            abs(actual - expect), tol_pp,
            f"[{self.ticker}] WACC drift {(actual-expect)*100:+.2f}%p > "
            f"±{tol_pp*100:.1f}%p (expect {expect*100:.2f}% → actual {actual*100:.2f}%)"
        )

    def test_dcf_grade_exact_match(self):
        self.assertEqual(
            self.actual["dcf_grade"], self.snap["dcf_grade"],
            f"[{self.ticker}] dcf_grade drift "
            f"{self.snap['dcf_grade']} → {self.actual['dcf_grade']}"
        )

    def test_peer_confidence_grade_exact(self):
        self.assertEqual(
            self.actual["peer_confidence_grade"], self.snap["peer_confidence_grade"],
            f"[{self.ticker}] peer_confidence_grade drift "
            f"{self.snap['peer_confidence_grade']} → "
            f"{self.actual['peer_confidence_grade']}"
        )

    def test_peer_confidence_score_within_tolerance(self):
        tol = self.snap["meta"]["tolerance"]["peer_confidence_score"]
        expect = self.snap["peer_confidence_score"]
        actual = self.actual["peer_confidence_score"]
        self.assertIsNotNone(actual, "peer_confidence_score 누락")
        self.assertLessEqual(
            abs(actual - expect), tol,
            f"[{self.ticker}] peer_confidence_score drift "
            f"{actual - expect:+d} > ±{tol} (expect {expect} → actual {actual})"
        )

    def test_industry_category_exact(self):
        self.assertEqual(
            self.actual["industry_category"], self.snap["industry_category"],
            f"[{self.ticker}] industry_category drift "
            f"{self.snap['industry_category']} → {self.actual['industry_category']}"
        )

    def test_n_peers_min_three(self):
        n = self.actual.get("n_peers")
        self.assertIsNotNone(n, "n_peers 누락")
        self.assertGreaterEqual(n, 3, f"[{self.ticker}] 피어 {n} < 3")
        expect_n = self.snap.get("n_peers")
        if expect_n is not None:
            self.assertEqual(
                n, expect_n,
                f"[{self.ticker}] n_peers drift {expect_n} → {n}"
            )


# ── 종목별 회귀 클래스 ────────────────────────────────────────
class TestGolden_009150_SamsungElectro(_GoldenCaseBase):
    """삼성전기 009150 (전자부품, cyclical) 회귀."""
    ticker = "009150"
    date = "2026-05-30"


class TestGolden_035420_NAVER(_GoldenCaseBase):
    """NAVER 035420 (인터넷/소프트웨어, growth) 회귀."""
    ticker = "035420"
    date = "2026-05-30"


class TestGolden_329180_HDHeavy(_GoldenCaseBase):
    """HD현대중공업 329180 (조선, growth) 회귀."""
    ticker = "329180"
    date = "2026-05-30"


if __name__ == "__main__":
    unittest.main()
