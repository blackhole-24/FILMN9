# -*- coding: utf-8 -*-
"""
build_sankey_fallback.py
========================
상세 IS/CIS가 없어 Sankey HTML이 안 만들어진 종목을, financials 요약
(매출액·영업이익·당기순이익)으로 간이 손익흐름 Sankey 생성 → 커버리지 보강.
외부 호출 0. 기존 HTML 있으면 건너뜀(상세본 보존).
"""
import sqlite3
import glob
import os
from pathlib import Path
import plotly.graph_objects as go

ROOT = Path(r"C:\Users\Admin\FILMN9")
DB = ROOT / "data" / "filmn9.db"
OUT = ROOT / "outputs" / "sankey"


def fmt(v):  # 백만원 → 억원 표기
    return f"{v/100:,.0f}억"


def build(code, name, fy, rev, op, ni):
    op = op or 0
    cost = max(0, rev - op)
    nodes = [
        f"매출액<br>{fmt(rev)}",
        f"영업비용<br>{fmt(cost)}",
        f"영업이익<br>{fmt(op)}",
        "법인세·기타",
        f"당기순이익<br>{fmt(ni)}" if ni is not None else "당기순이익",
        "영업외·금융손익",
    ]
    src, tgt, val, lab = [], [], [], []

    def link(s, t, v):
        if v and v > 0:
            src.append(s); tgt.append(t); val.append(round(v)); lab.append(fmt(v))

    link(0, 1, cost)                  # 매출 → 영업비용
    link(0, 2, max(0, op))            # 매출 → 영업이익
    if ni is not None and op > 0:
        link(2, 4, max(0, min(op, ni)))       # 영업이익 → 당기순이익
        if op > ni:
            link(2, 3, op - ni)               # 영업이익 → 법인세·기타
        elif ni > op:
            link(5, 4, ni - op)               # 영업외·금융손익 → 당기순이익
    if not val:
        return False
    colors = ["#6366f1", "#f87171", "#34d399", "#fbbf24", "#10b981", "#60a5fa"]
    fig = go.Figure(go.Sankey(
        node=dict(label=nodes, pad=18, thickness=18, color=colors,
                  line=dict(color="#e5e7eb", width=0.5),
                  hovertemplate="%{label}<extra></extra>"),
        link=dict(source=src, target=tgt, value=val,
                  customdata=lab, color="rgba(99,102,241,0.25)",
                  hovertemplate="%{source.label} → %{target.label}<br><b>%{customdata}원</b><extra></extra>")))
    fig.update_layout(
        title=dict(text=f"{name} ({code}) · {fy}년 손익 흐름도 <span style='font-size:11px;color:#94a3b8'>· 요약(연결)</span>",
                   font=dict(size=14)),
        font=dict(family="Malgun Gothic", size=12), height=480,
        margin=dict(l=10, r=10, t=50, b=10), paper_bgcolor="white")
    OUT.mkdir(parents=True, exist_ok=True)
    fig.write_html(str(OUT / f"{code}_sankey.html"), include_plotlyjs="cdn", full_html=True)
    return True


def main():
    have = set(os.path.basename(f)[:6] for f in glob.glob(str(OUT / "*_sankey.html")))
    conn = sqlite3.connect(DB)
    names = dict(conn.execute("SELECT stock_code, corp_name FROM company_info").fetchall())
    rows = conn.execute("""
        SELECT stock_code, fiscal_year, revenue, op_income, net_income
        FROM financials WHERE revenue IS NOT NULL AND revenue > 0 AND op_income IS NOT NULL
    """).fetchall()
    conn.close()

    # 상세본(요약 아님)은 보존, fallback(요약)본은 재생성 대상
    detailed = set()
    for f in glob.glob(str(OUT / "*_sankey.html")):
        try:
            head = open(f, encoding="utf-8").read()
            if "요약(연결)" not in head:
                detailed.add(os.path.basename(f)[:6])
        except Exception:
            pass

    before = len(have)
    made = skip = fail = 0
    for code, fy, rev, op, ni in rows:
        if code in detailed:      # 상세 IS/CIS 기반 본은 유지
            continue
        try:
            if build(code, names.get(code, code), fy, rev, op, ni):
                made += 1
            else:
                fail += 1
        except Exception:
            fail += 1
    after = len(glob.glob(str(OUT / "*_sankey.html")))
    print(f"보강 전 Sankey: {before}개")
    print(f"  신규 생성: {made} / 생성실패(데이터부족): {fail}")
    print(f"보강 후 Sankey: {after}개")


if __name__ == "__main__":
    main()
