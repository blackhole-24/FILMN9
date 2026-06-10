# -*- coding: utf-8 -*-
"""DART 사업보고서 RAG 챗봇 — 기술문서 PDF 생성 (가치평가 기술문서 포맷 준용).

embedding/chatbot/ 실제 소스·파라미터를 근거로 작성(추측 배제).
실행: python embedding/chatbot/eval/make_techdoc.py
출력: C:/Users/Admin/Desktop/DART_RAG_챗봇_기술문서.pdf
"""
from __future__ import annotations
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
                                PageBreak, Preformatted)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

OUT = Path(r"C:\Users\Admin\Desktop\DART_RAG_챗봇_기술문서.pdf")
HEADER = "DART 사업보고서 RAG 챗봇 기술문서 (v1)"

pdfmetrics.registerFont(TTFont("Malgun", r"C:\Windows\Fonts\malgun.ttf"))
pdfmetrics.registerFont(TTFont("MalgunB", r"C:\Windows\Fonts\malgunbd.ttf"))
# 흐름도는 한글이 섞이므로 한글 글리프가 있는 Malgun 사용(Consola는 라틴 전용 → 한글 깨짐)
MONO = "Malgun"

ss = getSampleStyleSheet()
NAVY = colors.HexColor("#1f3a5f")
TITLE = ParagraphStyle("TITLE", parent=ss["Title"], fontName="MalgunB", fontSize=22, leading=28, textColor=NAVY)
SUBT = ParagraphStyle("SUBT", parent=ss["Normal"], fontName="Malgun", fontSize=12, leading=18, alignment=1)
H1 = ParagraphStyle("H1", parent=ss["Heading1"], fontName="MalgunB", fontSize=15, leading=20,
                    spaceBefore=14, spaceAfter=8, textColor=NAVY)
H2 = ParagraphStyle("H2", parent=ss["Heading2"], fontName="MalgunB", fontSize=11.5, leading=16,
                    spaceBefore=9, spaceAfter=4, textColor=colors.HexColor("#274060"))
BODY = ParagraphStyle("BODY", parent=ss["Normal"], fontName="Malgun", fontSize=9.5, leading=15, spaceAfter=5)
BUL = ParagraphStyle("BUL", parent=BODY, leftIndent=10, bulletIndent=2, spaceAfter=2)
CODE = ParagraphStyle("CODE", parent=ss["Normal"], fontName=MONO, fontSize=8.5, leading=12.5,
                      textColor=colors.HexColor("#1a1a1a"), backColor=colors.HexColor("#f3f5f8"),
                      borderPadding=6, spaceBefore=3, spaceAfter=6)
CELL = ParagraphStyle("CELL", parent=ss["Normal"], fontName="Malgun", fontSize=8, leading=11)
CELLB = ParagraphStyle("CELLB", parent=CELL, fontName="MalgunB", textColor=colors.white)


def P(t): return Paragraph(t, BODY)
def H(t): return Paragraph(t, H1)
def S(t): return Paragraph(t, H2)
def BL(items): return [Paragraph("• " + x, BUL) for x in items]
def CB(t): return Preformatted(t, CODE)
def SP(h=4): return Spacer(1, h)


def TBL(rows, widths):
    data = [[Paragraph(c, CELLB) for c in rows[0]]] + [[Paragraph(c, CELL) for c in r] for r in rows[1:]]
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f7fa")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def _page(canvas, doc):
    canvas.saveState()
    canvas.setFont("Malgun", 7.5)
    canvas.setFillColor(colors.HexColor("#888888"))
    canvas.drawString(14 * mm, 287 * mm, HEADER)
    canvas.drawCentredString(105 * mm, 8 * mm, f"— {doc.page} —")
    canvas.setStrokeColor(colors.HexColor("#cccccc"))
    canvas.line(14 * mm, 285 * mm, 196 * mm, 285 * mm)
    canvas.restoreState()


def build():
    e = []
    # ───────────────────────── 표지 ─────────────────────────
    e += [SP(120), Paragraph("DART 사업보고서 RAG 챗봇", TITLE), SP(6),
          Paragraph("기술문서 — 전체 파이프라인 분석", SUBT), SP(4),
          Paragraph("Korean DART Report Retrieval-Augmented Chatbot", SUBT), SP(4),
          Paragraph("2026-06 · v1 · embedding/chatbot/", SUBT),
          PageBreak()]

    # ───────────────────────── 0. 개관 ─────────────────────────
    e += [H("0. 시스템 개관")]
    e += [S("0.1 이 시스템은 무엇을 하는가")]
    e += [P("본 시스템은 한국 상장기업의 <b>DART 사업보고서·분기보고서</b>를 근거로 자연어 질문에 답하는 "
            "검색증강생성(RAG, Retrieval-Augmented Generation) 챗봇이다. 사용자가 회사와 질문을 입력하면 "
            "(예: \"삼성전자 2025년 매출액\", \"에이피알 주요 사업\"), 시스템은 해당 회사 보고서의 관련 청크를 "
            "검색해 그 근거 위에서만 답을 생성하고, 답변 하단에 <b>DART 원문 출처</b>를 함께 제시한다.")]
    e += BL([
        "<b>근거 기반 답변</b> — LLM의 사전지식이 아니라, 검색된 보고서 청크에 적힌 사실만으로 답한다.",
        "<b>출처 투명성</b> — 어느 회사·연도·보고서종류(사업/1분기)의 어느 섹션인지 표기하고 DART로 딥링크한다.",
        "<b>NO-MOCK</b> — 근거 없는 수치·단위·내용을 만들어내지 않는다. 없으면 '찾을 수 없음'으로 정직 처리한다.",
    ])
    e += [P("핵심 가치는 <b>정확도와 정직성</b>이다. 단일 LLM이 그럴듯하게 지어내는(hallucination) 위험을 "
            "검색 근거·출처·NO-MOCK 원칙으로 차단하고, 답하지 못할 때는 그렇다고 말한다.")]

    e += [S("0.2 전체 처리 흐름 (End-to-End)")]
    e += [CB(
        "[사용자 입력]  회사명/종목코드 + 질문  (예: \"현대차 2026 1분기 영업이익\")\n"
        "      │\n      ▼\n"
        "[1] 질의 분석(LLM)   회사·연도·기간·intent + Multi-Query·HyDE\n"
        "      │\n      ▼\n"
        "[2] 회사 해석        별칭·구명·영문명 → 공식 ticker\n"
        "      │\n      ▼\n"
        "[3] 온톨로지 확장     개념 트리거 → 연관어·커버리지\n"
        "      │\n      ▼\n"
        "[4] 하이브리드 검색   BGE-M3 벡터 + BM25  (ticker·report_kind 필터)\n"
        "      │\n      ▼\n"
        "[5] RRF 융합         여러 랭킹 리스트 → 후보 풀(16)\n"
        "      │\n      ▼\n"
        "[6] 재랭킹           bge-reranker-v2-m3 + 빈표(stub) 강등\n"
        "      │\n      ▼\n"
        "[7] 재무제표 라우팅   P&L 질의 시 손익계산서 결정적 편입(다부문사)\n"
        "      │\n      ▼\n"
        "[8] 단위 동반        분할 재무청크에 단위 머리글 형제 부착\n"
        "      │\n      ▼\n"
        "[9] 답변 생성(LLM)   reasoning=high · 빈응답 medium 폴백\n"
        "      │\n      ▼\n"
        "[답변 + 출처]       평문 답변 + 보고서종류/연도 + DART 섹션 딥링크")]

    e += [S("0.3 설계를 관통하는 원칙")]
    e += BL([
        "<b>① NO-MOCK(근거 우선)</b> — 검색 청크에 없는 수치·단위·항목은 생성 금지. 회사별로 단위가 다르므로"
        "(삼성전자=백만원, POSCO홀딩스=원) 단위를 추정하지 않고, 없으면 '(단위 미확인)'으로 표기한다.",
        "<b>② 재임베딩 없는 개선</b> — 190만+ 청크를 다시 임베딩하지 않고도 검색 품질을 올린다(BM25 하이브리드, "
        "재무제표 라우팅, 단위 형제 동반 등은 모두 질의 시점 로직).",
        "<b>③ 회사 해석이 정확도의 출발점</b> — DB가 전 종목 통합이라, 회사를 잘못 잡으면 모든 게 틀린다. "
        "별칭·구명·영문명을 강건하게 해석한다.",
        "<b>④ Graceful degrade</b> — 재랭커·BM25·딥링크·온톨로지는 실패해도 전체가 멈추지 않고 기본 동작으로 폴백한다.",
        "<b>⑤ 정확도 우선 트레이드오프</b> — reasoning=high로 표 독해·수치 추출을 극대화한다(응답이 느려지는 비용 감수).",
    ])

    e += [S("0.4 데이터·모델 출처")]
    e += [TBL([
        ["구분", "사용 기술 / 출처", "역할"],
        ["원천 데이터", "DART OpenAPI (사업보고서·분기보고서)", "전 종목 보고서 본문·표"],
        ["벡터 임베딩", "BAAI/bge-m3 (1024차원, 다국어)", "청크·질의의 의미 벡터화"],
        ["재랭커", "BAAI/bge-reranker-v2-m3 (cross-encoder)", "후보 정밀 재정렬"],
        ["키워드 검색", "인라인 BM25 (외부 의존 없음)", "정확 용어 recall 보강"],
        ["생성 LLM", "OpenAI gpt-5.4-mini (reasoning=high)", "질의 분석 + 답변 생성"],
        ["벡터 DB", "ChromaDB (PersistentClient)", "청크·벡터·메타 영구 저장"],
    ], [30 * mm, 78 * mm, 74 * mm])]

    e += [S("0.5 이 문서를 읽는 방법")]
    e += [P("1~9장은 사용자 질문이 답변이 되기까지의 파이프라인을 순서대로 따라간다. 각 장은 "
            "<b>(개념 → 왜 필요한가 → 어떻게 구현했는가)</b> 순으로 설명한다. 10~12장은 데이터 계층·API·평가를, "
            "13장은 주요 설계 결정의 이유를, 부록은 전체 파라미터·트러블슈팅 이력·한계를 정리한다. "
            "모든 파라미터는 chatbot/config.py 실제 값이다."), PageBreak()]

    # ───────────────────────── 1. 회사 해석 ─────────────────────────
    e += [H("1. 사용자 입력과 회사 해석")]
    e += [S("1.1 왜 회사 해석이 먼저인가")]
    e += [P("ChromaDB에는 전 종목(코스피·코스닥) 보고서가 한 컬렉션(annual_reports)에 통합돼 있다. 따라서 "
            "회사(ticker) 메타필터 없이 검색하면 엉뚱한 회사 청크가 섞인다. 회사 해석은 정확도의 출발점이며, "
            "사용자가 약칭·구명·영문명 어떤 형태로 불러도 같은 회사로 수렴시켜야 한다.")]
    e += [S("1.2 정규화·별칭·퍼지매칭 — company_index.py")]
    e += BL([
        "<b>정규화</b> — 공백·기호 제거, 영문 대소문자 통일, 주식종류 접미사 제거(보통주/우선주 등).",
        "<b>별칭 사전(_ALIASES)</b> — 통칭→공식명 매핑(현대차→현대자동차, 네이버→NAVER, 하이닉스→에스케이하이닉스, "
        "삼전→삼성전자, 포스코→POSCO홀딩스, 한전→한국전력 등).",
        "<b>퍼지매칭</b> — rapidfuzz 점수 기반, FUZZY_MIN_SCORE=70 미만이면 '회사 못 찾음'으로 처리하고 후보를 되묻는다.",
        "<b>부분문자열 확정(_unique_containment)</b> — 질의가 단 하나의 회사명에만 부분 포함되면 확정"
        "(현대중공업 → 에이치디현대중공업).",
        "<b>엔티티 접미사 가드</b> — 증권/홀딩스/지주/금융/생명/화재/카드/은행 등 접미사로 '현대차'⊂'현대차증권' "
        "같은 오매칭을 차단.",
    ])
    e += [P("해석 실패 시에는 추측하지 않고 후보 최대 MAX_CANDIDATES=5개를 사용자에게 되묻는다(needs_clarification). "
            "해석된 정식명은 이후 검색·생성에 일관 주입되어, 청크의 '당사/회사'를 그 회사로 간주하게 한다.")]

    # ───────────────────────── 2. 질의 분석 ─────────────────────────
    e += [H("2. 질의 분석과 쿼리 변환")]
    e += [S("2.1 왜 질문을 그대로 검색하지 않는가")]
    e += [P("사용자 질문은 구어체이고 보고서 문체와 다르다(\"작년에 얼마 벌었어?\" vs \"매출액\"). 또 한 번의 "
            "벡터검색은 표현 차이에 취약하다. 그래서 LLM(gpt-5.4-mini)이 질문을 한 번에 분석·변환한다 — query_analyzer.py.")]
    e += [S("2.2 구조화 추출 + 다중 쿼리 생성")]
    e += [P("단일 LLM 호출로 다음을 동시에 산출한다(비용 효율):")]
    e += BL([
        "<b>company / company_aliases</b> — 질문 속 회사(원문 그대로) + 동의 표기들.",
        "<b>year / period</b> — 회계연도 + 보고서 종류(annual·q1·q2·h1·q3). '작년·최근' 등 상대표현을 기준연도로 환산.",
        "<b>intent</b> — 질문 의도 라벨(사업개요·재무실적·주식수·신용등급 등).",
        "<b>search_query</b> — 회사명을 뺀, 보고서에 나올 법한 검색 최적화 핵심 질의.",
        "<b>query_variants (Multi-Query)</b> — 의미는 같되 표현이 다른 변형 N개(N_QUERY_VARIANTS=2). 표현 누락 보완.",
        "<b>hypothetical_answer (HyDE)</b> — 사업보고서 문체의 가상 답변 1~2문장. 가상답변을 쿼리로 써서 정답 청크와의 "
        "의미 거리를 좁힌다.",
    ])
    e += [P("실제 검색에 쓰는 쿼리 묶음 = [핵심질의] + [변형들] + [HyDE] (+ 3장 온톨로지 확장어), "
            "MAX_TOTAL_QUERIES=9로 상한을 둔다.")]
    e += [S("2.3 기간·보고서 라우팅 (report_kind)")]
    e += [P("\"2026년 1분기\"는 분기보고서, \"2025 사업보고서\"는 연간으로 가야 한다. period를 메타필터 "
            "report_kind(예: '2026-q1')로 변환해, 분기 질의가 연간 표를 끌어오는 혼선을 막는다. "
            "(연간은 백업 임베딩 호환을 위해 year로 필터 — 부록 참조)"), PageBreak()]

    # ───────────────────────── 3. 온톨로지 ─────────────────────────
    e += [H("3. 온톨로지 기반 질의 확장")]
    e += [S("3.1 어휘 불일치 문제")]
    e += [P("사용자는 \"우발부채\"라 묻지만 보고서는 \"지급보증·채무보증·담보제공·계류 중 소송\"으로 적는다. "
            "벡터검색만으로는 이 어휘 격차를 다 메우기 어렵다. ontology_b.py가 도메인 개념을 연관어로 확장한다.")]
    e += [S("3.2 개념·트리거·연관어·커버리지")]
    e += BL([
        "<b>개념 28종</b> — ontology_b.json. 각 개념은 트리거(사용자 표현)·연관어(검색 확장어)·구성요소(커버리지 체크리스트)·"
        "scope(broad/narrow)를 가진다.",
        "<b>has_part 합집합</b> — 광의 질문(우발부채)은 하위 개념(지급보증·담보·약정)을 모두 커버하도록 확장.",
        "<b>커버리지 체크리스트</b> — 개념의 구성요소를 LLM 프롬프트에 주입해, 넓은 질문에서 일부 항목만 답하고 누락하는 "
        "것을 방지.",
    ])
    e += [S("3.3 Grounding — 과적합 방지")]
    e += [P("연관어·회계용어는 전부 VAR 코퍼스 문서빈도(doc-freq) ≥ 5를 통과한 것만 채택한다. 실제 보고서에 자주 "
            "나오는 표현만 확장에 쓰여, 특정 사례에 과적합되지 않는다. config: ENABLE_ONTOLOGY=True, ONTOLOGY_MAX_TERMS=6.")]

    # ───────────────────────── 4. 검색 ─────────────────────────
    e += [H("4. 검색 — 하이브리드 리트리벌")]
    e += [S("4.1 벡터 검색 (BGE-M3)")]
    e += [P("모든 쿼리를 1회 배치로 임베딩(BAAI/bge-m3, 1024차원)한 뒤 ChromaDB 멀티쿼리 1회 호출로 "
            "쿼리별 상위 RECALL_TOP_K=12 청크를 가져온다. 메타필터(ticker, report_kind/year)로 대상 회사·보고서를 좁힌다.")]
    e += [S("4.2 BM25 키워드 검색 (인라인 하이브리드)")]
    e += [P("벡터검색만으로는 \"영업이익·수주총액\" 같은 정확 용어가 흩어진 표에서 안정적으로 안 잡힌다. 종목 "
            "메타필터가 걸려 대상이 보통 수천 청크 이하이므로, 매 질의 즉석 BM25 색인(외부 의존성 없음)을 만들어 "
            "키워드 정확매칭 랭킹을 추가한다. config: ENABLE_HYBRID_BM25=True, BM25_TOP_N=30.")]
    e += [S("4.3 RRF 융합")]
    e += [P("벡터(쿼리별)·BM25·재무제표 후보 등 여러 랭킹 리스트를 <b>Reciprocal Rank Fusion</b>으로 합친다: "
            "RRF score = Σ 1/(k + rank), RRF_K=60. 순위 기반이라 서로 다른 점수 척도를 안전하게 결합하고, "
            "여러 신호에서 공통으로 상위인 청크를 끌어올린다. 융합 후 상위 RERANK_POOL=16을 재랭킹 대상으로 넘긴다.")]

    # ───────────────────────── 5. 재랭킹 ─────────────────────────
    e += [H("5. 재랭킹 (Cross-Encoder)")]
    e += [S("5.1 원리 — bi-encoder vs cross-encoder")]
    e += [P("임베딩(bi-encoder)은 질문과 청크를 따로 벡터화해 거리만 잰다. 재랭커(cross-encoder, "
            "bge-reranker-v2-m3)는 (질문, 청크) 쌍을 함께 입력받아 관련성을 직접 채점한다. 1단계에서 넓게 "
            "가져온 후보를 2단계에서 정밀 재정렬해 정확도를 끌어올린다(RERANKER_MAX_LEN=1024).")]
    e += [S("5.2 확장 인지 재랭킹")]
    e += [P("[원본 질문] + [온톨로지 개념어]로 각각 채점한 뒤 청크별 최고점을 쓴다(RERANK_MAX_QUERIES=3). "
            "단어 중심 질문(\"우발부채\")이 끌어온 동의 청크(지급보증·담보)가 재랭킹에서 살아남게 한다.")]
    e += [S("5.3 빈 표(stub) 강등")]
    e += [P("값 없이 헤더·라벨만 있는 빈 표는 답변에 무용하다. '짧고(STUB_TABLE_MAX_CHARS=80) 숫자가 거의 없는"
            "(STUB_MIN_DIGITS=3)' table 청크를 stub으로 보고 재랭킹 점수를 STUB_PENALTY=5.0 강등해, 값 있는 표가 "
            "위로 오게 한다. 값 있는 짧은 표나 긴 정성표는 보존한다.")]
    e += [PageBreak()]

    # ───────────────────────── 6. 재무제표 라우팅 ─────────────────────────
    e += [H("6. 재무제표 라우팅 (다부문사 손익계산서 보정)")]
    e += [S("6.1 문제 — 매출실적 표가 손익계산서를 가린다")]
    e += [P("정유·화학·지주처럼 사업부문이 많은 회사는 'II.사업의 내용 &gt; 매출 및 수주상황·주요 제품'이 품목별로 "
            "수십 건(실측: SK이노베이션 2026 1분기 <b>62건</b>)으로 쪼개진다. \"매출액·영업이익\" 질의에서 이 매출실적 "
            "표가 검색 상위를 독점해, 정작 답이 든 손익계산서(III.재무 &gt; 요약재무정보·연결재무제표) 청크가 후보에 "
            "못 들었다. DB 직접 조회로 데이터는 존재함을 확인 — 순수 검색 랭킹 문제였다.")]
    e += [S("6.2 해법 — 구조 기반 결정적 라우팅 (과적합 배제)")]
    e += [P("특정 회사가 통과하도록 가중치를 튜닝하지 않는다. 대신 <b>모든 DART 보고서가 공유하는 보편적 섹션 "
            "스키마</b>를 이용한다 — 손익계산서는 항상 'III. 재무에 관한 사항'에 있다. P&L 지표 질의"
            "(매출액·영업이익·순이익 등)를 감지하면:")]
    e += BL([
        "<b>① 손익 청크 직접 추출</b> — 종목 코퍼스에서 재무제표 섹션(요약재무정보·연결재무제표·재무제표, 주석 제외) 중 "
        "실제로 손익 라인아이템이 든 청크를 BM25로 골라 후보에 강제 편입(FINSTMT_FETCH_N=8).",
        "<b>② 점유 섹션 캡</b> — 매출실적·주요제품 표가 후보 풀을 독점하지 못하게 상한(FINSTMT_FLOOD_CAP=8).",
        "<b>③ 재랭킹 후 강제 포함</b> — 재랭커가 매출실적 표를 위로 올려도, 손익 청크를 최종 컨텍스트에 보장 "
        "포함(FINSTMT_RESERVE=3).",
    ])
    e += [S("6.3 검증 — 6개 업종 일반화")]
    e += [P("정유·화학·전자·식품·철강·중공업 6개 업종 전부에서 손익계산서 청크가 후보에 진입함을 확인했다(검색레벨 6/6). "
            "SK이노베이션은 이전엔 '영업이익 확인 불가'였으나, 수정 후 매출액·영업이익을 단위까지 정확히 답한다. "
            "특정 회사 튜닝이 아닌 구조 기반이라 과적합이 아니다.")]

    # ───────────────────────── 7. 단위 동반 ─────────────────────────
    e += [H("7. 단위 머리글 동반 (unit-sibling)")]
    e += [P("긴 재무제표가 청킹으로 분할되면 '(단위:백만원)' 머리글이 데이터 청크에서 떨어져 나간다. reasoning=high는 "
            "단위를 확신 못 하면 정직하게 '(단위 미확인)'으로 표기한다(추정 금지). 이를 보완하기 위해, 단위 라벨을 "
            "잃은 재무 청크에 대해 같은 명세서의 직전 형제(seq-1..6) 중 '(단위:백만원|천원|억원|원)' + 명세서 제목을 "
            "가진 머리글 청크를 찾아 컨텍스트에 함께 넣는다. <b>데이터를 바꾸지 않으므로 NO-MOCK 안전</b>"
            "(ENABLE_UNIT_SIBLING=True). 회사마다 단위가 다르므로(백만원·천원·원) 일괄 패치 대신 원문 머리글을 "
            "동반하는 방식을 택했다.")]

    # ───────────────────────── 8. 답변 생성 ─────────────────────────
    e += [H("8. 답변 생성 (llm_client.py)")]
    e += [S("8.1 시스템 프롬프트 규칙")]
    e += BL([
        "검색된 청크에 근거해서만 답하고, 없으면 '찾을 수 없음'. 단 회사명 표기 차이만으로 없다고 하지 않는다.",
        "표·목록형 데이터(보증·주식수·소송·재무·배당)는 관련 항목을 빠짐없이 수치와 함께 구체적으로.",
        "모든 금액에 단위 표기. 단위 미상이면 '(단위 미확인)'. 백만원·천원은 1,000배 차이이므로 추정 금지.",
        "마크다운 기호 금지(평문). 수치 언급 시 어느 보고서·연도 기준인지 밝히고, 연간/분기 혼선 방지.",
    ])
    e += [S("8.2 reasoning=high + 토큰 상한")]
    e += [P("표 독해·수치 추출 누락을 최소화하기 위해 reasoning_effort='high'로 생성한다. 추론+출력 토큰을 공유하므로 "
            "MAX_COMPLETION_TOKENS=16000으로 장문 답변 잘림을 막는다. chat_create()는 모델이 미지원하는 파라미터"
            "(temperature 등)를 만나면 그 파라미터만 빼고 재시도해 모델 교체 호환성을 확보한다.")]
    e += [S("8.3 빈 응답 자동 복구 (3단계)")]
    e += [P("reasoning=high는 드물게 출력 0토큰(빈 응답)을 내는 산발 현상이 있다(토큰 소진이 아님 — 실측 확인). "
            "이를 '빈 답변'으로 두면 데모에 치명적이라, 3단계 자동 복구를 둔다: high로 1차→2차 재시도, 그래도 비면 "
            "최후에 medium으로 1회 폴백. 평소엔 high를 유지한다. 스트리밍도 토큰이 하나도 안 나오면 논스트리밍으로 폴백한다.")]

    # ───────────────────────── 9. 출처 ─────────────────────────
    e += [H("9. 출처와 DART 딥링크")]
    e += [P("답변 하단에 출처를 회사·연도·보고서종류(2026 1분기보고서/2025 사업보고서)·섹션으로 표기한다. "
            "dart_links.py가 보고서 목차(TOC)를 1회 가져와 캐싱(dart_toc_cache.json)하고 섹션을 매칭해, 출처 클릭 시 "
            "DART 뷰어의 해당 섹션으로 바로 점프한다(ENABLE_DART_DEEPLINK=True, 실패 시 보고서 첫 화면으로 폴백)."),
          PageBreak()]

    # ───────────────────────── 10. 데이터 계층 ─────────────────────────
    e += [H("10. 데이터 계층 — 수집 · 청킹 · 임베딩")]
    e += [S("10.1 수집 (phaseA_collect.py)")]
    e += [P("DART OpenAPI로 전 종목의 2025 사업보고서 + 2026 1분기보고서 원문(document.xml)을 내려받는다. "
            "회사코드(corpcode.xml)로 종목↔법인코드를 매핑하고, 진행상황을 저장해 재개 가능하게 한다.")]
    e += [S("10.2 청킹 (dc_chunker.py)")]
    e += [P("XML을 정제(dc_xml_cleaner)한 뒤 섹션 경로(section_path_str)를 보존하며 청크로 자른다(CHAR_LIMIT=1500). "
            "표는 마크다운 표로 변환해 행·열 구조를 살린다(전치표 포함). 각 청크 메타에 ticker·corp_name·year·"
            "report_kind·report_nm·section_path_str·kind(table/text) 등을 부여한다.")]
    e += [S("10.3 임베딩 + 저장 (phaseB_embed.py, ChromaDB)")]
    e += [P("청크 본문을 BAAI/bge-m3(1024차원)로 임베딩해 ChromaDB(PersistentClient, 컬렉션 annual_reports)에 "
            "본문·벡터·메타와 함께 upsert한다. 현재 약 <b>377만+ 청크</b>(2025 사업보고서 + 2026 1분기 통합). "
            "런타임 챗봇은 이 컬렉션만 읽으면 동작한다.")]
    e += [S("10.4 자동 업데이트")]
    e += [P("auto_update(.py/.bat) + 작업 스케줄러로 신규 DART 보고서를 주기적으로 수집·임베딩해 컬렉션을 갱신한다.")]

    # ───────────────────────── 11. API/UI ─────────────────────────
    e += [H("11. API · UI")]
    e += [P("FastAPI 백엔드(api.py): GET /health(DB·디바이스), GET /companies(회사 해석/자동완성), POST /chat"
            "(논스트리밍 {answer, sources, meta}), POST /chat/stream(SSE 토큰 스트리밍), POST /session/reset. "
            "서버 부팅 시 임베더·재랭커·회사인덱스를 워밍업해 첫 질의 콜드스타트를 제거한다. 프론트는 단일 HTML"
            "(static/index.html)로 SSE 스트리밍·출처 뱃지·DART 링크를 표시한다. 세션은 최근 SESSION_MAX_TURNS=12턴 보관.")]

    # ───────────────────────── 12. 평가 ─────────────────────────
    e += [H("12. 평가 — 정확도 검증")]
    e += [S("12.1 골든셋 (NO-MOCK)")]
    e += BL([
        "<b>대기업 표본</b> — 대형주 다업종(삼성전자 등 검증 수치 포함).",
        "<b>층화 표본</b> — KOSPI 상장주식수 4분위 + KOSDAQ 소속부 4등급의 중소형주 — 대형주 과적합 방지.",
        "<b>산업 표본</b> — 코스피·코스닥 각 6개 세분 산업 × 대표 2종목 — 업종 전반 일반화 검증.",
    ])
    e += [S("12.2 채점기 (run_eval.py)")]
    e += [P("각 질문의 expect 조건만 평가한다: found(거부 아님), keywords(필수어 포함), numbers(검증 수치 — 조/억 "
            "재포맷 관용 매칭), numeric(숫자 존재), report_contains(보고서 라벨), unit_ok(단위 표기 + '단위 미확인' "
            "없음). 모든 골든 수치는 실제 보고서에서 확인된 것만 쓴다(NO-MOCK).")]
    e += [S("12.3 과적합 방지")]
    e += [P("특정 대형주(특히 삼성전자)에 맞춰 고치면 과적합된다는 점을 경계해, 생소한 중소형주 층화표본과 "
            "전 업종 산업표본으로 일반화를 교차검증한다. 보고서는 종목·질문·결과·시간·정확도와 함께 <b>문항별로 "
            "LLM이 생성한 쿼리·챗봇 답변·정답 라벨</b>을 함께 수록해 추적성을 높인다.")]

    # ───────────────────────── 13. 설계 결정 ─────────────────────────
    e += [H("13. 설계 결정과 그 이유")]
    e += [TBL([
        ["결정", "이유"],
        ["전 종목 단일 컬렉션 + ticker 필터", "보고서가 방대해 회사별 분리 관리보다 통합 후 메타필터가 단순·견고."],
        ["하이브리드(BM25+벡터)", "재무 숫자 질의는 정확 용어 매칭이 중요 — 벡터 단독은 recall 불안정."],
        ["재임베딩 대신 질의시 로직", "377만 청크 재임베딩은 비싸고 위험. 라우팅·단위동반은 질의시점에 해결."],
        ["구조 기반 재무 라우팅", "가중치 튜닝은 과적합. DART 보편 섹션 구조는 전 회사 공통이라 일반화."],
        ["reasoning=high 기본", "표 독해·수치 정확도 우선. 단위 미상은 정직하게 미확인 표기(NO-MOCK)."],
        ["빈응답 medium 폴백", "high의 산발적 빈응답을 재시도로 복구, 최후에만 medium(품질 저하 최소화)."],
    ], [52 * mm, 130 * mm])]
    e += [PageBreak()]

    # ───────────────────────── 부록 ─────────────────────────
    e += [H("부록 A. 전체 파라미터 총람 (chatbot/config.py)")]
    e += [TBL([
        ["파라미터", "값", "의미"],
        ["OPENAI_MODEL / ANALYZER", "gpt-5.4-mini", "생성·분석 LLM"],
        ["OPENAI_TEMPERATURE", "0.1", "사실 기반(미지원 시 자동 폴백)"],
        ["MAX_COMPLETION_TOKENS", "16000", "추론+출력 토큰 상한(장문 잘림 방지)"],
        ["OPENAI_TIMEOUT_S", "300", "high 응답 지연 대비"],
        ["RECALL_TOP_K", "12", "쿼리별 1단계 recall"],
        ["RERANK_POOL", "16", "재랭킹 대상 후보 상한"],
        ["FINAL_TOP_K", "12", "최종 컨텍스트 청크 수"],
        ["RRF_K", "60", "RRF 상수(작을수록 상위 가중)"],
        ["ENABLE_HYBRID_BM25 / BM25_TOP_N", "True / 30", "키워드 하이브리드"],
        ["ENABLE_FINSTMT_ROUTING", "True", "재무제표 결정적 라우팅"],
        ["FINSTMT_FETCH_N / RESERVE / FLOOD_CAP", "8 / 3 / 8", "손익청크 추출·보장·점유캡"],
        ["ENABLE_UNIT_SIBLING", "True", "단위 머리글 동반"],
        ["MULTI_QUERY / N_VARIANTS / HYDE", "True / 2 / True", "쿼리 변환"],
        ["ENABLE_ONTOLOGY / MAX_TERMS / MAX_TOTAL_Q", "True / 6 / 9", "온톨로지 확장"],
        ["RERANK / EXPANSION / MAX_QUERIES", "True / True / 3", "재랭킹"],
        ["STUB_DEMOTE(MAX_CHARS/MIN_DIGITS/PENALTY)", "True(80/3/5.0)", "빈 표 강등"],
        ["MAX_CONTEXT_CHARS", "16000", "LLM 컨텍스트 예산"],
        ["FUZZY_MIN_SCORE / MAX_CANDIDATES", "70 / 5", "회사 해석"],
        ["EMBEDDING_MODEL / DIM", "bge-m3 / 1024", "임베딩"],
        ["COLLECTION_NAME", "annual_reports", "ChromaDB 컬렉션"],
    ], [70 * mm, 36 * mm, 76 * mm])]

    e += [H("부록 B. 트러블슈팅 이력 (실제 해결 사례)")]
    e += [TBL([
        ["증상", "원인", "해결"],
        ["1분기 질의가 연간 표를 끌어옴", "기간 라우팅 부재", "period→report_kind 메타필터"],
        ["재무 숫자 recall 불안정", "벡터 단독 한계", "인라인 BM25 하이브리드 + RRF"],
        ["장문 답변 중간 잘림", "토큰 상한 미설정", "MAX_COMPLETION_TOKENS=16000"],
        ["산발적 빈 응답", "reasoning=high 산발(토큰소진 아님)", "high 재시도 → medium 폴백"],
        ["다부문사 영업이익 못 찾음", "매출실적 표가 손익계산서 가림", "재무제표 결정적 라우팅(6장)"],
        ["원(元)단위 '단위 미확인'", "단위동반이 백만원/천원만 인식", "_UNIT_ANY_RE에 원·억원 추가"],
        ["평가 중 네이티브 세그폴트", "chromadb/torch 산발 크래시", "문항별 저장 + 자동 재개 러너"],
    ], [50 * mm, 64 * mm, 68 * mm])]

    e += [H("부록 C. 한계와 주의")]
    e += BL([
        "<b>단위 표기</b> — 일부 보고서(특히 원단위 다부문사, 예: POSCO홀딩스)는 손익청크에 단위 머리글이 멀거나 "
        "없어 '단위 미확인'이 남을 수 있다. 추정하지 않는 NO-MOCK의 정직성 비용이며, 근본 해결은 소스 청킹 재처리.",
        "<b>응답 속도</b> — reasoning=high라 복잡 질문은 수십~수백 초가 걸린다(정확도 우선 트레이드오프).",
        "<b>전치표</b> — 행이 항목, 열이 구분인 복잡 표는 넓은 질문에서 얕게 읽힐 수 있다(커버리지 주입으로 대부분 보완).",
        "<b>수치 정합</b> — 보고서 자체가 MD&A·요약재무에 서로 다른 기준 수치를 담으면, 드물게 답변에 두 값이 함께 "
        "나올 수 있다(원문 근거 표기로 추적 가능).",
    ])
    e += [SP(8), P("<i>본 기술문서는 embedding/chatbot/ 원본 소스코드와 config.py 실제 값을 직접 근거로 작성되었다. "
                   "모든 파라미터·로직·해결 사례는 코드와 실측 검증에서 확인한 것이며 추측을 배제했다. 처음 접하는 "
                   "독자도 데이터 흐름(질문→회사해석→질의분석→온톨로지→검색→융합→재랭킹→재무라우팅→단위동반→생성→"
                   "출처)을 따라가며 각 단계의 목적과 근거를 이해할 수 있도록 구성했다.</i>")]

    SimpleDocTemplate(str(OUT), pagesize=A4, topMargin=20 * mm, bottomMargin=16 * mm,
                      leftMargin=16 * mm, rightMargin=14 * mm).build(e, onFirstPage=_page, onLaterPages=_page)
    print("PDF 생성:", OUT)


if __name__ == "__main__":
    build()
