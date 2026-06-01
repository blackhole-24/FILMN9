# -*- coding: utf-8 -*-
"""기존 2026 q1(valuation 포맷 — 폭주·포맷불일치) 정리.

재수집(phaseA_collect.py) 전에 1회 실행한다.
  1) ChromaDB에서 report_kind='2026-q1' 청크 삭제
  2) 디스크의 2026 q1 jsonl 삭제
  3) collect_progress.json / embed_progress.json 에서 q1 항목 제거 → 재수집·재임베딩 대상화

★ 2025 사업보고서(report_kind='2025-annual')는 건드리지 않는다.

실행:  python embedding/cleanup_q1.py
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

VAR_ROOT = Path(r"C:\Users\Admin\Desktop\VAR")
sys.path.insert(0, str(VAR_ROOT))
from dotenv import load_dotenv

load_dotenv(VAR_ROOT / ".env")
from embedding.vector_store import get_collection, get_stats

KOSPI_DIR, KOSDAQ_DIR = VAR_ROOT / "KOSPI", VAR_ROOT / "KOSDAQ"
PROGRESS_LOG = VAR_ROOT / "embedding" / "collect_progress.json"
EMBED_PROGRESS = VAR_ROOT / "embedding" / "embed_progress.json"
TARGET_KIND = "2026-q1"


def main():
    print("=== 2026 q1 정리 (2025 사업보고서는 보존) ===", flush=True)
    print("DB(전):", get_stats(), flush=True)

    # 1) DB 삭제
    coll = get_collection()
    print(f"DB에서 report_kind='{TARGET_KIND}' 삭제 중... (수십초~수분 소요 가능)", flush=True)
    coll.delete(where={"report_kind": TARGET_KIND})
    print("DB(후):", get_stats(), flush=True)

    # 2) jsonl 삭제
    files = glob.glob(str(KOSPI_DIR / "*_2026_q1_chunks.jsonl")) + \
            glob.glob(str(KOSDAQ_DIR / "*_2026_q1_chunks.jsonl"))
    for f in files:
        try:
            Path(f).unlink()
        except Exception as e:
            print(f"  jsonl 삭제 실패 {Path(f).name}: {e}", flush=True)
    print(f"q1 jsonl 삭제: {len(files)}개", flush=True)

    # 3) collect_progress.json — q1 키 제거 (key 형식 "{stock}:2026-q1")
    if PROGRESS_LOG.exists():
        d = json.loads(PROGRESS_LOG.read_text(encoding="utf-8"))
        rm = [k for k in d if k.endswith(":2026-q1")]
        for k in rm:
            d.pop(k, None)
        PROGRESS_LOG.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        print(f"collect_progress: q1 {len(rm)}건 제거 → 재수집 대상", flush=True)

    # 4) embed_progress.json — q1 파일 경로 제거 (있으면)
    if EMBED_PROGRESS.exists():
        ef = set(json.loads(EMBED_PROGRESS.read_text(encoding="utf-8")))
        kept = {p for p in ef if "_2026_q1_chunks.jsonl" not in p}
        EMBED_PROGRESS.write_text(json.dumps(sorted(kept), ensure_ascii=False), encoding="utf-8")
        print(f"embed_progress: q1 {len(ef)-len(kept)}건 제거", flush=True)

    print("=== 정리 완료 → 이제 phaseA_collect.py 실행 ===", flush=True)


if __name__ == "__main__":
    main()
