# -*- coding: utf-8 -*-
"""
build_competitors.py
====================
경쟁사 자동 추출 — WICS 동일 업종 + 자산총계(규모) 인접 N개

방법:
  1. ticker_universe.csv 에서 (stock_code, corp_name, wics, market) 로드 (SPAC·우선주 제외)
  2. financial_detail 에서 종목별 자산총계(연결 우선, 없으면 별도) 로드 → 규모 프록시
  3. 같은 wics 그룹 내에서 자산총계 내림차순 정렬
  4. 본 종목 기준 규모 인접(상위+하위) 또는 상위 N개를 경쟁사로 선정

결과: peer_competitors 테이블
"""
import csv
import re
import sqlite3
from pathlib import Path

ROOT = Path(r"C:\Users\Admin\FILMN9")
DB   = ROOT / "data" / "filmn9.db"
CSV  = ROOT / "data" / "ticker_universe.csv"

N_COMPETITORS = 5   # 종목당 경쟁사 수

# 지주회사 식별 키워드
HOLDING_KW = ["홀딩스", "지주", "Holdings", "홀딩"]


def _core_name(name):
    """그룹 핵심명 추출: 홀딩스·지주·그룹·G 접미사 제거"""
    import re as _re
    n = _re.sub(r"[\s\(\)（）㈜]|주식회사|보통주", "", name)
    n = _re.sub(r"(홀딩스|지주회사|지주|그룹|Holdings|홀딩)$", "", n)
    n = _re.sub(r"G$", "", n)  # 아모레G → 아모레
    return n


def is_holding(name):
    return any(k in name for k in HOLDING_KW)


def same_group(a, b):
    """같은 기업집단(지주-자회사·계열) 여부 — 핵심명 접두 일치"""
    ca, cb = _core_name(a), _core_name(b)
    if not ca or not cb:
        return False
    if ca == cb:
        return True
    # 핵심명이 4글자 이상이고 한쪽이 다른쪽의 접두면 같은 그룹으로 간주
    short, long = (ca, cb) if len(ca) <= len(cb) else (cb, ca)
    if len(short) >= 4 and long.startswith(short):
        return True
    return False


def load_universe():
    """활성 종목 (SPAC·우선주 제외)"""
    out = {}
    with open(CSV, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            code = (r.get("stock_code") or "").strip()
            if not code:
                continue
            if (r.get("is_spac") or "").lower() == "true":
                continue
            if (r.get("is_preferred") or "").lower() == "true":
                continue
            wics = (r.get("wics") or "").strip()
            if not wics:
                continue
            out[code] = {
                "corp_name": (r.get("corp_name") or "").strip(),
                "wics": wics,
                "market": (r.get("market") or "").strip(),
            }
    return out


def load_total_assets(conn):
    """종목별 최신연도 자산총계 (연결 우선, 없으면 별도)"""
    rows = conn.execute("""
        SELECT stock_code, statement_scope, MAX(fiscal_year) AS fy
        FROM financial_detail
        WHERE statement_type='BS' AND account_nm LIKE '%자산총계%'
        GROUP BY stock_code, statement_scope
    """).fetchall()
    # 종목별로 연결 우선 선택
    assets = {}
    for code, scope, fy in rows:
        val = conn.execute("""
            SELECT amount FROM financial_detail
            WHERE stock_code=? AND statement_type='BS' AND statement_scope=?
              AND fiscal_year=? AND account_nm LIKE '%자산총계%'
            ORDER BY ABS(amount) DESC LIMIT 1
        """, (code, scope, fy)).fetchone()
        if not val or val[0] is None:
            continue
        amt = abs(float(val[0]))
        # 연결 우선
        if code not in assets or scope == "연결":
            if code not in assets or scope == "연결":
                assets[code] = (amt, scope)
    return {k: v[0] for k, v in assets.items()}


def main():
    universe = load_universe()
    print(f"활성 종목: {len(universe)}개")

    conn = sqlite3.connect(DB)
    assets = load_total_assets(conn)
    print(f"자산총계 보유: {len(assets)}개")

    # WICS 그룹핑
    by_wics = {}
    for code, info in universe.items():
        by_wics.setdefault(info["wics"], []).append(code)

    # 테이블 생성
    conn.executescript("""
        DROP TABLE IF EXISTS peer_competitors;
        CREATE TABLE peer_competitors (
            stock_code      TEXT NOT NULL,
            rank            INTEGER NOT NULL,
            competitor_code TEXT NOT NULL,
            competitor_name TEXT NOT NULL,
            wics            TEXT,
            basis           TEXT,        -- 선정 근거
            PRIMARY KEY (stock_code, competitor_code)
        );
        CREATE INDEX idx_peer_stock ON peer_competitors(stock_code);
    """)

    total_rows = 0
    covered = 0
    for code, info in universe.items():
        wics = info["wics"]
        my_name = info["corp_name"]
        my_is_holding = is_holding(my_name)
        # 같은 그룹·지주사 제외 (지주회사 본인이면 지주 비교는 허용)
        peers = []
        for c in by_wics.get(wics, []):
            if c == code:
                continue
            cn = universe[c]["corp_name"]
            if same_group(my_name, cn):
                continue   # 같은 기업집단(아모레퍼시픽 vs 아모레퍼시픽홀딩스) 제외
            if is_holding(cn) and not my_is_holding:
                continue   # 영업회사의 경쟁사로 지주사 제외
            peers.append(c)
        if not peers:
            continue

        # 규모(자산총계) 보유 여부로 정렬
        with_assets = [(c, assets[c]) for c in peers if c in assets]
        without_assets = [c for c in peers if c not in assets]

        selected = []
        my_asset = assets.get(code)

        if my_asset and with_assets:
            # 규모 인접: 본 종목 자산 기준 가까운 순 + 큰 종목 우선
            # 전략: 같은 업종 자산 상위 N개 (대장주 = 경쟁 기준점)
            with_assets.sort(key=lambda x: -x[1])
            # 본 종목보다 큰 것 위주 + 부족하면 작은 것
            bigger = [x for x in with_assets if x[1] >= my_asset]
            smaller = [x for x in with_assets if x[1] < my_asset]
            # 규모 인접 = 본 종목 바로 위 2개 + 바로 아래 2개 + 업종 1위
            picks = []
            # 업종 1위 (대장주) 항상 포함
            if with_assets:
                picks.append(with_assets[0][0])
            # 바로 위
            for x in reversed(bigger[-3:]):
                if x[0] not in picks:
                    picks.append(x[0])
            # 바로 아래
            for x in smaller[:3]:
                if x[0] not in picks:
                    picks.append(x[0])
            selected = picks[:N_COMPETITORS]
            basis = "동종업계 자산규모 인접"
        else:
            # 규모 없으면 같은 업종 (자산 보유 종목 우선)
            ranked = [c for c, _ in sorted(with_assets, key=lambda x: -x[1])]
            selected = (ranked + without_assets)[:N_COMPETITORS]
            basis = "동종업계 (규모정보 일부)"

        for rank, comp_code in enumerate(selected, 1):
            conn.execute("""
                INSERT OR REPLACE INTO peer_competitors
                (stock_code, rank, competitor_code, competitor_name, wics, basis)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (code, rank, comp_code,
                  universe[comp_code]["corp_name"], wics, basis))
            total_rows += 1
        if selected:
            covered += 1

    conn.commit()

    # 검증
    print(f"\n경쟁사 적재: {covered}개 종목 / {total_rows}건")
    print("\n샘플 검증:")
    for code in ["005930", "035420", "090430", "009150", "068270"]:
        rows = conn.execute("""
            SELECT competitor_name FROM peer_competitors
            WHERE stock_code=? ORDER BY rank
        """, (code,)).fetchall()
        info = universe.get(code, {})
        comps = [r[0] for r in rows]
        print(f"  {code} {info.get('corp_name','?'):12s} [{info.get('wics','?')}] → {comps}")

    conn.close()
    print(f"\n[OK] peer_competitors 테이블 완료")


if __name__ == "__main__":
    main()
