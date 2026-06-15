# -*- coding: utf-8 -*-
"""
backfill_financials.py
======================
상장중인데 재무 누락된 종목(backfill_targets.json:gap_fin)만
unified_financial_loader.process_stock 으로 DART 재무 백필.
"""
import json
import sqlite3
import time
from pathlib import Path
import unified_financial_loader as U

TARGETS = Path(r"C:\Users\Admin\FILMN9\data\backfill_targets.json")


def main():
    codes = json.load(open(TARGETS, encoding="utf-8"))["gap_fin"]
    raw = U.load_corp_code_map()
    by = raw.get("by_stock_code", raw)
    # 평면 맵 {stock_code: corp_code} — process_stock 의 DART 경로가 요구하는 형식
    corp_map = {c: (v.get("corp_code") if isinstance(v, dict) else v)
                for c, v in by.items() if (v.get("corp_code") if isinstance(v, dict) else v)}
    codes = [c for c in codes if c in corp_map]
    print(f"재무 백필 대상(corp_code 보유): {len(codes)}개")

    conn = sqlite3.connect(U.DB, timeout=120)
    conn.execute("PRAGMA busy_timeout=120000")
    stat = {}
    total = 0
    start = time.time()
    for i, code in enumerate(codes, 1):
        try:
            src, n = U.process_stock(conn, code, corp_map)
        except Exception as e:
            src, n = "ERR", 0
        stat[src] = stat.get(src, 0) + 1
        total += n
        if i % 50 == 0 or i == len(codes):
            el = time.time() - start
            eta = (len(codes) - i) / (i / el) / 60 if el > 0 else 0
            print(f"  [{i}/{len(codes)}] {code}->{src} | {total}건 | "
                  f"{dict(stat)} | ETA {eta:.1f}분", flush=True)

    conn.close()
    print(f"\n완료 — {(time.time()-start)/60:.1f}분 / {total}건 / {dict(stat)}")


if __name__ == "__main__":
    main()
