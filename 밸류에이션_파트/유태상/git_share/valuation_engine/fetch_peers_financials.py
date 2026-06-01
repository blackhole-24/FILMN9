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
from datetime import date
from pathlib import Path
from typing import Optional

# 팀원 XBRL 모듈 경로 추가
_VAR_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_VAR_ROOT / "XBRL"))

# 팀원 코드 import
from xbrl_financials_v4 import extract_company  # noqa: E402

from .config import ALL_COMPANIES, FISCAL_YEARS, XBRL_RESULTS


def fetch_all(
    companies: Optional[list[dict]] = None,
    years: Optional[list[int]] = None,
    verbose: bool = True,
    skip_existing: bool = True,
) -> dict:
    """4사 × 3년치 재무 추출.

    skip_existing=True 면 이미 저장된 JSON 있으면 재호출 안 함 (DART API 절약).
    """
    companies = companies or ALL_COMPANIES
    years     = years     or FISCAL_YEARS

    all_data: dict = {}

    for i, comp in enumerate(companies, 1):
        name = comp["name"]
        if verbose:
            print(f"\n[{i}/{len(companies)}] {name} ({comp['ticker']})")
        all_data[name] = {"meta": comp, "by_year": {}}

        for j, year in enumerate(years, 1):
            out_path = XBRL_RESULTS / f"{name}_{year}.json"
            if skip_existing and out_path.exists():
                if verbose:
                    print(f"  [{j}/{len(years)}] FY{year} : 캐시 사용 {out_path.name}")
                with out_path.open("r", encoding="utf-8") as f:
                    result = json.load(f)
            else:
                if verbose:
                    print(f"  [{j}/{len(years)}] FY{year} : DART 호출 중...")
                # 팀원 함수 직접 호출 — outdir 로 저장 위치 지정
                result = extract_company(
                    name_or_code=name,
                    year=year,
                    outdir=str(XBRL_RESULTS),
                    save=True,
                    verbose=False,
                )

            all_data[name]["by_year"][year] = result

            if verbose:
                fin = result["financials"]
                rev = (fin.get("매출액") or 0) / 1e8
                ebit = (fin.get("영업이익") or 0) / 1e8
                opm = (ebit / rev * 100) if rev else 0
                print(f"     매출 {rev:>10,.0f}억  EBIT {ebit:>8,.0f}억  OPM {opm:.1f}%")

    # 통합 인덱스 저장
    today = date.today().isoformat()
    index_path = XBRL_RESULTS / f"all_financials_{today.replace('-','')}.json"
    with index_path.open("w", encoding="utf-8") as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2, default=str)

    if verbose:
        print(f"\n통합 인덱스 저장: {index_path}")
        print(f"총 {len(companies)}사 × {len(years)}년 = {len(companies)*len(years)}건")

    return all_data


def load_all(t: Optional[date] = None) -> dict:
    """저장된 통합 인덱스 로드."""
    t = t or date.today()
    path = XBRL_RESULTS / f"all_financials_{t.strftime('%Y%m%d')}.json"
    if not path.exists():
        # 가장 최근 파일 사용
        candidates = sorted(XBRL_RESULTS.glob("all_financials_*.json"))
        if not candidates:
            raise FileNotFoundError(
                f"통합 인덱스가 없습니다. 먼저 fetch_all() 실행 필요."
            )
        path = candidates[-1]
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    fetch_all(verbose=True)
