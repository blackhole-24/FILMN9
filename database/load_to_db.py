"""
db/load_to_db.py
================
FILMN9 PoC - JSON 산출물을 SQLite (filmn9.db) 에 적재하는 스크립트

특징
----
- 재실행 안전 (upsert: INSERT ... ON CONFLICT DO UPDATE)
- 종목별 폴더 자동 순회 (data/parsed/{stock_code}/*.json)
- 부분 적재 가능 (특정 JSON 파일이 없어도 다른 것만 적재)
- histories 는 적재 대상 아님 (MongoDB Atlas 에서 별도 관리)

대상 JSON 4종
-------------
1) company_info.json  -> company_info 테이블
2) financials.json    -> financials   테이블 (연도별 1행씩 분해)
3) ohlcv.json         -> ohlcv        테이블 (일자별 1행씩 적재)
4) valuation.json     -> valuations   테이블 (밸류에이션팀, 추후 도착)
5) shareholders.json  -> shareholders 테이블 (step3b 추후)

사용법
------
cd C:/Users/Admin/FILMN9

# 전체 종목 일괄 적재
python db/load_to_db.py

# 특정 종목만 적재
python db/load_to_db.py --code 090430

# 적재 결과 확인 (각 테이블 행수)
python db/load_to_db.py --stats
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# ─── 경로 설정 ────────────────────────────────────────────────────────────────
ROOT       = Path(__file__).resolve().parent.parent
DATA_DIR   = ROOT / "data"
PARSED_DIR = DATA_DIR / "parsed"
DB_PATH    = DATA_DIR / "filmn9.db"


# ─── 공통 유틸 ────────────────────────────────────────────────────────────────

def _read_json(path: Path) -> dict | None:
    """JSON 파일 안전 로드. 파일 없으면 None."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  [WARN] JSON 로드 실패 {path.name}: {e}")
        return None


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _clean_int(v) -> int | None:
    """문자열·실수 등을 int 로 안전 변환."""
    if v is None or v == "":
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _clean_float(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _listing_date_norm(raw: str | None) -> str | None:
    """
    listing_date 정규화.
    "2006년 06월 01일" -> "2006-06-01"
    "20060601"          -> "2006-06-01"
    이미 "2006-06-01"  -> 그대로
    """
    if not raw:
        return None
    digits = "".join(c for c in raw if c.isdigit())
    if len(digits) >= 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return raw


def _fiscal_month_int(raw) -> int | None:
    """fiscal_month '12' or 12 -> 12"""
    if raw is None or raw == "":
        return None
    try:
        m = int(str(raw))
        return m if 1 <= m <= 12 else None
    except (TypeError, ValueError):
        return None


# ─── 1. company_info 적재 ─────────────────────────────────────────────────────

def load_company_info(stock_code: str, conn: sqlite3.Connection) -> bool:
    path = PARSED_DIR / stock_code / "company_info.json"
    data = _read_json(path)
    if not data:
        return False

    conn.execute("""
        INSERT INTO company_info VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        ON CONFLICT(stock_code) DO UPDATE SET
            corp_name      = excluded.corp_name,
            market         = excluded.market,
            sector         = excluded.sector,
            listing_date   = excluded.listing_date,
            ceo            = excluded.ceo,
            employees      = excluded.employees,
            homepage       = excluded.homepage,
            address        = excluded.address,
            phone          = excluded.phone,
            fiscal_month   = excluded.fiscal_month,
            source         = excluded.source,
            generated_at   = excluded.generated_at,
            loaded_at      = excluded.loaded_at
    """, (
        data.get("stock_code", stock_code),
        data.get("corp_name", ""),
        data.get("market"),
        data.get("sector"),
        _listing_date_norm(data.get("listing_date")),
        data.get("ceo"),
        _clean_int(data.get("employees")),
        data.get("homepage"),
        data.get("address"),
        data.get("phone"),
        _fiscal_month_int(data.get("fiscal_month")),
        data.get("_source"),
        data.get("_generated_at"),
        _now(),
    ))
    return True


# ─── 2. financials 적재 ───────────────────────────────────────────────────────

def load_financials(stock_code: str, conn: sqlite3.Connection) -> int:
    """
    financials.json 의 연도별 dict 들을 unfold 해서 연도당 1행씩 적재.
    Returns: 적재된 행 수
    """
    path = PARSED_DIR / stock_code / "financials.json"
    data = _read_json(path)
    if not data:
        return 0

    years = data.get("fiscal_years", [])
    if not years:
        return 0

    inserted = 0
    for y in years:
        y_int = _clean_int(y)
        if y_int is None:
            continue

        # 연도별 dict 에서 해당 연도 값 추출
        def v(key: str) -> float | None:
            d = data.get(key, {})
            return _clean_float(d.get(str(y)) or d.get(y))

        conn.execute("""
            INSERT INTO financials VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            ON CONFLICT(stock_code, fiscal_year) DO UPDATE SET
                revenue      = excluded.revenue,
                op_income    = excluded.op_income,
                net_income   = excluded.net_income,
                assets       = excluded.assets,
                liabilities  = excluded.liabilities,
                equity       = excluded.equity,
                debt_ratio   = excluded.debt_ratio,
                cashflow_op  = excluded.cashflow_op,
                cashflow_inv = excluded.cashflow_inv,
                cashflow_fin = excluded.cashflow_fin,
                unit         = excluded.unit,
                source       = excluded.source,
                generated_at = excluded.generated_at,
                loaded_at    = excluded.loaded_at
        """, (
            stock_code, y_int,
            v("revenue"), v("op_income"), v("net_income"),
            v("assets"), v("liabilities"), v("equity"),
            v("debt_ratio"),
            v("cashflow_op"), v("cashflow_inv"), v("cashflow_fin"),
            data.get("unit", "백만원"),
            data.get("_source"),
            data.get("_generated_at"),
            _now(),
        ))
        inserted += 1

    return inserted


# ─── 3. ohlcv 적재 ────────────────────────────────────────────────────────────

def load_ohlcv(stock_code: str, conn: sqlite3.Connection) -> int:
    """ohlcv.json 의 data 배열을 일별 1행씩 적재."""
    path = PARSED_DIR / stock_code / "ohlcv.json"
    data = _read_json(path)
    if not data:
        return 0

    records = data.get("data", [])
    if not records:
        return 0

    rows = [
        (
            stock_code,
            r.get("date"),
            _clean_int(r.get("open")),
            _clean_int(r.get("high")),
            _clean_int(r.get("low")),
            _clean_int(r.get("close")),
            _clean_int(r.get("volume")),
        )
        for r in records
        if r.get("date")
    ]

    conn.executemany("""
        INSERT INTO ohlcv VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(stock_code, date) DO UPDATE SET
            open   = excluded.open,
            high   = excluded.high,
            low    = excluded.low,
            close  = excluded.close,
            volume = excluded.volume
    """, rows)

    return len(rows)


# ─── 4. valuations 적재 (밸류에이션팀 데이터 도착 시) ────────────────────────

def load_valuation(stock_code: str, conn: sqlite3.Connection) -> bool:
    path = PARSED_DIR / stock_code / "valuation.json"
    data = _read_json(path)
    if not data:
        return False

    def js(key: str) -> str | None:
        v = data.get(key)
        return json.dumps(v, ensure_ascii=False) if v is not None else None

    conn.execute("""
        INSERT INTO valuations VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        ON CONFLICT(stock_code) DO UPDATE SET
            fair_price_avg      = excluded.fair_price_avg,
            fair_price_min      = excluded.fair_price_min,
            fair_price_max      = excluded.fair_price_max,
            upside_pct          = excluded.upside_pct,
            analyst_count       = excluded.analyst_count,
            opinion_majority    = excluded.opinion_majority,
            dcf_value           = excluded.dcf_value,
            wacc                = excluded.wacc,
            perpetual_growth    = excluded.perpetual_growth,
            roic                = excluded.roic,
            roic_vs_wacc        = excluded.roic_vs_wacc,
            relative_per_value  = excluded.relative_per_value,
            relative_pbr_value  = excluded.relative_pbr_value,
            forecast_revenue    = excluded.forecast_revenue,
            forecast_op_income  = excluded.forecast_op_income,
            forecast_net_income = excluded.forecast_net_income,
            forecast_eps        = excluded.forecast_eps,
            forecast_per        = excluded.forecast_per,
            forecast_pbr        = excluded.forecast_pbr,
            forecast_roe        = excluded.forecast_roe,
            data_quality        = excluded.data_quality,
            data_sources        = excluded.data_sources,
            generated_at        = excluded.generated_at,
            loaded_at           = excluded.loaded_at
    """, (
        data.get("stock_code", stock_code),
        _clean_float(data.get("fair_price_avg")),
        _clean_float(data.get("fair_price_min")),
        _clean_float(data.get("fair_price_max")),
        _clean_float(data.get("upside_pct")),
        _clean_int(data.get("analyst_count")),
        data.get("opinion_majority"),
        _clean_float(data.get("dcf_value")),
        _clean_float(data.get("wacc")),
        _clean_float(data.get("perpetual_growth")),
        _clean_float(data.get("roic")),
        _clean_float(data.get("roic_vs_wacc")),
        _clean_float(data.get("relative_per_value")),
        _clean_float(data.get("relative_pbr_value")),
        js("forecast_revenue"),
        js("forecast_op_income"),
        js("forecast_net_income"),
        js("forecast_eps"),
        js("forecast_per"),
        js("forecast_pbr"),
        js("forecast_roe"),
        data.get("data_quality"),
        js("data_sources"),
        data.get("_generated_at"),
        _now(),
    ))
    return True


# ─── 5. shareholders 적재 (step3b 도착 시) ─────────────────────────────────────

def load_shareholders(stock_code: str, conn: sqlite3.Connection) -> int:
    path = PARSED_DIR / stock_code / "shareholders.json"
    data = _read_json(path)
    if not data:
        return 0

    fy = _clean_int(data.get("fiscal_year")) or 0
    items = data.get("shareholders", [])

    # 기존 동일 (stock_code, fiscal_year) 데이터 삭제 후 재삽입 (행 수 변동 가능)
    conn.execute("DELETE FROM shareholders WHERE stock_code=? AND fiscal_year=?", (stock_code, fy))

    rows = [
        (
            stock_code, fy, _clean_int(s.get("rank")) or i,
            s.get("name"),
            s.get("relation"),
            _clean_int(s.get("shares")),
            _clean_float(s.get("ratio")),
            data.get("_source"),
            _now(),
        )
        for i, s in enumerate(items, 1)
    ]

    conn.executemany("""
        INSERT INTO shareholders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows)
    return len(rows)


# ─── 종목별 적재 ──────────────────────────────────────────────────────────────

def load_one(stock_code: str, conn: sqlite3.Connection) -> dict:
    """한 종목의 모든 JSON 적재 → 결과 dict 반환."""
    return {
        "company"      : load_company_info(stock_code, conn),
        "financials"   : load_financials(stock_code, conn),
        "ohlcv"        : load_ohlcv(stock_code, conn),
        "valuation"    : load_valuation(stock_code, conn),
        "shareholders" : load_shareholders(stock_code, conn),
    }


def load_all(conn: sqlite3.Connection) -> dict:
    """data/parsed/ 아래의 모든 6자리 종목 폴더 적재."""
    summary = {"종목수": 0, "company": 0, "financials": 0, "ohlcv": 0,
               "valuation": 0, "shareholders": 0, "fail": 0}

    if not PARSED_DIR.exists():
        print(f"[ERR] {PARSED_DIR} 폴더 없음")
        return summary

    code_dirs = sorted(
        d for d in PARSED_DIR.iterdir()
        if d.is_dir() and re.match(r"^\d{6}$", d.name)
    )

    print(f"  대상 종목 폴더: {len(code_dirs)}개")
    for d in code_dirs:
        try:
            r = load_one(d.name, conn)
            summary["종목수"]      += 1
            summary["company"]     += 1 if r["company"]      else 0
            summary["financials"]  += r["financials"]
            summary["ohlcv"]       += r["ohlcv"]
            summary["valuation"]   += 1 if r["valuation"]    else 0
            summary["shareholders"]+= r["shareholders"]
        except Exception as e:
            print(f"  [FAIL] {d.name}: {e}")
            summary["fail"] += 1

    return summary


# ─── 통계 ─────────────────────────────────────────────────────────────────────

def show_stats():
    if not DB_PATH.exists():
        print(f"[ERR] DB 없음: {DB_PATH}")
        return
    with sqlite3.connect(DB_PATH) as conn:
        print(f"\n{'='*60}")
        print(f"  filmn9.db 테이블별 행 수")
        print(f"{'='*60}")
        for tbl in ["company_info", "financials", "ohlcv", "valuations", "shareholders"]:
            cnt = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
            print(f"  {tbl:18s}: {cnt:>10,} 행")

        # 종목별 ohlcv 분포 상위 3개
        rows = conn.execute("""
            SELECT stock_code, COUNT(*) AS n
            FROM ohlcv
            GROUP BY stock_code
            ORDER BY n DESC
            LIMIT 3
        """).fetchall()
        if rows:
            print(f"\n  [ohlcv 상위 3종목]")
            for code, n in rows:
                print(f"    {code}: {n:,} 일")
        print(f"{'='*60}\n")


# ─── 메인 ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="FILMN9 JSON → SQLite 적재기")
    parser.add_argument("--code",  help="특정 종목코드만 적재 (예: 090430)")
    parser.add_argument("--stats", action="store_true", help="DB 통계만 표시")
    args = parser.parse_args()

    if args.stats:
        show_stats()
        return

    if not DB_PATH.exists():
        print(f"[ERR] DB 없음. 먼저 init_db.py 실행 필요.")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  load_to_db.py 시작 -{_now()}")
    print(f"{'='*60}")

    with sqlite3.connect(DB_PATH) as conn:
        if args.code:
            print(f"  단일 종목 적재: {args.code}")
            r = load_one(args.code, conn)
            conn.commit()
            print(f"  결과: {r}")
        else:
            summary = load_all(conn)
            conn.commit()
            print(f"\n{'='*60}")
            print(f"  적재 완료")
            print(f"{'='*60}")
            for k, v in summary.items():
                print(f"  {k:14s}: {v:,}")

    show_stats()


if __name__ == "__main__":
    main()
