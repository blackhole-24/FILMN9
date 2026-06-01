"""
감사보고서로 받았던 529개 종목을 DART API fnlttSinglAcntAll 로 직접 보충
- 3개년 (2025, 2024, 2023)
- 연결 + 별도
- NAVER 방식과 동일 (이미 검증됨)
"""
import os
import re
import sys
import json
import time
import sqlite3
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime

ROOT = Path(r"C:\Users\Admin\FILMN9")
DB   = ROOT / "data" / "filmn9.db"
ENV  = ROOT / ".env"
RAW  = ROOT / "data" / "raw"
CORP_MAP = ROOT / "data" / "corp_code_map.json"
LOG  = ROOT / "fix_audit_log.txt"

def load_env():
    for line in ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

load_env()
DART_KEY = os.environ.get("DART_API_KEY", "").strip()

def log(msg):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def find_audit_stocks():
    """감사보고서로 잘못 받은 종목 식별"""
    audit_codes = []
    for child in RAW.iterdir():
        if not child.is_dir():
            continue
        m = re.match(r"^([0-9A-Z]{6})_", child.name)
        if not m:
            continue
        xml = child / "2025-annual_cleaned.xml"
        if not xml.exists():
            continue
        with open(xml, "rb") as f:
            head = f.read(2000).decode("utf-8", errors="ignore")
        if 'ACODE="00760"' in head and "감사보고서" in head:
            audit_codes.append(m.group(1))
    return audit_codes

def parse_amount(s):
    if not s:
        return None
    t = str(s).replace(",", "")
    if t.startswith("(") and t.endswith(")"):
        t = "-" + t[1:-1]
    try:
        return float(t)
    except:
        return None

def fetch_dart(corp_code: str, year: int, fs_div: str):
    url = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
    params = {
        "crtfc_key": DART_KEY,
        "corp_code": corp_code,
        "bsns_year": str(year),
        "reprt_code": "11011",
        "fs_div": fs_div,
    }
    full = url + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(full, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))
        if data.get("status") != "000":
            return []
        return data.get("list", [])
    except Exception:
        return []

def process(conn, stock_code: str, corp_code: str) -> int:
    total = 0
    for year in [2025, 2024, 2023]:
        for fs_div, scope in [("CFS", "연결"), ("OFS", "별도")]:
            items = fetch_dart(corp_code, year, fs_div)
            time.sleep(0.15)  # rate limit 안전
            if not items:
                continue
            rows = []
            for i, it in enumerate(items):
                sj = it.get("sj_div", "")
                if sj not in ("BS", "CIS", "IS"):
                    continue
                acc_id = it.get("account_id") or ""
                if not acc_id:
                    continue
                rows.append((
                    stock_code, year, sj, acc_id, scope,
                    it.get("account_nm") or "",
                    parse_amount(it.get("thstrm_amount")),
                    "원", i,
                    "DART fnlttSinglAcntAll (감사보고서 종목 보충)",
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                ))
            # 기존 같은 종목+연도+범위 삭제 후 재적재
            conn.execute("""
                DELETE FROM financial_detail
                WHERE stock_code=? AND fiscal_year=? AND statement_scope=?
            """, (stock_code, year, scope))
            conn.executemany("""
                INSERT OR REPLACE INTO financial_detail
                (stock_code, fiscal_year, statement_type, account_id, statement_scope,
                 account_nm, amount, unit, display_order, source, loaded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, rows)
            conn.commit()
            total += len(rows)
    return total

def main():
    LOG.unlink(missing_ok=True)
    log("=" * 70)
    log("  감사보고서 종목 → DART API 직접 보충")
    log("=" * 70)

    audit_stocks = find_audit_stocks()
    log(f"감사보고서 종목: {len(audit_stocks)}개")

    corp_map_raw = json.loads(CORP_MAP.read_text(encoding="utf-8"))
    corp_map = corp_map_raw.get("by_stock_code", {})

    conn = sqlite3.connect(DB)
    start = time.time()
    stats = {"OK": 0, "EMPTY": 0, "NO_CORP": 0}

    for i, code in enumerate(audit_stocks, 1):
        info = corp_map.get(code, {})
        corp_code = info.get("corp_code")
        if not corp_code:
            stats["NO_CORP"] += 1
            continue
        n = process(conn, code, corp_code)
        if n > 0:
            stats["OK"] += 1
        else:
            stats["EMPTY"] += 1
        if i % 20 == 0 or i == len(audit_stocks):
            elapsed = time.time() - start
            rate = i / elapsed if elapsed > 0 else 0
            eta = (len(audit_stocks) - i) / rate / 60 if rate > 0 else 0
            log(f"  [{i:>3}/{len(audit_stocks)}] OK {stats['OK']} | EMPTY {stats['EMPTY']} | "
                f"NO_CORP {stats['NO_CORP']} | ETA {eta:.1f}분")

    conn.close()
    log("=" * 70)
    log(f"  완료 — {(time.time()-start)/60:.1f}분")
    log(f"  성공: {stats['OK']} | 데이터 없음: {stats['EMPTY']} | corp_code 없음: {stats['NO_CORP']}")
    log("=" * 70)

if __name__ == "__main__":
    main()
