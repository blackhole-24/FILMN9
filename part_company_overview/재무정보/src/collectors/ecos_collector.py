"""
FILMN9 VEDA — ECOS API 무위험이자율(Rf) 수집
출처: 한국은행 ECOS (ecos.bok.or.kr)
대안: KOFIABOND CSV 다운로드 사용 가능
"""

import os
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
ECOS_KEY = os.getenv("ECOS_API_KEY")
ECOS_URL = "https://ecos.bok.or.kr/api/StatisticSearch"

RF_ITEMS = {
    "1Y" : "010100000",
    "3Y" : "010190000",
    "5Y" : "010200000",
    "10Y": "010210000",  # WACC 기본값
}


def get_rf(eval_date: str, tenor: str = "10Y") -> dict:
    """평가기준일 기준 국고채 수익률 조회"""
    item   = RF_ITEMS[tenor]
    date_f = eval_date.replace("-", "")
    url    = f"{ECOS_URL}/{ECOS_KEY}/json/kr/1/5/817Y002/DD/{date_f}/{date_f}/{item}"
    rows   = requests.get(url, timeout=15).json().get("StatisticSearch", {}).get("row", [])
    if not rows:
        for i in range(1, 6):
            prev  = (datetime.strptime(eval_date, "%Y-%m-%d") - timedelta(days=i)).strftime("%Y%m%d")
            url2  = f"{ECOS_URL}/{ECOS_KEY}/json/kr/1/5/817Y002/DD/{prev}/{prev}/{item}"
            rows  = requests.get(url2, timeout=15).json().get("StatisticSearch", {}).get("row", [])
            if rows:
                break
    if not rows:
        raise ValueError(f"Rf 데이터 없음: {eval_date} {tenor}")
    rf_pct = float(rows[0]["DATA_VALUE"])
    return {"rf": rf_pct/100, "rf_pct": rf_pct, "date": rows[0]["TIME"],
            "tenor": tenor, "source": "한국은행 ECOS API (817Y002)"}


def get_all_rf(eval_date: str) -> dict:
    """1Y/3Y/5Y/10Y 전체 조회"""
    result = {}
    for t in RF_ITEMS:
        try:
            result[t] = get_rf(eval_date, t)
        except Exception as e:
            result[t] = {"error": str(e)}
    return result
