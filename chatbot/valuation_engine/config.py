"""기업가치 평가 통합 상수.

설계 결정 (팀 회의 후 v3 — Forward DCF 복원):
  - Forward DCF (FCFF 5년 명시예측 + Gordon Growth TV) 유지
  - 단, FCFF Y+1 또는 EV 가 음수인 회사는 DCF 결과 표시 안 함
  - 정상화 표본: 최근 3년 (FY2023~FY2025) — DART XBRL 안정 확보 구간
  - ERP: 8% 고정 (한공회 가이던스 7~9% 중간값) — 신뢰구간 wacc_engine 에서 별도

설계 원칙:
  1. 현금성자산: Net Debt에서만 차감, NOA 제외 (이중차감 방지)
  2. 정상화 비율: 3년 평균 (OPM, D&A율, CapEx율, NWC율)
  3. 세율: max(유효, 한계) — DCF 는 매년 예측 EBIT 기준 갱신
  4. SRP: 시총 자동 매칭 (3분위 디폴트, 한공회 2025-06-10)
  5. NOA: 팀원 NOA_RULES_FINAL_V3 (확실/기본/조건부/OA/별도처리 5분류)
  6. 피어: config 의 TARGET + PEERS (자동 산정은 임베딩 완료 후 별도 모듈)
  7. T: today() 자동
  8. 임의값 절대 금지 — RAG/API 실패 시 RuntimeError
  9. FCFF 음수 회사: DCF 결과 숨김 (대신 멀티플만 표시)
"""
from __future__ import annotations
from pathlib import Path

# ── 모델 버전 ──────────────────────────────────────────────────────
# 평가 로직·산식이 바뀌면 갱신 → valuation 결과 JSON 에 기록된다. api._cache_is_fresh
# 가 캐시의 model_version 을 현재 값과 대조해, 구버전이면 stale 판정(자동 재평가).
# → 코드 개선(아래 v5 등)이 배포 즉시 사용자 결과에 반영된다.
#   v4: PoC 초판 / v5: 14-Phase 정밀화 / v6: FCFF 현실화(OPM 수렴완화·성장 own중심·g_perp 2.5%)
#   v7: 투자기 성장주 허용(dcf_valid=EV>0) + NWC율 winsorized_median(이상치 robust)
#   v8: 피어 βU median→이상치제외(MAD/Damodaran배수/D-E극단가드)+유사도가중평균
#       +Damodaran혼합(Vasicek shrinkage × gap-aware)
#   v9: NOA 과대 가드 — 비영업자산(NOA)이 시가총액 3배 초과 시 DCF 부적합(자산·지주회사 → NAV/SOTP 권장)
MODEL_VERSION = "v9"

# ── 평가 대상 ──────────────────────────────────────────────────────
# ⚠ 동시성·mutation 정책 (Phase 7 / H11):
#   TARGET·PEERS·ALL_COMPANIES 는 런타임에 run_valuation_auto._swap_config_target_peers()
#   가 in-place(clear + update/extend)로 교체한다. 다른 모듈이 `from .config import TARGET`
#   으로 잡은 '동일 참조'를 유지하기 위함이다. 따라서:
#     · 읽기전용(MappingProxyType) 보호는 불가 — in-place swap 자체가 막혀 시스템이 멈춤.
#     · 직접 mutation 금지 → 반드시 _swap_config_target_peers() 단일 경로로만 교체.
#     · 동시 평가 시 run_valuation_auto._VALUATION_LOCK(RLock)으로 직렬화 필수(이미 적용).
#     · 근본 해결(요청범위 ValuationContext 객체 전달)은 30+ 파일 영향 → 별도 과제(DAY3+).
TARGET = {"name": "현대건설", "ticker": "000720",
          "corp_code": "00164742", "market": "KOSPI"}

PEERS = [
    {"name": "대우건설",     "ticker": "047040", "market": "KOSPI"},
    {"name": "GS건설",       "ticker": "006360", "market": "KOSPI"},
    {"name": "코오롱글로벌", "ticker": "003070", "market": "KOSPI"},
]

ALL_COMPANIES = [TARGET] + PEERS

# ── 회계연도 (FY2025 기준 최근 3개년 — XBRL via DART API) ──────────
# DART XBRL 사업보고서는 안정적으로 최근 3개년만 확보 가능 (신규상장·정정 등으로
# 과거 연도는 status 014 빈번). 설계서 §2.1 정상화 비율도 3년 평균 기준.
# 데이터 출처: DART OpenAPI XBRL (xbrl_financials_v4 모듈)
FISCAL_YEARS = [2023, 2024, 2025]

# ── WACC 상수 ──────────────────────────────────────────────────────
# ERP: 단일값 (mid). 신뢰구간(7~9%) 은 wacc_engine 의 ERP_LOW/HIGH 사용.
#   근거·정책: 한국공인회계사회(한공회) 가치평가 가이던스 권고구간 7~9% 의 중간값 8%.
#   참고: Damodaran implied 한국 ERP 는 6~7% 수준이나, 본 PoC 는 한국 감정평가·
#   회계 실무 표준인 한공회 가이던스를 채택한다. 점추정 8% + 민감도(7~9%) 동시 제시로
#   투명성 확보. ERP 는 Ke·적정주가에 가장 민감한 단일 가정이므로 구간을 함께 보고한다.
ERP = 0.08            # 한공회 가이던스 7~9% 중간값
CRP = 0.0             # 한국 단일시장 (국내투자자 관점). Damodaran 외국인관점 CRP 0.5~0.85%p 별개.

# ── SRP 테이블 (한공회 2025-06-10, 3분위수 디폴트) ────────────────
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

# ── DCF Fade-out 곡선 ─────────────────────────────────────────────
# 영구성장률 — 2.0%→2.5% 상향(현실화). 한국 명목 GDP(~3%) 이내이되 물가상승분을
#   반영해, 영구 2% 고정이 유발하던 구조적 과소평가를 완화. (Damodaran: g ≤ 명목 GDP)
G_PERPETUAL = 0.025

# 명시예측 매출 성장률 상한 (Y+1 출발 성장률 cap).
#   경기민감주(반도체·화학 등)는 '불황 바닥→피크' 회복 구간의 3년 CAGR 이
#   비현실적으로 폭등(예: SK하이닉스 72%)해 ΔNWC·CapEx 가 과대 → FCFF 음수 왜곡.
#   이론 근거(Damodaran): 어떤 기업도 5년 명시예측 전체에 거시+산업성숙도를
#   크게 초과하는 성장을 지속할 수 없음. 일회성 회복은 지속성장이 아님.
#   한국 명목 GDP ~3-4% 대비 연 20%(5년 후 매출 2.5배)는 이미 매우 공격적 상한.
MAX_EXPLICIT_GROWTH = 0.20

FADE_OUT = {
    "Y1": ("3y_cagr",   1.0),    # Y+1 = 3년 CAGR
    "Y2": ("3y_cagr",   0.8),    # Y+2 = 3년 CAGR × 0.8
    "Y3": ("prev",      0.7),    # Y+3 = Y+2 × 0.7
    "Y4": ("prev",      0.7),    # Y+4 = Y+3 × 0.7
    "Y5": ("g_perp",    1.0),    # Y+5 = g_perpetual (영구 정착)
}

# ── Terminal Value 정합성 (Damodaran) ──────────────────────────────
# (#1) 영구구간 재투자율 = g_perp / ROIC_terminal 로 일관화 → 2% 영구성장을
#      지원하는 데 필요한 재투자만 차감. 명시예측 마지막 해의 CapEx율을 그대로
#      영구화하던 비일관성 제거.
# (#2) ROIC_terminal 수렴 — 초과수익(ROIC>WACC)이 영구 지속되지 않도록:
#      "auto":             Damodaran "경쟁우위에 따라 차등" — 데이터로 자동 판정 (디폴트)
#                          · 신호 A(지속성): 과거 ROIC 가 전 연도 WACC 초과
#                          · 신호 B(경쟁우위): 타깃 ROIC > 피어 중위 ROIC
#                          → A·B 모두 충족 시에만 ROIC_terminal=implied_roic(초과수익 유지),
#                            아니면 WACC 수렴. 임의판단 없이 펀더멘털로 결정.
#      "converge_to_wacc": ROIC_terminal = WACC (무초과수익, 가장 보수적)
#      "sustain":          ROIC_terminal = max(implied_roic, WACC) (경쟁우위 항상 가정)
TERMINAL_ROIC_MODE = "auto"

# moat(경제적 해자) 지속성 판정 임계 — 평균 ROIC 가 WACC 를 이 배수 이상 초과해야
#   '지속 가능한 초과수익' 으로 인정(경계 근처 초과는 노이즈로 배제). 향후 민감도·튜닝
#   대상 정책값이라 상수화(dcf_engine 의 moat persistence 판정에서 사용).
MOAT_ROIC_WACC_MARGIN = 1.15

# (#3) Mid-year convention — 현금흐름 연중 균등발생 가정 → (t−0.5) 할인.
#      연말발생 가정은 EV 를 체계적으로 ~WACC/2 과소평가하므로 보정.
MID_YEAR_CONVENTION = True

# ── 정상화 비율 검증 ──────────────────────────────────────────────
NORMALIZATION_OUTLIER_THRESHOLD = 0.50   # 정상화 표본 중 평균 대비 ±50% 이격 시 경고

# ── 발행/유통주식수 검산 (단위오류·오추출 탐지) ───────────────────────
# 사업보고서 '주식의 총수' 표가 천주(1,000)/백만주(1,000,000) 단위로 표기되면
#   RAG/LLM 이 단위 없이 109,142(=109,142천주) 처럼 읽어 발행주식수가 ×1000/×100
#   과소 추출된다. 그러면 적정주가(=자기자본가치/유통주식)가 그만큼 폭등한다
#   (현대로템: 109,142천주→109,142 로 1000배 과소 → 적정주가 9,328만원, upside +43,692%).
# 기존 '10만~100억주' 범위 검산만으로는 109,142(=10.9만)가 통과 → 아래 교차검증 추가.
#
# 임계값 설계 원칙: '단위오류(×1000/×100)만 잡고 정상 종목은 통과'하도록 자릿수 수준의
#   넉넉한 밴드를 쓴다(정밀 밸류에이션 밴드가 아님). 한국 상장사 P/B 실측은 사실상
#   [0.05, 50] 안이므로 [0.02, 200] 밖이면 주식수 자릿수 오류로 간주한다.
SHARES_PB_FLOOR = 0.02      # 시가총액(종가×유통주식) / 자본총계 하한 — 미만이면 주식수 과소 의심
SHARES_PB_CEIL  = 200.0     # 상한 — 초과면 주식수 과대 의심
# 역산 적정주가(=자기자본가치/유통주식)가 이 값을 넘으면 유통주식수 과소(역산 주식수
#   비현실적으로 작음) 의심. 한국 역대 최고가주(영풍·태광산업 등 ~150만원대)의 3배 초과.
FAIR_PRICE_SANITY_CEIL_WON = 5_000_000
# 직전 연도 발행주식 총수 대비 허용 배수 — 이 밖이면 단위오류/오추출 의심.
#   (증자·감자·액면분할로도 보통 10배를 넘지 않음. 넘으면 재추출로 재확인.)
SHARES_YOY_RATIO_LOW  = 0.1
SHARES_YOY_RATIO_HIGH = 10.0

# ── 토네이도 ± 변동 범위 ──────────────────────────────────────────
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

# v3 통합 표준 경로 — XBRL 캐시 (FISCAL_YEARS 시계열 + 자본·NCI·EPS 통합)
# VAR/data/xbrl/<corp_name>_<year>.json 로 통일
VAR_ROOT      = MODULE_DIR.parent
XBRL_RESULTS  = VAR_ROOT / "data" / "xbrl"

# 팀원 옛 경로 — 호환 fallback 탐색용 (자동 마이그레이션 예정)
XBRL_LEGACY_DIRS = [
    VAR_ROOT / "XBRL" / "xbrl_results_2021",
    VAR_ROOT / "XBRL" / "xbrl_results_2022",
    VAR_ROOT / "XBRL" / "xbrl_results_2023",
    VAR_ROOT / "XBRL" / "xbrl_results_2024",
    VAR_ROOT / "XBRL" / "xbrl_results_2025",
    DATA_DIR / "xbrl",        # v2 옛 경로
]

EQUITY_DIR    = DATA_DIR / "equity"         # E (시총)
WACC_DIR      = DATA_DIR / "wacc"
DCF_DIR       = DATA_DIR / "dcf"            # [deprecated] Forward DCF 산출물
RESULTS_DIR   = MODULE_DIR / "results"      # 최종 valuation_<T>.json

for _d in (XBRL_RESULTS, EQUITY_DIR, WACC_DIR, DCF_DIR, RESULTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ── 환경변수 키 ─────────────────────────────────────────────────────
ENV_KEY_DART = "DART_API_KEY"
ENV_KEY_ECOS = "ECOS_API_KEY"
ENV_KEY_KRX  = "krxdata"
