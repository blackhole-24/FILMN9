"""Tab3 RAG 챗봇용 임베딩 export — 데모 3종목 (KPMG PoC).

ChromaDB 의 종목별 청크 + 임베딩 벡터를 팀원 인수인계서(§5) 형식으로 추출:

  embedding/export/<stock_code>/
    ├── chunks.jsonl     # {"id","section","year","kind","text"} 한 줄당 1청크
    ├── embeddings.npy   # (N, 1024) float32 — BGE-M3 dense 벡터 (L2 정규화됨)
    └── metadata.json    # {stock_code, n_chunks, dim, embedding_model, source, generated_at}

⚠ 임베딩 모델·차원 명시 중요 (인수인계서 §9):
   우리는 BGE-M3(dim 1024). 팀원 예시(text-embedding-3-small/1536)와 다르므로
   metadata.json 에 정확히 기재하여 팀원 RAG 가 동일 모델로 질의하도록 한다.

실행:
  python -m embedding.export_for_poc
  python -m embedding.export_for_poc --tickers 090430,009150,035420
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import numpy as np

from embedding.vector_store import get_collection
from embedding.config import EMBEDDING_MODEL, EMBEDDING_DIM

_OUT_ROOT = Path(__file__).resolve().parent / "export"

DEMO = {"090430": "아모레퍼시픽", "009150": "삼성전기", "035420": "NAVER"}


def export_one(code: str, out_root: Path, verbose: bool = True) -> dict:
    coll = get_collection()
    res = coll.get(
        where={"ticker": code},
        include=["documents", "embeddings", "metadatas"],
    )
    ids   = res.get("ids") or []
    docs  = res.get("documents")
    embs  = res.get("embeddings")
    metas = res.get("metadatas")
    docs  = list(docs)  if docs  is not None else []
    embs  = list(embs)  if embs  is not None else []   # numpy array → list
    metas = list(metas) if metas is not None else []
    if not ids:
        if verbose:
            print(f"  [WARN] {code}: ChromaDB 에 청크 없음 — 임베딩 미수집")
        return {"code": code, "n_chunks": 0}

    out_dir = out_root / code
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1) chunks.jsonl — id 순서와 embeddings.npy 행 순서 일치 보장
    corp_name = metas[0].get("corp_name", DEMO.get(code, "")) if metas else ""
    with (out_dir / "chunks.jsonl").open("w", encoding="utf-8") as f:
        for i, cid in enumerate(ids):
            m = metas[i] if i < len(metas) else {}
            f.write(json.dumps({
                "id":      cid,
                "section": m.get("section_path_str", m.get("section_main", "")),
                "year":    m.get("year"),
                "kind":    m.get("kind", ""),
                "rcept_no": m.get("rcept_no", ""),
                "text":    docs[i] if i < len(docs) else "",
            }, ensure_ascii=False) + "\n")

    # 2) embeddings.npy — (N, dim) float32
    arr = np.asarray(embs, dtype=np.float32)
    np.save(out_dir / "embeddings.npy", arr)

    # 3) metadata.json — 모델·차원 명시 (팀원 RAG 정합)
    meta = {
        "stock_code":      code,
        "corp_name":       corp_name,
        "n_chunks":        len(ids),
        "dim":             EMBEDDING_DIM,
        "embedding_model": EMBEDDING_MODEL,          # "BAAI/bge-m3"
        "normalized":      True,                     # L2 정규화 → 코사인=내적
        "distance":        "cosine (= dot product on normalized vectors)",
        "source":          "DART 사업보고서 청크 (KOSPI/KOSDAQ annual_chunks)",
        "generated_at":    datetime.now().isoformat(timespec="seconds"),
        "note":            "팀원 예시(text-embedding-3-small/1536)와 다른 모델/차원. "
                           "질의 시 동일 BGE-M3(1024)로 임베딩 필요.",
    }
    with (out_dir / "metadata.json").open("w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    if verbose:
        print(f"  [OK] {code} {corp_name} → {out_dir}  "
              f"(청크 {len(ids)}, 벡터 {arr.shape})")
    return {"code": code, "n_chunks": len(ids), "shape": list(arr.shape)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", default=",".join(DEMO.keys()),
                    help="쉼표구분 종목코드 (기본: 데모 3종목)")
    ap.add_argument("--out-root", default=str(_OUT_ROOT))
    args = ap.parse_args()

    out_root = Path(args.out_root)
    codes = [c.strip() for c in args.tickers.split(",") if c.strip()]
    print(f"임베딩 export — {len(codes)}종목 → {out_root}")
    for c in codes:
        export_one(c, out_root)
    print(f"\n완료. 전달 경로: {out_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
