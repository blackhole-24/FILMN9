"""
db/load_extras.py
=================
build_extras.py가 생성한 JSON 4종을 SQLite에 적재.

대상 테이블
-----------
- shareholders        (주주)
- executives          (경영인)
- disclosures         (공시)
- financial_detail    (재무 상세 B/S + I/S)

사용법
------
cd C:/Users/Admin/FILMN9
python db/load_extras.py --code 090430
python db/load_extras.py --all          # data/parsed/ 하위 모든 종목
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import io
from datetime import datetime
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "filmn9.db"
PARSED = ROOT / "data" / "parsed"

NOW = datetime.now().isoformat()


def _upsert(con: sqlite3.Connection, table: str, rows: list[dict],
            pk_cols: list[str]) -> int:
    if not rows:
        return 0
    cols = list(rows[0].keys())
    placeholders = ",".join(["?"] * len(cols))
    cols_sql = ",".join(cols)
    update_sql = ",".join(f"{c}=excluded.{c}" for c in cols if c not in pk_cols)
    pk_sql = ",".join(pk_cols)
    sql = (
        f"INSERT INTO {table} ({cols_sql}) VALUES ({placeholders}) "
        f"ON CONFLICT({pk_sql}) DO UPDATE SET {update_sql}"
    )
    n = 0
    for r in rows:
        con.execute(sql, [r.get(c) for c in cols])
        n += 1
    return n


def load_one(stock_code: str) -> dict:
    out_dir = PARSED / stock_code
    if not out_dir.exists():
        return {"error": f"폴더 없음: {out_dir}"}

    stats = {"stock_code": stock_code}
    con = sqlite3.connect(DB)
    try:
        # 1) 주주
        p = out_dir / "shareholders.json"
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            year = data.get("fiscal_year", 2024)
            rows = []
            for it in data.get("items", []):
                rows.append({
                    "stock_code": stock_code,
                    "fiscal_year": year,
                    "rank": it["rank"],
                    "name": it.get("name"),
                    "relation": it.get("relation"),
                    "shares": it.get("shares"),
                    "ratio": it.get("ratio"),
                    "source": "DART hyslrSttus+majorstock",
                    "loaded_at": NOW,
                })
            stats["shareholders"] = _upsert(con, "shareholders", rows,
                                            ["stock_code", "fiscal_year", "rank"])

        # 2) 경영인
        p = out_dir / "executives.json"
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            year = data.get("fiscal_year", 2024)
            rows = []
            for it in data.get("items", []):
                rows.append({
                    "stock_code": stock_code,
                    "fiscal_year": year,
                    "rank": it["rank"],
                    "name": it.get("name"),
                    "position": it.get("position"),
                    "role": it.get("role"),
                    "birth_year": it.get("birth_year"),
                    "career": it.get("career"),
                    "shares": it.get("shares"),
                    "appointed_at": it.get("appointed_at"),
                    "term_end": it.get("term_end"),
                    "source": "DART exctvSttus",
                    "loaded_at": NOW,
                })
            stats["executives"] = _upsert(con, "executives", rows,
                                          ["stock_code", "fiscal_year", "rank"])

        # 3) 공시
        p = out_dir / "disclosures.json"
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            rows = []
            for it in data.get("items", []):
                if not it.get("rcept_no"):
                    continue
                rows.append({
                    "stock_code": stock_code,
                    "rcept_no": it["rcept_no"],
                    "report_nm": it.get("report_nm"),
                    "flr_nm": it.get("flr_nm"),
                    "rcept_dt": it.get("rcept_dt"),
                    "rm": it.get("rm"),
                    "url": it.get("url"),
                    "source": "DART list.json",
                    "loaded_at": NOW,
                })
            stats["disclosures"] = _upsert(con, "disclosures", rows,
                                           ["stock_code", "rcept_no"])

        # 4) 재무상세
        p = out_dir / "financial_detail.json"
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            rows = []
            for it in data.get("items", []):
                if not it.get("account_id"):
                    continue
                rows.append({
                    "stock_code": stock_code,
                    "fiscal_year": it["fiscal_year"],
                    "statement_type": it["statement_type"],
                    "account_id": it["account_id"],
                    "account_nm": it.get("account_nm"),
                    "amount": it.get("amount"),
                    "unit": "백만원",
                    "statement_scope": it.get("statement_scope", "연결"),
                    "display_order": it.get("display_order"),
                    "source": "DART fnlttSinglAcntAll",
                    "loaded_at": NOW,
                })
            stats["financial_detail"] = _upsert(con, "financial_detail", rows,
                                                ["stock_code", "fiscal_year",
                                                 "statement_type", "account_id",
                                                 "statement_scope"])

        con.commit()
    finally:
        con.close()

    return stats


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--code", help="단일 종목 적재")
    p.add_argument("--all", action="store_true", help="data/parsed/ 전체 적재")
    args = p.parse_args()

    if args.code:
        codes = [args.code]
    elif args.all:
        codes = sorted(d.name for d in PARSED.iterdir() if d.is_dir() and d.name.isdigit())
    else:
        codes = ["090430", "009150", "035420"]

    print(f"[INFO] 대상 {len(codes)}종목")
    for code in codes:
        stats = load_one(code)
        print(f"  {code}: {stats}")

    # 최종 통계
    con = sqlite3.connect(DB)
    print("\n[DB 통계]")
    for t in ["shareholders", "executives", "disclosures", "financial_detail"]:
        n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t:20s}: {n:>6,} 행")
    con.close()


if __name__ == "__main__":
    main()
