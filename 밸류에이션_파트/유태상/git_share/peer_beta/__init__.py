"""peer_beta - 피어 기업 Levered Beta 회귀 및 Blume 조정 모듈.

설계서 v4 §1.6 기준:
- 기간: 평가기준일 직전 2년
- 빈도: 주간 종가 로그수익률 (매주 금요일, 공휴일이면 직전 영업일)
- 벤치마크: KOSPI 종목 -> KOSPI 지수 / KOSDAQ 종목 -> KOSDAQ 지수
- 회귀: OLS (절편 포함)
- 검증: R^2 < 0.1, |z| > 4 이상치, 결측주, 상장 2년 미만
- Blume 조정: beta_adj = 0.67 * beta_raw + 0.33 * 1.0

사용 예시:
    from peer_beta.run_beta import run
    result = run(eval_date="2026-05-14")  # 또는 None -> today
    print(result["peers"]["LG생활건강"]["beta_adjusted"])

팀원의 XBRL 추출 결과(피어 D, E)와 합쳐 Hamada Unlever를 수행할 때는
beta_adjusted 값을 그대로 가져다 쓰면 됩니다.
"""
from .config import DEFAULT_PEERS, BETA_CONFIG  # noqa: F401
