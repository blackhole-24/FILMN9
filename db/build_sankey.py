"""
db/build_sankey.py
==================
financial_detail IS → Plotly Sankey HTML 생성

데모 3종목(090430·009150·035420) 또는 지정 종목코드에 대해
SQLite의 financial_detail 테이블에서 손익계산서 데이터를 읽어
Plotly Sankey 다이어그램을 HTML로 저장한다.

사용법
------
cd C:/Users/Admin/FILMN9
python db/build_sankey.py              # 데모 3종목 전체
python db/build_sankey.py 090430       # 단일 종목
python db/build_sankey.py 090430 009150  # 복수 지정
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

# ─── 계정명 → Sankey 카테고리 매핑 ───────────────────────────────────────────
# (category_type, category_name, color_hint)
# color_hint: "revenue" / "profit" / "cost"
ACCOUNT_MAP: dict[str, tuple[str, str, str]] = {
    # ── 매출 관련 ─────────────────────────────────────────────
    "매출액":               ("revenue",  "매출액",    "revenue"),
    "영업수익":             ("revenue",  "매출액",    "revenue"),
    "제품매출":             ("rev_det",  "제품매출",  "revenue"),
    "상품매출":             ("rev_det",  "상품매출",  "revenue"),
    "서비스매출":           ("rev_det",  "서비스매출","revenue"),
    "용역매출":             ("rev_det",  "용역매출",  "revenue"),
    "기타매출":             ("rev_det",  "기타매출",  "revenue"),

    # ── 매출원가 ───────────────────────────────────────────────
    "매출원가":             ("cogs",     "매출원가",  "cost"),
    "제품매출원가":         ("cogs",     "제품원가",  "cost"),
    "상품매출원가":         ("cogs",     "상품원가",  "cost"),
    "서비스매출원가":       ("cogs",     "서비스원가","cost"),

    # ── 매출총이익 ─────────────────────────────────────────────
    "매출총이익":           ("gross",    "매출총이익","profit"),

    # ── 판매비·관리비 세부 ─────────────────────────────────────
    "판매비와관리비":       ("sga",      "판관비",    "cost"),
    "급여":                 ("sga",      "인건비",    "cost"),
    "임원급여":             ("sga",      "인건비",    "cost"),
    "퇴직급여":             ("sga",      "인건비",    "cost"),
    "복리후생비":           ("sga",      "인건비",    "cost"),
    "주식보상비용":         ("sga",      "인건비",    "cost"),
    "감가상각비":           ("sga",      "감가상각비","cost"),
    "무형자산상각비":       ("sga",      "감가상각비","cost"),
    "지급수수료":           ("sga",      "지급수수료","cost"),
    "수수료비용":           ("sga",      "지급수수료","cost"),
    "임차료":               ("sga",      "임차료",    "cost"),
    "지급임차료":           ("sga",      "임차료",    "cost"),
    "광고선전비":           ("sga",      "광고선전비","cost"),
    "판매촉진비":           ("sga",      "광고선전비","cost"),
    "연구개발비":           ("sga",      "연구개발비","cost"),
    "운반비":               ("sga",      "운반비",    "cost"),
    "세금과공과":           ("sga",      "세금과공과","cost"),
    "기타판매관리비":       ("sga",      "기타판관비","cost"),

    # ── 영업이익 ───────────────────────────────────────────────
    "영업이익":             ("op",       "영업이익",  "profit"),

    # ── 영업외 손익 ────────────────────────────────────────────
    "금융수익":             ("fin",      "금융수익",  "revenue"),
    "금융비용":             ("fin",      "금융비용",  "cost"),
    "기타수익":             ("nonop",    "영업외이익","revenue"),
    "기타비용":             ("nonop",    "영업외손실","cost"),
    "지분법이익":           ("nonop",    "지분법이익","revenue"),
    "지분법손실":           ("nonop",    "지분법손실","cost"),

    # ── 법인세·순이익 ──────────────────────────────────────────
    "법인세비용":           ("tax",      "법인세",    "cost"),
    "계속영업이익":         ("ni",       "계속영업이익","profit"),
    "당기순이익":           ("ni",       "당기순이익","profit"),
    "지배기업소유주지분":   ("ni",       "당기순이익","profit"),
    "비지배지분":           ("ni",       "비지배지분순이익","profit"),
}

# 색상 팔레트
COLOR = {
    "revenue": "#3B82F6",   # 파란
    "profit":  "#10B981",   # 초록
    "cost":    "#EF4444",   # 빨강
    "tax":     "#6B7280",   # 회색
}


def load_is_data(stock_code: str) -> tuple[list[dict], str, str]:
    """SQLite에서 IS 데이터 로드 → [{account_nm, amount, display_order}, ...]"""
    if not DB_PATH.exists():
        raise FileNotFoundError(f"DB 없음: {DB_PATH}")

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row

        # 최신 연도 IS
        row = conn.execute(
            "SELECT MAX(fiscal_year) FROM financial_detail "
            "WHERE stock_code=? AND statement_type='IS'", (stock_code,)
        ).fetchone()
        if not row or row[0] is None:
            raise ValueError(f"{stock_code}: IS 데이터 없음")
        year = row[0]

        rows = conn.execute(
            "SELECT account_nm, amount, display_order FROM financial_detail "
            "WHERE stock_code=? AND fiscal_year=? AND statement_type='IS' "
            "ORDER BY display_order",
            (stock_code, year),
        ).fetchall()

        # 기업명
        cn = conn.execute(
            "SELECT corp_name FROM company_info WHERE stock_code=?", (stock_code,)
        ).fetchone()
        corp_name = cn["corp_name"] if cn else stock_code

    return [dict(r) for r in rows], str(year), corp_name


def build_sankey(stock_code: str) -> None:
    try:
        import plotly.graph_objects as go
    except ImportError:
        print("  [ERROR] plotly 미설치: pip install plotly")
        return

    print(f"  [{stock_code}] 데이터 로딩...", end="", flush=True)
    try:
        items, year, corp_name = load_is_data(stock_code)
    except (FileNotFoundError, ValueError) as e:
        print(f" FAIL ({e})")
        return
    print(f" OK ({len(items)}행, {year}년, {corp_name})")

    # ── 핵심 금액 추출 ───────────────────────────────────────────────────────
    def get_amt(names: list[str]) -> float:
        """names 순서를 우선순위로 사용: 앞 계정명이 먼저 매칭되면 반환"""
        for name in names:
            for row in items:
                if row["account_nm"] == name:
                    v = row["amount"]
                    return float(v) if v is not None else 0.0
        return 0.0

    # DB 값은 원(₩) 단위 → 백만원으로 변환
    def to_bm(v: float) -> float:
        return v / 1_000_000

    revenue    = to_bm(get_amt(["매출액", "영업수익"]))
    cogs       = to_bm(get_amt(["매출원가"]))
    gross      = to_bm(get_amt(["매출총이익"]))
    # 판관비 없으면 영업비용(통합) 시도 (NAVER 등 서비스업)
    sga        = to_bm(get_amt(["판매비와관리비", "영업비용"]))
    op_income  = to_bm(get_amt(["영업이익"]))
    fin_inc    = to_bm(get_amt(["금융수익"]))
    fin_exp    = to_bm(get_amt(["금융비용"]))
    other_inc  = to_bm(get_amt(["기타수익"]))
    other_exp  = to_bm(get_amt(["기타비용"]))
    tax        = to_bm(get_amt(["법인세비용"]))
    # "지배기업 소유주지분"(공백 포함) 도 순이익으로 인식
    net_income = to_bm(get_amt(["당기순이익", "지배기업소유주지분",
                                "지배기업 소유주지분", "계속영업이익"]))

    # 매출총이익이 없으면 계산
    if gross == 0 and revenue > 0 and cogs > 0:
        gross = revenue - cogs
    # 판관비가 없으면 계산 (일반 케이스)
    if sga == 0 and gross > 0 and op_income != 0:
        sga = gross - op_income

    # 음수 교정 (이익 항목은 절대값)
    if op_income < 0:
        op_inc_neg = abs(op_income)
        op_income  = 0.0
    else:
        op_inc_neg = 0.0

    if net_income < 0:
        net_loss   = abs(net_income)
        net_income = 0.0
    else:
        net_loss   = 0.0

    # 단위 표시 (백만원 기준: 100 백만원 = 1억, 1,000,000 백만원 = 1조)
    def fmt(v: float) -> str:
        if abs(v) >= 1_000_000:        # >= 1조
            return f"{v/1_000_000:.2f}조"
        elif abs(v) >= 100:            # >= 1억
            return f"{v/100:.0f}억"
        elif abs(v) > 0:
            return f"{v:.0f}백만"
        return "0"

    # 영업비용 통합 케이스 감지 (NAVER 등 서비스업: 매출원가 없이 영업비용만 존재)
    is_opex_only = (cogs == 0 and sga > 0 and gross == 0)

    # ── Sankey 노드 & 링크 정의 ──────────────────────────────────────────────
    # 노드 인덱스 매핑
    # 0: 매출액  1: 매출원가  2: 매출총이익  3: 판관비/영업비용  4: 영업이익
    # 5: 금융수익  6: 금융비용  7: 기타이익  8: 기타비용  9: 법인세  10: 당기순이익

    # 서비스업 영업비용 통합 케이스는 판관비 노드 레이블을 "영업비용"으로 표시
    sga_label = "영업비용" if is_opex_only else "판매관리비"

    labels = [
        f"매출액\n{fmt(revenue)}",              # 0
        f"매출원가\n{fmt(cogs)}",               # 1
        f"매출총이익\n{fmt(gross)}",            # 2
        f"{sga_label}\n{fmt(sga)}",             # 3
        f"영업이익\n{fmt(op_income)}",          # 4
        f"금융수익\n{fmt(fin_inc)}",            # 5
        f"금융비용\n{fmt(fin_exp)}",            # 6
        f"기타이익\n{fmt(other_inc)}",          # 7
        f"기타비용\n{fmt(other_exp)}",          # 8
        f"법인세\n{fmt(tax)}",                  # 9
        f"당기순이익\n{fmt(net_income)}",       # 10
    ]
    node_colors = [
        COLOR["revenue"],   # 0 매출액
        COLOR["cost"],      # 1 매출원가
        COLOR["profit"],    # 2 매출총이익
        COLOR["cost"],      # 3 판관비/영업비용
        COLOR["profit"],    # 4 영업이익
        COLOR["revenue"],   # 5 금융수익
        COLOR["cost"],      # 6 금융비용
        COLOR["revenue"],   # 7 기타이익
        COLOR["cost"],      # 8 기타비용
        COLOR["cost"],      # 9 법인세
        COLOR["profit"],    # 10 당기순이익
    ]

    srcs, tgts, vals, link_colors = [], [], [], []

    def add_link(s: int, t: int, v: float, color: str = "rgba(180,180,180,0.4)"):
        if v > 0:
            srcs.append(s); tgts.append(t); vals.append(v)
            link_colors.append(color)

    if is_opex_only:
        # 서비스업 통합 케이스: 매출액 → 영업비용 + 영업이익 직접 연결
        add_link(0, 3, sga,       "rgba(239,68,68,0.35)")   # 영업비용
        add_link(0, 4, op_income, "rgba(16,185,129,0.35)")  # 영업이익
    else:
        # 일반 케이스: 매출액 → 매출원가, 매출총이익
        add_link(0, 1, cogs,  "rgba(239,68,68,0.35)")    # 빨강
        add_link(0, 2, gross, "rgba(16,185,129,0.35)")   # 초록

        # 매출총이익 → 판관비, 영업이익
        add_link(2, 3, sga,        "rgba(239,68,68,0.35)")
        add_link(2, 4, op_income,  "rgba(16,185,129,0.35)")

    # 영업이익 + 금융·기타이익 → 순이익 경로
    add_link(4, 5, fin_inc,    "rgba(59,130,246,0.35)")   # 금융수익 입력
    add_link(4, 6, fin_exp,    "rgba(239,68,68,0.35)")    # 금융비용 지출
    add_link(4, 7, other_inc,  "rgba(59,130,246,0.35)")   # 기타이익 입력
    add_link(4, 8, other_exp,  "rgba(239,68,68,0.35)")    # 기타비용 지출
    add_link(4, 9, tax,        "rgba(107,114,128,0.35)")  # 법인세
    add_link(4, 10, net_income,"rgba(16,185,129,0.45)")   # 순이익

    # 금융수익, 기타이익 → 순이익 보조
    if fin_inc > 0 and net_income > 0:
        add_link(5, 10, min(fin_inc, net_income * 0.3), "rgba(16,185,129,0.25)")
    if other_inc > 0 and net_income > 0:
        add_link(7, 10, min(other_inc, net_income * 0.1), "rgba(16,185,129,0.25)")

    # x/y 위치 (0~1)
    node_x = [0.01, 0.25, 0.25, 0.50, 0.50, 0.70, 0.70, 0.70, 0.70, 0.88, 0.95]
    node_y = [0.50, 0.80, 0.30, 0.65, 0.25, 0.10, 0.40, 0.20, 0.55, 0.70, 0.25]

    fig = go.Figure(data=[go.Sankey(
        arrangement="snap",
        node=dict(
            pad=18,
            thickness=22,
            line=dict(color="white", width=0.8),
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
            hovertemplate="흐름: %{value:,.0f} 백만원<extra></extra>",
        ),
    )])

    fig.update_layout(
        title=dict(
            text=f"{corp_name} ({stock_code})  {year}년  손익 흐름도",
            font=dict(size=15, family="Pretendard, Apple SD Gothic Neo, sans-serif"),
            x=0.5,
        ),
        font=dict(
            family="Pretendard, Apple SD Gothic Neo, Segoe UI, sans-serif",
            size=11,
            color="#1e293b",
        ),
        paper_bgcolor="#F8FAFC",
        plot_bgcolor="#F8FAFC",
        height=520,
        margin=dict(l=20, r=20, t=60, b=20),
    )

    # HTML 저장
    out_path = OUT_DIR / f"{stock_code}_sankey.html"
    fig.write_html(
        str(out_path),
        include_plotlyjs="cdn",
        config={"displayModeBar": False, "responsive": True},
        full_html=True,
    )
    print(f"  [{stock_code}] 저장 완료 → {out_path.name}")


def main():
    codes = sys.argv[1:] if len(sys.argv) > 1 else DEMO_3
    print(f"\n{'='*55}")
    print(f"  build_sankey.py  대상 {len(codes)}종목")
    print(f"  출력: {OUT_DIR}")
    print(f"{'='*55}")
    for code in codes:
        build_sankey(code.strip())
    print(f"\n완료.")


if __name__ == "__main__":
    main()
