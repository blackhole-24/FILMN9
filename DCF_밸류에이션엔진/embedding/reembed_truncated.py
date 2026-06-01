"""512 토큰 초과로 잘렸던 청크만 선별 재임베딩 (max_length=1024) — GPU 최적화.

배경:
  기존 임베딩은 max_length=512 로 생성되어 긴 표(신용등급·자본·주식수 등)가
  뒷부분이 잘린 채 벡터화됨 (실측: 청크의 ~16.6% 가 512 초과). 1024 로 재임베딩.

성능 설계:
  - 512 토큰 이하 청크는 max_length 와 무관하게 벡터 동일 → 건드리지 않음 (~83% 보존).
  - 병목은 GPU(임베딩)가 아니라 ChromaDB upsert(디스크 flush + HNSW 인덱스 갱신).
    → upsert 배치를 크게(기본 5000) 묶어 호출 횟수를 1/10 로 줄여 flush 오버헤드 분산.
  - GPU 임베딩 배치(--emb-batch)는 GPU 메모리에 맞춰 조정. OOM 시 축소.
  - 작업 청크 단위 파이프라인 → 메모리 cap + 중단 시 멱등 재실행(upsert 덮어쓰기).

실행:
  python -m embedding.reembed_truncated                              # 기본 (emb 64, upsert 5000)
  python -m embedding.reembed_truncated --emb-batch 128 --upsert-batch 10000   # GPU 여유 시
  python -m embedding.reembed_truncated --emb-batch 32               # GPU OOM 시 축소
  python -m embedding.reembed_truncated --dry-run                    # 대상 개수만 확인
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from embedding.chunk_loader import load_all_chunks
from embedding.embedder import embed_texts
from embedding.vector_store import add_batch
from embedding.config import EMBEDDING_MODEL

# char_len 이 이 값 미만이면 512 토큰 초과가 불가능 → 토큰 측정 생략 (보수적)
CHAR_MIN_FOR_MEASURE = 200
TARGET_MAX_LENGTH = 1024
MEASURE_BATCH = 4096


def _select_targets(chunks: list[dict]) -> list[dict]:
    """char_len 1차 필터 + fast tokenizer 배치 측정으로 512 초과 청크 선별."""
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(EMBEDDING_MODEL, local_files_only=True)

    candidates = [c for c in chunks
                  if c["metadata"].get("char_len", 0) >= CHAR_MIN_FOR_MEASURE]
    print(f"      char_len>={CHAR_MIN_FOR_MEASURE} 후보 {len(candidates):,}개 "
          f"— fast tokenizer 배치 측정...", flush=True)

    targets = []
    for i in range(0, len(candidates), MEASURE_BATCH):
        sub = candidates[i:i + MEASURE_BATCH]
        enc = tok([c["text"] for c in sub],
                  add_special_tokens=True, padding=False,
                  truncation=False, return_length=True)
        for c, n in zip(sub, enc["length"]):
            if n > 512:
                targets.append(c)
    return targets


def main() -> int:
    ap = argparse.ArgumentParser(description="512 초과 청크 선별 재임베딩 (GPU)")
    ap.add_argument("--emb-batch", type=int, default=64,
                    help="GPU 임베딩 배치 크기 (OOM 시 축소, 여유 시 128/256)")
    ap.add_argument("--upsert-batch", type=int, default=5000,
                    help="ChromaDB upsert 배치 (클수록 flush 오버헤드↓)")
    ap.add_argument("--dry-run", action="store_true",
                    help="재임베딩 없이 대상 개수만 확인")
    args = ap.parse_args()

    print("[1/3] 전체 청크 로드...", flush=True)
    chunks, _stats = load_all_chunks(verbose=True)
    print(f"      총 {len(chunks):,}개", flush=True)

    print("[2/3] 512 초과 청크 선별...", flush=True)
    targets = _select_targets(chunks)
    del chunks   # 192만 청크 메모리 해제 (임베딩 메모리 확보)
    print(f"      재임베딩 대상 {len(targets):,}개", flush=True)

    if args.dry_run:
        print("      [dry-run] 종료", flush=True)
        return 0
    if not targets:
        print("      대상 없음 — 종료", flush=True)
        return 0

    print(f"[3/3] GPU 재임베딩 + upsert "
          f"(emb_batch={args.emb_batch}, upsert_batch={args.upsert_batch}, "
          f"max_length={TARGET_MAX_LENGTH})...", flush=True)
    t0 = time.time()
    UB = args.upsert_batch
    for i in range(0, len(targets), UB):
        sub = targets[i:i + UB]
        # GPU 임베딩 (작업 청크 내부에서 emb_batch 로 연속 처리)
        embs = embed_texts([c["text"] for c in sub],
                           batch_size=args.emb_batch,
                           max_length=TARGET_MAX_LENGTH,
                           show_progress=False)
        # 큰 배치 upsert (flush 오버헤드 분산)
        add_batch([c["id"] for c in sub],
                  [c["text"] for c in sub],
                  embs.tolist(),
                  [c["metadata"] for c in sub])

        done = min(i + UB, len(targets))
        el = time.time() - t0
        rate = done / el if el > 0 else 0
        eta = (len(targets) - done) / rate if rate > 0 else 0
        print(f"      {done:,}/{len(targets):,}  {rate:.0f}청크/s  "
              f"ETA {eta/60:.1f}분", flush=True)

    print(f"[완료] {len(targets):,}개 재임베딩 — {(time.time()-t0)/60:.1f}분 소요", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
