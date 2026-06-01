# -*- coding: utf-8 -*-
"""동시성 낮춤 + 전역 스로틀: DART 재차단 방지. 노트북 cell 1 교체."""
import json, ast
from pathlib import Path

NB = Path(r"C:\Users\Admin\Desktop\VAR\embedding\collect_embed_new_reports.ipynb")

new_cell1 = r'''# ── 1) 셋업 ───────────────────────────────────────────────────────────
import os, sys, time, json, re, io, zipfile, random, threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import xml.etree.ElementTree as ET
import requests

VAR_ROOT = Path(r"C:\Users\Admin\Desktop\VAR")     # 환경 확인
sys.path.insert(0, str(VAR_ROOT))
from dotenv import load_dotenv
load_dotenv(VAR_ROOT / ".env")
DART_KEY = os.getenv("DART_API_KEY"); assert DART_KEY, "DART_API_KEY 미설정"

from valuation_engine.report_ingest import download_document, parse_chunks
from valuation_engine.report_detector import list_periodic_reports
from embedding.embedder import embed_texts
from embedding.vector_store import add_batch, get_existing_ids, get_stats

KOSPI_DIR, KOSDAQ_DIR = VAR_ROOT / "KOSPI", VAR_ROOT / "KOSDAQ"

# 파라미터(튜닝) — DART 재차단 방지를 위해 동시성 낮춤 + 전역 스로틀
TARGET_PERIODS = {"2025.12", "2026.03"}      # 2025 사업 + 2026 1분기
LIST_BGN, LIST_END = "20260101", "20260527"
N_WORKERS     = 3        # DART 동시 호출(차단 방지로 낮춤. 안정되면 4~8로 상향 가능)
WAVE_SIZE     = 40       # 임베딩 1회에 모을 보고서 수
UPSERT_BATCH  = 4000     # ChromaDB upsert/임베딩 분할 크기(최대 5461 미만 필수)
TEST_LIMIT    = None     # 검증용 앞 N종목. 전체는 None
REQUEST_DELAY = 0.15     # DART 호출 간 최소 간격(초) — 전역 스로틀(WAF 차단 방지)
PROGRESS_LOG  = VAR_ROOT / "embedding" / "collect_progress.json"

_PERIOD = {"12": ("annual","annual","사업보고서"), "03": ("q1","quarterly","분기보고서"),
           "06": ("semiannual","semiannual","반기보고서"), "09": ("q3","quarterly","분기보고서")}

# 전역 스로틀: 모든 워커가 공유 — DART 호출이 REQUEST_DELAY 간격 이상 벌어지도록 직렬화
_throttle_lock = threading.Lock()
_last_call = [0.0]
def _throttle():
    with _throttle_lock:
        dt = time.time() - _last_call[0]
        if dt < REQUEST_DELAY:
            time.sleep(REQUEST_DELAY - dt)
        _last_call[0] = time.time()

def with_retry(fn, *a, tries=5, base=1.0, **k):
    # DART 호출 재시도(전역 스로틀 + 지수 백오프 + 지터). 연결 끊김(RemoteDisconnected)에도 견고.
    for t in range(tries):
        try:
            _throttle()
            return fn(*a, **k)
        except Exception:
            if t == tries - 1:
                raise
            time.sleep(base * (2 ** t) + random.uniform(0, 0.5))

print("DART OK |", get_stats())
'''

nb = json.load(open(NB, encoding="utf-8"))
patched = 0
for c in nb["cells"]:
    if c["cell_type"] == "code" and any("def with_retry" in ln for ln in c["source"]):
        c["source"] = new_cell1.splitlines(keepends=True)
        patched += 1
json.dump(nb, open(NB, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("cell 1 패치:", patched, "곳")

# 전체 문법 검증
for c in nb["cells"]:
    if c["cell_type"] == "code":
        ast.parse("".join(c["source"]))
print("전체 코드셀 문법 OK")
