"""C3 — Damodaran 산업 무차입베타(βU) 교차검증.

용도:
  우리 피어 4사 중위 βU 가 산업 표준(Damodaran emerging markets)과 크게 다르면 경고.
  교차검증 보조용 — 본 평가의 βU 자체를 대체하지는 않음 (피어 베타 그대로 유지).

소스:
  http://pages.stern.nyu.edu/~adamodar/pc/datasets/totalbetaemerg.xls
  · 매년 ~1회 갱신 (Damodaran 매년 1월 업데이트)
  · 한국 포함 emerging markets 종합 — 산업별 βU·βL 등 제공

캐시:
  data/damodaran/totalbetaemerg.xls (월별 갱신; mtime > 30일이면 재다운)

매핑:
  krx_desc Industry → Damodaran sector(영문) 키워드 매칭 (WICS_TO_DAMODARAN).
  매핑 실패 시 None 반환 (교차검증 스킵).
"""
from __future__ import annotations
from pathlib import Path
import json
import urllib.request
import time
from typing import Optional

_VAR_ROOT = Path(__file__).resolve().parent.parent
_CACHE_DIR = _VAR_ROOT / "valuation_engine" / "data" / "damodaran"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

DAMODARAN_URL = "http://pages.stern.nyu.edu/~adamodar/pc/datasets/totalbetaemerg.xls"
_HEADERS = {"User-Agent": "Mozilla/5.0"}
_REFRESH_DAYS = 30                          # 캐시 갱신 주기

# WICS/krx_desc Industry 키워드 → Damodaran 산업명 매핑 (대표적 케이스 우선)
WICS_TO_DAMODARAN = [
    ("반도체",           "Semiconductor"),
    ("디스플레이",        "Electronics (General)"),
    ("전자부품",          "Electronics (General)"),
    ("자동차",           "Auto & Truck"),
    ("자동차 부품",       "Auto Parts"),
    ("자동차용 엔진",     "Auto Parts"),
    ("조선",            "Shipbuilding & Marine"),
    ("철강",            "Steel"),
    ("비철금속",         "Metals & Mining"),
    ("기초화학",         "Chemical (Basic)"),
    ("기초 화학물질",     "Chemical (Basic)"),
    ("화학",            "Chemical (Diversified)"),
    ("정유",            "Oil/Gas (Production and Exploration)"),
    ("석유",            "Oil/Gas (Integrated)"),
    ("통신",            "Telecom (Wireless)"),
    ("방송",            "Broadcasting"),
    ("은행",            "Bank (Money Center)"),
    ("보험",            "Insurance (General)"),
    ("증권",            "Brokerage & Investment Banking"),
    ("건설",            "Engineering/Construction"),
    ("운송",            "Transportation"),
    ("해운",            "Shipbuilding & Marine"),
    ("항공",            "Air Transport"),
    ("음·식료품",        "Food Processing"),
    ("음료",            "Beverage (Soft)"),
    ("주류",            "Beverage (Alcoholic)"),
    ("담배",            "Tobacco"),
    ("유통",            "Retail (General)"),
    ("백화점",          "Retail (General)"),
    ("의약품",          "Drugs (Pharmaceutical)"),
    ("의료용 기기",      "Healthcare Products"),
    ("기초의약물질",     "Drugs (Pharmaceutical)"),
    ("자료처리",        "Computer Services"),
    ("소프트웨어",      "Software (System & Application)"),
    ("게임",            "Software (Entertainment)"),
    ("자연과학 및 공학 연구개발", "Biotechnology"),
    ("화장품",          "Household Products"),
]


def _cache_path() -> Path:
    return _CACHE_DIR / "totalbetaemerg.xls"


def _cache_meta() -> Path:
    return _CACHE_DIR / "meta.json"


def _need_refresh() -> bool:
    p = _cache_path()
    if not p.exists():
        return True
    age_days = (time.time() - p.stat().st_mtime) / 86400
    return age_days > _REFRESH_DAYS


def download_damodaran(verbose: bool = False) -> Optional[Path]:
    """Damodaran emerging markets βU 표 다운로드 (캐시 30일 갱신)."""
    p = _cache_path()
    if not _need_refresh():
        if verbose:
            print(f"  [Damodaran] 캐시 hit (≤30일): {p.name}")
        return p
    try:
        if verbose:
            print(f"  [Damodaran] 다운로드: {DAMODARAN_URL}")
        req = urllib.request.Request(DAMODARAN_URL, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
        p.write_bytes(data)
        _cache_meta().write_text(json.dumps({"downloaded": time.time(),
                                             "size": len(data)},
                                            ensure_ascii=False, indent=2),
                                 encoding="utf-8")
        if verbose:
            print(f"  [Damodaran] {len(data)} bytes 저장")
        return p
    except Exception as e:
        if verbose:
            print(f"  [Damodaran] 다운로드 실패: {str(e)[:120]}")
        return None


def _normalize_sector(name: str) -> str:
    """Damodaran 산업명 normalize — 공백·괄호·대소문자 무시."""
    if not isinstance(name, str):
        return ""
    return name.lower().replace(" ", "").replace("(", "").replace(")", "").replace("&", "and")


def parse_industry_betas(path: Path, verbose: bool = False) -> dict:
    """XLS 파싱 → {산업명_normalized: {unlevered_beta, beta, sector_raw}}.

    파일 구조: 첫 시트 Industry Name 열 + Unlevered beta corrected for cash 열 (또는 유사).
    Damodaran 시트 컬럼명 약간 변동 가능 → 휴리스틱 컬럼 매칭.
    """
    try:
        import pandas as pd
        # Damodaran 파일은 시트 0이 변수 정의표, 데이터는 'Industry Averages' 시트에 있음
        xls = pd.ExcelFile(path)
        target_sheet = None
        for sh in xls.sheet_names:
            if "industry" in sh.lower() and "average" in sh.lower():
                target_sheet = sh
                break
        if target_sheet is None:
            target_sheet = xls.sheet_names[-1]   # 마지막 시트로 폴백
        df = pd.read_excel(xls, sheet_name=target_sheet, header=None)
        # 헤더 행 자동 감지: "Industry Name" 정확 매치 우선
        header_row = None
        for i in range(min(20, len(df))):
            row_vals = [str(v).strip() for v in df.iloc[i].values if v == v]
            row_str = " | ".join(row_vals).lower()
            if "industry name" in row_str:
                header_row = i
                break
        if header_row is None:
            if verbose:
                print(f"  [Damodaran] 헤더 행 미탐지 (시트={target_sheet})")
            return {}
        df = pd.read_excel(xls, sheet_name=target_sheet, header=header_row)
        df.columns = [str(c).strip() for c in df.columns]
        # 산업명 컬럼
        ind_col = next((c for c in df.columns if "industry" in c.lower()), None)
        # Unlevered beta 컬럼 (정확 명 변동 — 부분 매칭)
        ub_cands = [c for c in df.columns
                    if "unlever" in c.lower() and ("beta" in c.lower())]
        ub_col = ub_cands[0] if ub_cands else None
        b_col = next((c for c in df.columns
                      if c.lower() == "beta" or "levered beta" in c.lower()), None)
        if not ind_col or not ub_col:
            if verbose:
                print(f"  [Damodaran] 컬럼 매칭 실패. 컬럼={list(df.columns)[:8]}")
            return {}
        result = {}
        for _, row in df.iterrows():
            name = str(row[ind_col]).strip() if row[ind_col] == row[ind_col] else ""
            if not name or name.lower() in ("nan", "total"):
                continue
            try:
                ub = float(row[ub_col])
            except (ValueError, TypeError):
                continue
            try:
                bL = float(row[b_col]) if b_col else None
            except (ValueError, TypeError):
                bL = None
            result[_normalize_sector(name)] = {
                "unlevered_beta": ub, "beta": bL, "sector_raw": name,
            }
        if verbose:
            print(f"  [Damodaran] 파싱 {len(result)}개 산업")
        return result
    except Exception as e:
        if verbose:
            print(f"  [Damodaran] 파싱 실패: {str(e)[:150]}")
        return {}


def lookup_industry_beta(krx_industry: str,
                         verbose: bool = False) -> Optional[dict]:
    """krx_desc Industry → 매핑된 Damodaran 산업의 βU 조회.

    Returns: {damodaran_sector, unlevered_beta, beta, mapping_keyword} 또는 None.
    """
    if not isinstance(krx_industry, str) or not krx_industry:
        return None
    # WICS_TO_DAMODARAN 키워드 룰 적용
    matched_sector = None
    matched_keyword = None
    for kw, sector in WICS_TO_DAMODARAN:
        if kw in krx_industry:
            matched_sector = sector
            matched_keyword = kw
            break
    if not matched_sector:
        return None

    path = download_damodaran(verbose=verbose)
    if path is None:
        return None
    betas = parse_industry_betas(path, verbose=verbose)
    if not betas:
        return None
    target_key = _normalize_sector(matched_sector)
    if target_key in betas:
        return {**betas[target_key],
                "damodaran_sector": matched_sector,
                "mapping_keyword": matched_keyword}
    # 정확 매치 실패 → 부분 매치 시도
    # Phase 7: 부분매치 오매칭 방지 — 양쪽 키가 최소 4자 이상일 때만 포함 매치 허용.
    #   (짧은 키, 예 "it"·"oil" 가 무관 산업명에 우연 포함돼 잘못 매핑되는 것 차단.)
    for key, val in betas.items():
        if len(target_key) >= 4 and len(key) >= 4 \
                and (target_key in key or key in target_key):
            return {**val, "damodaran_sector": matched_sector,
                    "mapping_keyword": matched_keyword,
                    "match_type": "partial"}
    return None


if __name__ == "__main__":
    import sys
    ind = sys.argv[1] if len(sys.argv) > 1 else "반도체 제조업"
    r = lookup_industry_beta(ind, verbose=True)
    if r:
        print(f"\n  매핑 결과: {ind} → {r['damodaran_sector']}")
        print(f"    Unlevered β = {r['unlevered_beta']:.3f}")
        print(f"    Levered β   = {r.get('beta'):.3f}" if r.get('beta') else "    Levered β = N/A")
    else:
        print(f"\n  매핑 실패: {ind}")
