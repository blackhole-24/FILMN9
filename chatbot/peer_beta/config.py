"""피어 리스트와 베타 계산 상수.

POC: 아모레퍼시픽 + 피어 3사 (LG생활건강, 한국콜마, 에이피알).
운영 단계에서는 DEFAULT_PEERS를 갈아 끼우거나 run()에 peers 인자로 주입하면 됩니다.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# 피어/타겟 리스트 (아모레퍼시픽 POC)
# ---------------------------------------------------------------------------
# market 값:
#   - "KOSPI"  -> KOSPI 지수와 회귀
#   - "KOSDAQ" -> KOSDAQ 지수와 회귀
# 타겟 자신도 피어처럼 베타를 계산해 두면, 운영 단계에서 sanity check로 활용 가능.
DEFAULT_PEERS: list[dict] = [
    {"name": "현대건설",     "ticker": "000720", "market": "KOSPI", "role": "target"},
    {"name": "대우건설",     "ticker": "047040", "market": "KOSPI", "role": "peer"},
    {"name": "GS건설",       "ticker": "006360", "market": "KOSPI", "role": "peer"},
    {"name": "코오롱글로벌", "ticker": "003070", "market": "KOSPI", "role": "peer"},
]

# ---------------------------------------------------------------------------
# 베타 회귀 설정
# ---------------------------------------------------------------------------
BETA_CONFIG: dict = {
    # 회귀 기간 (년)
    "lookback_years": 2,
    # 주간 종가 기준일 (0=월, 1=화, ..., 4=금)
    "weekday": 4,  # 금요일
    # Blume 조정 계수: beta_adj = alpha * beta_raw + (1-alpha) * 1.0
    # Blume(1971) 원본 = 2/3 (정확) = 0.666666...
    # KRX 공시 베타도 α = 2/3 사용 (역산 확인).
    # 설계서 §1.6 의 "0.67" 은 반올림 표기. 정확성을 위해 분수로 둠.
    "blume_alpha": 2 / 3,
    # 수익률 방식: "simple"(산술, P_t/P_{t-1}-1) | "log"(로그, ln)
    # KRX·한공회 공시 베타는 산술수익률 기준 → "simple" 이 공시값과 정합.
    "return_method": "simple",
    # 검증 임계치 (설계서 §1.6)
    "validation": {
        "r_squared_min": 0.10,        # R^2 < 0.10 -> 신뢰도 낮음 경고
        "residual_z_max": 4.0,        # |z| > 4 -> 이상치 일자 기록
        "missing_weeks_max": 0,       # 결측 주 >= 1 -> 경고 플래그
        # 상장연수 판단 — KRX 일별 API 에 상장일(LIST_DD)이 없어 list_dd 기반 판단 불가.
        # 대신 "2년 lookback 기대 주수 대비 실제 확보한 주간 관측 수 비율"로 판단:
        #   확보 주수 < 기대 주수 × min_weeks_2yr_ratio → 상장 2년 미만(또는 데이터 부족)
        # 신규상장은 lookback 앞부분에 종가가 아예 없어 관측 수가 크게 부족해짐.
        "min_weeks_2yr_ratio": 0.85,  # 기대 주수의 85% 미만이면 short_listing
    },
    # 이상치 처리 정책 (KRX 공시 베타와의 차이 보정 — 일반 투자자 대상)
    # "none"      : 설계서 §1.6 원안. 이상치 일자 기록만 하고 회귀에 포함.
    # "drop"      : 1차 OLS 후 표준화 잔차 |z| > residual_z_max 행을 제거하고 재회귀.
    #               표본 N 감소. 한 주를 통째로 무시.
    # "winsorize" : 1차 OLS 후 잔차의 |z| > winsorize_k 인 행의 r_stock 을
    #               (alpha + beta·r_index ± winsorize_k·σ_resid) 로 끌어당겨 재회귀.
    #               표본 N 유지. 한 주의 영향만 약화. ★ 일반 투자자 대상 권장.
    # 일반 투자자에게는 "이상치 한 주를 통째로 빼서 N이 줄었다"보다
    # "특이 사건이 있던 주의 영향을 ±3σ로 제한했다" 가 설명·이해가 더 자연스러움.
    "outlier_handling": "winsorize",
    # winsorize 임계 (잔차 표준편차 단위). Fama-French 등 실무 관행 = 3.0
    "winsorize_k": 3.0,
    # 시장 -> 지수명 매핑 (KRX 응답의 IDX_NM 값)
    # 실 응답에서 다른 표기가 보이면 이 값만 바꾸면 됩니다.
    "market_to_index_name": {
        "KOSPI":  "코스피",
        "KOSDAQ": "코스닥",
    },
}

# ---------------------------------------------------------------------------
# 경로 (모듈 루트 기준)
# ---------------------------------------------------------------------------
from pathlib import Path

MODULE_DIR  = Path(__file__).resolve().parent
DATA_DIR    = MODULE_DIR / "data"
RAW_DIR     = DATA_DIR / "raw"          # KRX 원본 JSON 캐시 (일자별 1파일)
PROC_DIR    = DATA_DIR / "processed"    # 정제된 주간 종가/수익률 CSV
RESULTS_DIR = MODULE_DIR / "results"    # 최종 베타 결과 JSON

for _d in (RAW_DIR, PROC_DIR, RESULTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# 환경변수 키 이름 (.env)
# ---------------------------------------------------------------------------
ENV_KEY_KRX = "krxdata"   # 사용자 지정 변수명
