# -*- coding: utf-8 -*-
"""
FILMN9 시스템 아키텍처 → Excalidraw 스케치 버전 2개 생성
- LOCAL  : 로컬 호스트 버전
- AWS    : AWS 배포 버전

생성 파일:
- handover/FILMN9_시스템아키텍처_LOCAL.excalidraw
- handover/FILMN9_시스템아키텍처_AWS.excalidraw
"""
import json
import random
from pathlib import Path

random.seed(20260529)
_seed_counter = 1000


def next_seed():
    global _seed_counter
    _seed_counter += 1
    return _seed_counter


def base_elem(t, x, y, w, h, **extra):
    elem = {
        "id": f"elem_{next_seed()}",
        "type": t,
        "x": x, "y": y,
        "width": w, "height": h,
        "angle": 0,
        "strokeColor": "#1e1e1e",
        "backgroundColor": "transparent",
        "fillStyle": "solid",
        "strokeWidth": 2,
        "strokeStyle": "solid",
        "roughness": 2,
        "opacity": 100,
        "groupIds": [],
        "frameId": None,
        "roundness": None,
        "seed": next_seed(),
        "version": 1,
        "versionNonce": next_seed(),
        "isDeleted": False,
        "boundElements": [],
        "updated": 1,
        "link": None,
        "locked": False,
    }
    elem.update(extra)
    return elem


def rect(x, y, w, h, stroke="#1e1e1e", bg="transparent", roundness=True):
    e = base_elem("rectangle", x, y, w, h, strokeColor=stroke, backgroundColor=bg)
    if roundness:
        e["roundness"] = {"type": 3}
    return e


def ellipse(x, y, w, h, stroke="#1e1e1e", bg="transparent"):
    return base_elem("ellipse", x, y, w, h, strokeColor=stroke, backgroundColor=bg)


def text(x, y, w, h, content, size=16, color="#1e1e1e", align="center", bold=False, family=5):
    # family 5 = Excalifont (손글씨), 1 = Virgil, 2 = Helvetica, 3 = Cascadia
    return base_elem("text", x, y, w, h,
        text=content, originalText=content,
        fontSize=size, fontFamily=family,
        textAlign=align, verticalAlign="middle",
        strokeColor=color, baseline=int(size * 0.78),
        lineHeight=1.25,
    )


def arrow(x1, y1, x2, y2, stroke="#e03131", label=None):
    a = base_elem("arrow", min(x1, x2), min(y1, y2),
                  abs(x2 - x1), abs(y2 - y1),
                  strokeColor=stroke)
    a["points"] = [[0, 0], [x2 - x1, y2 - y1]]
    a["x"] = x1
    a["y"] = y1
    a["width"] = abs(x2 - x1) or 1
    a["height"] = abs(y2 - y1) or 1
    a["startBinding"] = None
    a["endBinding"] = None
    a["startArrowhead"] = None
    a["endArrowhead"] = "arrow"
    a["roundness"] = {"type": 2}
    return a


def section_box(elements, x, y, w, h, title, subtitle="", stroke="#c92a2a", bg="#fff5f5"):
    """섹션 박스 + 제목 라벨 (위에 걸친 형태)"""
    # 큰 박스
    elements.append(rect(x, y, w, h, stroke=stroke, bg=bg, roundness=True))
    # 제목 뱃지 (위쪽에 걸친)
    badge_w = max(len(title) * 11 + 30, 140)
    badge_x = x + (w - badge_w) / 2
    elements.append(rect(badge_x, y - 18, badge_w, 36, stroke=stroke, bg="#1864ab", roundness=True))
    elements.append(text(badge_x, y - 10, badge_w, 22, title, size=14, color="#ffffff", bold=True))
    if subtitle:
        elements.append(text(x, y + 14, w, 16, subtitle, size=10, color="#5c5c5c"))


def sub_box(elements, x, y, w, h, title, items, stroke="#1864ab", bg="#e7f5ff"):
    """내부 카드 박스 + 제목 + 항목 리스트"""
    elements.append(rect(x, y, w, h, stroke=stroke, bg=bg, roundness=True))
    elements.append(text(x + 6, y + 8, w - 12, 22, title, size=13, color=stroke, bold=True))
    items_text = "\n".join(items)
    elements.append(text(x + 6, y + 36, w - 12, h - 42, items_text, size=11, color="#2c2c2c"))


def cell_box(elements, x, y, w, h, label, stroke="#666", bg="#ffffff", color="#1e1e1e", size=11):
    elements.append(rect(x, y, w, h, stroke=stroke, bg=bg, roundness=True))
    elements.append(text(x + 4, y + (h - 16) / 2, w - 8, 16, label, size=size, color=color))


def cylinder(elements, x, y, w, h, title, sub, desc, stroke="#2f9e44", bg="#d3f9d8"):
    """DB 원통 형태 (상단 타원 + 본체 + 하단 타원)"""
    ellipse_h = 16
    elements.append(ellipse(x, y, w, ellipse_h, stroke=stroke, bg=bg))
    elements.append(rect(x, y + ellipse_h / 2, w, h - ellipse_h, stroke=stroke, bg=bg, roundness=False))
    elements.append(ellipse(x, y + h - ellipse_h, w, ellipse_h, stroke=stroke, bg=bg))
    # 라벨
    elements.append(text(x, y + h + 8, w, 18, title, size=13, color=stroke, bold=True))
    elements.append(text(x, y + h + 28, w, 16, sub, size=11, color="#1e1e1e"))
    elements.append(text(x, y + h + 46, w, 30, desc, size=10, color="#5c5c5c"))


# ─────────────────────────────────────────────────────────────────
# 공통 레이아웃 함수
# ─────────────────────────────────────────────────────────────────
def build_architecture(version="LOCAL"):
    """version: 'LOCAL' or 'AWS'"""
    is_aws = version == "AWS"

    elements = []

    # 컬러 팔레트
    if is_aws:
        PRIMARY = "#d97706"   # AWS 오렌지
        ACCENT = "#232F3E"    # AWS 다크
        BG_SOFT = "#fff7e6"
        BADGE_BG = "#232F3E"
    else:
        PRIMARY = "#c92a2a"   # 빨강
        ACCENT = "#1E3A8A"    # 인디고
        BG_SOFT = "#fff5f5"
        BADGE_BG = "#1864ab"

    # 캔버스 시작점
    x0, y0 = 80, 80

    # 제목
    title_txt = "FILMN9 시스템 아키텍처" + (" — AWS 배포 버전" if is_aws else " — 로컬 호스트 버전")
    elements.append(text(x0, y0, 900, 40, title_txt, size=28, color=ACCENT, bold=True))
    sub_txt = "KOSPI/KOSDAQ 2,695 상장사 AI 분석 플랫폼" + (" · S3 · EC2 · RDS" if is_aws else " · localhost:3000 / 8000")
    elements.append(text(x0, y0 + 44, 900, 22, sub_txt, size=14, color="#5c5c5c"))

    # ─── User 섹션 ───
    USER_X, USER_Y = x0, y0 + 100
    USER_W, USER_H = 200, 380
    section_box(elements, USER_X, USER_Y, USER_W, USER_H, "User", stroke=PRIMARY, bg=BG_SOFT)
    user_names = ["학생", "일반투자자", "중급 투자자"]
    for i, name in enumerate(user_names):
        cy = USER_Y + 50 + i * 90
        cell_box(elements, USER_X + 20, cy, USER_W - 40, 70,
                 f"👤  {name}", stroke=ACCENT, bg="#eef2ff", color=ACCENT, size=13)

    if is_aws:
        # AWS Edge/DNS 박스
        elements.append(rect(USER_X + 10, USER_Y + 320, USER_W - 20, 50,
                             stroke=PRIMARY, bg="#fff7e6", roundness=True))
        elements.append(text(USER_X, USER_Y + 326, USER_W, 18, "▼ EDGE / DNS", size=11, color=PRIMARY, bold=True))
        elements.append(text(USER_X, USER_Y + 346, USER_W, 16, "Route 53 · ACM · WAF", size=10, color="#5c5c5c"))

    # ─── Front-end 섹션 ───
    FE_X = USER_X + USER_W + 80
    FE_Y = USER_Y
    FE_W, FE_H = 320, 580
    fe_sub = "S3 + CloudFront" if is_aws else "Next.js 16 · Port 3000"
    section_box(elements, FE_X, FE_Y, FE_W, FE_H, "Front-end", subtitle=fe_sub, stroke=PRIMARY, bg=BG_SOFT)

    fe_screens = [
        ("🏠 메인 홈페이지", [
            "기업명 / 종목코드 검색",
            "산업 · 업종 검색",
            "모닝루틴 위젯 (환율, 원자재)",
            "산업별 대장주 리스트",
            "산업 사이클"
        ]),
        ("📋 Tab1 · 기업개요", [
            "히스토리 브리핑",
            "주가차트 + 거래량",
            "손익흐름도 · BS · IS",
            "경영인 · 주주구성 · 건전성",
            "최근 공시 · 공급계약",
            "DART 인앱 뷰어"
        ]),
        ("💰 Tab2 · 밸류에이션", [
            "Bear / Base / Bull 카드",
            "DCF 테이블 · WACC"
        ]),
        ("🤖 Tab3 · AI 종합분석", [
            "AI 종합분석",
            "AI 사업보고서 RAG 챗봇"
        ]),
    ]
    fe_y_cur = FE_Y + 50
    for title, items in fe_screens:
        h = 30 + len(items) * 16
        sub_box(elements, FE_X + 16, fe_y_cur, FE_W - 32, h,
                title, items, stroke=ACCENT, bg="#ffffff")
        fe_y_cur += h + 10

    # ─── Back-end 섹션 ───
    BE_X = FE_X + FE_W + 100
    BE_Y = FE_Y
    BE_W, BE_H = 760, 800
    be_sub = "EC2 + ALB · FastAPI" if is_aws else "FastAPI · Python 3.11 · Port 8000"
    section_box(elements, BE_X, BE_Y, BE_W, BE_H, "Back-end", subtitle=be_sub, stroke=PRIMARY, bg=BG_SOFT)

    # FastAPI 게이트웨이 기둥 (좌측 세로)
    elements.append(rect(BE_X + 20, BE_Y + 60, 60, 700,
                         stroke=ACCENT, bg="#1864ab" if not is_aws else "#232F3E", roundness=True))
    # 세로 텍스트 표현 (한 글자씩)
    gateway_label = "FastAPI 외부 I/F"
    for i, ch in enumerate(gateway_label):
        elements.append(text(BE_X + 30, BE_Y + 90 + i * 28, 40, 24, ch,
                             size=14, color="#ffffff", bold=True))

    # Routers 그룹
    R_X, R_Y, R_W = BE_X + 100, BE_Y + 70, BE_W - 130
    elements.append(rect(R_X, R_Y, R_W, 200, stroke=ACCENT, bg="#ffffff", roundness=True))
    elements.append(text(R_X, R_Y + 8, R_W, 18, "Routers — API 요청을 받는 입구",
                         size=12, color=ACCENT, bold=True))
    routers = [
        "/api/overview", "/api/financial_detail", "/api/ohlcv", "/api/health",
        "/api/shareholders", "/api/executives", "/api/disclosures", "/api/supply_contracts",
        "/api/valuation", "/api/sectors", "/api/morning", "/api/search",
        "/api/rag/chat", "/api/tab3/analysis", "/sankey/{code}", "/api/history",
    ]
    for i, r in enumerate(routers):
        col = i % 4
        row = i // 4
        cx = R_X + 12 + col * (R_W - 30) / 4
        cy = R_Y + 36 + row * 38
        cell_box(elements, cx, cy, (R_W - 30) / 4 - 6, 30, r,
                 stroke="#666", bg="#f1f3f5", color="#1e1e1e", size=10)

    # Services 그룹
    S_X, S_Y, S_W = R_X, R_Y + 220, R_W
    S_H = 290
    elements.append(rect(S_X, S_Y, S_W, S_H, stroke="#a61e4d", bg="#ffffff", roundness=True))
    elements.append(text(S_X, S_Y + 8, S_W, 18, "Services — 사용자 요청 처리 · 비즈니스 로직",
                         size=12, color="#a61e4d", bold=True))
    services = [
        "기업명 / 종목코드 검색", "산업 · 업종 분류 검색", "모닝루틴 시장지표 집계",
        "히스토리 브리핑 조회", "주가차트 + 거래량 응답", "재무상태표 / 손익계산서 응답",
        "손익흐름도 렌더", "경영인 / 주주 / 건전성 응답", "최근 공시 + DART 프록시",
        "단일판매ㆍ공급계약 조회", "밸류에이션 계산", "DCF · WACC 산출",
        "AI 종합분석", "AI 사업보고서 RAG 챗봇", "산업별 대장주 응답",
    ]
    for i, s in enumerate(services):
        col = i % 3
        row = i // 3
        cx = S_X + 12 + col * (S_W - 30) / 3
        cy = S_Y + 36 + row * 50
        cell_box(elements, cx, cy, (S_W - 30) / 3 - 6, 40, s,
                 stroke="#a61e4d", bg="#fff0f6", color="#a61e4d", size=11)

    # Repositories 그룹
    P_X, P_Y, P_W = R_X, S_Y + S_H + 10, R_W
    elements.append(rect(P_X, P_Y, P_W, 80, stroke="#2f9e44", bg="#ffffff", roundness=True))
    elements.append(text(P_X, P_Y + 8, P_W, 18, "Repositories — 데이터 접근 계층",
                         size=12, color="#2f9e44", bold=True))
    repos_label = "RDS PostgreSQL 조회" if is_aws else "SQLite 조회"
    repos = [repos_label, "MongoDB 조회", "Chroma 벡터 검색", "S3 파일 저장소"]
    for i, r in enumerate(repos):
        cx = P_X + 12 + i * (P_W - 30) / 4
        cy = P_Y + 36
        cell_box(elements, cx, cy, (P_W - 30) / 4 - 6, 32, r,
                 stroke="#2f9e44", bg="#d3f9d8", color="#2b8a3e", size=11)

    # AWS 인프라 (AWS 버전만)
    if is_aws:
        I_X, I_Y, I_W = R_X, P_Y + 100, R_W
        elements.append(rect(I_X, I_Y, I_W, 70, stroke=ACCENT, bg="#e7f0fe", roundness=True))
        elements.append(text(I_X, I_Y + 6, I_W, 18, "▼ AWS INFRASTRUCTURE",
                             size=11, color=ACCENT, bold=True))
        infras = ["VPC 10.0.0.0/16", "IAM Role", "Security Group 80·443·8000", "CloudWatch"]
        for i, r in enumerate(infras):
            cx = I_X + 12 + i * (I_W - 30) / 4
            cy = I_Y + 30
            cell_box(elements, cx, cy, (I_W - 30) / 4 - 6, 30, r,
                     stroke=ACCENT, bg="#ffffff", color=ACCENT, size=10)

    # ─── Data Platform 섹션 ───
    DP_X = BE_X + BE_W + 100
    DP_Y = BE_Y
    DP_W, DP_H = 280, 800
    dp_sub = "AWS RDS · S3 · Atlas · Chroma" if is_aws else "SQLite · Atlas · Chroma · S3"
    section_box(elements, DP_X, DP_Y, DP_W, DP_H, "Data Platform", subtitle=dp_sub, stroke=PRIMARY, bg=BG_SOFT)

    db_label = "AWS RDS PostgreSQL" if is_aws else "SQLite filmn9.db"
    dbs = [
        ("RELATIONAL DB", db_label,
         "financial_detail 625K\nohlcv · valuations\ncompany_info · shareholders"),
        ("DOCUMENT DB", "MongoDB Atlas",
         "filmn9.histories\n2,526 docs\n기업 히스토리 브리핑"),
        ("VECTOR DB", "Chroma · BGE-M3",
         "20 GB · RAG 검색용\n사업보고서 임베딩"),
        ("OBJECT STORAGE", "AWS S3" if is_aws else "S3 / 로컬",
         "XML 원본 6.9 GB\nJSONL 청크 2.7 GB\n손익흐름도 HTML"),
    ]
    dp_y_cur = DP_Y + 60
    for title, sub, desc in dbs:
        cylinder(elements, DP_X + 30, dp_y_cur, DP_W - 60, 60, title, sub, desc,
                 stroke="#2f9e44", bg="#d3f9d8")
        dp_y_cur += 200

    # ─── External API 섹션 ───
    EXT_X = USER_X
    EXT_Y = USER_Y + USER_H + 60
    EXT_W = FE_X + FE_W - USER_X
    EXT_H = 200
    section_box(elements, EXT_X, EXT_Y, EXT_W, EXT_H, "External API", stroke=PRIMARY, bg=BG_SOFT)

    ext_apis = [
        ("DART OpenAPI", "사업·감사보고서\n공시 · XML"),
        ("OpenAI API", "gpt-5-mini\n임베딩 · RAG"),
        ("yfinance / KRX", "한국 종가\n환율 · 원자재"),
        ("네이버 / 한경", "컨센서스\n적정주가"),
        ("WICS / KIND", "78개 업종\nticker_universe"),
    ]
    ext_cell_w = (EXT_W - 60) / 5
    for i, (b, d) in enumerate(ext_apis):
        cx = EXT_X + 20 + i * (ext_cell_w + 5)
        cy = EXT_Y + 50
        elements.append(rect(cx, cy, ext_cell_w, 110,
                             stroke=PRIMARY, bg="#ffffff", roundness=True))
        elements.append(text(cx, cy + 6, ext_cell_w, 20, b, size=12, color=PRIMARY, bold=True))
        elements.append(text(cx + 4, cy + 30, ext_cell_w - 8, 70, d, size=10, color="#1e1e1e"))

    # ─── 흐름 화살표 ───
    arrow_color = PRIMARY

    # User → Frontend
    a1 = arrow(USER_X + USER_W + 5, USER_Y + USER_H / 2,
               FE_X - 5, USER_Y + USER_H / 2, stroke=arrow_color)
    a1["startArrowhead"] = "arrow"
    a1["endArrowhead"] = "arrow"
    elements.append(a1)
    elements.append(text((USER_X + USER_W + FE_X) / 2 - 50, USER_Y + USER_H / 2 - 30,
                         100, 18, "요청 / 응답", size=11, color=arrow_color, bold=True))

    # Frontend → Backend
    a2 = arrow(FE_X + FE_W + 5, FE_Y + 250,
               BE_X - 5, FE_Y + 250, stroke=arrow_color)
    a2["startArrowhead"] = "arrow"
    a2["endArrowhead"] = "arrow"
    elements.append(a2)
    label2 = "REST API (ALB)" if is_aws else "REST API 호출"
    elements.append(text((FE_X + FE_W + BE_X) / 2 - 60, FE_Y + 220,
                         120, 18, label2, size=11, color=arrow_color, bold=True))

    # Backend → Data
    a3 = arrow(BE_X + BE_W + 5, BE_Y + 300,
               DP_X - 5, BE_Y + 300, stroke=arrow_color)
    a3["startArrowhead"] = "arrow"
    a3["endArrowhead"] = "arrow"
    elements.append(a3)
    elements.append(text((BE_X + BE_W + DP_X) / 2 - 50, BE_Y + 270,
                         100, 18, "조회 / 저장", size=11, color=arrow_color, bold=True))

    # External API → Backend (가로)
    a4 = arrow(EXT_X + EXT_W + 5, EXT_Y + EXT_H / 2,
               BE_X - 5, EXT_Y + EXT_H / 2, stroke=arrow_color)
    a4["endArrowhead"] = "arrow"
    elements.append(a4)
    label4 = "NAT Gateway → 외부" if is_aws else "외부 API 호출"
    elements.append(text((EXT_X + EXT_W + BE_X) / 2 - 70, EXT_Y + EXT_H / 2 - 30,
                         140, 18, label4, size=11, color=arrow_color, bold=True))

    return {
        "type": "excalidraw",
        "version": 2,
        "source": "https://excalidraw.com",
        "elements": elements,
        "appState": {
            "gridSize": None,
            "viewBackgroundColor": "#FAFAFB",
        },
        "files": {},
    }


# ─────────────────────────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────────────────────────
def main():
    out_dir = Path(r"C:\Users\Admin\FILMN9\handover")
    out_dir.mkdir(parents=True, exist_ok=True)

    for v, name in [("LOCAL", "FILMN9_시스템아키텍처_로컬"),
                    ("AWS", "FILMN9_시스템아키텍처_AWS")]:
        data = build_architecture(v)
        path = out_dir / f"{name}.excalidraw"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[OK] {path}  (요소 {len(data['elements'])}개)")


if __name__ == "__main__":
    main()
