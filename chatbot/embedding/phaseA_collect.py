# -*- coding: utf-8 -*-
"""Phase A — 정기보고서 수집 + jsonl 변환 (임베딩 없음). 멀티프로세스 파싱.

분리 구조 1단계: DART에서 미보유 2025 사업보고서 + 2026 1분기보고서를 다운로드→파싱→jsonl 저장만 한다.

★ 성능 핵심: parse_chunks(거대 표 파싱)가 CPU-바운드라 ThreadPool에서는 GIL 때문에
   1코어로 직렬화된다(큰 보고서 1건 27초 동안 전체 스톨). → ProcessPoolExecutor로
   파싱을 멀티코어에 진짜 병렬화. DART 호출은 프로세스 공유 rate-limiter로 분당 600회 유지.

실행:  python embedding/phaseA_collect.py
"""
from __future__ import annotations

import csv
import json
import multiprocessing as mp
import os
import random
import re
import sys
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
from pathlib import Path

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

# ── 파라미터 ──────────────────────────────────────────────────────────
KOSPI_DIR, KOSDAQ_DIR = VAR_ROOT / "KOSPI", VAR_ROOT / "KOSDAQ"
KOSPI_DIR.mkdir(exist_ok=True)
KOSDAQ_DIR.mkdir(exist_ok=True)

CSV_KOSPI = r"C:\Users\Admin\Downloads\data_1426_20260527.csv"
CSV_KOSDAQ = r"C:\Users\Admin\Downloads\data_1439_20260527.csv"

TARGET_PERIODS = {"2025.12", "2026.03"}     # 2025 사업 + 2026 1분기
LIST_BGN, LIST_END = "20260101", "20260531"
DISCOVERY_WORKERS = 8        # 탐색(list.json, 가벼움) 스레드 수
COLLECT_PROCS = 8            # 수집(다운로드+파싱) 프로세스 수 — 파싱 멀티코어 병렬(16코어 중 8)
REQUEST_DELAY = 0.1          # DART 호출 간 최소 간격(초) — 분당 600회(한도 1000회의 60%)

CORPCODE_CACHE = VAR_ROOT / "embedding" / "corpcode.xml"
PROGRESS_LOG = VAR_ROOT / "embedding" / "collect_progress.json"
LOG_FILE = VAR_ROOT / "embedding" / "phaseA_collect.log"

_PERIOD = {"12": ("annual", "annual", "사업보고서"), "03": ("q1", "quarterly", "분기보고서"),
           "06": ("semiannual", "semiannual", "반기보고서"), "09": ("q3", "quarterly", "분기보고서")}


def log(msg: str) -> None:
    line = f"[{time.strftime('%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ── 경로 · 보유 여부 ──────────────────────────────────────────────────
def jsonl_path(market, stock, corp_name, year, plabel) -> Path:
    safe = re.sub(r'[\\/:*?"<>|]+', "", corp_name).strip() or stock
    d = KOSPI_DIR if market == "KOSPI" else KOSDAQ_DIR
    return d / f"{stock}_{safe}_{year}_{plabel}_chunks.jsonl"


def already_have(market, stock, year, plabel) -> bool:
    d = KOSPI_DIR if market == "KOSPI" else KOSDAQ_DIR
    return any(d.glob(f"{stock}_*_{year}_{plabel}_chunks*.jsonl"))


# ── 워커(프로세스) 공유 rate-limiter ──────────────────────────────────
_RL_LOCK = None   # multiprocessing.Lock proxy
_RL_LAST = None   # multiprocessing.Value('d')


def _init_worker(lock, last):
    global _RL_LOCK, _RL_LAST
    _RL_LOCK, _RL_LAST = lock, last


def _throttle_mp():
    with _RL_LOCK:
        dt = time.time() - _RL_LAST.value
        if dt < REQUEST_DELAY:
            time.sleep(REQUEST_DELAY - dt)
        _RL_LAST.value = time.time()


def _retry_mp(fn, *a, tries=5, base=1.0):
    for t in range(tries):
        try:
            _throttle_mp()
            return fn(*a)
        except Exception:
            if t == tries - 1:
                raise
            time.sleep(base * (2 ** t) + random.uniform(0, 0.5))


def collect_worker(task):
    """(프로세스) 다운로드 → XML정제 → 마크다운 청킹(dc_chunker) → jsonl 원자적 저장.

    task=(stock,market,corp_code,corp_name,rep). build_chunks가 최종 jsonl 레코드(18키)를 직접 생성.
    """
    stock, market, corp_code, corp_name, rep = task
    plabel, rtype, prefix = _PERIOD[rep["month"]]
    year = rep["year"]
    rkind = f"{year}-{plabel}"            # 예: 2026-q1, 2025-annual (소문자 — 챗봇 라벨 호환)
    rnm = f"{prefix} ({rep['period']})"
    src = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rep['rcept_no']}"
    xml = _retry_mp(download_document, rep["rcept_no"])
    root, mode = parse_with_fallback(clean_xml(xml))
    meta = {
        "group": market, "stock_code": stock, "corp_code": corp_code, "corp_name": corp_name,
        "report_nm": rnm, "report_kind": rkind, "report_type": rtype,
        "rcept_no": rep["rcept_no"], "rcept_dt": rep["rcept_dt"], "fiscal_period": rkind,
        "source_url": src, "parse_mode": mode,
    }
    recs = build_chunks(root, meta)       # id+메타+kind/section/char_len/text (기존 스키마)
    path = jsonl_path(market, stock, corp_name, year, plabel)
    tmp = path.with_suffix(".jsonl.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for rr in recs:
            f.write(json.dumps(rr, ensure_ascii=False) + "\n")
    tmp.replace(path)
    return f"{stock}:{year}-{plabel}", len(recs)


# ── 탐색(스레드) ──────────────────────────────────────────────────────
_t_lock = threading.Lock()
_t_last = [0.0]


def _throttle_thread():
    with _t_lock:
        dt = time.time() - _t_last[0]
        if dt < REQUEST_DELAY:
            time.sleep(REQUEST_DELAY - dt)
        _t_last[0] = time.time()


def fetch_targets(rec, CORP):
    cc = CORP[rec["stock_code"]]["corp_code"]
    for t in range(5):
        try:
            _throttle_thread()
            reps = list_periodic_reports(cc, LIST_BGN, LIST_END)
            break
        except Exception:
            if t == 4:
                raise
            time.sleep(1.0 * (2 ** t) + random.uniform(0, 0.5))
    return rec, [r for r in reps if r["period"] in TARGET_PERIODS]


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


def build_corpcode_map() -> dict:
    if not (CORPCODE_CACHE.exists() and CORPCODE_CACHE.stat().st_size > 100000):
        raise RuntimeError(f"corpCode 캐시 없음: {CORPCODE_CACHE}")
    root = ET.fromstring(CORPCODE_CACHE.read_bytes())
    m = {}
    for el in root.iter("list"):
        sc = (el.findtext("stock_code") or "").strip()
        cc = (el.findtext("corp_code") or "").strip()
        cn = (el.findtext("corp_name") or "").strip()
        if sc and cc:
            m[sc.zfill(6)] = {"corp_code": cc.zfill(8), "corp_name": cn}
    return m


def main():
    log("=== Phase A: 수집/변환 시작 (멀티프로세스 파싱) ===")
    universe = load_universe()
    CORP = build_corpcode_map()
    universe = [r for r in universe if r["stock_code"] in CORP]
    log(f"유니버스 {len(universe)} | corp_code {len(CORP)} | CPU {os.cpu_count()} | 수집프로세스 {COLLECT_PROCS}")

    progress = json.loads(PROGRESS_LOG.read_text(encoding="utf-8")) if PROGRESS_LOG.exists() else {}

    # Phase 1: 정기공시 목록 병렬 탐색(스레드 — list.json은 가벼움)
    log(f"[1/2] 대상 탐색 (스레드 {DISCOVERY_WORKERS}) — 종목 {len(universe)}")
    work = []
    with ThreadPoolExecutor(DISCOVERY_WORKERS) as ex:
        futs = [ex.submit(fetch_targets, rec, CORP) for rec in universe]
        for j, fut in enumerate(as_completed(futs), 1):
            try:
                rec, reps = fut.result()
            except Exception as e:
                log(f"  탐색 실패: {str(e)[:90]}")
                continue
            for rep in reps:
                plabel = _PERIOD[rep["month"]][0]
                key = f"{rec['stock_code']}:{rep['year']}-{plabel}"
                if progress.get(key) == "done":
                    continue
                if already_have(rec["market"], rec["stock_code"], rep["year"], plabel):
                    progress[key] = "done"
                    continue
                work.append((rec["stock_code"], rec["market"],
                             CORP[rec["stock_code"]]["corp_code"],
                             CORP[rec["stock_code"]]["corp_name"], rep))
            if j % 300 == 0:
                log(f"   탐색 {j}/{len(futs)}")
    log(f"[1/2] 수집 대상 보고서 {len(work)}건")

    if not work:
        log("=== Phase A 완료: 수집 대상 없음 (이미 전부 보유) ===")
        log("다음 단계: python embedding/phaseB_embed.py")
        return

    # Phase 2: 멀티프로세스 다운로드+파싱 (GIL 회피 → 16코어 진짜 병렬)
    log(f"[2/2] 수집 시작 (프로세스 {COLLECT_PROCS})")
    manager = mp.Manager()
    lock = manager.Lock()
    last = manager.Value("d", 0.0)
    done = fail = 0
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=COLLECT_PROCS,
                             initializer=_init_worker, initargs=(lock, last)) as ex:
        futs = {ex.submit(collect_worker, task): task for task in work}
        for fut in as_completed(futs):
            task = futs[fut]
            try:
                key, nrec = fut.result()
                progress[key] = "done"
                done += 1
                if done % 50 == 0:
                    PROGRESS_LOG.write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")
                    el = time.time() - t0
                    log(f"   수집 {done}/{len(work)} | {el:.0f}s ({done/el*60 if el else 0:.0f}건/분) | 최근 {key} {nrec}청크")
            except Exception as e:
                fail += 1
                log(f"   수집 실패 {task[0]} {task[4].get('period')}: {str(e)[:110]}")
    PROGRESS_LOG.write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")
    log(f"=== Phase A 완료: 수집 {done}건 · 실패 {fail}건 · {time.time()-t0:.0f}s ===")
    log("다음 단계: python embedding/phaseB_embed.py")


if __name__ == "__main__":
    mp.freeze_support()
    main()
