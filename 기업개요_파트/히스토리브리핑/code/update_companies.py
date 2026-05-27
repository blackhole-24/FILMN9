"""KOSPI + KOSDAQ 전 종목 자동 갱신 + WICS 보충.

흐름:
  1. FinanceDataReader 로 KRX 전 종목 수집
  2. 제외 필터 (SPAC, 우선주, 리츠)
  3. WICS 캐시 로드 (data/wics_cache.json — 없으면 wics_seed.json 으로 부트스트랩)
  4. 신규 종목 식별 (KRX 에 있지만 WICS 캐시에 없는 것)
  5. 신규 종목만 네이버에서 WICS 크롤링 (병렬)
  6. 캐시 업데이트 → data/wics_cache.json
  7. companies.json 저장 (전체 종목 + wics 컬럼)

사용:
  python -m code.update_companies                 # 자동
  python -m code.update_companies --refresh-wics  # 전체 WICS 재크롤링 (느림)
"""
import argparse
import json
import re
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import pandas as pd
import requests
import FinanceDataReader as fdr
from bs4 import BeautifulSoup

from . import config as cfg

sys.stdout.reconfigure(encoding="utf-8")


# ─── 제외 패턴 ────────────────────────────────────────────────────────────────
EXCLUDE_NAME_PATTERNS = [
    r"기업인수목적", r"스팩", r"우선주", r"\(우\)$", r"리츠$", r"인프라$",
]


def is_excluded(name: str) -> bool:
    for p in EXCLUDE_NAME_PATTERNS:
        if re.search(p, name):
            return True
    return False


# ─── 네이버 WICS 크롤링 ───────────────────────────────────────────────────────
WICS_URL    = "https://navercomp.wisereport.co.kr/v2/company/c1010001.aspx"
WICS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer":    "https://finance.naver.com/",
}


def fetch_wics_one(stock_code: str, retries: int = 2) -> str | None:
    """네이버 위세리포트에서 WICS 분류 추출."""
    for _ in range(retries):
        try:
            r = requests.get(WICS_URL, params={"cmp_cd": stock_code, "cn": ""},
                             headers=WICS_HEADERS, timeout=10)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            for tag in soup.find_all("dt", class_="line-left"):
                text = tag.get_text(strip=True)
                if text.startswith("WICS"):
                    return text.split(":")[-1].strip()
        except Exception:
            pass
        time.sleep(0.3)
    return None


def fetch_wics_parallel(stock_codes: list[str], max_workers: int = 5) -> dict[str, str]:
    """병렬 WICS 크롤링."""
    results = {}
    print(f"  네이버 WICS 크롤링: {len(stock_codes)}개  (병렬 {max_workers})")
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(fetch_wics_one, sc): sc for sc in stock_codes}
        done = 0
        for f in as_completed(futures):
            sc = futures[f]
            wics = f.result()
            if wics:
                results[sc] = wics
            done += 1
            if done % 20 == 0 or done == len(stock_codes):
                print(f"    [{done}/{len(stock_codes)}] {sc} → {wics or '실패'}")
    return results


# ─── 종목 수집 + 필터 ─────────────────────────────────────────────────────────
def fetch_all_stocks() -> pd.DataFrame:
    print("[1/5] FinanceDataReader 로 종목 조회")
    frames = []
    for market in ("KOSPI", "KOSDAQ"):
        df = fdr.StockListing(market)[["Code", "Name"]].copy()
        df["Market"] = market
        frames.append(df)
        print(f"  {market}: {len(df):,}개")
    return pd.concat(frames, ignore_index=True)


def filter_active(df: pd.DataFrame) -> pd.DataFrame:
    print("\n[2/5] 필터링 (SPAC, 우선주, 리츠 제외)")
    before = len(df)
    df = df[~df["Name"].apply(is_excluded)].copy()
    df = df.sort_values("Code").reset_index(drop=True)
    print(f"  {before:,} → {len(df):,}개 (제외 {before-len(df):,}개)")
    return df


# ─── WICS 캐시 관리 ──────────────────────────────────────────────────────────
def load_wics_cache(refresh: bool = False) -> dict[str, str]:
    """캐시 우선, 없으면 seed로 부트스트랩.

    refresh=True 면 캐시 무시 (전체 재크롤링용).
    """
    cache_path = cfg.LOCAL_DATA_DIR / "wics_cache.json"
    seed_path  = cfg.CODE_DIR / "wics_seed.json"

    if refresh:
        return {}

    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))

    if seed_path.exists():
        print(f"\n[3/5] WICS 캐시 부트스트랩: seed → cache")
        cfg.LOCAL_DATA_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy(seed_path, cache_path)
        return json.loads(cache_path.read_text(encoding="utf-8"))

    return {}


def save_wics_cache(mapping: dict[str, str]):
    path = cfg.LOCAL_DATA_DIR / "wics_cache.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(mapping, ensure_ascii=False, indent=1), encoding="utf-8")


# ─── 저장 ─────────────────────────────────────────────────────────────────────
def save_companies(df: pd.DataFrame):
    out = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total":        len(df),
        "kospi_count":  int((df["Market"] == "KOSPI").sum()),
        "kosdaq_count": int((df["Market"] == "KOSDAQ").sum()),
        "with_wics":    int(df["wics"].notna().sum()),
        "without_wics": int(df["wics"].isna().sum()),
        "companies": [
            {
                "market":     row["Market"],
                "stock_code": row["Code"],
                "name":       row["Name"],
                "wics":       row["wics"] if pd.notna(row["wics"]) else None,
            }
            for _, row in df.iterrows()
        ],
    }
    cfg.LOCAL_DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = cfg.LOCAL_DATA_DIR / "companies.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[5/5] 저장: {path}")
    print(f"  KOSPI       : {out['kospi_count']:,}")
    print(f"  KOSDAQ      : {out['kosdaq_count']:,}")
    print(f"  합계        : {out['total']:,}")
    print(f"  WICS 있음   : {out['with_wics']:,}")
    print(f"  WICS 없음   : {out['without_wics']:,}")


# ─── 메인 ────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh-wics", action="store_true",
                    help="전체 WICS 재크롤링 (느림, ~20분)")
    args = ap.parse_args()

    print(f"{'='*60}")
    print(f"  종목 마스터 리스트 자동 갱신 (KRX + WICS)")
    print(f"{'='*60}\n")

    df = fetch_all_stocks()
    df = filter_active(df)

    # WICS 캐시 로드
    cache = load_wics_cache(refresh=args.refresh_wics)
    print(f"\n[3/5] WICS 캐시: {len(cache):,}개 종목 매핑 로드됨")

    # 신규 종목 식별
    krx_codes = set(df["Code"])
    if args.refresh_wics:
        new_codes = sorted(krx_codes)
    else:
        new_codes = sorted(krx_codes - set(cache.keys()))

    print(f"\n[4/5] 신규 종목 식별 + WICS 크롤링")
    print(f"  KRX 종목       : {len(krx_codes):,}")
    print(f"  캐시 매칭       : {len(krx_codes & set(cache.keys())):,}")
    print(f"  WICS 크롤링 필요: {len(new_codes):,}")

    if new_codes:
        new_wics = fetch_wics_parallel(new_codes, max_workers=5)
        cache.update(new_wics)
        save_wics_cache(cache)
        print(f"  크롤링 결과: {len(new_wics)}개 성공, {len(new_codes)-len(new_wics)}개 실패")

    # WICS 컬럼 채우기
    df["wics"] = df["Code"].map(cache)

    save_companies(df)
    print(f"\n완료!")


if __name__ == "__main__":
    main()
