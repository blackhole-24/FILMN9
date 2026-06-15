# -*- coding: utf-8 -*-
"""
build_financials_summary.py
===========================
financial_detail(계정 상세, 2,708종목) → financials(요약 테이블) 전수 생성.
재무 하이라이트(매출·영업이익·당기순이익) + 재무 건전성(부채비율 등) 빈칸 해결.

핵심:
  - 종목별 최신연도, scope 연결 우선(없으면 별도)
  - 단위 자동 정규화: 자산총계 크기로 원/천원/백만원 판별 → 백만원 통일
    (외감 JSONL 단위 혼재 대응 / DART·XML은 원 → /1e6)
  - debt_ratio = 부채총계/자본총계×100 (비율은 단위 무관)
"""
import re
import sqlite3
from datetime import datetime
from pathlib import Path

DB = Path(r"C:\Users\Admin\FILMN9\data\filmn9.db")
NOW = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# 정규화(괄호·공백 제거) 후 매칭할 기준 계정명 (우선순위 순)
REVENUE = ("매출액", "영업수익", "매출", "수익")
OP      = ("영업이익", "영업이익손실", "영업손익")
NI      = ("당기순이익", "당기순이익손실", "당기순손익", "분기순이익")
ASSETS  = ("자산총계",)
LIAB    = ("부채총계",)
EQUITY  = ("자본총계",)
# DB LIKE 1차 필터용 키워드
LIKE_KW = ("매출액", "영업수익", "영업이익", "당기순이익", "당기순손익",
           "자산총계", "부채총계", "자본총계", "유동자산", "유동부채")


def norm(nm):
    """'매출액 (주30)' → '매출액', '영업이익(손실)' → '영업이익손실'"""
    return re.sub(r"\(.*?\)", "", nm or "").replace(" ", "").replace("(", "").replace(")", "").strip()


def pick(d, names):
    """정규화 account 후보 중 연결 우선 → 별도 → 무관, 첫 유효값"""
    for sc in ("연결", "별도", ""):
        for nm in names:
            v = d.get((nm, sc))
            if v is not None:
                return v
    for nm in names:
        for (a, sc), v in d.items():
            if a == nm and v is not None:
                return v
    return None


def scale_div(assets_raw, revenue_raw):
    """자산총계(없으면 매출)로 단위 판별 → 백만원 환산 제수"""
    anchor = abs(assets_raw or 0) or abs(revenue_raw or 0)
    if anchor >= 1e9:      # 원 단위 (10억+)
        return 1_000_000
    if anchor >= 1e6:      # 천원 단위
        return 1_000
    return 1               # 이미 백만원


def main():
    conn = sqlite3.connect(DB, timeout=120)
    conn.execute("PRAGMA busy_timeout=120000")

    # 종목별 최신 연도 (정상 범위, 2025 우선)
    latest = dict(conn.execute("""
        SELECT stock_code, MAX(fiscal_year) FROM financial_detail
        WHERE fiscal_year BETWEEN 2022 AND 2025 GROUP BY stock_code
    """).fetchall())

    like = " OR ".join(["account_nm LIKE ?"] * len(LIKE_KW))
    rows = conn.execute(f"""
        SELECT stock_code, fiscal_year, statement_scope, account_nm, amount
        FROM financial_detail WHERE {like}
    """, tuple(f"%{k}%" for k in LIKE_KW)).fetchall()

    # stock -> {(정규화account, scope): amount}  (최신연도만)
    bag = {}
    for code, fy, scope, acc, amt in rows:
        if latest.get(code) != fy or amt is None:
            continue
        bag.setdefault(code, {}).setdefault((norm(acc), scope or ""), amt)

    out = []
    cnt_hi = cnt_ratio = 0
    for code, d in bag.items():
        fy = latest[code]
        rev_r = pick(d, REVENUE); op_r = pick(d, OP); ni_r = pick(d, NI)
        as_r = pick(d, ASSETS); li_r = pick(d, LIAB); eq_r = pick(d, EQUITY)
        div = scale_div(as_r, rev_r)
        f = lambda x: round(x / div) if x is not None else None
        revenue, op_income, net_income = f(rev_r), f(op_r), f(ni_r)
        assets, liab, equity = f(as_r), f(li_r), f(eq_r)
        debt_ratio = round(li_r / eq_r * 100, 2) if (li_r and eq_r and eq_r != 0) else None
        if any(v is not None for v in (revenue, op_income, net_income)):
            cnt_hi += 1
        if debt_ratio is not None:
            cnt_ratio += 1
        out.append((code, fy, revenue, op_income, net_income, assets, liab, equity,
                    debt_ratio, None, None, None, "백만원",
                    "financial_detail 요약(자동단위정규화)", NOW, NOW))

    # 직전 자동생성분 제거(재실행 안전) — 원본 데모/파싱본은 유지
    conn.execute("DELETE FROM financials WHERE source LIKE '%자동단위정규화%'")
    conn.executemany("""
        INSERT OR REPLACE INTO financials
        (stock_code,fiscal_year,revenue,op_income,net_income,assets,liabilities,equity,
         debt_ratio,cashflow_op,cashflow_inv,cashflow_fin,unit,source,generated_at,loaded_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, out)
    conn.commit()
    total = conn.execute("SELECT COUNT(DISTINCT stock_code) FROM financials").fetchone()[0]
    conn.close()
    print(f"financials 요약 생성: {len(out)}종목 처리")
    print(f"  매출/이익 보유: {cnt_hi} · 부채비율 보유: {cnt_ratio}")
    print(f"  financials 테이블 총 종목수: {total}")


if __name__ == "__main__":
    main()
