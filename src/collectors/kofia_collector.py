"""
FILMN9 VEDA — KOFIABOND Kd 수집 (CSV 파싱)
DART 주석에서 신용평가등급 확인 후 해당 등급 수익률 매칭

CSV 다운로드 방법:
  URL  : https://www.kofiabond.or.kr
  경로 : 채권정보 → 채권시가평가 → 등급별 수익률
  설정 : 조회기간=평가기준일, 등급=기업의 신용등급(예: BBB-), 만기=5년
  저장 : data/raw/kofiabond_YYYYMMDD.csv
"""

import pandas as pd
import os


def get_kd_from_csv(csv_path: str, credit_grade: str, tenor_year: int = 5) -> dict:
    """
    KOFIABOND CSV → Kd 추출
    Args:
        csv_path    : 'data/raw/kofiabond_20241231.csv'
        credit_grade: 'BBB-', 'BBB+', 'A-' 등 (DART 주석에서 확인)
        tenor_year  : 1, 3, 5
    """
    df = pd.read_csv(csv_path, encoding="cp949")
    grade_col = [c for c in df.columns if "등급" in c][0]
    tenor_col = [c for c in df.columns if "만기" in c][0]
    yield_col = [c for c in df.columns if "수익률" in c][0]
    filtered  = df[(df[grade_col].str.strip() == credit_grade) &
                   (df[tenor_col] == tenor_year)]
    if filtered.empty:
        raise ValueError(f"KOFIABOND: {credit_grade} {tenor_year}년물 없음")
    kd_pct = float(filtered.iloc[0][yield_col])
    return {
        "kd"    : kd_pct / 100,
        "kd_pct": kd_pct,
        "grade" : credit_grade,
        "tenor" : tenor_year,
        "source": f"KOFIABOND ({os.path.basename(csv_path)})"
    }
