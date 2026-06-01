"""
FILMN9 VEDA — Beta 계산 모듈
β_L: yfinance 회귀분석 (Raw Beta → Adjusted Beta)
β_U: Hamada 방정식
Adjusted Beta = Raw Beta × 2/3 + 1.0 × 1/3 (블룸버그 방식)
"""

import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta


def get_raw_beta(ticker: str, benchmark: str,
                 period_days: int, interval: str,
                 eval_date: datetime) -> dict:
    """yfinance 회귀분석으로 Raw β_L 계산"""
    start = eval_date - timedelta(days=period_days)
    stock_raw = yf.download(ticker, start=start, end=eval_date,
                             interval=interval, auto_adjust=True, progress=False)
    mkt_raw   = yf.download(benchmark, start=start, end=eval_date,
                             interval=interval, auto_adjust=True, progress=False)
    stock_ret = np.log(stock_raw["Close"] / stock_raw["Close"].shift(1)).dropna()
    mkt_ret   = np.log(mkt_raw["Close"]   / mkt_raw["Close"].shift(1)).dropna()
    df = pd.DataFrame({"stock": stock_ret.squeeze(),
                       "market": mkt_ret.squeeze()}).dropna()
    n = len(df)
    if n < 5:
        return {"beta_raw": None, "error": f"데이터 부족: {n}개"}
    beta_raw, alpha = np.polyfit(df["market"], df["stock"], 1)
    r2 = df["stock"].corr(df["market"]) ** 2
    return {
        "beta_raw" : round(beta_raw, 4),
        "alpha"    : round(alpha, 4),
        "r_squared": round(r2, 4),
        "n_obs"    : n,
        "interval" : interval,
        "outlier"  : (beta_raw < 0 or beta_raw > 3.5 or r2 < 0.05),
    }


def calc_adjusted_beta(beta_raw: float) -> float:
    """Adjusted Beta = Raw Beta × 2/3 + 1.0 × 1/3 (블룸버그 방식, 평균회귀 보정)"""
    return round(beta_raw * (2/3) + 1.0 * (1/3), 4)


def unlever_beta(beta_l: float, tc: float, ibd: float, mktcap: float) -> dict:
    """
    Hamada 방정식: β_U = β_L ÷ (1 + (1-Tc) × D/E)
    Python 확정 로직 — LLM 절대 사용 금지
    D = IBD (이자부부채), E = 시가총액 (시장가치)
    """
    d_e    = ibd / mktcap
    factor = 1 + (1 - tc) * d_e
    return {"beta_u": round(beta_l / factor, 4), "d_e": round(d_e, 4)}


def relever_beta(beta_u: float, tc: float, target_d: float, target_e: float) -> float:
    """리레버링: β_L = β_U × (1 + (1-Tc) × D/E)"""
    return round(beta_u * (1 + (1 - tc) * (target_d / target_e)), 4)


def calc_all_betas(ticker: str, benchmark: str, eval_date: datetime,
                   tc: float, ibd: float, mktcap: float) -> dict:
    """5년 월간 + 2년 주간 Beta 비교 계산"""
    b5y = get_raw_beta(ticker, benchmark, 1825, "1mo", eval_date)
    b2y = get_raw_beta(ticker, benchmark, 730,  "1wk", eval_date)
    result = {}
    for label, bdata in [("5년월간", b5y), ("2년주간", b2y)]:
        if not bdata.get("beta_raw"):
            result[label] = bdata
            continue
        beta_adj = calc_adjusted_beta(bdata["beta_raw"])
        beta_u   = unlever_beta(beta_adj, tc, ibd, mktcap)
        result[label] = {**bdata, "beta_adjusted": beta_adj,
                         "beta_u": beta_u["beta_u"], "d_e": beta_u["d_e"]}
    primary = "5년월간" if result.get("5년월간", {}).get("beta_raw") else "2년주간"
    result["primary"]               = primary
    result["recommended_beta_l"]    = result[primary].get("beta_adjusted")
    result["recommended_beta_u"]    = result[primary].get("beta_u")
    return result
