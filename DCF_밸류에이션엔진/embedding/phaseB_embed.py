# -*- coding: utf-8 -*-
"""Phase B — jsonl → 임베딩 → ChromaDB (DART 의존성 0).

분리 구조 2단계: Phase A가 만든 jsonl을 읽어, 아직 임베딩 안 된 청크만 골라
전역 길이정렬 배치로 임베딩하고 ChromaDB(annual_reports)에 upsert 한다.

특징:
  · DART를 전혀 호출하지 않음 → DART 장애로 죽지 않음.
  · 이미 임베딩된 파일은 첫/끝 id 1회 조회로 빠르게 건너뜀(2025 사업보고서 등).
  · 임베딩(GPU)·upsert(CPU) 오버랩(writer 스레드) → GPU가 쉬지 않음.
  · 청크수 상한(CHUNK_CAP)으로 그룹을 묶어 메모리 안전 + 큰 정렬창으로 패딩 낭비 최소화.
  · 재개 가능: embed_progress.json(완료 파일) + get_existing_ids(청크 단위 안전망).

실행:  python embedding/phaseB_embed.py
"""
from __future__ import annotations

import glob
import json
import queue
import sys
import threading
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

VAR_ROOT = Path(r"C:\Users\Admin\Desktop\VAR")
sys.path.insert(0, str(VAR_ROOT))
from dotenv import load_dotenv

load_dotenv(VAR_ROOT / ".env")

from embedding.embedder import embed_texts
from embedding.vector_store import add_batch, get_existing_ids, get_stats

# ── 파라미터 ──────────────────────────────────────────────────────────
KOSPI_DIR, KOSDAQ_DIR = VAR_ROOT / "KOSPI", VAR_ROOT / "KOSDAQ"
EMBED_PROGRESS = VAR_ROOT / "embedding" / "embed_progress.json"   # 임베딩 완료 jsonl 파일 목록
LOG_FILE = VAR_ROOT / "embedding" / "phaseB_embed.log"

UPSERT_BATCH = 4000        # ChromaDB upsert/embed 분할(최대 5461 미만)
CHUNK_CAP = 40000          # 한 그룹에 모을 최대 청크 수(메모리 상한 + 정렬창)
QUEUE_MAX = 8              # upsert 큐 버퍼(오버랩 폭)


def log(msg: str) -> None:
    line = f"[{time.strftime('%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def jsonl_to_chunk(rec: dict):
    """flat jsonl 레코드 → (id, text, metadata). 기존 임베딩 메타 스키마와 일치시킴."""
    sp = rec.get("section_path") or []
    sec_main = sp[0] if len(sp) >= 1 else ""
    sec_sub = sp[1] if len(sp) >= 2 else ""
    rkind = rec.get("report_kind") or ""
    year = None
    for cand in (rkind.split("-")[0] if "-" in rkind else "",
                 str(rec.get("fiscal_period", "")).split("-")[0]):
        try:
            year = int(cand)
            break
        except Exception:
            continue
    meta = {
        "ticker": rec.get("stock_code", ""),
        "corp_name": rec.get("corp_name", ""),
        "corp_name_raw": rec.get("corp_name", ""),
        "corp_code": rec.get("corp_code", ""),
        "year": year,
        "section_main": sec_main,
        "section_sub": sec_sub,
        "section_path_str": rec.get("section_path_str", ""),
        "kind": rec.get("kind", ""),
        "char_len": rec.get("char_len", len(rec.get("text", ""))),
        "rcept_no": rec.get("rcept_no", ""),
        "rcept_dt": rec.get("rcept_dt", ""),
        "parse_mode": rec.get("parse_mode", "ingest_v1"),
        "report_type": rec.get("report_type", ""),
        "report_kind": rkind,
        "report_nm": rec.get("report_nm", ""),
        "group": rec.get("group", ""),
        "source_url": rec.get("source_url", ""),
    }
    return rec.get("id", ""), rec.get("text", ""), meta


def _first_last_line(path: str):
    """파일 전체를 읽지 않고 첫 줄 + 마지막 줄만 반환(거대 파일 대비)."""
    with open(path, "rb") as f:
        first = f.readline()
        try:
            f.seek(-min(65536, f.seek(0, 2)), 2)  # 끝에서 최대 64KB 뒤로
        except OSError:
            f.seek(0)
        tail = f.read().splitlines()
    last = tail[-1] if tail else first
    return (first.decode("utf-8", "replace"), last.decode("utf-8", "replace"))


def file_already_embedded(path: str) -> bool:
    """파일의 첫·끝 청크 id가 모두 DB에 있으면 임베딩 완료로 간주(빠른 스킵)."""
    try:
        first, last = _first_last_line(path)
        if not first.strip():
            return True
        ids = []
        for ln in (first, last):
            try:
                ids.append(json.loads(ln)["id"])
            except Exception:
                return False
        have = get_existing_ids(list(set(ids)))
        return all(i in have for i in ids)
    except Exception:
        return False


def main():
    log("=== Phase B: 임베딩 시작 ===")
    log(f"DB(시작): {get_stats()}")

    files = sorted(glob.glob(str(KOSPI_DIR / "*_chunks.jsonl"))
                   + glob.glob(str(KOSDAQ_DIR / "*_chunks.jsonl")))
    done_files = set()
    if EMBED_PROGRESS.exists():
        try:
            done_files = set(json.loads(EMBED_PROGRESS.read_text(encoding="utf-8")))
        except Exception:
            done_files = set()
    todo = [f for f in files if f not in done_files]
    log(f"jsonl 전체 {len(files)} | 진행기록 완료 {len(done_files)} | 검토대상 {len(todo)}")

    # upsert writer 스레드(오버랩) — upsert는 이 스레드 1개만 수행(동시쓰기 없음)
    q: queue.Queue = queue.Queue(maxsize=QUEUE_MAX)
    err = []

    def _writer():
        while True:
            item = q.get()
            if item is None:
                q.task_done()
                break
            ids, texts, embs, metas = item
            try:
                add_batch(ids, texts, embs, metas)
            except Exception as e:
                err.append(e)
            finally:
                q.task_done()

    t = threading.Thread(target=_writer, daemon=True)
    t.start()

    total_emb = 0
    skipped = 0
    t0 = time.time()
    newly_done: list[str] = []

    # 청크수 상한으로 그룹 누적
    group_files: list[str] = []
    group_ids: list[str] = []
    group_txt: list[str] = []
    group_meta: list[dict] = []

    def flush_group():
        nonlocal total_emb, group_files, group_ids, group_txt, group_meta
        if err or not group_ids:
            group_files, group_ids, group_txt, group_meta = [], [], [], []
            return
        # ★ 그룹 내 중복 id 제거 (사명변경 등으로 같은 stock에 jsonl이 둘 이상인 경우 방어)
        seen = set()
        keep_idx = []
        for i, cid in enumerate(group_ids):
            if cid not in seen:
                seen.add(cid)
                keep_idx.append(i)
        if len(keep_idx) < len(group_ids):
            group_ids = [group_ids[i] for i in keep_idx]
            group_txt = [group_txt[i] for i in keep_idx]
            group_meta = [group_meta[i] for i in keep_idx]
        # 이미 임베딩된 id 제외(안전망)
        existing = set()
        for s in range(0, len(group_ids), 5000):
            try:
                existing |= get_existing_ids(group_ids[s:s + 5000])
            except Exception:
                pass
        keep = [i for i in range(len(group_ids)) if group_ids[i] not in existing]
        if keep:
            k_txt = [group_txt[i] for i in keep]
            # embed_texts 내부에서 길이정렬 적응형 배치(패딩 낭비 최소화)
            embs = embed_texts(k_txt, show_progress=False)
            k_ids = [group_ids[i] for i in keep]
            k_meta = [group_meta[i] for i in keep]
            for s in range(0, len(k_ids), UPSERT_BATCH):
                if err:
                    break
                q.put((k_ids[s:s + UPSERT_BATCH], k_txt[s:s + UPSERT_BATCH],
                       [e.tolist() for e in embs[s:s + UPSERT_BATCH]], k_meta[s:s + UPSERT_BATCH]))
            total_emb += len(keep)
        newly_done.extend(group_files)
        EMBED_PROGRESS.write_text(json.dumps(sorted(set(list(done_files) + newly_done)),
                                             ensure_ascii=False), encoding="utf-8")
        el = time.time() - t0
        log(f"   그룹 처리 | 파일누적 {len(newly_done)}/{len(todo)} | 임베딩누적 {total_emb:,} "
            f"| {el:.0f}s ({total_emb/el if el else 0:.0f}청크/s)")
        group_files, group_ids, group_txt, group_meta = [], [], [], []

    for path in todo:
        if err:
            break
        # 이미 임베딩된 파일(예: 2025 사업보고서) 빠른 스킵
        if file_already_embedded(path):
            skipped += 1
            newly_done.append(path)
            if skipped % 200 == 0:
                log(f"   스킵(이미 임베딩) {skipped}건…")
            continue
        # 파일 적재
        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    cid, text, meta = jsonl_to_chunk(rec)
                    if cid and text and text.strip():
                        group_ids.append(cid)
                        group_txt.append(text)
                        group_meta.append(meta)
            group_files.append(path)
        except Exception as e:
            log(f"   파일 읽기 실패 {Path(path).name}: {e}")
            continue
        if len(group_ids) >= CHUNK_CAP:
            flush_group()

    flush_group()  # 잔여
    q.put(None)
    t.join()

    if err:
        log(f"ERROR(upsert): {err[0]}")
        raise err[0]

    log(f"=== Phase B 완료: 신규 임베딩 {total_emb:,} 청크 · 스킵 {skipped} 파일 · {time.time()-t0:.0f}s ===")
    log(f"DB(종료): {get_stats()}")


if __name__ == "__main__":
    main()
