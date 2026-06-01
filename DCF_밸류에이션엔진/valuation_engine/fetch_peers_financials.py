"""Phase 1-B — 팀원 XBRL 모듈로 피어 4사 × 3년치 재무 일괄 추출.

사용자 환경 (conda dart-rag) 에서 실행:
    python -m valuation_engine.fetch_peers_financials

산출물:
  valuation_engine/data/xbrl/<회사명>_<연도>.json   (팀원 포맷)
  valuation_engine/data/xbrl/all_financials_<T>.json (통합 인덱스)

각 회사·연도 결과 dict:
  meta:       {corp_code, corp_name, stock_code, year, rcept_no, 재무제표기준, ...}
  financials: {매출액, 영업이익, 당기순이익, 지배순이익,
               da, ebitda,
               nwc_cur, nwc_pfy, delta_nwc,
               capex,                                  # 유형자산만 Gross (팀원 결정)
               ibd, ibd_detail,
               noa, noa_items,                         # 팀원 5분류 (확실 1개)
               한계세율, 세율구간,
               nopat, fcff}                            # 단년 FCFF
"""
from __future__ import annotations

import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Optional

# 팀원 XBRL 모듈 경로 추가
_VAR_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_VAR_ROOT / "XBRL"))

# 팀원 코드 import
from xbrl_financials_v4 import extract_company  # noqa: E402

from .config import ALL_COMPANIES, FISCAL_YEARS, XBRL_RESULTS, XBRL_LEGACY_DIRS

# DART 동시 호출 워커 수 (속도 최적화 #4). OpenDART 분당 한도 내 보수적 설정.
_DART_MAX_WORKERS = 5
_PRINT_LOCK = threading.Lock()


def _find_cached_json(name: str, year: int) -> Optional[Path]:
    """캐시 JSON 탐색 — 통일 경로 우선, 팀원 옛 경로 fallback."""
    # 1차: v3 통합 경로
    p = XBRL_RESULTS / f"{name}_{year}.json"
    if p.exists():
        return p
    # 2차: 팀원 옛 경로들 (5년 × XBRL/xbrl_results_<year>/)
    for legacy_dir in XBRL_LEGACY_DIRS:
        cand = legacy_dir / f"{name}_{year}.json"
        if cand.exists():
            return cand
    return None


def _fetch_one_year(comp: dict, year: int, skip_existing: bool,
                    use_v3_collector: bool):
    """단일 (회사, 연도) 재무 추출 — 캐시 우선, 미스 시 DART. (회사명, 연도, result|None, err)"""
    name = comp["name"]
    cached = _find_cached_json(name, year) if skip_existing else None
    if cached:
        try:
            with cached.open("r", encoding="utf-8") as f:
                return name, year, json.load(f), None
        except Exception:
            pass   # 손상 → DART 재호출
    dart_id = comp.get("ticker") or name
    if not str(dart_id).isdigit():
        dart_id = name
    try:
        if use_v3_collector:
            from .xbrl_collector import extract_company_v3
            result = extract_company_v3(name_or_code=dart_id, year=year,
                                        outdir=XBRL_RESULTS, save=True, verbose=False)
        else:
            result = extract_company(name_or_code=dart_id, year=year,
                                     outdir=str(XBRL_RESULTS), save=True, verbose=False)
        return name, year, result, None
    except Exception as e:
        return name, year, None, str(e)[:160]


def _collect_company(comp: dict, years: list[int], is_target: bool,
                     skip_existing: bool, use_v3_collector: bool, verbose: bool):
    """회사 1개 수집 (속도 #5: 타깃=전 연도 / 피어=최신 가용 1개).

    Returns: (name, by_year dict, failures list[(name,year,msg)])
    """
    name = comp["name"]
    by_year: dict = {}
    failures: list[tuple] = []
    if is_target:
        # 타깃: 정상화·Fade 위해 전 연도 필요
        attempt = sorted(years)
        stop_first = False
    else:
        # 피어: 멀티플·WACC 는 최신연도만 사용 → 최신부터 첫 성공까지만
        attempt = sorted(years, reverse=True)
        stop_first = True
    for year in attempt:
        _n, _y, result, err = _fetch_one_year(comp, year, skip_existing, use_v3_collector)
        if result is not None:
            by_year[year] = result
            if verbose:
                fin = result.get("financials", {})
                rev = (fin.get("매출액") or 0) / 1e8
                ebit = (fin.get("영업이익") or 0) / 1e8
                opm = (ebit / rev * 100) if rev else 0
                with _PRINT_LOCK:
                    role = "타깃" if is_target else "피어"
                    print(f"  [{role}] {name} FY{year}: 매출 {rev:,.0f}억 OPM {opm:.1f}%")
            if stop_first:
                break
        else:
            failures.append((name, year, err))
    return name, by_year, failures


def fetch_all(
    companies: Optional[list[dict]] = None,
    years: Optional[list[int]] = None,
    verbose: bool = True,
    skip_existing: bool = True,
    use_v3_collector: bool = True,
    eval_date: Optional[date] = None,
) -> dict:
    """회사별 재무 추출 — 병렬(#4) + 피어 깊이 차등(#5).

    · 타깃(config.TARGET): FISCAL_YEARS 전 연도 (정상화/Fade).
    · 피어:               최신 가용 1개 연도 (멀티플·WACC 은 latest 만 사용).
    · 회사 단위 ThreadPoolExecutor 병렬 — 첫 평가 XBRL 수집 시간 대폭 단축.
    skip_existing=True 면 캐시 우선.
    """
    companies = companies or ALL_COMPANIES
    years     = years     or FISCAL_YEARS

    from .config import TARGET as _TARGET
    target_tkr = _TARGET.get("ticker")

    all_data: dict = {}
    failed_years: list[tuple[str, int, str]] = []

    def _is_target(c):
        return (c.get("ticker") and target_tkr and
                str(c["ticker"]).zfill(6) == str(target_tkr).zfill(6))

    workers = max(1, min(_DART_MAX_WORKERS, len(companies)))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="xbrl") as ex:
        futs = {ex.submit(_collect_company, comp, years, _is_target(comp),
                          skip_existing, use_v3_collector, verbose): comp
                for comp in companies}
        for fut in as_completed(futs):
            comp = futs[fut]
            name, by_year, failures = fut.result()
            all_data[name] = {"meta": comp, "by_year": by_year}
            failed_years.extend(failures)
            if not by_year:
                raise RuntimeError(
                    f"{name}: 모든 연도 수집 실패 — DCF 진행 불가. "
                    f"실패 내역: {[(y, m) for n, y, m in failures]}")

    # 통합 인덱스 저장 — ticker prefix 로 동시 평가 시 충돌 방지
    _save_d = eval_date or date.today()
    if isinstance(_save_d, str):
        from datetime import datetime as _dt
        _save_d = _dt.fromisoformat(_save_d).date()
    from .config import TARGET as _TARGET
    _target_tkr = _TARGET.get("ticker") or "default"
    index_path = XBRL_RESULTS / f"all_financials_{_target_tkr}_{_save_d.strftime('%Y%m%d')}.json"
    with index_path.open("w", encoding="utf-8") as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2, default=str)

    if verbose:
        print(f"\n통합 인덱스 저장: {index_path}")
        n_total = len(companies) * len(years)
        n_ok = sum(len(v["by_year"]) for v in all_data.values())
        print(f"총 {n_total}건 중 {n_ok}건 확보  (실패 {len(failed_years)}건)")
        if failed_years:
            for n, y, m in failed_years[:5]:
                print(f"   - {n} FY{y}: {m}")

    return all_data


def load_all(t: Optional[date] = None) -> dict:
    """저장된 통합 인덱스 로드 — 현재 config.TARGET ticker 일치 파일 우선."""
    t = t or date.today()
    if isinstance(t, str):
        from datetime import datetime as _dt
        t = _dt.fromisoformat(t).date()

    from .config import TARGET as _TARGET
    tkr = _TARGET.get("ticker") or "default"
    date_str = t.strftime("%Y%m%d")

    # 1) ticker prefix 매칭 (현재 표준)
    path = XBRL_RESULTS / f"all_financials_{tkr}_{date_str}.json"
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    # 2) 구 포맷 (ticker 없음) 호환
    legacy = XBRL_RESULTS / f"all_financials_{date_str}.json"
    if legacy.exists():
        with legacy.open("r", encoding="utf-8") as f:
            return json.load(f)

    raise FileNotFoundError(
        f"통합 인덱스 없음 (찾은 패턴: {path.name} 또는 {legacy.name}). "
        f"먼저 fetch_all() 실행 필요."
    )


if __name__ == "__main__":
    fetch_all(verbose=True)
