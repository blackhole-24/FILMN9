"""
processors/ratio_calculator.py
────────────────────────────────
재무 건전성 5개 비율 계산 (Python only — LLM 사용 금지).

공식
────
부채비율    = 부채총계 / 자본총계 × 100
유동비율    = 유동자산 / 유동부채 × 100
이자보상배율 = 영업이익 / 금융비용(이자비용)
당좌비율    = (유동자산 - 재고자산) / 유동부채 × 100
유보율      = (자본잉여금 + 이익잉여금) / 자본금 × 100

출처: 재무상태표(연결) (financial_parser.get_financial_detail)
단위: 백만원 (비율은 %)
"""

from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.processors.financial_parser import get_financial_detail


# ─────────────────────────────────────────────────────────────────────────────
# 내부 유틸 — DataFrame에서 특정 항목 값 추출
# ─────────────────────────────────────────────────────────────────────────────

def _get_val(df: pd.DataFrame, keyword: str, year: str = "2025",
             exact: bool = False) -> float | None:
    """
    구분 컬럼에서 keyword 를 포함(또는 정확히 일치)하는 첫 번째 행의 year 컬럼 값.
    여러 행 매칭 시 첫 번째 비-NaN 값 반환.
    """
    if exact:
        mask = df["구분"].str.strip() == keyword
    else:
        mask = df["구분"].str.contains(keyword, na=False)

    matched = df[mask]
    if matched.empty:
        return None

    for _, row in matched.iterrows():
        val = row.get(year)
        if val is not None and not pd.isna(val):
            return float(val)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# 5개 비율 계산
# ─────────────────────────────────────────────────────────────────────────────

def calculate_ratios(
    stock_code: str = "090430",
    year: str = "2025",
    fs_type: str = "재무상태표(연결)",  # "재무상태표(연결)" | "별도재무제표"
) -> dict:
    """
    재무 건전성 5개 비율 계산.

    Returns
    -------
    {
      "부채비율"    : {"value": float, "부채총계": float, "자본총계": float, "단위": "%"},
      "유동비율"    : {"value": float, "유동자산": float, "유동부채": float, "단위": "%"},
      "이자보상배율" : {"value": float, "영업이익": float, "금융비용": float, "단위": "배"},
      "당좌비율"    : {"value": float, "유동자산": float, "재고자산": float, "유동부채": float, "단위": "%"},
      "유보율"      : {"value": float, "자본잉여금": float, "이익잉여금": float, "자본금": float, "단위": "%"},
      "_year"      : str,
      "_fs_type"   : str,
    }
    value 가 None 이면 계산 불가 (데이터 없음).
    """
    detail = get_financial_detail(stock_code)
    df = detail.get(fs_type)
    if df is None or df.empty:
        raise ValueError(f"재무제표 없음: {fs_type}")

    result: dict = {"_year": year, "_fs_type": fs_type}

    # ── 1) 부채비율 ──────────────────────────────────────────
    부채총계 = _get_val(df, "부채총계", year, exact=True)
    자본총계 = _get_val(df, "자본총계", year, exact=True)
    result["부채비율"] = {
        "부채총계" : 부채총계,
        "자본총계" : 자본총계,
        "단위"    : "%",
        "value"   : round(부채총계 / 자본총계 * 100, 2)
                    if 부채총계 and 자본총계 and 자본총계 != 0 else None,
    }

    # ── 2) 유동비율 ──────────────────────────────────────────
    유동자산 = _get_val(df, "유동자산", year, exact=True)
    유동부채 = _get_val(df, "유동부채", year, exact=True)
    result["유동비율"] = {
        "유동자산" : 유동자산,
        "유동부채" : 유동부채,
        "단위"    : "%",
        "value"   : round(유동자산 / 유동부채 * 100, 2)
                    if 유동자산 and 유동부채 and 유동부채 != 0 else None,
    }

    # ── 3) 이자보상배율 ───────────────────────────────────────
    영업이익 = _get_val(df, "영업이익", year, exact=True)
    금융비용 = _get_val(df, "금융비용", year, exact=True)
    # 금융비용이 없으면 이자의 지급(현금흐름) 절댓값으로 대체
    if 금융비용 is None:
        금융비용_raw = _get_val(df, "이자의 지급", year)
        금융비용 = abs(금융비용_raw) if 금융비용_raw else None
    result["이자보상배율"] = {
        "영업이익" : 영업이익,
        "금융비용" : 금융비용,
        "단위"    : "배",
        "value"   : round(영업이익 / 금융비용, 2)
                    if 영업이익 and 금융비용 and 금융비용 != 0 else None,
    }

    # ── 4) 당좌비율 ──────────────────────────────────────────
    재고자산 = _get_val(df, "재고자산", year, exact=True)
    result["당좌비율"] = {
        "유동자산" : 유동자산,
        "재고자산" : 재고자산,
        "유동부채" : 유동부채,
        "단위"    : "%",
        "value"   : round((유동자산 - (재고자산 or 0)) / 유동부채 * 100, 2)
                    if 유동자산 and 유동부채 and 유동부채 != 0 else None,
    }

    # ── 5) 유보율 ────────────────────────────────────────────
    자본잉여금  = _get_val(df, "자본잉여금", year, exact=True)
    이익잉여금  = _get_val(df, "이익잉여금", year, exact=True)
    자본금     = _get_val(df, "자본금",     year, exact=True)
    result["유보율"] = {
        "자본잉여금" : 자본잉여금,
        "이익잉여금" : 이익잉여금,
        "자본금"    : 자본금,
        "단위"     : "%",
        "value"    : round(((자본잉여금 or 0) + (이익잉여금 or 0)) / 자본금 * 100, 2)
                     if 자본금 and 자본금 != 0 else None,
    }

    return result


# ─────────────────────────────────────────────────────────────────────────────
# 동작 확인
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ratios = calculate_ratios("090430", "2025", "재무상태표(연결)")
    print("=" * 55)
    print("FILMN9 ratio_calculator 검증 — 아모레퍼시픽(090430)")
    print("=" * 55)

    NAMES = ["부채비율", "유동비율", "이자보상배율", "당좌비율", "유보율"]
    for name in NAMES:
        r = ratios[name]
        val = r["value"]
        unit = r["단위"]
        print(f"\n[{name}]  →  {val} {unit}")
        for k, v in r.items():
            if k not in ("value", "단위") and v is not None:
                print(f"    {k}: {v:,.0f} 백만원" if isinstance(v, float) else f"    {k}: {v}")

    print("\n" + "=" * 55)
    print("✅ ratio_calculator 검증 완료")

