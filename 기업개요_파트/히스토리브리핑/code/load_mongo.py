"""MongoDB Atlas 적재 (upsert).

data/briefs/ 의 모든 brief JSON 을 MongoDB.filmn9.histories 에 upsert.

사용:
  python -m code.load_mongo               # 실제 업로드
  python -m code.load_mongo --dry-run     # 시뮬레이션
  python -m code.load_mongo --find 005930 # 특정 종목 조회
  python -m code.load_mongo --list        # 전체 목록
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import certifi
from pymongo import MongoClient, UpdateOne

from . import config as cfg

sys.stdout.reconfigure(encoding="utf-8")


def get_collection():
    if not cfg.MONGO_URI:
        raise RuntimeError("MONGO_URI 미설정. .env 확인.")
    client = MongoClient(cfg.MONGO_URI, tlsCAFile=certifi.where(),
                         serverSelectionTimeoutMS=10000)
    return client[cfg.MONGO_DB][cfg.MONGO_COLL]


def list_brief_files() -> list[Path]:
    return sorted([f for f in cfg.LOCAL_BRIEFS_DIR.glob("*.json")
                   if not f.name.startswith("_")])


def normalize_doc(path: Path) -> dict:
    doc = json.loads(path.read_text(encoding="utf-8"))
    stem_parts = path.stem.split("_", 1)
    file_code  = stem_parts[0]
    file_name  = stem_parts[1] if len(stem_parts) > 1 else ""
    doc.setdefault("stock_code", file_code)
    doc.setdefault("corp_name",  file_name)
    doc.setdefault("_llm_model", cfg.LLM_MODEL_1PASS)
    doc.setdefault("_generated_at", datetime.utcnow().isoformat())
    return doc


def cmd_dry_run():
    files = list_brief_files()
    print(f"[DRY-RUN] 대상: {len(files):,}개")
    print(f"          소스: {cfg.LOCAL_BRIEFS_DIR}")
    print(f"          타겟: {cfg.MONGO_DB}.{cfg.MONGO_COLL}")
    print()
    for i, f in enumerate(files[:5], 1):
        d = normalize_doc(f)
        print(f"  [{i}/{len(files)}] {d['stock_code']}  {d['corp_name']}")
    if len(files) > 5:
        print(f"  ... 외 {len(files)-5}개")


def cmd_upload():
    coll = get_collection()
    files = list_brief_files()
    print(f"[INFO] 대상: {len(files):,}개")
    print(f"       적재 전 컬렉션 문서 수: {coll.count_documents({}):,}")
    print()

    BATCH = 100
    total_upserted = total_modified = total_failed = 0

    for start in range(0, len(files), BATCH):
        batch = files[start : start + BATCH]
        ops = []
        for f in batch:
            try:
                d = normalize_doc(f)
                ops.append(UpdateOne({"stock_code": d["stock_code"]},
                                     {"$set": d}, upsert=True))
            except Exception as e:
                print(f"  ✗ {f.name}: {e}")
                total_failed += 1
        if ops:
            try:
                r = coll.bulk_write(ops)
                total_upserted += len(r.upserted_ids)
                total_modified += r.modified_count
                done = start + len(batch)
                print(f"  [{done:,}/{len(files):,}] "
                      f"upsert={len(r.upserted_ids)} modified={r.modified_count}")
            except Exception as e:
                print(f"  ✗ 배치 실패: {e}")
                total_failed += len(ops)

    print()
    print(f"[완료]  신규={total_upserted:,}  수정={total_modified:,}  실패={total_failed:,}")
    print(f"        컬렉션 총 문서 수: {coll.count_documents({}):,}")


def cmd_find(stock_code: str):
    coll = get_collection()
    doc = coll.find_one({"stock_code": stock_code}, {"_id": 0})
    if doc:
        print(f"[{doc['stock_code']}] {doc.get('corp_name', '?')}")
        print(f"  생성: {doc.get('_generated_at', '?')}")
        print(f"  모델: {doc.get('_llm_model', '?')}")
        print(f"  brief 키: {list(doc.get('brief', {}).keys())}")
    else:
        print(f"[NOT FOUND] {stock_code}")


def cmd_list():
    coll = get_collection()
    cursor = coll.find({}, {"_id": 0, "stock_code": 1, "corp_name": 1}).sort("stock_code", 1)
    n = 0
    for d in cursor:
        print(f"  {d.get('stock_code', '?'):6s}  {d.get('corp_name', '?')}")
        n += 1
    print(f"\n총 {n:,}개")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--find",    type=str)
    p.add_argument("--list",    action="store_true")
    args = p.parse_args()

    if args.find:
        cmd_find(args.find)
    elif args.list:
        cmd_list()
    elif args.dry_run:
        cmd_dry_run()
    else:
        cmd_upload()


if __name__ == "__main__":
    main()
