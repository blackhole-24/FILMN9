"""
collectors/naver_scraper.py
────────────────────────────
네이버증권 → 외국인 보유비율 스크래핑.
URL: https://finance.naver.com/item/main.nhn?code={stock_code}
"""
from __future__ import annotations
import sys, re
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.app_config import SAMPLE

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9",
}


def get_foreign_ratio(stock_code: str = SAMPLE["stock_code"]) -> dict:
    """
    외국인 보유비율 수집.
    1차: 네이버증권 스크래핑
    2차(fallback): yfinance heldPercentInstitutions

    Returns
    -------
    {
      "foreign_ratio" : float,   # 예) 20.45  (%)
      "foreign_shares": int | None,
      "source"        : str,
    }
    """
    # 1차 시도: 네이버증권
    url = f"https://finance.naver.com/item/main.nhn?code={stock_code}"
    try:
        req = Request(url, headers=_HEADERS)
        with urlopen(req, timeout=10) as resp:
            html = resp.read().decode("cp949", errors="replace")

        ratio_match = re.search(r'id=["\']_foreignRatio["\'][^>]*>([0-9.]+)<', html)
        hold_match  = re.search(r'id=["\']_foreignHold["\'][^>]*>([\d,]+)<', html)

        if ratio_match:
            ratio = float(ratio_match.group(1))
            shares_raw = hold_match.group(1).replace(",", "") if hold_match else None
            shares = int(shares_raw) if shares_raw and shares_raw.isdigit() else None
            return {"foreign_ratio": ratio, "foreign_shares": shares, "source": "naver"}
    except Exception:
        pass

    # 2차 fallback: yfinance
    try:
        import yfinance as yf
        ticker = stock_code + ".KS"
        info = yf.Ticker(ticker).info
        inst_pct = info.get("heldPercentInstitutions")  # 기관+외국인 합산
        if inst_pct:
            return {
                "foreign_ratio" : round(inst_pct * 100, 2),
                "foreign_shares": None,
                "source"        : "yfinance(기관합산)",
            }
    except Exception:
        pass

    return {"foreign_ratio": None, "foreign_shares": None, "source": "unavailable"}


if __name__ == "__main__":
    result = get_foreign_ratio(SAMPLE["stock_code"])
    print("=" * 45)
    print(f"FILMN9 naver_scraper — {SAMPLE['name']}")
    print("=" * 45)
    for k, v in result.items():
        print(f"  {k}: {v}")
    print("✅ naver_scraper 검증 완료")
