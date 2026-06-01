"""
db/load_history_to_mongo.py
============================
휘주님 history JSON 파일(data/parsed_history/*.json)을
MongoDB Atlas(filmn9.histories)에 일괄 업로드.

특징
----
- 파일명에서 stock_code, corp_name 자동 추출
- 본문에 누락된 4개 필드 자동 보강 (휘주님 스키마 정합 작업 대행)
- upsert (이미 있으면 업데이트, 없으면 삽입)
- --dry-run 시뮬레이션 모드
- 실패 종목은 별도 로그

사용법
------
cd C:/Users/Admin/FILMN9
python db/load_history_to_mongo.py                    # 전체 업로드
python db/load_history_to_mongo.py --dry-run          # 실행 안 함, 시뮬레이션만
python db/load_history_to_mongo.py --list             # MongoDB 적재 종목 목록
python db/load_history_to_mongo.py --find 090430      # 특정 종목 조회
python db/load_history_to_mongo.py --clear            # 전체 삭제 (위험)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# ─── 경로 ─────────────────────────────────────────────────────────────────────
ROOT       = Path(__file__).resolve().parent.parent
HIST_DIR   = ROOT / "data" / "parsed_history"
ENV_PATH   = ROOT / ".env"
LLM_MODEL  = "gpt-5-mini"   # 휘주님 사용 모델 (변경 시 .env에서 덮어쓰기 가능)


# ─── .env 로드 ────────────────────────────────────────────────────────────────
def load_env():
    if not ENV_PATH.exists():
        print(f"[ERR] .env 파일 없음: {ENV_PATH}")
        sys.exit(1)
    with open(ENV_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


# ─── MongoDB 연결 ─────────────────────────────────────────────────────────────
def get_collection():
    load_env()
    uri = os.getenv("MONGO_URI", "").strip()
    if not uri:
        print("[ERR] .env에 MONGO_URI 비어있음")
        sys.exit(1)

    from pymongo import MongoClient
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    try:
        client.admin.command("ping")
    except Exception as e:
        print(f"[ERR] MongoDB 연결 실패: {e}")
        sys.exit(1)

    db   = client[os.getenv("MONGO_DB", "filmn9")]
    col  = db[os.getenv("MONGO_COLLECTION", "histories")]
    return client, col


# ─── 파일명 파싱 ─────────────────────────────────────────────────────────────
#  허용 패턴: 6자리 (숫자 또는 영문) _ 기업명
#  예) 0001A0_덕양에너젠.json
#      090430_아모레퍼시픽.json
#      031210_서울보증보험.json
FILENAME_PATTERN = re.compile(r"^([0-9A-Z]{6})_(.+)\.json$")


def parse_filename(filename: str) -> tuple[str, str] | None:
    m = FILENAME_PATTERN.match(filename)
    if not m:
        return None
    return m.group(1), m.group(2)


# ─── 본문 정합 (휘주님 스키마 보강) ──────────────────────────────────────────
def normalize(data: dict, stock_code: str, corp_name: str) -> dict:
    """
    휘주님 인수인계서의 4개 필드 자동 추가 (이미 있으면 유지).
      - stock_code
      - corp_name
      - _llm_model
      - _generated_at
    + 키 순서 가독성 위해 재배치.
    """
    data.setdefault("stock_code"   , stock_code)
    data.setdefault("corp_name"    , corp_name)
    data.setdefault("_llm_model"   , LLM_MODEL)
    data.setdefault("_generated_at", datetime.now().strftime("%Y-%m-%d %H:%M"))

    # 키 순서 재배치 (가독성)
    ordered = {
        "stock_code"    : data["stock_code"],
        "corp_name"     : data["corp_name"],
        "_llm_model"    : data["_llm_model"],
        "_generated_at" : data["_generated_at"],
        "meta"          : data.get("meta", {}),
        "brief"         : data.get("brief", {}),
        "usage"         : data.get("usage", {}),
        "warnings"      : data.get("warnings", []),
    }
    return ordered


# ─── 메인 적재 ────────────────────────────────────────────────────────────────
def cmd_upload(dry_run: bool = False):
    if not HIST_DIR.exists():
        print(f"[ERR] 폴더 없음: {HIST_DIR}")
        sys.exit(1)

    files = sorted(HIST_DIR.glob("*.json"))
    if not files:
        print(f"[ERR] JSON 파일 없음: {HIST_DIR}")
        sys.exit(1)

    print(f"\n{'='*70}")
    print(f"  load_history_to_mongo.py {'(DRY-RUN)' if dry_run else ''}")
    print(f"  파일 수: {len(files)}")
    print(f"  소스   : {HIST_DIR}")
    print(f"  타겟   : MongoDB Atlas filmn9.histories")
    print(f"{'='*70}\n")

    if not dry_run:
        client, col = get_collection()

    stats = {"ok": [], "skip": [], "fail": []}

    for i, f in enumerate(files, 1):
        parsed = parse_filename(f.name)
        if parsed is None:
            print(f"  [{i:3d}/{len(files)}] [SKIP] 파일명 패턴 불일치: {f.name}")
            stats["skip"].append(f.name)
            continue

        stock_code, corp_name = parsed

        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            normalized = normalize(data, stock_code, corp_name)

            if dry_run:
                print(f"  [{i:3d}/{len(files)}] [PREVIEW] {stock_code}  {corp_name[:15]:<15}  "
                      f"meta={bool(normalized.get('meta'))} "
                      f"brief={bool(normalized.get('brief'))}")
            else:
                col.update_one(
                    {"stock_code": stock_code},
                    {"$set": normalized},
                    upsert=True,
                )
                print(f"  [{i:3d}/{len(files)}] [OK] {stock_code}  {corp_name[:25]:<25}  "
                      f"({len(json.dumps(normalized)):,} bytes)")
            stats["ok"].append((stock_code, corp_name))

        except Exception as e:
            print(f"  [{i:3d}/{len(files)}] [FAIL] {f.name}: {e}")
            stats["fail"].append((f.name, str(e)))

    # 요약
    print(f"\n{'='*70}")
    print(f"  결과 요약")
    print(f"{'='*70}")
    print(f"  성공  : {len(stats['ok'])}")
    print(f"  스킵  : {len(stats['skip'])}")
    print(f"  실패  : {len(stats['fail'])}")

    if stats["fail"]:
        print(f"\n  실패 상세:")
        for fname, err in stats["fail"]:
            print(f"    - {fname}: {err}")

    if not dry_run:
        cnt = col.estimated_document_count()
        print(f"\n  MongoDB 현재 문서 수: {cnt:,}건")


def cmd_list():
    client, col = get_collection()
    codes = sorted(col.distinct("stock_code"))
    print(f"\n  MongoDB 적재 종목 ({len(codes)}개):\n")
    for c in codes:
        doc = col.find_one(
            {"stock_code": c},
            {"stock_code": 1, "corp_name": 1, "_generated_at": 1, "_id": 0}
        )
        print(f"    {c}  {doc.get('corp_name', '?'):<25}  {doc.get('_generated_at', '?')}")


def cmd_find(stock_code: str):
    client, col = get_collection()
    doc = col.find_one({"stock_code": stock_code}, {"_id": 0})
    if not doc:
        print(f"\n  [없음] {stock_code}")
        return
    print(f"\n  [{stock_code}] {doc.get('corp_name', '?')}")
    print(f"  생성시각  : {doc.get('_generated_at')}")
    print(f"  LLM 모델  : {doc.get('_llm_model')}")
    print(f"  meta      : {doc.get('meta', {}).get('corp_type', '?')} / "
          f"{doc.get('meta', {}).get('wics', '?')}")
    print(f"  brief 키  : {list(doc.get('brief', {}).keys())}")
    print(f"  confidence: {doc.get('brief', {}).get('confidence', '?')}")
    print(f"\n  brief.company_overview (앞 200자):")
    ov = doc.get("brief", {}).get("company_overview", "") or ""
    print(f"    {ov[:200]}")


def cmd_clear():
    client, col = get_collection()
    ans = input("\n  정말 모든 histories 문서를 삭제하시겠습니까? (yes/N): ").strip()
    if ans.lower() != "yes":
        print("  취소됨.")
        return
    r = col.delete_many({})
    print(f"  [OK] {r.deleted_count}건 삭제됨.")


# ─── 메인 ─────────────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description="휘주님 history JSON → MongoDB Atlas 적재")
    p.add_argument("--dry-run", action="store_true", help="실행 안 하고 시뮬레이션만")
    p.add_argument("--list",    action="store_true", help="적재된 종목 목록")
    p.add_argument("--find",    type=str,            help="특정 종목 조회")
    p.add_argument("--clear",   action="store_true", help="전체 삭제 (위험)")
    args = p.parse_args()

    if args.list:    cmd_list()
    elif args.find:  cmd_find(args.find)
    elif args.clear: cmd_clear()
    else:            cmd_upload(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
