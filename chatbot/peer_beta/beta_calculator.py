"""Levered Beta 회귀 + 검증 + Blume 조정.

순수 계산 모듈 (KRX 호출 없음). 정제된 주간 종가 시계열을 받아 설계서 §1.6 절차 수행:

  1) 주간 로그수익률  r_t = ln(P_t / P_{t-1})
  2) 종목·지수 동일 날짜 정렬
  3) OLS 회귀 (절편 포함) -> beta_raw, alpha, R^2, 잔차
  4) 검증 로깅 (R^2, 잔차 |z|>4, 결측주, 상장기간)
  5) Blume 조정: beta_adj = α × beta_raw + (1-α) × 1.0
                 α = 2/3 (Blume 1971 원본, KRX 공시 베타와 일치)
  6) outlier_handling="drop" 옵션: |z|>4 행 제거 후 재회귀
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd
import statsmodels.api as sm

from .config import BETA_CONFIG


# ---- 결과 데이터 클래스 ----------------------------------------------------
@dataclass
class BetaResult:
    name: str
    ticker: str
    market: str
    eval_date: str
    n_weeks_used: int
    beta_raw: float
    beta_adjusted: float
    alpha: float
    r_squared: float
    std_err_beta: float
    blume_alpha: float
    outlier_handling: str = "none"           # "none" / "drop" / "winsorize"
    n_outliers_dropped: int = 0              # drop 모드: 제거된 행 수
    n_outliers_winsorized: int = 0           # winsorize 모드: 조정된 행 수
    winsorize_k: Optional[float] = None      # winsorize 모드: 사용한 k (잔차 σ 배수)
    listing_years: Optional[float] = None
    warnings: list[str] = field(default_factory=list)
    outlier_dates: list[str] = field(default_factory=list)  # 1차 OLS 기준 이상치 일자
    missing_weeks: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


# ---- 유틸 -----------------------------------------------------------------
def _to_series(points, label: str) -> pd.Series:
    if isinstance(points, pd.DataFrame):
        df = points.copy()
    else:
        df = pd.DataFrame(points)
    if df.empty:
        return pd.Series(dtype=float, name=label)
    date_col  = "actual_date" if "actual_date" in df.columns else df.columns[0]
    close_col = "close"       if "close"       in df.columns else df.columns[-1]
    df = df[[date_col, close_col]].copy()
    df.columns = ["date", "close"]
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").drop_duplicates("date", keep="last")
    s = df.set_index("date")["close"]
    s.name = label
    return s


def align_weekly_returns(stock_points, index_points,
                         method: Optional[str] = None) -> pd.DataFrame:
    """주간 종가 -> 같은 일자 inner join 후 수익률 산출.

    method: "simple"(산술, P_t/P_{t-1}-1) | "log"(로그, ln(P_t/P_{t-1}))
            None 이면 BETA_CONFIG["return_method"] 사용.
    KRX·한공회 공시 베타는 산술수익률 기준이므로 기본은 "simple".
    """
    m = method or BETA_CONFIG.get("return_method", "simple")
    s_stock = _to_series(stock_points, "stock_close")
    s_index = _to_series(index_points, "index_close")
    df = pd.concat([s_stock, s_index], axis=1, join="inner").sort_index()
    if df.empty:
        return df
    if m == "log":
        df["r_stock"] = np.log(df["stock_close"] / df["stock_close"].shift(1))
        df["r_index"] = np.log(df["index_close"] / df["index_close"].shift(1))
    else:  # "simple" (산술) — 기본
        df["r_stock"] = df["stock_close"].pct_change()
        df["r_index"] = df["index_close"].pct_change()
    return df.dropna(subset=["r_stock", "r_index"])


def run_ols(returns: pd.DataFrame) -> dict:
    """returns[['r_stock','r_index']] 에 OLS 회귀 (절편 포함)."""
    y = returns["r_stock"].values
    X = sm.add_constant(returns["r_index"].values)
    fit = sm.OLS(y, X, missing="drop").fit()
    return {
        "alpha":     float(fit.params[0]),
        "beta_raw":  float(fit.params[1]),
        "r_squared": float(fit.rsquared),
        "std_err":   {"alpha": float(fit.bse[0]), "beta": float(fit.bse[1])},
        "resid":     pd.Series(fit.resid, index=returns.index, name="resid"),
        "fit":       fit,
    }


def blume_adjust(beta_raw: float, alpha: float = None) -> float:
    """β_adj = α × β_raw + (1-α). α 기본값은 BETA_CONFIG['blume_alpha'] = 2/3."""
    a = BETA_CONFIG["blume_alpha"] if alpha is None else alpha
    return a * beta_raw + (1.0 - a) * 1.0


# ---- 메인 진입점 ----------------------------------------------------------
def compute_beta(
    name: str,
    ticker: str,
    market: str,
    stock_points,
    index_points,
    eval_date: date,
    *,
    expected_weeks: Optional[int] = None,
    outlier_handling: Optional[str] = None,
) -> BetaResult:
    """한 종목의 levered beta 산출.

    outlier_handling:
        None이면 BETA_CONFIG["outlier_handling"] 사용.
        "none"      -> 이상치 일자만 기록, 회귀에는 포함 (설계서 §1.6 원안)
        "drop"      -> 1차 OLS 후 |z|>residual_z_max 행 제거 후 재회귀 (표본 감소)
        "winsorize" -> 1차 OLS 후 |z|>winsorize_k 인 잔차를 ±k·σ로 자르고 재회귀
                       (표본 N 유지, 영향만 완화 — 일반 투자자 대상 권장)
    """
    handling = outlier_handling or BETA_CONFIG.get("outlier_handling", "none")
    if handling not in ("none", "drop", "winsorize"):
        raise ValueError(
            f"outlier_handling은 'none' / 'drop' / 'winsorize': got {handling!r}"
        )

    returns = align_weekly_returns(stock_points, index_points)
    if returns.empty or len(returns) < 5:
        return BetaResult(
            name=name, ticker=ticker, market=market,
            eval_date=eval_date.isoformat(),
            n_weeks_used=int(len(returns)),
            beta_raw=float("nan"), beta_adjusted=float("nan"),
            alpha=float("nan"), r_squared=float("nan"),
            std_err_beta=float("nan"),
            blume_alpha=BETA_CONFIG["blume_alpha"],
            outlier_handling=handling,
            n_outliers_dropped=0,
            listing_years=None,
            warnings=["insufficient_data"],
            outlier_dates=[],
            missing_weeks=(expected_weeks - len(returns)) if expected_weeks else 0,
        )

    val_cfg = BETA_CONFIG["validation"]
    win_k   = BETA_CONFIG.get("winsorize_k", 3.0)

    # 1차 OLS - 이상치 식별 용
    first_ols = run_ols(returns)
    resid: pd.Series = first_ols["resid"]
    sigma_resid = resid.std(ddof=1) or 1.0
    z = (resid - resid.mean()) / sigma_resid
    # 식별용 임계는 residual_z_max (보통 4.0). 보고서/로깅용.
    outlier_mask = z.abs() > val_cfg["residual_z_max"]
    outlier_dates = [d.strftime("%Y-%m-%d") for d in resid.index[outlier_mask]]

    # 최종 회귀 결정
    n_dropped = 0
    n_winsorized = 0
    used_winsorize_k: Optional[float] = None

    if handling == "drop" and outlier_mask.any():
        clean_returns = returns.loc[~outlier_mask.values]
        n_dropped = int(outlier_mask.sum())
        if len(clean_returns) >= 5:
            ols = run_ols(clean_returns)
            used_returns = clean_returns
        else:
            # 이상치가 너무 많으면 원본 사용
            ols = first_ols
            used_returns = returns
            n_dropped = 0
    elif handling == "winsorize":
        # 잔차 표준편차 σ 기준으로 |잔차| > k·σ 행을 식별
        win_mask = resid.abs() > (win_k * sigma_resid)
        if win_mask.any():
            alpha_1 = first_ols["alpha"]
            beta_1  = first_ols["beta_raw"]
            cap     = win_k * sigma_resid
            # 원 잔차의 부호 보존하면서 ±cap 으로 자름
            capped_resid = resid.clip(lower=-cap, upper=cap)
            # 수정된 r_stock = 1차 회귀 예측 + 자른 잔차
            new_r_stock = alpha_1 + beta_1 * returns["r_index"] + capped_resid
            wins_returns = returns.copy()
            wins_returns["r_stock"] = new_r_stock
            ols = run_ols(wins_returns)
            used_returns = wins_returns
            n_winsorized = int(win_mask.sum())
            used_winsorize_k = float(win_k)
        else:
            ols = first_ols
            used_returns = returns
            used_winsorize_k = float(win_k)  # 옵션은 사용했으나 해당 행 없음
    else:
        ols = first_ols
        used_returns = returns

    # 경고 플래그
    warnings: list[str] = []
    if ols["r_squared"] < val_cfg["r_squared_min"]:
        warnings.append("low_r_squared")
    if outlier_dates:
        warnings.append("outliers")

    missing = 0
    if expected_weeks is not None:
        missing = max(0, expected_weeks - len(returns))
        if missing > val_cfg["missing_weeks_max"]:
            warnings.append("missing_weeks")

    # ── 상장연수 판단 — 주간 관측 수 기반 (KRX 일별 API 에 상장일 없음) ──
    # 2년 lookback 의 기대 주수 대비 실제 확보한 주간 수익률 관측 수로 판단.
    # 신규상장은 lookback 앞부분에 종가가 없어 관측 수가 크게 부족 → short_listing.
    # listing_years 는 관측 수 기반 추정(연 52주)으로, 회귀에 실제 쓰인 데이터 기간.
    n_obs = len(used_returns)
    listing_years = round(n_obs / 52.0, 2)
    ratio = val_cfg.get("min_weeks_2yr_ratio", 0.85)
    if expected_weeks:
        if n_obs < expected_weeks * ratio:
            warnings.append("short_listing")
    elif n_obs < 104 * ratio:   # expected 미제공 시 2년(104주) 기준
        warnings.append("short_listing")

    beta_raw = ols["beta_raw"]
    beta_adj = blume_adjust(beta_raw)

    return BetaResult(
        name=name, ticker=ticker, market=market,
        eval_date=eval_date.isoformat(),
        n_weeks_used=int(len(used_returns)),
        beta_raw=beta_raw,
        beta_adjusted=beta_adj,
        alpha=ols["alpha"],
        r_squared=ols["r_squared"],
        std_err_beta=ols["std_err"]["beta"],
        blume_alpha=BETA_CONFIG["blume_alpha"],
        outlier_handling=handling,
        n_outliers_dropped=n_dropped,
        n_outliers_winsorized=n_winsorized,
        winsorize_k=used_winsorize_k,
        listing_years=listing_years,   # Phase 7: 이미 round(,2) 적용됨 — 이중 round 제거
        warnings=warnings,
        outlier_dates=outlier_dates,
        missing_weeks=int(missing),
    )
