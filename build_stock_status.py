# -*- coding: utf-8 -*-
"""
build_stock_status.py
=====================
상장폐지 · 거래정지 · 관리종목 상태 일일 갱신

소스 (모두 KRX 공식 피드, FinanceDataReader 경유, 무료/키불필요):
  - KRX-DESC          : 현재 상장 중인 전체 종목 (살아있는 유니버스)
  - KRX-DELISTING     : 상장폐지 이력 (Symbol, DelistingDate, Reason)
  - KRX-ADMINISTRATIVE: 관리종목 (DesignationDate, Reason)

판정 (우선순위):
  1) DELISTED  : 현재 비상장(DESC X) + 상폐이력 O          → "상장 폐지된 종목"
  2) HALT      : 상장중(DESC O) 인데 최근 거래일 정체       → "현재 거래 정지 중인 종목"
  3) ADMIN     : 상장중 + 관리종목 지정                     → "관리종목 (투자 주의)"
  4) NORMAL    : 상장중 + 최근 거래 정상                    → 배너 없음

HALT 기준: 상장중인데 우리 ohlcv 최신 거래일이 시장 최신일보다 STALE_DAYS 이상 뒤.
           (yfinance/거래소는 거래정지 종목에 새 봉을 주지 않음 → 결정론적)
           ※ 주가 백필 이후 재실행하면, 백필로 채워진 종목은 NORMAL 로 정정됨.

결과: stock_status 테이블 (idempotent, 매일 덮어씀)
"""
from __future__ import annotations
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
import FinanceDataReader as fdr
import halt_sources

# 참고: 절차적 정지(무상증자·액면병합 등)는 dart_halt_events 의 net 상태로 자동 제외되므로
#       별도 키워드 필터가 필요 없다 (정지→다음날 해제 → net=RESUMED).

DB = Path(r"C:\Users\Admin\FILMN9\data\filmn9.db")
STALE_DAYS = 10          # 시장 최신일 대비 이만큼 뒤처지면 거래정지로 간주
NOW = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def pad(s):
    return str(s).zfill(6)


def ensure_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stock_status (
            stock_code      TEXT PRIMARY KEY,
            status          TEXT NOT NULL,    -- NORMAL/ADMIN/HALT/DELISTED
            label           TEXT,             -- 화면 표기용 한글
            reason          TEXT,             -- 사유
            ref_date        TEXT,             -- 상폐일/지정일
            last_trade_date TEXT,             -- 마지막 거래일(our ohlcv)
            source          TEXT,
            checked_at      TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_status_code ON stock_status(stock_code)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_status_status ON stock_status(status)")


LABELS = {
    "DELISTED": "상장 폐지된 종목",
    "HALT":     "현재 거래 정지 중인 종목",
    "ADMIN":    "관리종목 (투자 주의)",
    "NEW":      "신규 상장 종목 (데이터 준비 중)",
    "NORMAL":   "",
}
NEW_LISTING_DAYS = 60     # 최근 이만큼 내 상장 + 거래기록 없음 → 신규상장(거래정지 아님)


def main():
    print(f"[{NOW}] 상장 상태 갱신 시작")
    # 1) FDR 피드
    desc = fdr.StockListing("KRX-DESC")
    delist = fdr.StockListing("KRX-DELISTING")
    admin = fdr.StockListing("KRX-ADMINISTRATIVE")

    desc_set = set(pad(c) for c in desc["Code"])
    # 상장일 맵 (신규상장 판별용)
    listing_date = {}
    if "ListingDate" in desc.columns:
        for c, d in zip(desc["Code"], desc["ListingDate"]):
            listing_date[pad(c)] = str(d)[:10]
    delist_map = {}
    for _, r in delist.iterrows():
        code = pad(r["Symbol"])
        dd = str(r["DelistingDate"])[:10] if r["DelistingDate"] else ""
        delist_map[code] = (dd, str(r.get("Reason") or ""))
    admin_map = {pad(r["Symbol"]): str(r.get("Reason") or "") for _, r in admin.iterrows()}
    print(f"  DESC={len(desc_set)} DELIST={len(delist_map)} ADMIN={len(admin_map)}")

    conn = sqlite3.connect(DB, timeout=120)
    conn.execute("PRAGMA busy_timeout=120000")
    ensure_table(conn)

    market_latest = conn.execute("SELECT MAX(date) FROM ohlcv").fetchone()[0] or "1900-01-01"
    mkt_dt = datetime.strptime(market_latest, "%Y-%m-%d")
    stale_cut = (mkt_dt - timedelta(days=STALE_DAYS)).strftime("%Y-%m-%d")
    new_cut = (mkt_dt - timedelta(days=NEW_LISTING_DAYS)).strftime("%Y-%m-%d")
    ohlcv_last = dict(conn.execute("SELECT stock_code, MAX(date) FROM ohlcv GROUP BY stock_code").fetchall())
    # 최근 거래량 합계 — '실제 거래 중'인지의 가장 신뢰도 높은 신호.
    # (yfinance는 정지 종목에 마지막 종가를 거래량 0으로 복제 → 날짜는 가짜여도 volume=0)
    vol_cut = (mkt_dt - timedelta(days=14)).strftime("%Y-%m-%d")
    recent_vol = dict(conn.execute(
        "SELECT stock_code, SUM(volume) FROM ohlcv WHERE date >= ? GROUP BY stock_code", (vol_cut,)).fetchall())

    # 우리가 아는 전체 코드 ∪ 현재 상장 ∪ 상폐이력(우리DB 교집합용)
    ci_codes = set(r[0] for r in conn.execute("SELECT stock_code FROM company_info").fetchall())
    universe = ci_codes | desc_set | set(ohlcv_last.keys())

    # 종목명 → 코드 매핑 (KIND 이름 매칭용)
    name2code = {}
    for cd, nm in conn.execute("SELECT stock_code, corp_name FROM company_info").fetchall():
        if nm:
            name2code[nm.replace(" ", "")] = cd
    for cd, nm in zip(desc["Code"], desc["Name"]):
        if isinstance(nm, str):
            name2code.setdefault(nm.replace(" ", ""), pad(cd))

    # ── 1순위: KIND 공식 거래정지 (이름→코드) ──
    kind_halt = {}   # code -> reason
    for it in halt_sources.fetch_kind_halts():
        cd = name2code.get(it["name"].replace(" ", ""))
        if cd and cd in desc_set:        # 우리 유니버스(상장중)만
            kind_halt[cd] = it["reason"]
    # ── 3순위 보완(가장 정확): DART 거래소공시 3년 net 상태 (dart_halt_events 테이블) ──
    # 종목별 최신 이벤트가 HALT면 현재 정지, RESUMED면 재개. 절차적 정지(무상증자 등)는
    # 다음날 '정지해제'가 떠서 net=RESUMED → 자동 제외 (키워드 필터 불필요).
    dart_halt = {}   # code -> (report_nm, 정지공시일 YYYYMMDD)
    try:
        for cd, state, rpt, dt in conn.execute("""
            SELECT e.stock_code, e.state, e.report_nm, e.rcept_dt
            FROM dart_halt_events e
            JOIN (SELECT stock_code, MAX(rcept_dt) md FROM dart_halt_events GROUP BY stock_code) m
              ON e.stock_code=m.stock_code AND e.rcept_dt=m.md
        """).fetchall():
            if state == "HALT":
                dart_halt[cd] = (rpt, dt)
    except sqlite3.OperationalError:
        pass   # 테이블 미생성 시 (시드 전)
    print(f"  공식소스: KIND정지(유니버스내)={len(kind_halt)} / DART net-정지(3년)={len(dart_halt)}")

    rows = []
    cnt = {"NORMAL": 0, "ADMIN": 0, "HALT": 0, "NEW": 0, "DELISTED": 0}
    for code in universe:
        last_trade = ohlcv_last.get(code)
        rvol = recent_vol.get(code)            # 최근 14일 거래량 합 (None=데이터없음)
        trading = (rvol or 0) > 0              # 실제 거래 중 여부 (핵심 게이트)
        if code in desc_set:
            # 상장중
            lst = listing_date.get(code, "")
            if code in kind_halt:
                # 1순위: KIND 공식 현재 정지 (당일 스냅샷)
                status, src = "HALT", "KIND 매매거래정지(공식)"
                reason = kind_halt[code]
                ref = ""
            elif trading:
                # 최근 거래량>0 → 실제 거래 중. DART 단기정지 잔재(오탐) 여기서 정상화.
                if code in admin_map:
                    status, src, reason, ref = "ADMIN", "KRX-ADMINISTRATIVE", admin_map[code], ""
                else:
                    status, src, reason, ref = "NORMAL", "KRX-DESC", "", ""
            elif code in dart_halt:
                # 거래량 0 + DART net-정지 → 확정 거래정지 (사유 = 거래소 공시명)
                status, src = "HALT", "DART 거래소공시(3년)"
                rpt, hdt = dart_halt[code]
                reason = re.sub(r"\s+", " ", rpt).strip()
                # 정지공시일 YYYYMMDD → YYYY-MM-DD
                ref = f"{hdt[:4]}-{hdt[4:6]}-{hdt[6:8]}" if len(hdt) == 8 else hdt
            elif last_trade is None and lst and lst >= new_cut:
                # 거래기록 없음 + 최근 상장 → 신규상장 (거래정지 아님)
                status, src = "NEW", "KRX-DESC 신규상장"
                reason = f"{lst} 신규 상장, 시세 데이터 준비 중"
                ref = lst
            else:
                # 상장중인데 최근 거래량 0 (KIND/DART/신규 아님) → 거래정지 추정
                status, src = "HALT", "거래정체 추정(2순위)"
                reason = "최근 거래 내역 없음 (거래정지 추정)"
                ref = ""
        elif code in delist_map:
            status, src = "DELISTED", "KRX-DELISTING"
            ref, reason = delist_map[code]
        else:
            # 현재 비상장 + 상폐이력 없음 → 구종목/비상장으로 상폐 취급
            status, src = "DELISTED", "비상장(이력없음)"
            reason, ref = "현재 상장되어 있지 않은 종목", ""
        rows.append((code, status, LABELS[status], reason, ref, last_trade or "", src, NOW))
        cnt[status] += 1

    conn.execute("DELETE FROM stock_status")
    conn.executemany("""INSERT INTO stock_status
        (stock_code,status,label,reason,ref_date,last_trade_date,source,checked_at)
        VALUES (?,?,?,?,?,?,?,?)""", rows)
    conn.commit()
    conn.close()

    print(f"  적재 {len(rows)}건 | 시장최신={market_latest} stale<{stale_cut} new>={new_cut}")
    print(f"  정상={cnt['NORMAL']} 관리={cnt['ADMIN']} 거래정지={cnt['HALT']} "
          f"신규상장={cnt['NEW']} 상폐={cnt['DELISTED']}")
    print(f"[{datetime.now():%H:%M:%S}] 완료")


if __name__ == "__main__":
    main()
