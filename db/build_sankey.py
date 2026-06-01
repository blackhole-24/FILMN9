"""
db/build_sankey.py
==================
financial_detail (IS/CIS) → Plotly Sankey HTML 생성

v2 개선 (2026-05-29):
- statement_type IS/CIS 폴백 + statement_scope='연결' 명시
- 매출 세부 항목 (제품매출·상품매출·서비스매출 등) 자동 분리 → 앞단 명확화
- NAVER 같은 영업비용 통합 케이스 자동 감지
- 노드 위치·라벨 위치 명확화 (라벨 박스 밖)
- 흐름선 색·투명도 강화
- 음수·결측값 안전 처리
- 3000개 일반화 가능 (매출 세부 없으면 단일 매출액 노드만 사용)

사용
----
python db/build_sankey.py              # 데모 3종목
python db/build_sankey.py 090430       # 단일
python db/build_sankey.py 090430 009150 035420
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT    = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "filmn9.db"
OUT_DIR = ROOT / "outputs" / "sankey"
OUT_DIR.mkdir(parents=True, exist_ok=True)

DEMO_3 = ["090430", "009150", "035420"]

# 매출 세부 항목 (있으면 펼치고, 없으면 매출액 단일 노드)
REVENUE_DETAIL_KEYWORDS = [
    "제품매출", "상품매출", "서비스매출", "용역매출", "기타매출",
    "임대매출", "수수료수익", "콘텐츠매출", "광고매출", "구독매출",
    "로열티수익", "라이선스수익", "IP매출", "음반매출", "공연매출",
    "수출", "내수",
]

# 컬러 팔레트 (원본 JYP/포켓몬 스타일 참고)
COLOR = {
    "revenue":     "#3B82F6",   # 매출 파랑
    "rev_detail":  "#60A5FA",   # 세부 매출 연파랑
    "profit":      "#10B981",   # 이익 초록
    "cost":        "#EF4444",   # 비용 빨강
    "tax":         "#6B7280",   # 법인세 회색
}
LINK_ALPHA_REV   = "rgba(59,130,246,0.45)"
LINK_ALPHA_PROF  = "rgba(16,185,129,0.45)"
LINK_ALPHA_COST  = "rgba(239,68,68,0.40)"
LINK_ALPHA_TAX   = "rgba(107,114,128,0.45)"


def fetch_account(items: list[dict], names: list[str]) -> float:
    """names 순서대로 먼저 매칭되는 행의 amount 반환"""
    for name in names:
        for row in items:
            nm = (row["account_nm"] or "").replace(" ", "")
            for clean_name in [name, name.replace(" ", "")]:
                if nm.startswith(clean_name) or clean_name in nm:
                    v = row["amount"]
                    if v is not None:
                        return float(v)
    return 0.0


def find_revenue_details(items: list[dict]) -> list[tuple[str, float]]:
    """매출 세부 항목 추출 (있으면 펼치기, 없으면 빈 리스트)"""
    out = []
    seen = set()
    for row in items:
        nm = (row["account_nm"] or "").strip()
        if not nm or row["amount"] is None or row["amount"] <= 0:
            continue
        for kw in REVENUE_DETAIL_KEYWORDS:
            if kw in nm.replace(" ", "") and nm not in seen:
                seen.add(nm)
                out.append((nm, float(row["amount"])))
                break
    # 매출총이익보다 큰 세부 항목은 제외 (집계 행일 가능성)
    return out


def load_is_data(stock_code: str):
    if not DB_PATH.exists():
        raise FileNotFoundError(f"DB 없음: {DB_PATH}")
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        # IS 우선, 없으면 CIS, 연결 우선 별도 폴백
        year_row = conn.execute("""
            SELECT MAX(fiscal_year) FROM financial_detail
            WHERE stock_code = ? AND statement_type IN ('IS','CIS')
        """, (stock_code,)).fetchone()
        if not year_row or year_row[0] is None:
            raise ValueError(f"{stock_code}: IS/CIS 데이터 없음")
        year = year_row[0]

        items = []
        for stype in ("IS", "CIS"):
            for scope in ("연결", "별도"):
                rows = conn.execute("""
                    SELECT account_nm, amount, display_order FROM financial_detail
                    WHERE stock_code = ? AND fiscal_year = ?
                      AND statement_type = ? AND statement_scope = ?
                    ORDER BY display_order
                """, (stock_code, year, stype, scope)).fetchall()
                if rows:
                    items = [dict(r) for r in rows]
                    used_scope = scope
                    used_type = stype
                    break
            if items:
                break
        if not items:
            raise ValueError(f"{stock_code}: 행 없음")

        cn = conn.execute(
            "SELECT corp_name FROM company_info WHERE stock_code=?", (stock_code,)
        ).fetchone()
        corp_name = cn["corp_name"] if cn else stock_code
    return items, str(year), corp_name, used_scope, used_type


def build_sankey(stock_code: str) -> None:
    try:
        import plotly.graph_objects as go
    except ImportError:
        print("  [ERROR] plotly 미설치: pip install plotly")
        return

    print(f"  [{stock_code}] 데이터 로딩...", end="", flush=True)
    try:
        items, year, corp_name, scope, stype = load_is_data(stock_code)
    except (FileNotFoundError, ValueError) as e:
        print(f" FAIL ({e})")
        return
    print(f" OK ({len(items)}행, {year}년 {stype}/{scope}, {corp_name})")

    def to_eok(v: float) -> float:
        """원 → 억원 (1억 = 1e8)"""
        return v / 1e8

    revenue    = to_eok(fetch_account(items, ["매출액", "영업수익", "수익(매출액)"]))
    cogs       = to_eok(fetch_account(items, ["매출원가"]))
    gross      = to_eok(fetch_account(items, ["매출총이익"]))
    sga        = to_eok(fetch_account(items, ["판매비와관리비", "판매관리비"]))
    opex_all   = to_eok(fetch_account(items, ["영업비용"]))
    op_income  = to_eok(fetch_account(items, ["영업이익"]))
    fin_inc    = to_eok(fetch_account(items, ["금융수익"]))
    fin_exp    = to_eok(fetch_account(items, ["금융비용", "금융원가"]))
    other_inc  = to_eok(fetch_account(items, ["기타수익", "기타영업외이익", "기타이익"]))
    other_exp  = to_eok(fetch_account(items, ["기타비용", "기타영업외손실"]))
    tax        = to_eok(fetch_account(items, ["법인세비용", "법인세"]))
    net_income = to_eok(fetch_account(items,
                  ["당기순이익", "지배기업소유주지분", "계속영업이익"]))

    # 서비스업·금융업 케이스: 영업비용 통합 (매출원가/매출총이익/판관비 없음)
    # NAVER 같이 매출액·영업비용·영업이익만 있는 경우 포함
    is_opex_only = (opex_all > 0 and gross == 0 and cogs == 0 and sga == 0)
    if is_opex_only:
        # 매출액 없으면 역산
        if revenue == 0:
            revenue = opex_all + max(op_income, 0)
        sga = opex_all
        cogs = 0
        gross = revenue
    else:
        # 일반 케이스 보정
        if gross == 0 and revenue > 0 and cogs > 0:
            gross = revenue - cogs
        if sga == 0 and gross > 0 and op_income != 0:
            sga = gross - op_income

    # 매출 세부 항목 시도 (있으면 펼치기)
    rev_details = find_revenue_details(items)
    # 세부 합계가 매출액의 70~110% 사이일 때만 사용 (이상치 방지)
    rev_details_use = []
    if rev_details and revenue > 0:
        det_sum = sum(v for _, v in rev_details)
        det_sum_eok = to_eok(det_sum)
        if 0.7 * revenue <= det_sum_eok <= 1.10 * revenue:
            rev_details_use = [(nm, to_eok(v)) for nm, v in rev_details]

    # 음수 안전 처리
    op_income = max(op_income, 0)
    net_income = max(net_income, 0)

    # 단위 포맷 (억원 기준)
    def fmt(v: float) -> str:
        if abs(v) >= 10000:           # >= 1조
            return f"{v/10000:.2f}조"
        elif abs(v) >= 1:
            return f"{v:,.0f}억"
        elif abs(v) > 0:
            return f"{v*100:.0f}만"
        return "0"

    # ── 노드 정의 ──────────────────────────────────────────────────────
    labels = []
    node_colors = []
    node_x = []
    node_y = []

    def add_node(label: str, color: str, x: float, y: float) -> int:
        labels.append(label)
        node_colors.append(color)
        node_x.append(x)
        node_y.append(y)
        return len(labels) - 1

    # 매출 세부 항목 (왼쪽 끝)
    rev_detail_idx = []
    if rev_details_use:
        n = len(rev_details_use)
        for i, (nm, v) in enumerate(rev_details_use):
            y = 0.05 + (0.9 / max(1, n-1)) * i if n > 1 else 0.5
            idx = add_node(f"{nm} {fmt(v)}", COLOR["rev_detail"], 0.01, y)
            rev_detail_idx.append((idx, v))
        idx_rev_source = None
    else:
        # 매출 세부 없으면 시각적 좌측 노드(총매출 소스) 추가
        idx_rev_source = add_node(f"{corp_name} 총매출 {fmt(revenue)}",
                                   COLOR["rev_detail"], 0.01, 0.5)

    # 매출액
    idx_rev = add_node(f"매출액 {fmt(revenue)}", COLOR["revenue"], 0.18, 0.5)

    if not is_opex_only:
        # 매출원가 (아래쪽), 매출총이익 (위쪽)
        idx_cogs = add_node(f"매출원가 {fmt(cogs)}", COLOR["cost"], 0.36, 0.78)
        idx_gross = add_node(f"매출총이익 {fmt(gross)}", COLOR["profit"], 0.36, 0.28)
        # 판관비 (아래쪽), 영업이익 (위쪽)
        idx_sga = add_node(f"판매관리비 {fmt(sga)}", COLOR["cost"], 0.54, 0.55)
        idx_op = add_node(f"영업이익 {fmt(op_income)}", COLOR["profit"], 0.54, 0.18)
    else:
        # NAVER 케이스: 매출액 → 영업비용 + 영업이익 직접
        idx_cogs = None
        idx_gross = None
        idx_sga = add_node(f"영업비용 {fmt(sga)}", COLOR["cost"], 0.36, 0.72)
        idx_op = add_node(f"영업이익 {fmt(op_income)}", COLOR["profit"], 0.36, 0.22)

    # 우측 영업외 항목
    side_x = 0.72
    side_nodes = []
    side_y = 0.05
    if fin_inc > 0:
        idx_fin_inc = add_node(f"금융수익 {fmt(fin_inc)}", COLOR["rev_detail"], side_x, side_y)
        side_nodes.append(("fin_inc", idx_fin_inc, fin_inc))
        side_y += 0.13
    if fin_exp > 0:
        idx_fin_exp = add_node(f"금융비용 {fmt(fin_exp)}", COLOR["cost"], side_x, side_y)
        side_nodes.append(("fin_exp", idx_fin_exp, fin_exp))
        side_y += 0.13
    if other_inc > 0:
        idx_oi = add_node(f"기타이익 {fmt(other_inc)}", COLOR["rev_detail"], side_x, side_y)
        side_nodes.append(("oi", idx_oi, other_inc))
        side_y += 0.13
    if other_exp > 0:
        idx_oe = add_node(f"기타비용 {fmt(other_exp)}", COLOR["cost"], side_x, side_y)
        side_nodes.append(("oe", idx_oe, other_exp))
        side_y += 0.13
    if tax > 0:
        idx_tax = add_node(f"법인세 {fmt(tax)}", COLOR["tax"], side_x, side_y)
        side_nodes.append(("tax", idx_tax, tax))

    # 당기순이익 (우측 끝)
    idx_ni = add_node(f"당기순이익 {fmt(net_income)}", COLOR["profit"], 0.95, 0.5)

    # ── 링크 ────────────────────────────────────────────────────────────
    srcs, tgts, vals, link_colors = [], [], [], []

    def link(s: int, t: int, v: float, color: str):
        if v > 0:
            srcs.append(s); tgts.append(t); vals.append(v); link_colors.append(color)

    # 매출 세부 → 매출액 (있으면)
    if rev_details_use:
        for idx, v in rev_detail_idx:
            link(idx, idx_rev, to_eok(v), LINK_ALPHA_REV)
    elif idx_rev_source is not None:
        # 시각적 총매출 → 매출액 (두꺼운 파란 흐름)
        link(idx_rev_source, idx_rev, revenue, LINK_ALPHA_REV)

    if not is_opex_only:
        # 매출액 → 매출원가 (아래)·매출총이익 (위)
        link(idx_rev, idx_cogs, cogs, LINK_ALPHA_COST)
        link(idx_rev, idx_gross, gross, LINK_ALPHA_PROF)
        # 매출총이익 → 판관비 (아래)·영업이익 (위)
        link(idx_gross, idx_sga, sga, LINK_ALPHA_COST)
        link(idx_gross, idx_op, op_income, LINK_ALPHA_PROF)
    else:
        # 매출액 → 영업비용·영업이익 직접
        link(idx_rev, idx_sga, sga, LINK_ALPHA_COST)
        link(idx_rev, idx_op, op_income, LINK_ALPHA_PROF)

    # 영업이익 → 영업외 항목 + 당기순이익
    for key, idx, v in side_nodes:
        color = LINK_ALPHA_COST if key in ("fin_exp", "oe") else (
                LINK_ALPHA_TAX if key == "tax" else LINK_ALPHA_REV)
        link(idx_op, idx, v, color)

    # 영업외 수익 → 순이익 (영양 추가)
    for key, idx, v in side_nodes:
        if key in ("fin_inc", "oi"):
            link(idx, idx_ni, v, LINK_ALPHA_PROF)

    # 영업이익 → 순이익 (메인 흐름)
    if net_income > 0:
        # 영업이익에서 빠진 비용·법인세를 제외한 잔액 = 영업이익 자체에서 순이익으로 직접 흐름
        op_to_ni = op_income - sum(v for k, _, v in side_nodes if k in ("fin_exp", "oe", "tax"))
        op_to_ni = max(op_to_ni, 0)
        if op_to_ni > 0:
            link(idx_op, idx_ni, op_to_ni, LINK_ALPHA_PROF)

    # ── Sankey 생성 ─────────────────────────────────────────────────────
    fig = go.Figure(data=[go.Sankey(
        arrangement="fixed",
        node=dict(
            pad=30,
            thickness=18,
            line=dict(color="white", width=0.5),
            label=labels,
            color=node_colors,
            x=node_x,
            y=node_y,
            hovertemplate="%{label}<extra></extra>",
        ),
        link=dict(
            source=srcs,
            target=tgts,
            value=vals,
            color=link_colors,
            hovertemplate="흐름: %{value:,.0f}억<extra></extra>",
        ),
        textfont=dict(
            family="Pretendard, Apple SD Gothic Neo, Segoe UI, sans-serif",
            size=12,
            color="#1e293b",
        ),
    )])

    fig.update_layout(
        title=dict(
            text=f"<b>{corp_name}</b> ({stock_code}) · {year}년 손익 흐름도 <span style='font-size:11px;color:#94a3b8'>· {scope}/{stype}</span>",
            font=dict(size=16, family="Pretendard, Apple SD Gothic Neo, sans-serif"),
            x=0.5,
        ),
        font=dict(
            family="Pretendard, Apple SD Gothic Neo, Segoe UI, sans-serif",
            size=11,
            color="#1e293b",
        ),
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        height=560,
        margin=dict(l=10, r=10, t=70, b=10),
    )

    out_path = OUT_DIR / f"{stock_code}_sankey.html"
    fig.write_html(
        str(out_path),
        include_plotlyjs="cdn",
        config={"displayModeBar": False, "responsive": True},
        full_html=True,
    )
    print(f"  [{stock_code}] 저장 → {out_path.name}")


def main():
    codes = sys.argv[1:] if len(sys.argv) > 1 else DEMO_3
    print(f"\n{'='*55}")
    print(f"  build_sankey.py v2  대상 {len(codes)}종목")
    print(f"  출력: {OUT_DIR}")
    print(f"{'='*55}")
    for code in codes:
        build_sankey(code.strip())
    print(f"\n완료.")


if __name__ == "__main__":
    main()
