"""
DART 공시 → 임베딩용 JSONL 수집 파이프라인 (CLI).

순서:
1. config.py 의 TARGET_FISCAL_YEAR / REPORT_TYPES / RAG_DIR / RAW_DIR 로드
2. companies.py 의 COMPANIES 리스트 로드
3. corp_code 매핑
4. 회사별 보고서 (REPORT_TYPES 의 각 보고서 종류) 처리
   ① list.json 으로 rcept_no 조회
   ② document.xml 다운로드
   ③ XML 정제 (clean_xml v3)
   ④ 표·문장 청킹
   ⑤ JSONL 저장 → RAG_DIR/{stock_code}_{name}_{year}_{type}_chunks.jsonl
5. 진행 로그 → outputs/progress.csv + outputs/failed.json

사용:
    python pipeline.py                      # 전체 회사 처리
    python pipeline.py --group G1           # 특정 그룹만
    python pipeline.py --limit 5            # 처음 5개만 (테스트용)
"""
from __future__ import annotations
import argparse, json, re, sys, time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import config as cfg
from companies import COMPANIES, validate
from dart_downloader import (
    DART_API_KEY, get_corp_map, fetch_reports, download_document, STATUS_MSG,
)
from xml_cleaner import clean_xml, parse_with_fallback
from chunker import build_chunks


def safe_filename(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|&\s]+', '_', s).strip('_')


def process_one_report(company: dict, report_type: str, report_meta: dict,
                       skip_existing: bool = True) -> dict:
    """
    한 회사의 한 보고서를 처리 (다운로드 → 정제 → 청킹 → JSONL 저장).

    Args:
        company: {'group', 'stock_code', 'name', 'corp_code'}
        report_type: 'annual' | 'Q1' | 'H1' | 'Q3'
        report_meta: fetch_reports 로 받은 dict (rcept_no, rcept_dt, report_nm)
    """
    sc, name = company["stock_code"], company["name"]
    safe = safe_filename(name)

    # 출력 파일 경로
    cfg.RAG_DIR.mkdir(parents=True, exist_ok=True)
    cfg.RAW_DIR.mkdir(parents=True, exist_ok=True)
    fn       = cfg.jsonl_filename(sc, safe, report_type)
    out_jsonl = cfg.RAG_DIR / fn
    co_dir    = cfg.RAW_DIR / f"{sc}_{safe}"
    co_dir.mkdir(exist_ok=True, parents=True)

    if skip_existing and out_jsonl.exists() and out_jsonl.stat().st_size > 0:
        n = sum(1 for _ in open(out_jsonl, encoding="utf-8"))
        return {"status": "skipped", "chunks": n, "out": str(out_jsonl)}

    # ① document.xml 다운로드
    rcept_no = report_meta["rcept_no"]
    xml_text, err = download_document(rcept_no)
    if err:
        return {"status": "error", "stage": "download", "msg": err}

    # raw + cleaned 저장
    rk = cfg.report_kind_label(report_type)   # 예: "2024-annual"
    (co_dir / f"{rk}_raw.xml").write_text(xml_text, encoding="utf-8")
    cleaned = clean_xml(xml_text)
    (co_dir / f"{rk}_cleaned.xml").write_text(cleaned, encoding="utf-8")

    # ② 파싱
    try:
        root, mode = parse_with_fallback(cleaned)
    except Exception as e:
        return {"status": "error", "stage": "parse", "msg": f"{type(e).__name__}: {e}"}

    # ③ 청킹
    meta = {
        "group":          company["group"],
        "stock_code":     sc,
        "corp_code":      company["corp_code"],
        "corp_name":      name,
        "report_nm":      report_meta.get("report_nm", ""),
        "report_kind":    rk,
        "report_type":    report_type,
        "rcept_no":       rcept_no,
        "rcept_dt":       report_meta.get("rcept_dt", ""),
        "fiscal_period":  rk,
        "source_url":     f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}",
        "parse_mode":     mode,
    }
    try:
        chunks = build_chunks(root, meta)
    except Exception as e:
        return {"status": "error", "stage": "chunk", "msg": f"{type(e).__name__}: {e}"}

    # ④ JSONL 저장
    with open(out_jsonl, "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    return {"status": "ok", "chunks": len(chunks), "mode": mode, "out": str(out_jsonl)}


def main():
    ap = argparse.ArgumentParser(description="DART 공시 → 임베딩용 JSONL 수집")
    ap.add_argument("--group",  default=None, help="특정 그룹만 (예: G1)")
    ap.add_argument("--limit",  type=int, default=None, help="첫 N개사만 (테스트)")
    ap.add_argument("--no-skip", action="store_true", help="이미 있는 JSONL 도 덮어쓰기")
    args = ap.parse_args()

    # ─── 사전 점검 ───
    if not DART_API_KEY:
        print("❌ DART_API_KEY 미설정. .env 또는 환경변수 등록 후 재시도.")
        sys.exit(1)

    res = validate()
    if not res["ok"]:
        print("❌ companies.py 무결성 오류:")
        for e in res["errors"]: print(f"  - {e}")
        sys.exit(1)

    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"  TARGET_FISCAL_YEAR : {cfg.TARGET_FISCAL_YEAR}")
    print(f"  REPORT_TYPES       : {cfg.REPORT_TYPES}")
    print(f"  검색 기간          : {cfg.get_search_window()}")
    print(f"  회사 수            : {res['n_total']} ({res['n_groups']} 그룹)")
    print(f"  RAG (JSONL)        : {cfg.RAG_DIR}")
    print(f"  raw (XML)          : {cfg.RAW_DIR}")
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

    # ─── corp_code 매핑 ───
    print("[1/4] corp_code 매핑")
    stock_to_corp = get_corp_map()
    print(f"  → {len(stock_to_corp):,}개 매핑 로드\n")

    # ─── 회사 리스트 필터 ───
    targets = COMPANIES
    if args.group:
        targets = [c for c in targets if c[0] == args.group]
    if args.limit:
        targets = targets[:args.limit]

    # 매핑 가능한 회사만
    mapped = []
    for grp, sc, name in targets:
        info = stock_to_corp.get(sc)
        if info:
            mapped.append({"group": grp, "stock_code": sc, "name": name,
                           "corp_code": info["corp_code"]})
        else:
            print(f"  ⚠ 매핑 실패: {sc} {name} (corpCode.xml 에 없음)")

    print(f"\n[2/4] 회사 리스트 확정: {len(mapped)} / {len(targets)}\n")

    # ─── 회사·보고서별 처리 ───
    print(f"[3/4] DART 다운로드 + 청킹 (skip_existing={not args.no_skip})\n")

    results = []
    failed  = []
    skip_existing = not args.no_skip

    try:
        from tqdm import tqdm
        company_iter = tqdm(mapped, desc="Companies")
    except ImportError:
        company_iter = mapped

    for co in company_iter:
        # 보고서 조회
        try:
            reports = fetch_reports(co["corp_code"])
        except Exception as e:
            print(f"  ❌ {co['stock_code']} {co['name']} list.json 실패: {e}")
            failed.append({**co, "stage": "list", "error": str(e)})
            time.sleep(cfg.RATE_LIMIT_SLEEP)
            continue

        if reports.get("_status") != "000":
            err = reports.get("_error")
            print(f"  ⚠ {co['stock_code']} {co['name']} list.json: {err}")

        # 각 보고서 종류별 처리
        for rt in cfg.REPORT_TYPES:
            report_meta = reports.get(rt)
            if not report_meta:
                continue   # 그 보고서 종류 미공시 → 정상 (건너뜀)

            r = process_one_report(co, rt, report_meta, skip_existing=skip_existing)
            row = {**co, "report_type": rt, "rcept_no": report_meta["rcept_no"],
                   "report_nm": report_meta.get("report_nm"), **r}
            results.append(row)
            if r["status"] == "error":
                failed.append(row)

        time.sleep(cfg.RATE_LIMIT_SLEEP)

    # ─── 로그 저장 ───
    print(f"\n[4/4] 결과 저장")
    cfg.LOG_DIR.mkdir(parents=True, exist_ok=True)

    try:
        import pandas as pd
        df = pd.DataFrame(results)
        out_csv = cfg.LOG_DIR / f"progress_{datetime.now():%Y%m%d_%H%M%S}.csv"
        df.to_csv(out_csv, index=False, encoding="utf-8-sig")
        print(f"  → {out_csv}")
    except ImportError:
        out_json = cfg.LOG_DIR / f"progress_{datetime.now():%Y%m%d_%H%M%S}.json"
        out_json.write_text(json.dumps(results, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        print(f"  → {out_json}")

    if failed:
        out_fail = cfg.LOG_DIR / "failed.json"
        out_fail.write_text(json.dumps(failed, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        print(f"  ⚠ 실패 {len(failed)}건 → {out_fail}")

    # 요약
    n_ok      = sum(1 for r in results if r["status"] == "ok")
    n_skipped = sum(1 for r in results if r["status"] == "skipped")
    n_error   = sum(1 for r in results if r["status"] == "error")
    print(f"\n✅ ok={n_ok}  skipped={n_skipped}  error={n_error}  total={len(results)}")


if __name__ == "__main__":
    main()
