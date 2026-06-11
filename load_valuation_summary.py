"""
load_valuation_summary.py
=========================
밸류에이션 엔진 v8 산출물(summary.csv)을 SQLite(filmn9.db)에 적재.

입력 : data/valuation_inbox/repr20_export/summary.csv  (산업 대표 20종)
출력 : filmn9.db  →  테이블 valuation_summary (stock_code PK)

특징
----
- CSV BOM(utf-8-sig) 처리
- 빈 값(fair_price/upside 등 E등급 무효종목) → NULL 로 정직 저장 (NO-MOCK)
- INSERT OR REPLACE (idempotent — 재실행해도 중복 없이 갱신)

실행:
    conda activate FILMN9_env
    python load_valuation_summary.py
"""
from __future__ import annotations

import csv
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB   = ROOT / "data" / "filmn9.db"
CSV  = ROOT / "data" / "valuation_inbox" / "repr20_export" / "summary.csv"

DDL = """
CREATE TABLE IF NOT EXISTS valuation_summary (
    stock_code            TEXT PRIMARY KEY,
    corp_name             TEXT,
    market                TEXT,
    industry              TEXT,
    dcf_grade             TEXT,
    dcf_confidence        TEXT,
    peer_confidence_grade TEXT,
    fair_price            REAL,
    current_price         REAL,
    upside_pct            REAL,
    wacc                  REAL,
    as_of_date            TEXT,
    model_version         TEXT,
    source_file           TEXT,
    loaded_at             TEXT
);
"""


def _f(v):
    """빈 문자열/None → None, 그 외 float 변환. (NO-MOCK: 없는 값은 NULL)"""
    if v is None:
        return None
    s = str(v).strip()
    if s == "" or s.lower() in ("none", "nan", "null"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def main() -> None:
    if not CSV.exists():
        raise SystemExit(f"[ERROR] CSV 없음: {CSV}")
    if not DB.exists():
        raise SystemExit(f"[ERROR] DB 없음: {DB}")

    rows = []
    with open(CSV, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            rows.append((
                (r.get("code") or "").strip(),
                (r.get("name") or "").strip(),
                (r.get("market") or "").strip(),
                (r.get("industry") or "").strip(),
                (r.get("dcf_grade") or "").strip(),
                (r.get("dcf_confidence") or "").strip(),
                (r.get("peer_confidence_grade") or "").strip(),
                _f(r.get("fair_price")),
                _f(r.get("current_price")),
                _f(r.get("upside_pct")),
                _f(r.get("wacc")),
                (r.get("as_of_date") or "").strip(),
                (r.get("model_version") or "").strip(),
                "repr20_export/summary.csv",
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ))

    con = sqlite3.connect(DB)
    con.execute(DDL)
    con.executemany("""
        INSERT OR REPLACE INTO valuation_summary
        (stock_code, corp_name, market, industry, dcf_grade, dcf_confidence,
         peer_confidence_grade, fair_price, current_price, upside_pct, wacc,
         as_of_date, model_version, source_file, loaded_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, rows)
    con.commit()

    n = con.execute("SELECT COUNT(*) FROM valuation_summary").fetchone()[0]
    valid = con.execute("SELECT COUNT(*) FROM valuation_summary WHERE fair_price IS NOT NULL").fetchone()[0]
    con.close()

    print(f"[OK] valuation_summary 적재 완료: {len(rows)}건 입력 / 테이블 총 {n}건")
    print(f"     적정가 산출 종목(fair_price NOT NULL): {valid} / {n}  (나머지는 E등급 무효 → NULL)")


if __name__ == "__main__":
    main()
