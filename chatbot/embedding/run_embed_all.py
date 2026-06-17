"""KOSPI + KOSDAQ 모든 사업보고서 청크를 임베딩하여 ChromaDB에 저장.

실행:
    conda activate dart-rag
    cd C:\\Users\\Admin\\Desktop\\VAR
    python -m embedding.run_embed_all

옵션:
    --skip-existing      이미 임베딩된 ID 는 스킵 (증분 업데이트, 기본 True)
    --reset              컬렉션 초기화 후 처음부터 (주의)
    --batch-size N       배치 크기 (기본 32)
    --dry-run            실제 임베딩 안 하고 통계만 표시

산출물:
    VAR/embedding/chroma_db/   영구 저장된 ChromaDB
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime

from .config import BATCH_SIZE
from .chunk_loader import load_all_chunks
from .embedder import embed_texts, get_device_info
from .vector_store import (
    add_batch, get_existing_ids, get_stats, reset_collection,
)


def _configure_stdio() -> None:
    """Make console output safe on Windows shells with legacy encodings."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()

    parser = argparse.ArgumentParser(
        description="사업보고서 청크 임베딩 — BGE-M3 + ChromaDB"
    )
    parser.add_argument("--market", type=str, default="all",
                        choices=["all", "kospi", "kosdaq"],
                        help="처리할 시장 (kospi / kosdaq / all). 기본 all")
    parser.add_argument("--skip-existing", action="store_true", default=True,
                        help="이미 임베딩된 ID 스킵 (증분, 기본)")
    parser.add_argument("--full-reembed", action="store_true",
                        help="모든 청크 재임베딩 (덮어쓰기)")
    parser.add_argument("--reset", action="store_true",
                        help="⚠ 컬렉션 초기화 후 처음부터")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE,
                        help=f"배치 크기 (기본 {BATCH_SIZE})")
    parser.add_argument("--dry-run", action="store_true",
                        help="실제 임베딩 안 함, 통계만")
    args = parser.parse_args(argv)

    print("=" * 70)
    print(f"  사업보고서 청크 임베딩 — BGE-M3 + ChromaDB")
    print(f"  시작 시각: {datetime.now().isoformat(timespec='seconds')}")
    print("=" * 70)

    # ── 0. 디바이스 확인 ──────────────────────────────────────
    info = get_device_info()
    print(f"\n[디바이스]")
    print(f"  Device: {info['device']}")
    print(f"  Model:  {info['model']}")
    print(f"  Dim:    {info['dim']}")
    if info["device"] == "cuda":
        print(f"  GPU:    {info.get('gpu_name','?')} "
              f"(VRAM {info.get('gpu_mem_total_gb','?'):.1f}GB)")
    else:
        print(f"  ⚠ GPU 미사용 — 임베딩 속도 느림")

    # ── 1. 청크 로드 ───────────────────────────────────────────
    markets = [args.market] if args.market != "all" else ["all"]
    print(f"\n[1/4] 청크 로드 + 전처리  (시장: {args.market.upper()})")
    chunks, stats = load_all_chunks(markets=markets, verbose=True)
    if not chunks:
        print("⚠ 청크 0개 — 종료")
        return 1

    # ── 2. 초기화 여부 ─────────────────────────────────────────
    if args.reset:
        print(f"\n⚠ 컬렉션 초기화...")
        reset_collection()

    # ── 3. 증분 필터링 ─────────────────────────────────────────
    skip_existing = args.skip_existing and not args.full_reembed
    if skip_existing:
        print(f"\n[2/4] 기존 ID 확인 (증분 업데이트)")
        all_ids = [c["id"] for c in chunks]
        # ChromaDB get 은 한 번에 너무 많이 못 받으므로 청크 단위로
        existing_ids: set[str] = set()
        CHUNK = 5000
        for i in range(0, len(all_ids), CHUNK):
            existing_ids.update(get_existing_ids(all_ids[i:i+CHUNK]))
        new_chunks = [c for c in chunks if c["id"] not in existing_ids]
        print(f"  전체: {len(chunks):,}  /  기존: {len(existing_ids):,}  "
              f"/  신규: {len(new_chunks):,}")
        chunks = new_chunks
    else:
        print(f"\n[2/4] (스킵 안 함, 전체 재임베딩)")

    if not chunks:
        print("\n✓ 신규 임베딩할 청크 없음 — 종료")
        stats_db = get_stats()
        print(f"\nDB 현황: {stats_db['total_chunks']:,}개 청크 저장됨")
        return 0

    # ── 4. dry-run 종료 ────────────────────────────────────────
    if args.dry_run:
        print(f"\n[DRY-RUN] 임베딩 대상 {len(chunks):,}개. 실제 실행 안 함.")
        return 0

    # ── 5. 배치 임베딩 + DB 저장 ───────────────────────────────
    print(f"\n[3/4] 임베딩 + DB 저장 (배치 {args.batch_size})", flush=True)
    total = len(chunks)
    t0 = time.time()
    BATCH = args.batch_size * 4    # DB 쓰기는 더 큰 배치로 (임베딩 배치의 4배)

    for i in range(0, total, BATCH):
        batch_chunks = chunks[i:i+BATCH]
        texts     = [c["text"] for c in batch_chunks]
        ids       = [c["id"] for c in batch_chunks]
        metadatas = [c["metadata"] for c in batch_chunks]

        # 임베딩
        embeddings = embed_texts(texts, batch_size=args.batch_size,
                                 show_progress=False)
        embeddings_list = embeddings.tolist()

        # DB 쓰기
        add_batch(ids, texts, embeddings_list, metadatas)

        done = min(i + BATCH, total)
        elapsed = time.time() - t0
        rate = done / elapsed if elapsed > 0 else 0
        eta_sec = (total - done) / rate if rate > 0 else 0
        print(f"  [{done:>7,}/{total:>7,}] "
              f"속도 {rate:>5.0f} 청크/sec  "
              f"경과 {elapsed:>5.0f}s  "
              f"남음 {eta_sec:>5.0f}s", flush=True)

    # ── 6. 최종 통계 ──────────────────────────────────────────
    print(f"\n[4/4] 완료")
    stats_db = get_stats()
    print(f"  총 임베딩 청크: {stats_db['total_chunks']:,}")
    print(f"  DB 경로:       {stats_db['db_path']}")
    print(f"  총 소요 시간:   {time.time()-t0:.0f}s")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
