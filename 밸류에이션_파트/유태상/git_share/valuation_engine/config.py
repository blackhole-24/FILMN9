"""기업가치 평가 통합 상수.

8개 결정사항 (일반투자자 관점):
  1. 현금성자산: Net Debt에서만 차감, NOA 제외
  2. 정상화 비율: 3년 평균 (OPM, D&A율, CapEx율, NWC율)
  3. 세율: max(유효, 한계) 보수적
  4. SRP: 시총 자동 매칭 (3분위 디폴트)
  5. NOA: 팀원 NOA_RULES_FINAL_V3 그대로 (확실 6항목 보완 안 함)
  6. 에이피알: 피어 포함
  7. T: today() 자동
  8. 추가 필드: 별도 모듈 (compute_equity.py 등)
"""
from __future__ import annotations
from pathlib import Path

# ── 평가 대상 ──────────────────────────────────────────────────────
TARGET = {"name": "현대건설", "ticker": "000720",
          "corp_code": "00164742", "market": "KOSPI"}

PEERS = [
    {"name": "대우건설",     "ticker": "047040", "market": "KOSPI"},
    {"name": "GS건설",       "ticker": "006360", "market": "KOSPI"},
    {"name": "코오롱글로벌", "ticker": "003070", "market": "KOSPI"},
]

ALL_COMPANIES = [TARGET] + PEERS

# ── 회계연도 (POC: FY2025 사업보고서 기준 3개년) ──────────────────
FISCAL_YEARS = [2023, 2024, 2025]

# ── WACC 상수 ──────────────────────────────────────────────────────
ERP = 0.08            # 한공회 가이던스 7~9% 중간 (v4 §1.2)
CRP = 0.0             # POC (v4 §1.4)

# ── SRP 테이블 (한공회 2025-06-10, v4 §1.3 3분위수 디폴트) ─────────
# 단위: 백만원. 평가기준일 직전 사업연도말 시가총액으로 매칭.
SRP_TERCILE = [
    {"name": "Mid",   "srp": -0.0036, "min":   684805, "max": 333000000},
    {"name": "Low",   "srp":  0.0137, "min":   225687, "max":    683357},
    {"name": "Micro", "srp":  0.0402, "min":    30080, "max":    225640},
]


def match_srp(market_cap_won: float) -> tuple[float, str]:
    """시가총액(원) → SRP(소수), 구간명. v4 §1.3 자동 매칭."""
    mcap_mn = market_cap_won / 1e6   # 원 → 백만원
    for tier in SRP_TERCILE:
        if tier["min"] <= mcap_mn <= tier["max"]:
            return tier["srp"], tier["name"]
    # 범위 밖이면 가까운 구간
    if mcap_mn > SRP_TERCILE[0]["max"]:
        return SRP_TERCILE[0]["srp"], SRP_TERCILE[0]["name"]
    return SRP_TERCILE[-1]["srp"], SRP_TERCILE[-1]["name"]


# ── 한계세율 (팀원 함수와 동일, 백업용) ───────────────────────────
TAX_BRACKETS_WON = [
    (200_000_000,        0.110),   # 2억 이하
    (20_000_000_000,     0.220),   # 200억 이하
    (300_000_000_000,    0.242),   # 3000억 이하
    (float("inf"),       0.275),   # 3000억 초과
]

# ── DCF Fade-out 곡선 (v4 §2.3) ───────────────────────────────────
G_PERPETUAL = 0.02
FADE_OUT = {
    "Y1": ("3y_cagr",   1.0),
    "Y2": ("3y_cagr",   0.8),
    "Y3": ("prev",      0.7),
    "Y4": ("prev",      0.7),
    "Y5": ("g_perp",    1.0),
}

# ── 정상화 비율 검증 (v4 §2.2) ─────────────────────────────────────
NORMALIZATION_OUTLIER_THRESHOLD = 0.50  # 3년 중 평균 대비 ±50% 이상 이격 시 경고

# ── 토네이도 ± 범위 (v4 §3.3) ──────────────────────────────────────
TORNADO_RANGES = {
    "revenue_growth_y1": 0.02,
    "opm":               0.02,
    "capex_ratio":       0.02,
    "nwc_ratio":         0.02,
    "wacc":              0.01,
    "g_perpetual":       0.005,
}

# ── 경로 ───────────────────────────────────────────────────────────
MODULE_DIR    = Path(__file__).resolve().parent
DATA_DIR      = MODULE_DIR / "data"
XBRL_RESULTS  = DATA_DIR / "xbrl"           # 팀원 모듈 출력
EQUITY_DIR    = DATA_DIR / "equity"         # E (시총)
WACC_DIR      = DATA_DIR / "wacc"
DCF_DIR       = DATA_DIR / "dcf"
RESULTS_DIR   = MODULE_DIR / "results"      # 최종 valuation_<T>.json

for _d in (XBRL_RESULTS, EQUITY_DIR, WACC_DIR, DCF_DIR, RESULTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ── 환경변수 키 ─────────────────────────────────────────────────────
ENV_KEY_DART = "DART_API_KEY"
ENV_KEY_ECOS = "ECOS_API_KEY"
ENV_KEY_KRX  = "krxdata"
