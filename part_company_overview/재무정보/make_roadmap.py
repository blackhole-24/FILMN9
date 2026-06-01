"""
기업개요 파트 — 개발 단계 로드맵 PDF 생성기
run: python make_roadmap.py
output: outputs/part_company_overview_개발로드맵.pdf
"""

from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph,
    Spacer, HRFlowable, KeepTogether
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os

# ── 폰트 등록 (Windows 맑은 고딕) ─────────────────────────────────────────────
_FONT_PATHS = [
    r"C:\Windows\Fonts\malgun.ttf",
    r"C:\Windows\Fonts\NanumGothic.ttf",
    r"C:\Windows\Fonts\gulim.ttc",
]
_FONT_NAME = "Korean"
for fp in _FONT_PATHS:
    if os.path.exists(fp):
        pdfmetrics.registerFont(TTFont(_FONT_NAME, fp))
        break
else:
    # fallback: Helvetica (영문만)
    _FONT_NAME = "Helvetica"

# ── 색상 ────────────────────────────────────────────────────────────────────
C_NAVY    = colors.HexColor("#0A1628")
C_BLUE    = colors.HexColor("#1E3A5F")
C_ORANGE  = colors.HexColor("#F97316")
C_GREEN   = colors.HexColor("#10B981")
C_RED     = colors.HexColor("#EF4444")
C_GRAY    = colors.HexColor("#64748B")
C_LGRAY   = colors.HexColor("#F1F5F9")
C_WHITE   = colors.white
C_DONE    = colors.HexColor("#D1FAE5")  # 완료 배경
C_WIP     = colors.HexColor("#FEF3C7")  # 진행중 배경
C_TODO    = colors.HexColor("#FEE2E2")  # 미완 배경

# ── 스타일 ───────────────────────────────────────────────────────────────────
def style(name, parent="Normal", **kw):
    if "fontName" not in kw:
        kw["fontName"] = _FONT_NAME
    return ParagraphStyle(name, **kw)

ST_TITLE   = style("Title",   fontSize=20, textColor=C_WHITE, spaceAfter=4, leading=26)
ST_SUB     = style("Sub",     fontSize=11, textColor=colors.HexColor("#94A3B8"), spaceAfter=0, leading=14)
ST_H1      = style("H1",      fontSize=13, textColor=C_NAVY, spaceBefore=10, spaceAfter=4, leading=18)
ST_H2      = style("H2",      fontSize=11, textColor=C_BLUE, spaceBefore=6,  spaceAfter=3, leading=15)
ST_BODY    = style("Body",    fontSize=9,  textColor=colors.HexColor("#1E293B"), leading=13, spaceAfter=2)
ST_CODE    = style("Code",    fontSize=8,  textColor=colors.HexColor("#1E293B"), fontName="Courier", leading=12)
ST_SMALL   = style("Small",   fontSize=8,  textColor=C_GRAY, leading=11)
ST_TBL_HDR = style("TblHdr",  fontSize=9,  textColor=C_WHITE, leading=12)
ST_TBL_CELL= style("TblCell", fontSize=8,  textColor=colors.HexColor("#1E293B"), leading=12)

def P(text, st=None):
    return Paragraph(text, st or ST_BODY)

def CODE(text):
    return Paragraph(text, ST_CODE)

def SP(h=6):
    return Spacer(1, h)

def HR():
    return HRFlowable(width="100%", thickness=1, color=C_LGRAY, spaceAfter=6)

# ── 헤더 배너 ────────────────────────────────────────────────────────────────
def make_header():
    data = [[
        Paragraph("FILMN9 기업개요 파트", ST_TITLE),
        Paragraph("개발 단계 로드맵 v1.0", ST_TITLE),
    ], [
        Paragraph("데이터 소스 → 추출 → HTML 표시 → 임베딩 파이프라인", ST_SUB),
        Paragraph("2026-05-18  |  아모레퍼시픽(090430) POC 기준", ST_SUB),
    ]]
    t = Table(data, colWidths=[9*cm, 9*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), C_NAVY),
        ("ROUNDEDCORNERS", [8]),
        ("TOPPADDING",    (0,0), (-1,-1), 10),
        ("BOTTOMPADDING", (0,0), (-1,-1), 10),
        ("LEFTPADDING",   (0,0), (-1,-1), 16),
        ("RIGHTPADDING",  (0,0), (-1,-1), 16),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
    ]))
    return t

# ── 범례 테이블 ───────────────────────────────────────────────────────────────
def make_legend():
    data = [["범례:", "[완료]", "[진행중]", "[예정]"]]
    t = Table(data, colWidths=[2*cm, 3*cm, 3*cm, 3*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (1,0), (1,0), C_DONE),
        ("BACKGROUND", (2,0), (2,0), C_WIP),
        ("BACKGROUND", (3,0), (3,0), C_TODO),
        ("FONTNAME",   (0,0), (-1,-1), _FONT_NAME),
        ("FONTSIZE",   (0,0), (-1,-1), 8),
        ("ALIGN",      (0,0), (-1,-1), "CENTER"),
        ("VALIGN",     (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (-1,-1), 4),
        ("BOTTOMPADDING",(0,0),(-1,-1), 4),
        ("BOX",        (0,0), (-1,-1), 0.5, C_GRAY),
        ("INNERGRID",  (0,0), (-1,-1), 0.3, C_GRAY),
    ]))
    return t

# ── 섹션 제목 ────────────────────────────────────────────────────────────────
def section_title(phase_num, title, subtitle=""):
    color_map = {1: C_NAVY, 2: C_BLUE, 3: colors.HexColor("#1D4ED8"),
                 4: colors.HexColor("#7C3AED"), 5: colors.HexColor("#0F766E")}
    bg = color_map.get(phase_num, C_NAVY)
    items = [[
        Paragraph(f"PHASE {phase_num}", style("pn", fontSize=9, textColor=C_ORANGE, leading=12)),
        Paragraph(title, style("ptitle", fontSize=12, textColor=C_WHITE, leading=16)),
    ]]
    if subtitle:
        items.append([
            Paragraph("", ST_SMALL),
            Paragraph(subtitle, style("psub", fontSize=9, textColor=colors.HexColor("#94A3B8"), leading=12)),
        ])
    t = Table(items, colWidths=[2*cm, 16*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), bg),
        ("SPAN",       (0,1), (-1,1)) if subtitle else ("NOP",(0,0),(0,0)),
        ("TOPPADDING", (0,0), (-1,-1), 8),
        ("BOTTOMPADDING",(0,0),(-1,-1), 8),
        ("LEFTPADDING",  (0,0), (-1,-1), 12),
        ("RIGHTPADDING", (0,0), (-1,-1), 12),
        ("ROUNDEDCORNERS", [6]),
    ]))
    return t

# ── 데이터 흐름 테이블 ────────────────────────────────────────────────────────
def flow_table(rows, col_widths=None):
    """rows: list of [컬럼1, ...] — 첫 행이 헤더"""
    if col_widths is None:
        n = len(rows[0])
        w = 18*cm / n
        col_widths = [w] * n
    header = [Paragraph(str(c), ST_TBL_HDR) for c in rows[0]]
    body   = [[Paragraph(str(c), ST_TBL_CELL) for c in row] for row in rows[1:]]
    data   = [header] + body
    t = Table(data, colWidths=col_widths)
    style_cmds = [
        ("BACKGROUND", (0,0), (-1,0), C_BLUE),
        ("FONTNAME",   (0,0), (-1,-1), _FONT_NAME),
        ("FONTSIZE",   (0,0), (-1,0),  9),
        ("FONTSIZE",   (0,1), (-1,-1), 8),
        ("VALIGN",     (0,0), (-1,-1), "TOP"),
        ("TOPPADDING", (0,0), (-1,-1), 5),
        ("BOTTOMPADDING",(0,0),(-1,-1), 5),
        ("LEFTPADDING",  (0,0), (-1,-1), 6),
        ("RIGHTPADDING", (0,0), (-1,-1), 6),
        ("INNERGRID",  (0,0), (-1,-1), 0.3, C_GRAY),
        ("BOX",        (0,0), (-1,-1), 0.5, C_BLUE),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [C_WHITE, C_LGRAY]),
    ]
    # 완료/진행/예정 셀 배경
    for r_idx, row in enumerate(body, start=1):
        for c_idx, cell in enumerate(rows[r_idx]):
            cell_str = str(cell)
            if "[완료]" in cell_str:
                style_cmds.append(("BACKGROUND", (c_idx, r_idx), (c_idx, r_idx), C_DONE))
            elif "[진행중]" in cell_str:
                style_cmds.append(("BACKGROUND", (c_idx, r_idx), (c_idx, r_idx), C_WIP))
            elif "[예정]" in cell_str:
                style_cmds.append(("BACKGROUND", (c_idx, r_idx), (c_idx, r_idx), C_TODO))
    t.setStyle(TableStyle(style_cmds))
    return t

# ── PDF 빌드 ─────────────────────────────────────────────────────────────────

def build():
    out = Path(__file__).parent / "outputs" / "part_company_overview_개발로드맵.pdf"
    out.parent.mkdir(exist_ok=True)

    doc = SimpleDocTemplate(
        str(out),
        pagesize=A4,
        leftMargin=1.5*cm, rightMargin=1.5*cm,
        topMargin=1.5*cm,  bottomMargin=1.5*cm,
        title="FILMN9 기업개요 파트 개발 로드맵",
        author="FILMN9 Team",
    )

    story = []

    # ── 헤더 ────────────────────────────────────────────────────────────────
    story.append(make_header())
    story.append(SP(8))
    story.append(make_legend())
    story.append(SP(12))

    # ════════════════════════════════════════════════════════════════════════
    # PHASE 1 — 아키텍처 개요
    # ════════════════════════════════════════════════════════════════════════
    story.append(section_title(1, "아키텍처 개요 & 파일 구조",
                               "기업개요 파트 전체 데이터 흐름"))
    story.append(SP(6))

    arch_rows = [
        ["계층",         "파일 경로",                                          "역할",                   "상태"],
        ["데이터 소스",   "data/RAG/{종목코드}_*_annual_chunks.jsonl",           "사업보고서 JSONL 청크 저장소 (2,596개)", "[완료]"],
        ["설정",         "src/app_config.py",                                  "경로·API키·섹션 경로 상수 정의",         "[완료]"],
        ["JSONL 로더",   "src/collectors/jsonl_loader.py",                     "섹션 필터링 + 테이블 병합",              "[완료]"],
        ["재무 파서",    "src/processors/financial_parser.py",                  "마크다운 표 → DataFrame 변환",          "[완료]"],
        ["비율 계산기",  "src/processors/ratio_calculator.py",                  "부채비율 등 5개 재무비율",               "[완료]"],
        ["데이터 집계",  "src/processors/data_aggregator.py",                   "전체 데이터 통합 딕셔너리",              "[완료]"],
        ["HTML 빌더",    "src/components/html_builder.py",                     "Plotly.js 차트 + 테이블 HTML 생성",     "[완료]"],
        ["배치 저장",    "batch_save.py",                                       "2,596개 기업 배치 처리",                "[예정]"],
        ["리포트 생성",  "generate_report.py",                                  "단일 기업 HTML 리포트 출력",             "[완료]"],
    ]
    story.append(flow_table(arch_rows,
                            col_widths=[3*cm, 5.5*cm, 6.5*cm, 3*cm]))
    story.append(SP(10))

    # ── 데이터 흐름 화살표 다이어그램 ──────────────────────────────────────────
    story.append(P("전체 데이터 흐름", ST_H2))
    flow_diag = [
        ["JSONL 파일\n(data/RAG/)", "→", "jsonl_loader\nget_section()", "→", "financial_parser\nget_financial_detail()", "→", "html_builder\nbuild_html()", "→", "report.html\n(브라우저 출력)"],
    ]
    t_flow = Table(flow_diag, colWidths=[2.5*cm,0.8*cm,2.5*cm,0.8*cm,3.5*cm,0.8*cm,2.5*cm,0.8*cm,2.8*cm])
    t_flow.setStyle(TableStyle([
        ("BACKGROUND", (0,0),(0,0), C_NAVY),
        ("BACKGROUND", (2,0),(2,0), C_BLUE),
        ("BACKGROUND", (4,0),(4,0), C_BLUE),
        ("BACKGROUND", (6,0),(6,0), C_BLUE),
        ("BACKGROUND", (8,0),(8,0), C_GREEN),
        ("FONTNAME",   (0,0),(-1,-1), _FONT_NAME),
        ("FONTSIZE",   (0,0),(-1,-1), 8),
        ("TEXTCOLOR",  (0,0),(0,0),  C_WHITE),
        ("TEXTCOLOR",  (2,0),(2,0),  C_WHITE),
        ("TEXTCOLOR",  (4,0),(4,0),  C_WHITE),
        ("TEXTCOLOR",  (6,0),(6,0),  C_WHITE),
        ("TEXTCOLOR",  (8,0),(8,0),  C_WHITE),
        ("TEXTCOLOR",  (1,0),(1,0),  C_ORANGE),
        ("TEXTCOLOR",  (3,0),(3,0),  C_ORANGE),
        ("TEXTCOLOR",  (5,0),(5,0),  C_ORANGE),
        ("TEXTCOLOR",  (7,0),(7,0),  C_ORANGE),
        ("ALIGN",      (0,0),(-1,-1), "CENTER"),
        ("VALIGN",     (0,0),(-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0),(-1,-1), 8),
        ("BOTTOMPADDING",(0,0),(-1,-1), 8),
        ("FONTSIZE",   (1,0),(1,0), 14),
        ("FONTSIZE",   (3,0),(3,0), 14),
        ("FONTSIZE",   (5,0),(5,0), 14),
        ("FONTSIZE",   (7,0),(7,0), 14),
    ]))
    story.append(t_flow)
    story.append(SP(12))

    # ════════════════════════════════════════════════════════════════════════
    # PHASE 2 — JSONL 섹션 경로 매핑
    # ════════════════════════════════════════════════════════════════════════
    story.append(section_title(2, "JSONL 섹션 경로 매핑",
                               "app_config.py SECTION 딕셔너리 → section_path_str 필터"))
    story.append(SP(6))

    section_rows = [
        ["컴포넌트 (HTML)",      "SECTION 키",   "section_path_str (JSONL 내 경로)",                              "단위",    "상태"],
        ["재무 하이라이트 카드\n(컴포넌트 ②)",
         "요약재무정보",
         "III. 재무에 관한 사항 > 1. 요약재무정보",
         "백만원\n(원본 백만)",
         "[완료]"],
        ["재무정보 상세 탭\n포괄손익계산서(연결)\n(컴포넌트 ③)",
         "연결재무제표",
         "III. 재무에 관한 사항 > 2. 연결재무제표",
         "원 → 백만원\n(÷1,000,000)",
         "[완료]"],
        ["재무정보 상세 탭\n재무상태표(연결)\n(컴포넌트 ③)",
         "연결재무제표",
         "III. 재무에 관한 사항 > 2. 연결재무제표",
         "원 → 백만원\n(÷1,000,000)",
         "[완료]"],
        ["주주 구성\n(컴포넌트 ⑤)",
         "주주정보",
         "VII. 주주에 관한 사항",
         "-",
         "[예정]"],
        ["경영인 테이블\n(컴포넌트 ⑦)",
         "임원현황",
         "VIII. 임원 및 직원 등에 관한 사항\n> 1. 임원 및 직원 등의 현황",
         "-",
         "[완료]"],
    ]
    story.append(flow_table(section_rows,
                            col_widths=[3.5*cm, 2.5*cm, 6*cm, 2*cm, 2*cm]))
    story.append(SP(8))

    story.append(P("핵심 코드: app_config.py — SECTION 딕셔너리 (L72-78)", ST_H2))
    story.append(CODE(
        'SECTION = {<br/>'
        '&nbsp;&nbsp;"요약재무정보" : "III. 재무에 관한 사항 &gt; 1. 요약재무정보",<br/>'
        '&nbsp;&nbsp;"연결재무제표" : "III. 재무에 관한 사항 &gt; 2. 연결재무제표",<br/>'
        '&nbsp;&nbsp;"별도재무제표" : "III. 재무에 관한 사항 &gt; 4. 재무제표",<br/>'
        '&nbsp;&nbsp;"주주정보"     : "VII. 주주에 관한 사항",           # 2026-05-18 추가<br/>'
        '&nbsp;&nbsp;"임원현황"     : "VIII. 임원 및 직원 등 &gt; 1. 임원 및 직원 등의 현황",<br/>'
        '}'
    ))
    story.append(SP(12))

    # ════════════════════════════════════════════════════════════════════════
    # PHASE 3 — 데이터 추출 로직 (파일별 줄번호)
    # ════════════════════════════════════════════════════════════════════════
    story.append(section_title(3, "데이터 추출 로직 — 파일별 핵심 변경 이력",
                               "financial_parser.py 중심 파이프라인"))
    story.append(SP(6))

    change_rows = [
        ["파일",                          "함수/위치",                         "변경 내용",                                                   "상태"],
        ["src/app_config.py\nL11",
         "ROOT_DIR 경로",
         "parent.parent → parent.parent.parent.parent\n(git mv 후 4단계 상위 폴더)",
         "[완료]"],
        ["src/app_config.py\nL72-78",
         "SECTION 딕셔너리",
         '"주주정보": "VII. 주주에 관한 사항" 추가',
         "[완료]"],
        ["src/processors/\nfinancial_parser.py\nL406-530",
         "get_financial_detail()",
         "parse_요약재무정보() 호출 → get_section(\"연결재무제표\") 직접 읽기\n"
         "+ _split_연결재무제표() 섹션 분리\n"
         "+ _build_period_year_map() 기수→연도 정확 변환\n"
         "→ 재무상태표(연결)/포괄손익계산서(연결) 원본 데이터 반환",
         "[완료]"],
        ["src/processors/\nratio_calculator.py\nL63",
         "calculate_ratios()\nfs_type 기본값",
         '"별도재무제표" → "재무상태표(연결)"',
         "[완료]"],
        ["src/components/\nhtml_builder.py\nL352",
         "_build_bar_chart()\nJS 단위 변환",
         "v>=1e4?(v/1e4) → v>=100?(v/100)\n(백만원 단위: 1억=100백만원)",
         "[완료]"],
        ["src/components/\nhtml_builder.py\nL373-375",
         "_build_detail_tab()\n탭 레이블",
         '"포괄손익계산서(연결)", "재무상태표(연결)" 키 정렬',
         "[완료]"],
        ["src/components/\nhtml_builder.py\nL538-600",
         "_build_executives()\n임원 테이블",
         "임원 5명 표시 + 접기/펼치기 버튼\n지분율 병합 표시",
         "[완료]"],
        ["src/processors/\nfinancial_parser.py\n(추가 예정)",
         "get_shareholder_table()",
         'get_section("주주정보") → 주주 DataFrame 파싱\nDART API 대신 JSONL 직접 활용',
         "[예정]"],
    ]
    story.append(flow_table(change_rows,
                            col_widths=[3.5*cm, 3*cm, 8*cm, 2*cm]))
    story.append(SP(10))

    # ── 연결재무제표 파싱 로직 상세 ────────────────────────────────────────────
    story.append(P("연결재무제표 파싱 로직 — financial_parser.py 핵심 함수 흐름", ST_H2))
    parse_rows = [
        ["단계", "함수",                          "입력",                          "출력",                          "비고"],
        ["1",   "get_section()\njsonl_loader.py", "stock_code,\n\"연결재무제표\"",  "병합된 표 1개\n(title=\"\", 200행)", "15청크 → 1 merged_text"],
        ["2",   "_split_연결재무제표()",            "merged_text\n(200행)",         "{'재무상태표(연결)': lines,\n'포괄손익계산서(연결)': lines, ...}",
         "단일셀행으로 섹션 분리"],
        ["3",   "_build_period_year_map()",        "섹션 lines",                   "{20: 2025, 19: 2024, 18: 2023}", "\"제 20기 2025.12.31\" 파싱"],
        ["4",   "_parse_detail_section()",         "섹션 lines +\nunit_divisor=1e6", "DataFrame\n(구분, 2025, 2024, 2023)", "원 → 백만원 변환"],
        ["5",   "get_financial_detail()",          "stock_code",                   "{'재무상태표(연결)': df,\n'포괄손익계산서(연결)': df}", "최종 반환 딕셔너리"],
    ]
    story.append(flow_table(parse_rows,
                            col_widths=[1*cm, 3.5*cm, 3.5*cm, 5*cm, 4*cm]))
    story.append(SP(12))

    # ════════════════════════════════════════════════════════════════════════
    # PHASE 4 — HTML 화면 표시 컴포넌트 맵
    # ════════════════════════════════════════════════════════════════════════
    story.append(section_title(4, "HTML 화면 표시 — 컴포넌트별 데이터 소스",
                               "html_builder.py 내부 빌더 함수 → 화면 영역 매핑"))
    story.append(SP(6))

    html_rows = [
        ["컴포넌트 번호", "HTML 영역",             "빌더 함수",              "data_aggregator 키",         "원 데이터 소스",                            "상태"],
        ["①",  "헤더 (주가)",        "_build_header()",       "price_info",            "yfinance API",                              "[완료]"],
        ["②",  "재무 하이라이트 카드", "_build_highlight()",    "highlight['연결']",     "요약재무정보 JSONL\n(1-1 연결)",             "[완료]"],
        ["③",  "재무정보 상세 탭",    "_build_detail_tabs()",  "detail",                "연결재무제표 JSONL\n(III>2 섹션)",           "[완료]"],
        ["④",  "재무비율 카드",       "_build_ratios()",       "ratios",                "ratio_calculator.py\n(재무상태표(연결) 계산)", "[완료]"],
        ["⑤",  "주주 구성 도넛차트",  "_build_shareholders()", "shareholders",          "DART API\n(get_major_shareholders)",         "[완료]"],
        ["⑥",  "최근 공시 목록",      "_build_disclosures()",  "disclosures",           "DART API\n(get_recent_disclosures)",         "[완료]"],
        ["⑦",  "경영인 테이블",       "_build_executives()",   "executives",            "임원현황 JSONL\n(VIII>1 섹션)",              "[완료]"],
        ["⑧",  "기업 현황 카드",      "_build_company()",      "company",               "DART API\n(get_company_info)",               "[완료]"],
        ["⑨",  "주가 히스토리 차트",  "_build_price_chart()",  "price_history",         "yfinance API",                              "[완료]"],
    ]
    story.append(flow_table(html_rows,
                            col_widths=[1.2*cm, 3*cm, 3.5*cm, 3*cm, 4*cm, 2.3*cm]))
    story.append(SP(10))

    # ── 수정된 핵심 JS 로직 ────────────────────────────────────────────────────
    story.append(P("html_builder.py — 바차트 단위 변환 로직 (L352 수정)", ST_H2))
    story.append(CODE(
        "// 백만원 단위 기준: 1억 = 100 백만원<br/>"
        "// 수정 전 (버그): v>=1e4 ? (v/1e4)+'억'  → 10,000백만원 이상만 억 표시<br/>"
        "// 수정 후 (정상): v>=100  ? (v/100)+'억'  → 100백만원(=1억) 이상이면 억 표시<br/>"
        "const fmt = v => v>=100 ? (v/100).toFixed(0)+'억' : v.toLocaleString()+'백만';"
    ))
    story.append(SP(12))

    # ════════════════════════════════════════════════════════════════════════
    # PHASE 5 — 임베딩 파이프라인
    # ════════════════════════════════════════════════════════════════════════
    story.append(section_title(5, "임베딩 파이프라인 — RAG 연동 설계",
                               "JSONL 청크 → 벡터 DB → 질의응답 파이프라인 (예정)"))
    story.append(SP(6))

    embed_rows = [
        ["단계",  "컴포넌트",              "입력",                    "처리",                             "출력",               "상태"],
        ["E-1",  "JSONL 청크 로더",        "data/RAG/*.jsonl",        "section_path_str 필터링\nkind='table'+'prose'",
         "청크 딕셔너리 리스트",          "[완료]"],
        ["E-2",  "텍스트 전처리",          "chunk['text']",           "마크다운 → 평문 변환\n메타데이터 추출",
         "정제된 텍스트 + 메타",          "[예정]"],
        ["E-3",  "임베딩 생성",            "청크 텍스트",             "OpenAI text-embedding-3-small\n또는 로컬 모델 (EXAONE)",
         "벡터 (1536-dim)",              "[예정]"],
        ["E-4",  "벡터 DB 저장",          "벡터 + 메타",             "ChromaDB / FAISS\n(stock_code, section, chunk_id 인덱스)",
         "영구 벡터 저장소",             "[예정]"],
        ["E-5",  "검색 API",             "질의문",                  "코사인 유사도 검색\nTop-K 청크 반환",
         "관련 청크 리스트",             "[예정]"],
        ["E-6",  "답변 생성",             "질의 + 컨텍스트 청크",   "Claude / GPT 프롬프트 완성\n재무 수치 정확도 검증",
         "자연어 답변",                  "[예정]"],
    ]
    story.append(flow_table(embed_rows,
                            col_widths=[1.2*cm, 3*cm, 3*cm, 4.5*cm, 3*cm, 2.3*cm]))
    story.append(SP(8))

    story.append(P("임베딩 전략 권장 사항", ST_H2))
    embed_notes = [
        ["항목",                  "권장 방향",                                                               "이유"],
        ["청크 단위",             "table 청크 1개 = 임베딩 1개 (merge 전 원본 청크 기준)",                 "표 분할 시 컨텍스트 단절 방지"],
        ["메타데이터 필드",       "stock_code, section_path_str, kind, rcept_no, char_len",               "필터링 검색 + 출처 추적"],
        ["우선 임베딩 섹션",      "요약재무정보, 연결재무제표, 임원현황, 주주정보",                          "기업개요 파트 핵심 데이터"],
        ["임베딩 모델",           "text-embedding-3-small (OpenAI) 또는 ko-sroberta-multitask (로컬)",     "한국어 재무 텍스트 최적화"],
        ["배치 처리",             "batch_save.py → outputs/cache/{stock_code}_data.json 저장 후 임베딩",  "DART API 속도 제한 우회"],
    ]
    story.append(flow_table(embed_notes,
                            col_widths=[3*cm, 9*cm, 6*cm]))
    story.append(SP(12))

    # ════════════════════════════════════════════════════════════════════════
    # PHASE 6 — 남은 작업 & 우선순위
    # ════════════════════════════════════════════════════════════════════════
    story.append(HR())
    story.append(P("남은 작업 & 우선순위 (기업개요 파트)", ST_H1))
    story.append(SP(4))

    todo_rows = [
        ["우선순위", "작업",                                        "파일",                        "세부 내용",                                  "상태"],
        ["HIGH",   "주주정보 JSONL 파서 추가",                    "financial_parser.py",          "get_shareholder_table() 구현\n사업보고서 VII 섹션 직접 파싱",  "[예정]"],
        ["HIGH",   "html_builder 재무현황 숫자 검증",             "html_builder.py",              "현금흐름표 현재 2025만 표시\n→ 3개년 모두 표시되도록 수정",  "[진행중]"],
        ["HIGH",   "GitHub commit & push",                       "전체 수정 파일",               "2026-05-18 수정분 커밋",                        "[진행중]"],
        ["MED",    "batch_save.py 완성",                         "batch_save.py",               "2,596개 기업 순차 처리\nJSONL+DART API 통합",  "[예정]"],
        ["MED",    "현금흐름표(연결) 헤더 파싱 수정",              "financial_parser.py",          "_build_period_year_map: 현금흐름 기간 형식\n'2025.01.01~2025.12.31' 패턴 추가",  "[예정]"],
        ["LOW",    "임베딩 파이프라인 설계",                       "embed_pipeline.py (신규)",    "ChromaDB 연동 + 검색 API",                      "[예정]"],
        ["LOW",    "다기업 테스트",                                "generate_report.py",          "top 10 시총 기업으로 검증",                      "[예정]"],
    ]
    story.append(flow_table(todo_rows,
                            col_widths=[1.5*cm, 4*cm, 3.5*cm, 6*cm, 2*cm]))
    story.append(SP(10))

    # ── 데이터 정확도 검증 기준 ───────────────────────────────────────────────
    story.append(HR())
    story.append(P("데이터 정확도 검증 기준 (아모레퍼시픽 090430, FY2025)", ST_H1))
    story.append(SP(4))

    verify_rows = [
        ["항목",               "DART 원본값 (2025 사업보고서)",     "코드 파싱값",          "단위",     "일치 여부"],
        ["매출액",             "4,252,820,221,496",               "4,252,820",          "백만원",   "[완료]"],
        ["영업이익",           "335,826,572,918",                 "335,827",            "백만원",   "[완료]"],
        ["당기순이익(연결)",    "320,021,135,977",                 "320,021",            "백만원",   "[완료]"],
        ["유동자산",           "2,003,730,249,566",               "2,003,730",          "백만원",   "[완료]"],
        ["부채총계",           "1,457,756 (백만원)",              "1,457,756",          "백만원",   "[완료]"],
        ["부채비율",           "-",                               "26.49%",             "%",        "[완료]"],
        ["DART 섹션",         "III. 재무에 관한 사항 > 2. 연결재무제표", "SECTION[\"연결재무제표\"]", "-", "[완료]"],
    ]
    story.append(flow_table(verify_rows,
                            col_widths=[3*cm, 5*cm, 3*cm, 2*cm, 4*cm]))

    story.append(SP(12))
    story.append(HR())
    story.append(P("문서 작성: FILMN9 기업개요 파트  |  2026-05-18  |  POC 기준 (아모레퍼시픽 090430)",
                   style("footer", fontSize=8, textColor=C_GRAY, alignment=1)))

    doc.build(story)
    print(f"[OK] 로드맵 PDF 생성: {out}")
    return out


if __name__ == "__main__":
    build()
