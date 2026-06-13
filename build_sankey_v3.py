# -*- coding: utf-8 -*-
"""
build_sankey_v3.py
==================
손익흐름도 전수 생성 (ekke 스타일 업데이트)
변경사항:
  1. 매출액 앞에 "{기업명}" 진한파랑 소스노드 추가 → 연파랑 긴 띠 효과
     (맨 왼쪽 진파랑 = 기업명, 연파랑 흐름, 오른쪽 끝 진파랑 = 총매출+금액)
  2. 음수(-) 값인 노드/링크 → 노란색(#eab308) 강조
  3. 고정 10노드 템플릿 전종목 통일 (구버전 13개 파일도 덮어씌움)
"""
import re
import sqlite3
import glob
import os
from pathlib import Path
import plotly.graph_objects as go

ROOT = Path(r"C:\Users\Admin\FILMN9")
DB   = ROOT / "data" / "filmn9.db"
OUT  = ROOT / "outputs" / "sankey"


def norm(nm):
    # 로마숫자/번호 접두사 제거 (Ⅴ.영업이익·XI.당기순이익 → 영업이익·당기순이익)
    nm = re.sub(r"^\s*[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫXVIxvi0-9]+\s*[.)]\s*", "", nm or "")
    return re.sub(r"\(.*?\)", "", nm).replace(" ", "").replace("(", "").replace(")", "").strip()


ACC = {
    "rev":     ["매출액", "영업수익", "매출및기타수익", "매출", "수익"],
    "cogs":    ["매출원가"],
    "gp":      ["매출총이익"],
    "sga":     ["판매비와관리비"],
    "op":      ["영업이익", "영업이익손실"],
    "noni":    ["영업외수익"],
    "nonx":    ["영업외비용"],
    "fin_inc": ["금융수익", "기타영업외수익", "기타수익"],
    "fin_exp": ["금융비용", "금융원가", "기타비용"],
    "tax":     ["법인세비용", "법인세비용수익"],
    "pretax":  ["법인세비용차감전순이익", "법인세비용차감전순이익손실"],
    "ni":      ["당기순이익", "당기순이익손실"],
}

# ── 색상 팔레트 ──────────────────────────────────────────────
BLUE_DARK = "#1d4ed8"   # 기업명 소스노드 (진한 파랑)
BLUE_MID  = "#3b82f6"   # 총매출/매출액 노드
GREEN_C   = "#22c55e"   # 이익 계열
RED_C     = "#ef4444"   # 비용 계열
YELLOW_C  = "#eab308"   # 음수(-) 노드/링크

GREEN_SET = {"매출총이익", "영업이익", "세전이익", "당기순이익", "영업외수익"}

LINK_ALPHA = {
    BLUE_DARK: "rgba(29,78,216,0.38)",   # 기업명→총매출 띠 (선명한 파랑)
    BLUE_MID:  "rgba(59,130,246,0.28)",
    GREEN_C:   "rgba(34,197,94,0.36)",
    RED_C:     "rgba(239,68,68,0.28)",
    YELLOW_C:  "rgba(234,179,8,0.42)",   # 음수 링크
}


def ncolor(n, v=None):
    """노드 색상 결정: 값이 음수면 노랑, 아니면 역할별 색"""
    if v is not None and v < 0:
        return YELLOW_C
    if n == "__src__":
        return BLUE_DARK
    if n == "매출액":
        return BLUE_MID
    if n in GREEN_SET:
        return GREEN_C
    return RED_C


def fmt(v):
    """백만원 → 조/억 (앱 fmtAmt와 동일 표기). '원'은 호출부에서 붙임. 음수 유지.
    예: 45,932,167백만원 → '45.93조' / 977,063 → '9,771억' / 16,000 → '160억'."""
    if v is None:
        return ""
    sign = "-" if v < 0 else ""
    a = abs(v)
    if a >= 1_000_000:        # 1조 = 1,000,000 백만원
        return f"{sign}{a / 1_000_000:,.2f}조"
    if a >= 100:              # 1억 = 100 백만원
        return f"{sign}{a / 100:,.0f}억"
    return f"{sign}{a:,.0f}백만"


def pick(bag, keys):
    for sc in ("연결", "별도", ""):
        for k in keys:
            if (k, sc) in bag and bag[(k, sc)] is not None:
                return bag[(k, sc)]
    return None


def scale_div(rev):
    # 2026-06-13: financial_detail·financials를 DART에서 백만원으로 통일 재구축 →
    # 더 이상 단위 분할 불필요(과거엔 원 단위 raw 혼재라 adaptive 분할했음). 항상 1.
    # fmt()가 백만원 → 억(÷100) 변환을 담당.
    return 1


def build(code, name, fy, bag, fin_summary):
    g = lambda key: pick(bag, ACC[key])

    rev_raw = g("rev")
    div = scale_div(rev_raw if rev_raw else (fin_summary or {}).get("revenue"))
    def S(v): return None if v is None else v / div

    rev  = S(g("rev"));  cogs = S(g("cogs")); gp   = S(g("gp"))
    sga  = S(g("sga"));  op   = S(g("op"));   noni = S(g("noni"))
    nonx = S(g("nonx")); tax  = S(g("tax"));  ni   = S(g("ni"))
    fin_inc = S(g("fin_inc")); fin_exp = S(g("fin_exp"))

    # financials 요약 폴백
    fs = fin_summary or {}
    if rev  is None and fs.get("revenue")   is not None: rev  = fs["revenue"]
    if op   is None and fs.get("op_income") is not None: op   = fs["op_income"]
    if ni   is None and fs.get("net_income") is not None: ni  = fs["net_income"]
    if rev is None or rev <= 0:
        return False

    # 보완 계산
    if gp   is None and cogs is not None: gp   = rev - cogs
    if cogs is None and gp   is not None: cogs = rev - gp
    if op   is None and gp   is not None and sga is not None: op = gp - sga
    if noni is None and (fin_inc or 0) > 0: noni = fin_inc
    if nonx is None and (fin_exp or 0) > 0: nonx = fin_exp
    pretax = (op + (noni or 0) - (nonx or 0)) if op is not None else None

    # ── 노드값 (signed — 음수 그대로) ──
    vals = {
        "매출액":        rev,    "매출원가":    cogs,
        "매출총이익":    gp,     "판매비와관리비": sga,
        "영업이익":      op,     "영업외수익":  noni,
        "영업외비용":    nonx,   "세전이익":    pretax,
        "법인세":        tax,    "당기순이익":  ni,
    }
    ORDER = [
        "매출액", "매출원가", "매출총이익", "판매비와관리비", "영업이익",
        "영업외수익", "영업외비용", "세전이익", "법인세", "당기순이익",
    ]
    nodes_data = [n for n in ORDER if vals.get(n) is not None]
    if "매출액" not in nodes_data:
        return False

    # ── 소스노드 "__src__" (기업명, 진한 파랑) 맨 앞에 추가 ──
    all_nodes = ["__src__"] + nodes_data
    NV = {n: i for i, n in enumerate(all_nodes)}

    floor = max(abs(rev), 1) * 0.006

    srcs, tgts, vals_w = [], [], []

    def link(a, b):
        if a not in NV or b not in NV:
            return
        # 링크 폭: target의 abs값 (최소 floor 보장)
        if b == "매출액":
            w = round(max(abs(rev), floor))
        else:
            bv = vals.get(b)
            if bv is None:
                return
            w = round(max(abs(bv), floor))
        srcs.append(NV[a]); tgts.append(NV[b]); vals_w.append(w)

    # 소스노드 → 총매출 (긴 파란 띠)
    link("__src__", "매출액")
    # 기존 흐름
    link("매출액",      "매출원가")
    link("매출액",      "매출총이익")
    link("매출총이익",  "판매비와관리비")
    link("매출총이익",  "영업이익")
    link("영업이익",    "세전이익")
    link("영업외수익",  "세전이익")
    link("세전이익",    "영업외비용")
    link("세전이익",    "법인세")
    link("세전이익",    "당기순이익")

    if not vals_w:
        return False

    # ── 노드 색상 ──
    node_colors = [ncolor(n, vals.get(n)) for n in all_nodes]

    # ── 링크 색상 (target 값 기준) ──
    link_colors = []
    for t_idx in tgts:
        t_name = all_nodes[t_idx]
        t_val  = vals.get(t_name)
        c = ncolor(t_name, t_val)
        if t_name == "매출액":
            c = BLUE_DARK
        link_colors.append(LINK_ALPHA.get(c, "rgba(150,150,150,0.3)"))

    # ── 노드 x,y 좌표 (arrangement="fixed") ──
    # 총매출(매출액)을 차트 중간에 배치 → 매출원가가 위로 곡선, 매출총이익이 아래로 곡선
    POS = {
        "__src__":        (0.01, 0.42),
        "매출액":         (0.24, 0.42),   # 총매출 — 중간 위치 (여기서 위/아래로 분기)
        "매출원가":       (0.90, 0.16),   # 상단 오른쪽 → 총매출에서 위로 커브 생성 ★
        "매출총이익":     (0.48, 0.63),   # 중하단
        "판매비와관리비": (0.90, 0.56),
        "영업이익":       (0.64, 0.69),
        "영업외수익":     (0.01, 0.85),
        "영업외비용":     (0.90, 0.83),
        "세전이익":       (0.77, 0.71),
        "법인세":         (0.90, 0.93),
        "당기순이익":     (0.90, 0.76),
    }
    node_x = [POS.get(n, (0.5, 0.5))[0] for n in all_nodes]
    node_y = [POS.get(n, (0.5, 0.5))[1] for n in all_nodes]

    # ── 라벨 ──
    ratio = {}
    if rev and rev > 0:
        if gp  is not None: ratio["매출총이익"] = gp  / rev * 100
        if op  is not None: ratio["영업이익"]   = op  / rev * 100
        if ni  is not None: ratio["당기순이익"] = ni  / rev * 100

    labels = []
    for n in all_nodes:
        if n == "__src__":
            # 맨 왼쪽: 진한 파랑 — 기업명만 표시
            labels.append(f"<b>{name}</b>")
            continue
        v = vals[n]
        if n == "매출액":
            # 총매출 라벨로 교체
            t = f"총매출<br>{fmt(v)}원"
        else:
            t = f"{n}<br>{fmt(v)}원"
        if n in ratio:
            t += f"<br>({ratio[n]:.1f}%)"
        labels.append(t)

    # ── 레이아웃 ──
    title_txt = (
        f"<b>{name}</b> 손익 흐름도 · {fy}년(연결)　"
        f"<span style='color:{BLUE_MID}'>■매출</span> "
        f"<span style='color:{GREEN_C}'>■이익</span> "
        f"<span style='color:{RED_C}'>■비용</span> "
        f"<span style='color:{YELLOW_C}'>■손실(적자)</span>"
    )
    fig = go.Figure(go.Sankey(
        arrangement="fixed",
        node=dict(
            label=labels,
            x=node_x,
            y=node_y,
            pad=20,
            thickness=16,
            color=node_colors,
            line=dict(color="white", width=1.0),
            hovertemplate="%{label}<extra></extra>",
        ),
        link=dict(
            source=srcs,
            target=tgts,
            value=vals_w,
            color=link_colors,
            hovertemplate="%{source.label} → %{target.label}<extra></extra>",
        ),
    ))
    fig.update_layout(
        title=dict(text=title_txt, font=dict(size=13), x=0.02, xanchor="left"),
        font=dict(family="Malgun Gothic", size=11),
        height=470,
        margin=dict(l=10, r=10, t=46, b=10),
        paper_bgcolor="white",
        plot_bgcolor="white",
    )
    OUT.mkdir(parents=True, exist_ok=True)
    fig.write_html(
        str(OUT / f"{code}_sankey.html"),
        include_plotlyjs="cdn",
        full_html=True,
        default_height="470px",
    )
    return True


def main():
    conn  = sqlite3.connect(DB)
    names = dict(conn.execute("SELECT stock_code, corp_name FROM company_info").fetchall())
    fin   = {}
    # financials가 다년·다보고서(2024/2025/2026·연간/분기)로 확장됨 → Sankey는 financial_detail
    # (연간 2023~2025)과 짝이 맞는 2025 연간(11011)만 요약 폴백으로 사용. 임의 행 선택 방지.
    for r in conn.execute(
        "SELECT stock_code,fiscal_year,revenue,op_income,net_income FROM financials "
        "WHERE fiscal_year=2025 AND reprt_code='11011'"
    ):
        fin[r[0]] = {"fy": r[1], "revenue": r[2], "op_income": r[3], "net_income": r[4]}

    targets = set(sum(ACC.values(), []))
    rows = conn.execute(
        "SELECT stock_code, fiscal_year, statement_scope, account_nm, amount "
        "FROM financial_detail WHERE statement_type IN ('IS','CIS')"
    ).fetchall()
    conn.close()

    latest = {}
    for code, fy, *_ in rows:
        if fy and 2022 <= fy <= 2025:
            latest[code] = max(latest.get(code, 0), fy)

    bags = {}
    for code, fy, scope, acc, amt in rows:
        if latest.get(code) != fy or amt is None:
            continue
        n = norm(acc)
        if n in targets:
            bags.setdefault(code, {}).setdefault((n, scope or ""), amt)

    codes = set(bags.keys()) | set(fin.keys())
    made = fail = 0
    for code in codes:
        nm = names.get(code, code)
        fs = fin.get(code)
        fy = (fs or {}).get("fy") or latest.get(code) or ""
        try:
            if build(code, nm, fy, bags.get(code, {}), fs):
                made += 1
            else:
                fail += 1
        except Exception as e:
            fail += 1
    total = len(glob.glob(str(OUT / "*_sankey.html")))
    print(f"Sankey v3 생성 완료: {made}개 성공 / {fail}개 실패 / 총 파일 {total}개")


if __name__ == "__main__":
    main()
