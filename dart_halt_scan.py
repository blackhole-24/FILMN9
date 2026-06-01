# -*- coding: utf-8 -*-
"""
dart_halt_scan.py
=================
DART 거래소공시(pblntf_ty=I)에서 '주권매매거래정지' / '정지해제' 이벤트를
수집해 dart_halt_events 테이블에 누적.

정확도 핵심:
  · 종목별 '최신 이벤트'가 정지(HALT)면 현재 거래정지, 해제(RESUMED)면 재개.
  · 무상증자·액면병합 등 절차적 정지는 다음날 '정지해제'가 떠서 net 상태가
    RESUMED → 자동 제외 (키워드 필터 불필요, 더 정확).

사용:
  python dart_halt_scan.py --years 3     # 최초 1회 3년 시드
  python dart_halt_scan.py --days 14     # 일일 증분 (스케줄러용)
"""
from __future__ import annotations
import argparse
import re
import json
import sqlite3
import urllib.request
import urllib.parse
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(r"C:\Users\Admin\FILMN9")
DB = ROOT / "data" / "filmn9.db"
ENV = ROOT / ".env"


def dart_key():
    m = re.search(r"DART_API_KEY=(\S+)", ENV.read_text(encoding="utf-8"))
    return m.group(1) if m else ""


def ensure_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dart_halt_events (
            stock_code  TEXT NOT NULL,
            rcept_dt    TEXT NOT NULL,      -- 공시 접수일 YYYYMMDD
            state       TEXT NOT NULL,      -- HALT / RESUMED
            report_nm   TEXT,
            rcept_no    TEXT,
            PRIMARY KEY (stock_code, rcept_no)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_halt_ev_code ON dart_halt_events(stock_code)")


def _scan_window(bgn: str, end: str, key: str):
    """단일 윈도우(<=90일) 내 매매거래정지/해제 이벤트 → list[tuple]"""
    rows = []
    pg = 1
    while True:
        p = {"crtfc_key": key, "bgn_de": bgn, "end_de": end,
             "pblntf_ty": "I", "page_no": str(pg), "page_count": "100"}
        url = "https://opendart.fss.or.kr/api/list.json?" + urllib.parse.urlencode(p)
        try:
            d = json.loads(urllib.request.urlopen(url, timeout=20).read().decode("utf-8"))
        except Exception:
            time.sleep(1)
            continue
        st = d.get("status")
        if st == "013":      # 해당 기간 데이터 없음
            break
        if st != "000":      # 그 외 오류(범위초과 등)
            print(f"    [경고] status={st} {d.get('message','')} ({bgn}~{end} p{pg})")
            break
        for it in d.get("list", []):
            nm = it.get("report_nm", "")
            code = (it.get("stock_code") or "").strip()
            if not code or len(code) != 6 or "매매거래정지" not in nm:
                continue
            state = "RESUMED" if "정지해제" in nm else "HALT"
            rows.append((code, it.get("rcept_dt", ""), state,
                         nm.strip(), it.get("rcept_no", "")))
        tp = d.get("total_page", 1)
        if pg >= tp:
            break
        pg += 1
    return rows


def scan(bgn: str, end: str, key: str):
    """전체 기간을 90일 윈도우로 쪼개 스캔 (DART 범위 제한 회피)"""
    b = datetime.strptime(bgn, "%Y%m%d")
    e = datetime.strptime(end, "%Y%m%d")
    rows = []
    cur = b
    while cur <= e:
        win_end = min(cur + timedelta(days=89), e)
        wr = _scan_window(cur.strftime("%Y%m%d"), win_end.strftime("%Y%m%d"), key)
        rows.extend(wr)
        print(f"    윈도우 {cur:%Y%m%d}~{win_end:%Y%m%d}: {len(wr)}건 (누적 {len(rows)})", flush=True)
        cur = win_end + timedelta(days=1)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=0)
    ap.add_argument("--days", type=int, default=0)
    args = ap.parse_args()
    key = dart_key()
    if not key:
        print("DART_API_KEY 없음"); return

    end = datetime.now()
    if args.years:
        bgn = end - timedelta(days=365 * args.years)
        mode = f"{args.years}년 시드"
    else:
        days = args.days or 14
        bgn = end - timedelta(days=days)
        mode = f"{days}일 증분"
    print(f"DART 거래정지 스캔 ({mode}): {bgn:%Y%m%d}~{end:%Y%m%d}")

    t0 = time.time()
    rows = scan(bgn.strftime("%Y%m%d"), end.strftime("%Y%m%d"), key)

    conn = sqlite3.connect(DB, timeout=120)
    conn.execute("PRAGMA busy_timeout=120000")
    ensure_table(conn)
    conn.executemany("""INSERT OR REPLACE INTO dart_halt_events
        (stock_code,rcept_dt,state,report_nm,rcept_no) VALUES (?,?,?,?,?)""", rows)
    conn.commit()

    # 종목별 net 최신 상태 요약
    cur = conn.execute("""
        SELECT stock_code, state FROM dart_halt_events e
        WHERE rcept_dt = (SELECT MAX(rcept_dt) FROM dart_halt_events e2 WHERE e2.stock_code=e.stock_code)
        GROUP BY stock_code
    """)
    halt_now = sum(1 for _, s in cur.fetchall() if s == "HALT")
    total_codes = conn.execute("SELECT COUNT(DISTINCT stock_code) FROM dart_halt_events").fetchone()[0]
    conn.close()
    print(f"완료 — {(time.time()-t0)/60:.1f}분 / 이벤트 {len(rows)}건 적재 "
          f"/ 누적 종목 {total_codes} / 현재 net-정지 {halt_now}")


if __name__ == "__main__":
    main()
