"""
db/test_mongo.py
================
MongoDB Atlas 연결 테스트 + 샘플 데이터 삽입/조회.

사용법
------
1. .env 파일에 MONGO_URI 입력
2. python db/test_mongo.py             # 연결 + ping
3. python db/test_mongo.py --insert    # 샘플 history 1건 삽입
4. python db/test_mongo.py --list      # 적재된 종목 목록
5. python db/test_mongo.py --find 090430   # 특정 종목 조회

목적
----
- Atlas 클러스터 정상 작동 확인
- 기업개요 파트이 데이터 적재하기 전 채널 점검
- FastAPI 시작 전 사전 검증
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent


# ─── .env 로드 ──────────────────────────────────────────────────────────────
def load_env():
    env_path = ROOT / ".env"
    if not env_path.exists():
        print(f"[ERR] {env_path} 없음")
        sys.exit(1)
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


# ─── 연결 ───────────────────────────────────────────────────────────────────
def connect():
    load_env()
    uri = os.getenv("MONGO_URI", "").strip()
    if not uri:
        print("[ERR] .env 파일에 MONGO_URI가 비어있습니다.")
        print("      Atlas connection string을 받아서 .env에 입력하세요.")
        print("      형식: mongodb+srv://<user>:<pw>@<cluster>.mongodb.net/?retryWrites=true&w=majority")
        sys.exit(1)

    from pymongo import MongoClient
    try:
        client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        client.admin.command("ping")
    except Exception as e:
        print(f"[ERR] 연결 실패: {e}")
        sys.exit(1)

    db   = client[os.getenv("MONGO_DB", "filmn9")]
    col  = db[os.getenv("MONGO_COLLECTION", "histories")]
    print(f"[OK] MongoDB Atlas 연결 성공")
    print(f"     DB         : {db.name}")
    print(f"     Collection : {col.name}")
    print(f"     URI prefix : {uri[:30]}...")
    return client, col


# ─── 명령들 ──────────────────────────────────────────────────────────────────

def cmd_ping():
    client, col = connect()
    cnt = col.estimated_document_count()
    print(f"     현재 문서수: {cnt:,} 개")


def cmd_insert():
    """샘플 history 1건 삽입 (테스트용)."""
    client, col = connect()
    sample = {
        "stock_code"    : "TEST01",
        "corp_name"     : "테스트기업",
        "_llm_model"    : "gpt-5-mini",
        "_generated_at" : datetime.now().strftime("%Y-%m-%d %H:%M"),
        "meta"          : {"wics": "테스트", "market": "KOSPI", "corp_type": "test"},
        "brief"         : {
            "company_overview": "테스트용 샘플 데이터입니다.",
            "business_model"  : "test",
            "main_customers"  : "test",
            "price_factors"   : [],
            "key_evidence"    : [],
            "confidence"      : "high",
        },
        "usage"         : {"prompt_tokens": 100, "completion_tokens": 50, "reasoning_tokens": 30, "output_tokens": 20},
        "warnings"      : [],
    }
    # upsert
    col.update_one({"stock_code": "TEST01"}, {"$set": sample}, upsert=True)
    print(f"[OK] 샘플 1건 upsert 완료: TEST01")
    cmd_ping()


def cmd_list():
    """적재된 종목코드 목록 출력."""
    client, col = connect()
    codes = sorted(col.distinct("stock_code"))
    print(f"\n  적재된 종목 ({len(codes)}개):")
    for c in codes:
        doc = col.find_one({"stock_code": c}, {"stock_code": 1, "corp_name": 1, "_generated_at": 1, "_id": 0})
        print(f"    {c}  {doc.get('corp_name', '?'):20s}  {doc.get('_generated_at', '?')}")


def cmd_find(stock_code: str):
    """특정 종목 history 조회."""
    client, col = connect()
    doc = col.find_one({"stock_code": stock_code}, {"_id": 0})
    if not doc:
        print(f"\n  [없음] {stock_code} 종목 history 미적재")
        return
    print(f"\n  [발견] {stock_code} {doc.get('corp_name', '?')}")
    print(f"  생성시각: {doc.get('_generated_at', '?')}")
    print(f"  LLM 모델: {doc.get('_llm_model', '?')}")
    print(f"  본문 키 : {list(doc.get('brief', {}).keys())}")
    print(f"\n  brief.company_overview (앞 200자):")
    print(f"    {(doc.get('brief', {}).get('company_overview', '') or '')[:200]}")


def cmd_delete_test():
    """TEST01 샘플 삭제."""
    client, col = connect()
    r = col.delete_one({"stock_code": "TEST01"})
    print(f"[OK] 삭제: {r.deleted_count}건")


# ─── 메인 ───────────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description="MongoDB Atlas 연결 테스트")
    p.add_argument("--insert", action="store_true", help="샘플 1건 upsert")
    p.add_argument("--list",   action="store_true", help="적재된 종목 목록")
    p.add_argument("--find",   type=str, help="특정 종목 조회 (예: 090430)")
    p.add_argument("--del-test", action="store_true", help="TEST01 샘플 삭제")
    args = p.parse_args()

    if args.insert:    cmd_insert()
    elif args.list:    cmd_list()
    elif args.find:    cmd_find(args.find)
    elif args.del_test: cmd_delete_test()
    else:              cmd_ping()


if __name__ == "__main__":
    main()
