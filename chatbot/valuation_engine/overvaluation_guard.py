"""DCF 적정가 과대 가드 — NOA 지주사 가드와 동일 철학의 '겸손 장치'.

배경:
  소·중형주에서 DCF 가 정상화 영업이익(NOPAT)을 과대 영구화하면, 적정가가 현재가의
  수 배~수십 배로 산출된다(예: 케이지에코솔루션 적정가 130,405 vs 현재가 5,830 = 22배).
  주식수·계산은 정상이지만(역산 주식수 = 발행주식수 일치), 시장은 그 이익이 지속
  불가능하다고 보고 낮게 가격한다(내재성장률 음수 = 시장 쇠퇴 가정). 즉 '모델과 시장이
  과도하게 충돌'하는 신호다. 이 경우 점추정을 확신하듯 노출하면 도구 신뢰가 깨진다.

처리:
  적정가 ÷ 현재가 > OVERVALUATION_GUARD_RATIO 이면
    - dcf_show_point_estimate = False  (점추정 숨김 → UI 가 '범위·5종 진단'으로 유도)
    - dcf_grade 를 D 로 하향 (이미 D·E 면 유지)
    - dcf_confidence 를 low 로 하향
    - 사유를 dcf_grade_reason 에 기록 + dcf_overvaluation_guard / _ratio 플래그
  fair_price 자체는 보존한다(범위·진단 참고용, 멀티플·EPV 와 교차검증 가능).

NOA 지주사 가드(equity_value.equity_value_valid=False → fair_price=None)와는 독립 신호다.
  - NOA 가드: 비영업자산(보유자산)이 시총의 3배 초과 → DCF 부적합(점·범위 모두 무효).
  - 본 가드: 영업가치 추정이 시장과 과도 괴리 → 점추정만 신뢰 불가(범위·진단은 유지).

순수 후처리(네트워크·재계산 불필요)라 import 가 가볍다. 평가 경로(run_valuation)와
기존 도큐먼트 일괄보정(backfill) 양쪽에서 동일 함수를 재사용한다.
"""
from __future__ import annotations

# DCF 적정가 ÷ 현재가 가 이 배수를 초과하면 점추정 신뢰 불가로 판정.
#   5.0 = 이 5종목만 포착(보수적) · 3.0 = 더 빡세게(추가 종목 포착). 튜닝은 이 한 값.
OVERVALUATION_GUARD_RATIO = 5.0


def apply_overvaluation_guard(summary: dict,
                              ratio_cap: float = OVERVALUATION_GUARD_RATIO) -> dict:
    """summary dict 를 in-place 보정하고 반환. 발동 조건 미충족 시 무변경.

    Parameters
    ----------
    summary : dict
        통합 평가 JSON 의 'summary' 블록 (fair_price·current_price·dcf_grade 등 포함).
    ratio_cap : float
        적정가/현재가 상한 배수. 초과 시 가드 발동.
    """
    if not isinstance(summary, dict):
        return summary

    fp = summary.get("fair_price")
    cp = summary.get("current_price")
    # 점추정이 없거나(이미 숨김/무효) 현재가 미상이면 대상 아님
    if not (isinstance(fp, (int, float)) and isinstance(cp, (int, float))):
        return summary
    if cp <= 0 or fp <= 0:
        return summary
    # 이미 점추정을 숨긴 등급(D·E)은 대상 아님 — 가드의 역할은 '노출된' 점추정 차단.
    #   기존 등급 사유(dcf_grade_reason)·신뢰도를 덮어쓰지 않도록 조기 반환.
    if summary.get("dcf_grade") not in ("A", "B", "C"):
        return summary

    ratio = fp / cp
    if ratio <= ratio_cap:
        return summary

    # ── 가드 발동 ──────────────────────────────────────────────
    summary["dcf_overvaluation_guard"] = True
    summary["dcf_overvaluation_ratio"] = round(ratio, 1)
    summary["dcf_show_point_estimate"] = False            # 점추정 숨김
    if summary.get("dcf_grade") in ("A", "B", "C"):       # 등급 하향 (D·E 는 유지)
        summary["dcf_grade"] = "D"
    if summary.get("dcf_confidence") not in ("invalid", "very_low", "low"):
        summary["dcf_confidence"] = "low"
    summary["dcf_grade_reason"] = (
        f"DCF 적정가(₩{fp:,.0f})가 현재가(₩{cp:,.0f})의 {ratio:.1f}배로, 모델 추정과 "
        f"시장가격이 과도하게 괴리합니다 — 정상화 이익 가정이 시장 기대와 크게 달라 "
        f"점추정 신뢰가 어렵습니다. 추정 범위·5종 진단을 참고하세요."
    )
    return summary
