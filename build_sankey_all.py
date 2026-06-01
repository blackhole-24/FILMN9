# -*- coding: utf-8 -*-
"""Sankey 전체 생성 — IS/CIS 데이터 있는 모든 종목 (읽기전용 + HTML 출력)"""
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\Users\Admin\FILMN9")
import db.build_sankey as BS

DB = Path(r"C:\Users\Admin\FILMN9\data\filmn9.db")


def main():
    conn = sqlite3.connect(DB, timeout=60)
    conn.execute("PRAGMA busy_timeout=60000")
    codes = [r[0] for r in conn.execute("""
        SELECT DISTINCT stock_code FROM financial_detail
        WHERE statement_type IN ('IS','CIS')
        ORDER BY stock_code
    """).fetchall()]
    conn.close()
    print(f"Sankey 생성 대상: {len(codes)}개 종목")

    ok, fail = 0, 0
    start = time.time()
    for i, code in enumerate(codes, 1):
        try:
            BS.build_sankey(code)
            ok += 1
        except Exception as e:
            fail += 1
        if i % 100 == 0 or i == len(codes):
            el = time.time() - start
            eta = (len(codes) - i) / (i / el) / 60 if el > 0 else 0
            print(f"  [{i}/{len(codes)}] OK={ok} FAIL={fail} | ETA {eta:.0f}분", flush=True)

    print(f"\n완료 — {(time.time()-start)/60:.1f}분 / 생성 {ok}개 / 실패 {fail}개")


if __name__ == "__main__":
    main()
