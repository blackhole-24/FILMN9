"""타깃 종목의 확장 손익 history — 기본 FISCAL_YEARS(3년) 외 추가 연도 매출 수집.

용도:
  B2 (다중 성장률 후보)에서 5년 CAGR 산출용. 타깃 한정(피어 미적용 — 비용 절감).
  fnlttSinglAcntAll(11011 사업보고서) 재사용 — 별도 API 추가 불필요.

캐시:
  data/extended/revenue_<corp_code>.json  → {연도: 매출, ...}
  연도별 lazy 채움 → 동일 종목 재호출 시 추가 API 콜 0.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Optional

from .quarterly_financials import _fetch_income   # 기존 fnlttSinglAcntAll wrapper 재사용

_VAR_ROOT = Path(__file__).resolve().parent.parent
_CACHE_DIR = _VAR_ROOT / "valuation_engine" / "data" / "extended"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ── .env 자동 로드 (DART_API_KEY 필요) — 단독 실행 시 fallback 보장 ──
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(_VAR_ROOT / ".env", override=False)
except ImportError:
    pass


def _cache_path(corp_code: str) -> Path:
    return _CACHE_DIR / f"revenue_{corp_code}.json"


def get_annual_revenue(corp_code: str, year: int,
                       use_cache: bool = True, verbose: bool = False) -> Optional[float]:
    """해당 (corp_code, 연도)의 연간 매출 (CFS 우선). 캐시 hit 시 API 호출 없음."""
    p = _cache_path(corp_code)
    cache = {}
    if use_cache and p.exists():
        try:
            cache = json.load(open(p, encoding="utf-8"))
        except Exception:
            cache = {}
    k = str(year)
    if k in cache:
        v = cache[k]
        return float(v) if v is not None else None

    # 캐시 미스 → API 호출 (사업보고서 = 연간)
    try:
        rev, _ebit, _prev = _fetch_income(corp_code, year, "11011")
    except Exception as e:
        if verbose:
            print(f"  [extended_history] {year} fetch 실패: {str(e)[:80]}")
        rev = None

    # 정책: None(전체 결측)은 캐시 금지 — 일시적 API 실패가 영구 잔존하는 것 차단.
    if rev is not None:
        cache[k] = rev
        try:
            with p.open("w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    if verbose and rev is not None:
        print(f"  [extended_history] {year} 매출 {rev/1e12:.2f}조 (API)")
    return rev


def get_revenue_series(corp_code: str, latest_year: int, n_years: int = 5,
                       use_cache: bool = True, verbose: bool = False) -> list:
    """latest_year 포함 직전 n_years 연도 매출 시계열.

    Returns: [(year, revenue), ...] 오름차순. 결측은 (year, None).
    """
    out = []
    for y in range(latest_year - n_years + 1, latest_year + 1):
        v = get_annual_revenue(corp_code, y, use_cache=use_cache, verbose=verbose)
        out.append((y, v))
    return out


# ── 영업이익 포함 시계열 (B1 영구 OPM 수렴용) ─────────────────────────────
def _income_cache_path(corp_code: str) -> Path:
    return _CACHE_DIR / f"income_{corp_code}.json"


def get_annual_income(corp_code: str, year: int,
                      use_cache: bool = True, verbose: bool = False) -> tuple:
    """(매출, 영업이익) 동시 fetch — 캐시 hit 시 API 0.

    Returns: (revenue, ebit) — 어느 한 쪽 결측이면 그 항목만 None.
    """
    from .quarterly_financials import _fetch_income
    p = _income_cache_path(corp_code)
    cache = {}
    if use_cache and p.exists():
        try:
            cache = json.load(open(p, encoding="utf-8"))
        except Exception:
            cache = {}
    k = str(year)
    if k in cache and isinstance(cache[k], dict):
        e = cache[k]
        return (e.get("rev"), e.get("ebit"))
    # 캐시 미스
    try:
        rev, ebit, _ = _fetch_income(corp_code, year, "11011")
    except Exception as exc:
        if verbose:
            print(f"  [extended_history.income] {year} 실패: {str(exc)[:80]}")
        rev, ebit = None, None
    # 정책: 둘 다 None(전체 결측 — 일시적 API 오류 또는 영구 결측 구분 불가)이면 캐시 X.
    #   영구 결측(상폐 등)인 경우 매번 호출은 비용이지만, 오염된 None 영구 잔존을 막는 게 우선.
    if rev is not None or ebit is not None:
        cache[k] = {"rev": rev, "ebit": ebit}
        try:
            with p.open("w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    return rev, ebit


def get_income_series(corp_code: str, latest_year: int, n_years: int = 8,
                      use_cache: bool = True, verbose: bool = False) -> list:
    """latest_year 포함 직전 n_years 연도 (year, rev, ebit) 시계열.

    Default n_years=8 — 자기 long-run OPM 평균(B1)용. 7~10년이 통상 한 cycle 포함.
    Returns: [(year, rev, ebit), ...] 오름차순. 결측은 None.
    """
    out = []
    for y in range(latest_year - n_years + 1, latest_year + 1):
        r, e = get_annual_income(corp_code, y, use_cache=use_cache, verbose=verbose)
        out.append((y, r, e))
    return out


def compute_long_run_opm(corp_code: str, latest_year: int, n_years: int = 8,
                         min_years: int = 4, use_cache: bool = True,
                         verbose: bool = False) -> Optional[float]:
    """자기 long-run OPM 평균 — n_years 윈도우(기본 8년). 결측 제외 후 평균.

    min_years: 가용 연도가 이 이하면 None 반환(신뢰 불가). 기본 4 (8년 중 최소 절반).
    """
    series = get_income_series(corp_code, latest_year, n_years, use_cache, verbose)
    opms = []
    for _y, r, e in series:
        if r and e is not None and r > 0:
            opms.append(e / r)
    if len(opms) < min_years:
        return None
    return sum(opms) / len(opms)


if __name__ == "__main__":
    import sys
    cc = sys.argv[1] if len(sys.argv) > 1 else "00126380"
    yr = int(sys.argv[2]) if len(sys.argv) > 2 else 2025
    series = get_income_series(cc, yr, n_years=8, verbose=True)
    for y, r, e in series:
        if r is None:
            print(f"  {y}: 결측")
        else:
            opm = (e / r * 100) if (e is not None and r > 0) else None
            print(f"  {y}: 매출 {r/1e12:.2f}조  영업이익 {e/1e12 if e else 0:+.3f}조  "
                  f"OPM {f'{opm:.1f}%' if opm is not None else 'N/A'}")
    lr = compute_long_run_opm(cc, yr, 8)
    print(f"\n  자기 8년 OPM 평균: {f'{lr*100:.2f}%' if lr is not None else 'N/A(데이터 부족)'}")
