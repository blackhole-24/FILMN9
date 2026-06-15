"""평가기준일 T 기준 직전 N년의 '금요일' 리스트 생성 및 영업일 대체.

설계서 v4 §1.6:
- 매주 금요일 종가 기준
- 금요일이 공휴일이면 직전 영업일 종가
- 종목·지수 동일 영업일 매칭

KRX 영업일 캘린더를 별도로 발급받지 않으므로,
"금요일 후보 -> 그날 KRX API에 데이터가 있으면 사용 / 없으면 -1일씩 후행"
하는 방식으로 처리합니다 (krx_client.fetch_close 에서 lookback 인자로 구현).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable

import pandas as pd


def parse_date(d: str | date | None) -> date:
    """문자열/None을 date로 정규화. None이면 today."""
    if d is None:
        return date.today()
    if isinstance(d, date):
        return d
    return pd.Timestamp(d).date()


def fridays_between(start: date, end: date) -> list[date]:
    """[start, end] 범위 내 모든 금요일 (오름차순). 양 끝 포함."""
    if start > end:
        start, end = end, start
    # 가장 가까운 금요일로 정렬
    offset_to_friday = (4 - start.weekday()) % 7
    first_fri = start + timedelta(days=offset_to_friday)
    out: list[date] = []
    d = first_fri
    while d <= end:
        out.append(d)
        d += timedelta(days=7)
    return out


def weekly_friday_dates(eval_date: date, lookback_years: int) -> list[date]:
    """평가기준일 T 기준 직전 N년 동안의 '금요일' 후보 리스트.

    실제 영업일 대체는 KRX 응답 가용성을 보고 결정 (calendar_utils 자체는 후보만 생성).
    예: T=2026-05-14(목), N=2 -> 약 104개의 금요일.
    """
    eval_d = parse_date(eval_date)
    start = eval_d - timedelta(days=int(lookback_years * 365.25) + 7)
    fridays = fridays_between(start, eval_d)
    # 평가기준일 자체가 금요일이 아니면, eval_d 이하의 금요일까지만
    return [f for f in fridays if f <= eval_d]


def previous_business_day_candidates(target: date, max_lookback: int = 5) -> list[date]:
    """target에서 거꾸로 max_lookback일까지 후보 날짜 (target 포함, 주말 제외)."""
    out: list[date] = []
    d = target
    for _ in range(max_lookback + 1):
        if d.weekday() < 5:  # 0=월, ..., 4=금
            out.append(d)
        d -= timedelta(days=1)
    return out


def as_yyyymmdd(d: date) -> str:
    return d.strftime("%Y%m%d")


def from_yyyymmdd(s: str) -> date:
    return pd.Timestamp(s).date()
