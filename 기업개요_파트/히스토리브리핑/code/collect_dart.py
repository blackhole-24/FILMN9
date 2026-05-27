"""DART 공시 → 임베딩용 JSONL 수집.

데이터 흐름:
  1. KRX 종목 목록 자동 로드 (또는 .env 의 회사 리스트)
  2. DART corpCode.xml 로 종목코드 → corp_code 매핑
  3. 회사별 사업보고서 조회 (list.json)
  4. document.xml 다운로드 → XML 정제 → 청킹 → JSONL 저장

산출물:
  data/rag/{stock_code}_{name}_{year}_annual_chunks.jsonl   # 청크
  data/raw/{stock_code}_{name}/{year}-annual_raw.xml        # 원본
  data/raw/{stock_code}_{name}/{year}-annual_cleaned.xml    # 정제본
  logs/dart_collect_YYYYMMDD_HHMMSS.csv                     # 진행 로그

사용:
  python -m code.collect_dart                # 전체 처리
  python -m code.collect_dart --limit 5      # 처음 5개사 (테스트)
  python -m code.collect_dart --no-skip      # 기존 JSONL 도 덮어쓰기
"""
from __future__ import annotations
import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# 같은 패키지 내부 import (python -m code.collect_dart 로 실행 시)
from . import config as cfg
from .helpers.dart_downloader import (
    DART_API_KEY, get_corp_map, fetch_reports, download_document, STATUS_MSG,
)
from .helpers.xml_cleaner import clean_xml, parse_with_fallback
from .helpers.chunker import build_chunks

sys.stdout.reconfigure(encoding="utf-8")


# ─── 회사 리스트 로드 ────────────────────────────────────────────────────────
def load_companies() -> list[tuple[str, str, str]]:
    """data/companies.json 에서 회사 리스트 로드.

    Returns: [(market, stock_code, name), ...]

    파일이 없으면 update_companies.py 를 먼저 실행하라고 안내.
    """
    companies_file = cfg.LOCAL_DATA_DIR / "companies.json"
    if not companies_file.exists():
        raise FileNotFoundError(
            f"회사 리스트 파일 없음: {companies_file}\n"
            f"먼저 'python -m code.update_companies' 실행 필요."
        )
    data = json.loads(companies_file.read_text(encoding="utf-8"))
    return [(c["market"], c["stock_code"], c["name"]) for c in data["companies"]]


# ─── 한 회사·보고서 처리 ─────────────────────────────────────────────────────
def safe_filename(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|&\s]+', '_', s).strip('_')


def process_one_report(company: dict, report_type: str, report_meta: dict,
                       skip_existing: bool = True) -> dict:
    sc, name = company["stock_code"], company["name"]
    safe = safe_filename(name)

    cfg.ensure_dirs()
    fn        = cfg.jsonl_filename(sc, safe, report_type)
    out_jsonl = cfg.LOCAL_RAG_DIR / fn
    co_dir    = cfg.LOCAL_RAW_DIR / f"{sc}_{safe}"
    co_dir.mkdir(exist_ok=True, parents=True)

    if skip_existing and out_jsonl.exists() and out_jsonl.stat().st_size > 0:
        n = sum(1 for _ in open(out_jsonl, encoding="utf-8"))
        return {"status": "skipped", "chunks": n, "out": str(out_jsonl)}

    # 1) document.xml 다운로드
    rcept_no = report_meta["rcept_no"]
    xml_text, err = download_document(rcept_no)
    if err:
        return {"status": "error", "stage": "download", "msg": err}

    # 2) XML 저장 + 정제
    rk = cfg.report_kind_label(report_type)
    (co_dir / f"{rk}_raw.xml").write_text(xml_text, encoding="utf-8")
    cleaned = clean_xml(xml_text)
    (co_dir / f"{rk}_cleaned.xml").write_text(cleaned, encoding="utf-8")

    # 3) 파싱
    try:
        root, mode = parse_with_fallback(cleaned)
    except Exception as e:
        return {"status": "error", "stage": "parse", "msg": f"{type(e).__name__}: {e}"}

    # 4) 청킹
    meta = {
        "group":         company["group"],
        "stock_code":    sc,
        "corp_code":     company["corp_code"],
        "corp_name":     name,
        "report_nm":     report_meta.get("report_nm", ""),
        "report_kind":   rk,
        "report_type":   report_type,
        "rcept_no":      rcept_no,
        "rcept_dt":      report_meta.get("rcept_dt", ""),
        "fiscal_period": rk,
        "source_url":    f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}",
        "parse_mode":    mode,
    }
    try:
        chunks = build_chunks(root, meta)
    except Exception as e:
        return {"status": "error", "stage": "chunk", "msg": f"{type(e).__name__}: {e}"}

    # 5) JSONL 저장
    with open(out_jsonl, "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    return {"status": "ok", "chunks": len(chunks), "mode": mode, "out": str(out_jsonl)}


# ─── 메인 ────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit",   type=int, default=None, help="첫 N개사만 (테스트)")
    ap.add_argument("--no-skip", action="store_true",    help="이미 있는 JSONL 도 덮어쓰기")
    args = ap.parse_args()

    if not DART_API_KEY:
        print("[FAIL] DART_API_KEY 미설정. .env 확인.")
        sys.exit(1)

    cfg.ensure_dirs()

    print(f"{'='*70}")
    print(f"  DART 사업보고서 수집")
    print(f"{'='*70}")
    print(f"  TARGET_FISCAL_YEAR : {cfg.TARGET_FISCAL_YEAR}")
    print(f"  REPORT_TYPES       : {cfg.REPORT_TYPES}")
    print(f"  검색 기간          : {cfg.get_search_window()}")
    print(f"  RAG (JSONL)        : {cfg.LOCAL_RAG_DIR}")
    print(f"  raw (XML)          : {cfg.LOCAL_RAW_DIR}")
    print()

    # 회사 리스트 + corp_code 매핑
    print("[1/4] 회사 리스트 로드")
    targets = load_companies()
    if args.limit:
        targets = targets[:args.limit]
    print(f"  → {len(targets):,}개사")

    print("\n[2/4] corp_code 매핑")
    stock_to_corp = get_corp_map()
    print(f"  → {len(stock_to_corp):,}개 매핑")

    mapped = []
    for grp, sc, name in targets:
        info = stock_to_corp.get(sc)
        if info:
            mapped.append({"group": grp, "stock_code": sc, "name": name,
                           "corp_code": info["corp_code"]})
    print(f"  → 매핑 성공: {len(mapped)}/{len(targets)}")

    print(f"\n[3/4] DART 다운로드 + 청킹 (skip_existing={not args.no_skip})")

    results = []
    failed  = []
    try:
        from tqdm import tqdm
        company_iter = tqdm(mapped, desc="Companies")
    except ImportError:
        company_iter = mapped

    for co in company_iter:
        try:
            reports = fetch_reports(co["corp_code"])
        except Exception as e:
            failed.append({**co, "stage": "list", "error": str(e)})
            time.sleep(cfg.RATE_LIMIT_SLEEP)
            continue

        for rt in cfg.REPORT_TYPES:
            rm = reports.get(rt)
            if not rm:
                continue
            r = process_one_report(co, rt, rm, skip_existing=not args.no_skip)
            row = {**co, "report_type": rt, "rcept_no": rm["rcept_no"],
                   "report_nm": rm.get("report_nm"), **r}
            results.append(row)
            if r["status"] == "error":
                failed.append(row)

        time.sleep(cfg.RATE_LIMIT_SLEEP)

    print(f"\n[4/4] 결과 저장")
    cfg.LOG_DIR.mkdir(parents=True, exist_ok=True)

    try:
        import pandas as pd
        df = pd.DataFrame(results)
        out_csv = cfg.LOG_DIR / f"dart_collect_{datetime.now():%Y%m%d_%H%M%S}.csv"
        df.to_csv(out_csv, index=False, encoding="utf-8-sig")
        print(f"  → {out_csv}")
    except ImportError:
        out_json = cfg.LOG_DIR / f"dart_collect_{datetime.now():%Y%m%d_%H%M%S}.json"
        out_json.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  → {out_json}")

    if failed:
        out_fail = cfg.LOG_DIR / "dart_collect_failed.json"
        out_fail.write_text(json.dumps(failed, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  실패 {len(failed)}건 → {out_fail}")

    n_ok      = sum(1 for r in results if r["status"] == "ok")
    n_skipped = sum(1 for r in results if r["status"] == "skipped")
    n_error   = sum(1 for r in results if r["status"] == "error")
    print(f"\n[완료] ok={n_ok}  skipped={n_skipped}  error={n_error}  total={len(results)}")


if __name__ == "__main__":
    main()
