"""
batch_save.py
─────────────────────────────────────────────────────────────────────────────
역할: 2,596개 기업 데이터를 사전 추출하여 JSON으로 저장 (화면 표시 속도 향상)

출력: outputs/cache/{종목코드}_data.json  (기업당 1파일)

추출 데이터:
  - 재무 하이라이트  : JSONL 사업보고서 → financial_parser.get_financial_highlight()
  - 재무 상세        : JSONL 사업보고서 → financial_parser.get_financial_detail()
  - 임원현황         : JSONL 사업보고서 → financial_parser.get_executive_table()
  - 기업개요/주주/공시: DART API (rate limit: 0.3초 간격)

실행:
  python batch_save.py              # 전체 실행
  python batch_save.py --limit 10   # 테스트: 10개만
  python batch_save.py --skip-api   # JSONL만 추출 (API 호출 없음)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.processors.financial_parser  import (
    get_financial_highlight,
    get_financial_detail,
    get_executive_table,
)
from src.collectors.dart_api_collector import (
    get_company_info,
    get_major_shareholders,
    get_recent_disclosures,
)
from src.app_config import RAG_DIR

CACHE_DIR = _ROOT / "outputs" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# JSONL 파일에서 종목코드 목록 추출
# ─────────────────────────────────────────────────────────────────────────────

def get_stock_codes() -> list[str]:
    """data/RAG/ 에서 종목코드 목록 반환"""
    codes = set()
    for f in Path(RAG_DIR).glob("*.jsonl"):
        code = f.stem.split("_")[0]  # "090430_아모레퍼시픽_2025_annual_chunks"
        if code:
            codes.add(code)
    return sorted(codes)


# ─────────────────────────────────────────────────────────────────────────────
# 단일 기업 데이터 추출
# ─────────────────────────────────────────────────────────────────────────────

def _df_to_records(df) -> list:
    """DataFrame → JSON 직렬화 가능 형태"""
    if df is None or df.empty:
        return []
    return df.where(df.notna(), None).to_dict(orient="records")


def extract_jsonl_data(stock_code: str) -> dict:
    """
    JSONL 사업보고서에서 재무 데이터 추출 (DART API 불필요)
    출처 파일: src/processors/financial_parser.py
    """
    highlight = {}
    for kind, df in get_financial_highlight(stock_code).items():
        highlight[kind] = _df_to_records(df)

    detail = {}
    for label, df in get_financial_detail(stock_code).items():
        detail[label] = _df_to_records(df)

    exec_df = get_executive_table(stock_code)

    return {
        "highlight": highlight,   # 출처: 사업보고서 재무정보 1-1 포괄손익계산서
        "detail":    detail,      # 출처: 사업보고서 재무정보 1-1 재무상태표+포괄손익
        "executives": _df_to_records(exec_df),  # 출처: 사업보고서 임원현황 섹션
    }


def extract_api_data(corp_code: str) -> dict:
    """
    DART API에서 기업개요/주주/공시 추출
    출처:
      company    : DART company.json    → dart_api_collector.py:get_company_info()
      shareholders: DART majorstock.json → dart_api_collector.py:get_major_shareholders()
      disclosures : DART list.json       → dart_api_collector.py:get_recent_disclosures()
    """
    company      = get_company_info(corp_code)
    time.sleep(0.3)
    shareholders = get_major_shareholders(corp_code)
    time.sleep(0.3)
    disclosures  = get_recent_disclosures(corp_code, n=10)
    return {
        "company":      company,       # 출처: DART company.json
        "shareholders": shareholders,  # 출처: DART majorstock.json
        "disclosures":  disclosures,   # 출처: DART list.json (dart_url 포함)
    }


# ─────────────────────────────────────────────────────────────────────────────
# 배치 저장 메인 루프
# ─────────────────────────────────────────────────────────────────────────────

def run_batch(limit: int | None = None, skip_api: bool = False) -> None:
    codes = get_stock_codes()
    if limit:
        codes = codes[:limit]

    total   = len(codes)
    success = 0
    failed  = []

    print(f"[배치 저장 시작] 총 {total}개 기업 | skip_api={skip_api}")
    print(f"출력 경로: {CACHE_DIR}")
    print("─" * 60)

    for i, code in enumerate(codes, 1):
        out_path = CACHE_DIR / f"{code}_data.json"
        if out_path.exists():
            print(f"[{i:4d}/{total}] {code} SKIP (이미 존재)")
            success += 1
            continue

        try:
            data = extract_jsonl_data(code)
            if not skip_api:
                # corp_code 조회: 종목코드로 DART corp_code 매핑 필요
                # 현재는 company.json에서 stock_code로 조회 불가 → 추후 연동
                pass  # TODO: corp_code 매핑 테이블 연동

            data["stock_code"]   = code
            data["generated_at"] = time.strftime("%Y-%m-%d %H:%M")

            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)

            success += 1
            print(f"[{i:4d}/{total}] {code} OK  → {out_path.name}")

        except Exception as e:
            failed.append((code, str(e)))
            print(f"[{i:4d}/{total}] {code} FAIL: {e}")

        if i % 100 == 0:
            print(f"  진행률: {i}/{total} ({i/total*100:.1f}%) | 실패: {len(failed)}개")

    print("─" * 60)
    print(f"완료: 성공 {success}개 / 실패 {len(failed)}개")
    if failed:
        fail_path = CACHE_DIR / "batch_errors.json"
        with open(fail_path, "w", encoding="utf-8") as f:
            json.dump(failed, f, ensure_ascii=False, indent=2)
        print(f"실패 목록: {fail_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FILMN9 배치 데이터 저장")
    parser.add_argument("--limit",    type=int,  default=None, help="처리 기업 수 제한 (테스트용)")
    parser.add_argument("--skip-api", action="store_true",     help="DART API 호출 생략 (JSONL만)")
    args = parser.parse_args()

    run_batch(limit=args.limit, skip_api=args.skip_api)
