# -*- coding: utf-8 -*-
"""자동 정기 업데이트 — DART 새 보고서 감지 → 이전 보고서 교체 → 임베딩.

정책(교체 규칙):
  · 새 사업보고서(annual) → 이전 사업보고서 + 같은 회계연도의 마지막 분기 삭제
  · 새 분기/반기(Q1·H1·Q3) → 같은 회계연도의 직전 분기/반기 삭제

종목별 atomic 처리(작은 트랜잭션):
  현재 상태(jsonl 파일명) vs DART 최신 상태 비교 → 차분 → 삭제·추가

  · 종목당 보유 패턴: (latest annual) + (annual보다 newer일 때만 latest 분기)
  · 분기는 (annual_year+1) 회계연도에 속할 때만 보유 의미
  · 삭제: jsonl 즉시 제거 + ChromaDB 해당 종목+report_kind 청크 삭제
  · 추가: download_document → dc_xml_cleaner → dc_chunker → jsonl 저장 → 임베딩 → upsert

실행:
  python embedding/auto_update.py            # 변경 즉시 반영
  python embedding/auto_update.py --dry      # 변경 미리보기 (실제 수정 X)
  python embedding/auto_update.py --limit 10 # 첫 10종목만 (테스트)
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import random
import re
import sys
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

VAR_ROOT = Path(r"C:\Users\Admin\Desktop\VAR")
sys.path.insert(0, str(VAR_ROOT))
from dotenv import load_dotenv

load_dotenv(VAR_ROOT / ".env")
DART_KEY = os.getenv("DART_API_KEY")
assert DART_KEY, "DART_API_KEY 미설정"

from valuation_engine.report_ingest import download_document
from valuation_engine.report_detector import list_periodic_reports
from embedding.dc_xml_cleaner import clean_xml, parse_with_fallback
from embedding.dc_chunker import build_chunks
from embedding.embedder import embed_texts
from embedding.vector_store import get_collection, get_stats, add_batch

# ── 파라미터 ──────────────────────────────────────────────────────────
KOSPI_DIR, KOSDAQ_DIR = VAR_ROOT / "KOSPI", VAR_ROOT / "KOSDAQ"
CSV_KOSPI = r"C:\Users\Admin\Downloads\data_1426_20260527.csv"
CSV_KOSDAQ = r"C:\Users\Admin\Downloads\data_1439_20260527.csv"
CORPCODE_CACHE = VAR_ROOT / "embedding" / "corpcode.xml"
LOG_FILE = VAR_ROOT / "embedding" / "auto_update.log"

REQUEST_DELAY = 0.1     # 전역 스로틀(초) — 분당 600회(한도 1000회의 60%)
UPSERT_BATCH = 4000     # ChromaDB upsert/embed 분할

# 월 → (period_label, report_nm_prefix)
_PERIOD = {"12": ("annual", "사업보고서"),
           "03": ("q1", "분기보고서"),
           "06": ("h1", "반기보고서"),
           "09": ("q3", "분기보고서")}
_PERIOD_TO_MONTH = {"annual": "12", "q1": "03", "h1": "06", "q3": "09"}
_REPORT_NM = {"annual": "사업보고서", "q1": "분기보고서", "h1": "반기보고서", "q3": "분기보고서"}
_REPORT_KIND_LABEL = {"annual": "사업보고서", "q1": "1분기보고서",
                      "h1": "반기보고서", "q3": "3분기보고서"}


def log(msg: str) -> None:
    line = f"[{time.strftime('%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ── 전역 스로틀 + 재시도 ──────────────────────────────────────────────
_lock = threading.Lock()
_last = [0.0]


def _throttle() -> None:
    with _lock:
        dt = time.time() - _last[0]
        if dt < REQUEST_DELAY:
            time.sleep(REQUEST_DELAY - dt)
        _last[0] = time.time()


def with_retry(fn, *a, tries=5, base=1.0, **k):
    for t in range(tries):
        try:
            _throttle()
            return fn(*a, **k)
        except Exception:
            if t == tries - 1:
                raise
            time.sleep(base * (2 ** t) + random.uniform(0, 0.5))


# ── 유니버스 · corp_code ──────────────────────────────────────────────
def load_universe() -> list[dict]:
    files = {"KOSPI": CSV_KOSPI, "KOSDAQ": CSV_KOSDAQ}
    rows, seen = [], set()
    for market, p in files.items():
        with open(p, encoding="cp949", newline="") as f:
            for r in csv.DictReader(f):
                code = (r.get("단축코드") or "").strip().zfill(6)
                if (code and (r.get("증권구분") or "").strip() == "주권"
                        and (r.get("주식종류") or "").strip() == "보통주" and code not in seen):
                    seen.add(code)
                    rows.append({"stock_code": code, "market": market,
                                 "corp_name": (r.get("한글 종목약명") or "").strip()})
    return rows


def load_corp_map() -> dict:
    root = ET.fromstring(CORPCODE_CACHE.read_bytes())
    m = {}
    for el in root.iter("list"):
        sc = (el.findtext("stock_code") or "").strip()
        cc = (el.findtext("corp_code") or "").strip()
        cn = (el.findtext("corp_name") or "").strip()
        if sc and cc:
            m[sc.zfill(6)] = {"corp_code": cc.zfill(8), "corp_name": cn}
    return m


# ── 상태 비교 ─────────────────────────────────────────────────────────
_FILENAME_RE = re.compile(r"^[A-Z0-9]{6}[A-Z0-9]*_.+_(\d{4})_(annual|q1|q2|h1|q3|semiannual)_chunks\.jsonl$",
                          re.IGNORECASE)


def current_state(stock: str, market: str) -> set[tuple[int, str]]:
    """현재 보유한 (year, period) 집합 — jsonl 파일명에서 추출."""
    d = KOSPI_DIR if market == "KOSPI" else KOSDAQ_DIR
    found: set[tuple[int, str]] = set()
    pat = re.compile(rf"^{re.escape(stock)}_.+_(\d{{4}})_(annual|q1|q2|h1|q3|semiannual)_chunks\.jsonl$")
    for f in glob.glob(str(d / f"{stock}_*_chunks.jsonl")):
        m = pat.match(Path(f).name)
        if m:
            found.add((int(m.group(1)), m.group(2)))
    return found


def classify_reports(reports: list[dict]) -> list[dict]:
    """list_periodic_reports 결과 → (year, period, rcept_no, rcept_dt, fiscal_period) 정규화."""
    out = []
    for r in reports:
        month = r.get("month", "")
        if month not in _PERIOD:
            continue
        period = _PERIOD[month][0]
        out.append({
            "year": int(r["year"]),
            "period": period,
            "rcept_no": r["rcept_no"],
            "rcept_dt": r["rcept_dt"],
            "fiscal_period": r.get("period", ""),  # 예: 2025.12
        })
    return out


def compute_target(classified: list[dict]) -> set[tuple[int, str]]:
    """정책 적용: 최신 annual + (annual보다 newer일 때만) 최신 분기/반기."""
    if not classified:
        return set()
    annuals = [r for r in classified if r["period"] == "annual"]
    latest_ann = max(annuals, key=lambda r: r["year"]) if annuals else None
    quarters = [r for r in classified if r["period"] in {"q1", "h1", "q3"}]
    q_month_order = {"q1": 3, "h1": 6, "q3": 9}
    if quarters:
        quarters.sort(key=lambda r: (r["year"], q_month_order.get(r["period"], 0)), reverse=True)
        latest_q = quarters[0]
    else:
        latest_q = None
    target: set[tuple[int, str]] = set()
    if latest_ann:
        target.add((latest_ann["year"], "annual"))
    if latest_q:
        # 분기는 annual보다 newer 회계연도에 있어야 보유 의미
        if (not latest_ann) or (latest_q["year"] > latest_ann["year"]):
            target.add((latest_q["year"], latest_q["period"]))
    return target


# ── 삭제 ─────────────────────────────────────────────────────────────
def delete_report(stock: str, market: str, year: int, period: str,
                  coll, dry: bool = False) -> str:
    """jsonl + DB 청크 삭제. annual은 ticker+year로 (백업 era 호환), 그 외는 report_kind로."""
    d = KOSPI_DIR if market == "KOSPI" else KOSDAQ_DIR
    files = glob.glob(str(d / f"{stock}_*_{year}_{period}_chunks.jsonl"))
    if dry:
        return f"  DEL(dry) {year}-{period} | jsonl {len(files)}건 · DB chunks 예정"
    # 1) jsonl 즉시 삭제 (사용자 요구: 자동삭제)
    for f in files:
        try:
            Path(f).unlink()
        except Exception as e:
            log(f"   jsonl 삭제 실패 {f}: {e}")
    # 2) DB 청크 삭제 — 종목 단위라 작은 트랜잭션(안전)
    try:
        if period == "annual":
            # 백업 era 호환: report_kind 없을 수 있어 year로
            coll.delete(where={"$and": [{"ticker": stock}, {"year": year}]})
        else:
            coll.delete(where={"$and": [{"ticker": stock}, {"report_kind": f"{year}-{period}"}]})
    except Exception as e:
        return f"  DEL FAILED {year}-{period}: {str(e)[:80]}"
    return f"  DEL {year}-{period} | jsonl {len(files)}건 삭제 + DB 청크 삭제 완료"


# ── 추가(다운로드+청킹+임베딩) ────────────────────────────────────────
def collect_and_embed(rec: dict, market: str, corp_code: str, corp_name: str,
                      report: dict, coll, dry: bool = False) -> tuple[str, int]:
    year, period = report["year"], report["period"]
    rcept_no = report["rcept_no"]
    if dry:
        return f"  ADD(dry) {year}-{period} rcept={rcept_no}", 0

    xml = with_retry(download_document, rcept_no)
    root, mode = parse_with_fallback(clean_xml(xml))
    rkind = f"{year}-{period}"
    fiscal_period_str = report.get("fiscal_period") or f"{year}.{_PERIOD_TO_MONTH[period]}"
    rnm = f"{_REPORT_NM[period]} ({fiscal_period_str})"
    src = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"
    meta = {
        "group": market, "stock_code": rec["stock_code"], "corp_code": corp_code,
        "corp_name": corp_name, "report_nm": rnm, "report_kind": rkind,
        "report_type": "annual" if period == "annual" else "quarterly",
        "rcept_no": rcept_no, "rcept_dt": report["rcept_dt"], "fiscal_period": rkind,
        "source_url": src, "parse_mode": mode,
    }
    recs = build_chunks(root, meta)
    if not recs:
        return f"  ADD {year}-{period}: 청크 0 (파싱 결과 없음)", 0

    # jsonl 원자적 쓰기
    safe = re.sub(r'[\\/:*?"<>|]+', "", corp_name).strip() or rec["stock_code"]
    d = KOSPI_DIR if market == "KOSPI" else KOSDAQ_DIR
    path = d / f"{rec['stock_code']}_{safe}_{year}_{period}_chunks.jsonl"
    tmp = path.with_suffix(".jsonl.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for rr in recs:
            f.write(json.dumps(rr, ensure_ascii=False) + "\n")
    tmp.replace(path)

    # 임베딩 + upsert (ticker/year 메타 일관화)
    ids, texts, metas = [], [], []
    for r in recs:
        ids.append(r["id"])
        texts.append(r["text"])
        sp = r.get("section_path") or []
        m = {
            "ticker": r.get("stock_code", ""),
            "corp_name": r.get("corp_name", ""),
            "corp_name_raw": r.get("corp_name", ""),
            "corp_code": r.get("corp_code", ""),
            "year": year,
            "section_main": sp[0] if len(sp) >= 1 else "",
            "section_sub":  sp[1] if len(sp) >= 2 else "",
            "section_path_str": r.get("section_path_str", ""),
            "kind": r.get("kind", ""),
            "char_len": r.get("char_len", len(r.get("text", ""))),
            "rcept_no": r.get("rcept_no", ""),
            "rcept_dt": r.get("rcept_dt", ""),
            "parse_mode": r.get("parse_mode", "ingest_v1"),
            "report_type": r.get("report_type", ""),
            "report_kind": r.get("report_kind", ""),
            "report_nm": r.get("report_nm", ""),
            "group": r.get("group", ""),
            "source_url": r.get("source_url", ""),
        }
        metas.append(m)

    n_emb = 0
    for s in range(0, len(ids), UPSERT_BATCH):
        sub_ids = ids[s:s + UPSERT_BATCH]
        sub_txt = texts[s:s + UPSERT_BATCH]
        sub_meta = metas[s:s + UPSERT_BATCH]
        embs = embed_texts(sub_txt, show_progress=False)
        add_batch(sub_ids, sub_txt, [e.tolist() for e in embs], sub_meta)
        n_emb += len(sub_ids)
    return f"  ADD {year}-{period} rcept={rcept_no} | {n_emb}청크 임베딩+upsert 완료", n_emb


# ── 종목 단위 처리 ────────────────────────────────────────────────────
def process_stock(rec: dict, corp_map: dict, coll, dry: bool = False) -> Optional[str]:
    stock, market = rec["stock_code"], rec["market"]
    info = corp_map.get(stock)
    if not info:
        return None  # corpCode 없는 종목 (소수 — 신규상장 등)
    corp_code = info["corp_code"]
    corp_name = info["corp_name"] or rec.get("corp_name") or stock

    # 최근 2년치 정기공시 (annual + 4개 분기 충분)
    today = time.localtime()
    bgn = f"{today.tm_year - 1}0101"
    end = f"{today.tm_year}1231"
    try:
        reports = with_retry(list_periodic_reports, corp_code, bgn, end)
    except Exception as e:
        return f"❌ {stock} {corp_name}: 탐색 실패 - {str(e)[:90]}"

    classified = classify_reports(reports)
    target = compute_target(classified)
    current = current_state(stock, market)

    to_delete = current - target
    to_add = target - current
    if not to_delete and not to_add:
        return None  # 변경 없음(대다수 종목)

    cur_s = "·".join(f"{y}-{p}" for y, p in sorted(current)) or "(없음)"
    tgt_s = "·".join(f"{y}-{p}" for y, p in sorted(target)) or "(없음)"
    msgs = [f"📊 {stock} {corp_name}: current=[{cur_s}] → target=[{tgt_s}]"]

    # 1) 삭제 먼저 (id 충돌 방지)
    for year, period in sorted(to_delete):
        msgs.append(delete_report(stock, market, year, period, coll, dry))

    # 2) 추가
    for year, period in sorted(to_add):
        match = next((r for r in classified if r["year"] == year and r["period"] == period), None)
        if not match:
            msgs.append(f"  ADD 실패 {year}-{period}: DART에 rcept_no 없음")
            continue
        try:
            m, _ = collect_and_embed(rec, market, corp_code, corp_name, match, coll, dry)
            msgs.append(m)
        except Exception as e:
            msgs.append(f"  ADD 실패 {year}-{period}: {str(e)[:120]}")
    return "\n".join(msgs)


# ── 메인 ─────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="DART 정기보고서 자동 교체·임베딩 업데이트")
    ap.add_argument("--dry", action="store_true", help="변경 미리보기 (실제 수정 안 함)")
    ap.add_argument("--limit", type=int, default=0, help="첫 N 종목만 처리 (0=전체)")
    args = ap.parse_args()

    log(f"=== auto_update 시작 ({'DRY-RUN' if args.dry else '실행'}) ===")
    log(f"DB(시작): {get_stats()}")
    universe = load_universe()
    corp_map = load_corp_map()
    universe = [r for r in universe if r["stock_code"] in corp_map]
    if args.limit > 0:
        universe = universe[:args.limit]
    log(f"대상 종목: {len(universe)}")

    coll = get_collection()
    t0 = time.time()
    n_changed = n_failed = 0
    for i, rec in enumerate(universe, 1):
        try:
            result = process_stock(rec, corp_map, coll, args.dry)
            if result:
                log(result)
                if "❌" in result:
                    n_failed += 1
                else:
                    n_changed += 1
        except Exception as e:
            n_failed += 1
            log(f"❌ {rec['stock_code']} 처리 실패: {str(e)[:120]}")
        if i % 200 == 0:
            log(f"--- 진행 {i}/{len(universe)} | 변경 {n_changed} · 실패 {n_failed} · {time.time()-t0:.0f}s ---")

    log(f"=== auto_update 완료: 변경 {n_changed} · 실패 {n_failed} · {time.time()-t0:.0f}s ===")
    log(f"DB(종료): {get_stats()}")


if __name__ == "__main__":
    main()
