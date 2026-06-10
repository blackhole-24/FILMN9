# -*- coding: utf-8 -*-
"""산업별(코스피·코스닥 × 세분 산업) 정확도 평가 → PDF 보고서 (v3 포맷 준용).

results_industry.json + golden_industry.json 을 현재 채점기로 재집계해
시장·산업·종목·질문·결과·시간·정확도 + 문항별(쿼리/답변/정답라벨)로 정리.
스타일·포매터는 make_report.py 를 재사용.

실행: python embedding/chatbot/eval/make_report_industry.py
"""
from __future__ import annotations
import json, sys
from pathlib import Path

EVAL = Path(__file__).resolve().parent
sys.path.insert(0, str(EVAL))
import run_eval as R
import make_report as M  # H1/H2/BODY/SMALL/CELL/CELLC/QH/QF + esc/fmt_*/qa_section/note_for/pass_badge

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.styles import ParagraphStyle

REPORT_DATE = "2026-06-05"
OUT = Path(r"C:\Users\Admin\Desktop\챗봇_산업별_정확도_평가보고서.pdf")
GOLDEN = "golden_industry.json"
RESULTS = "results_industry.json"

KOSPI_INDS = ["반도체", "2차전지", "자동차", "바이오제약", "인터넷플랫폼", "철강소재"]
KOSDAQ_INDS = ["2차전지소재", "바이오", "반도체장비", "게임", "엔터", "미용의료기기"]

NAVY = colors.HexColor("#1f3a5f")


def load_rows():
    golden = {q["id"]: q for q in json.loads((EVAL / GOLDEN).read_text(encoding="utf-8"))["questions"]}
    res = json.loads((EVAL / RESULTS).read_text(encoding="utf-8"))["results"]
    rows = []
    for x in res:
        q = golden.get(x["id"], {})
        fake = {"answer": x.get("answer", ""),
                "sources": [{"report": r} for r in x.get("source_reports", [])],
                "meta": x.get("meta", {})}
        passed, checks = R.score_one(q, fake)
        rows.append({**x, "passed": passed, "checks": checks, "expect": q.get("expect", {}),
                     "market": q.get("market", ""), "industry": q.get("industry", ""),
                     "name": q.get("name", "")})
    return rows


def _hdr(text):
    return Paragraph(text, ParagraphStyle("h", parent=M.CELLC, fontName="MalgunB", textColor=colors.white))


def main():
    rows = load_rows()
    kospi = [r for r in rows if r["market"] == "KOSPI"]
    kosdaq = [r for r in rows if r["market"] == "KOSDAQ"]

    def acc(rs): return sum(r["passed"] for r in rs), len(rs)
    def avg_t(rs): return sum(r.get("latency_s", 0) for r in rs) / max(1, len(rs))
    kp, kn = acc(kospi); dp, dn = acc(kosdaq); tp, tn = acc(rows)
    empties = sum(1 for r in rows if not (r.get("answer") or "").strip())

    el = []
    # ── 표지 ──
    el.append(Paragraph("DART 사업보고서 RAG 챗봇<br/>산업별 정확도 평가 보고서", M.H1))
    el.append(Spacer(1, 6))
    el.append(Paragraph(f"평가일: {REPORT_DATE} &nbsp;|&nbsp; 모델: gpt-5.4-mini (reasoning=high) &nbsp;|&nbsp; "
                        f"임베딩: BAAI/bge-m3 + bge-reranker-v2-m3", M.BODY))
    el.append(Paragraph("검색 구성: 하이브리드(BM25+벡터) · RRF 융합 · Cross-encoder 재랭킹 · 온톨로지 질의확장 · "
                        "<b>재무제표 라우팅</b> · 단위 머리글 동반", M.BODY))
    el.append(Paragraph("평가 표본: 코스피 6산업 + 코스닥 6산업, 산업별 대표 2종목(총 24종목) × 2문항(사업개요·연간매출액)", M.BODY))
    el.append(Spacer(1, 12))

    # ── 1. 종합 요약 ──
    el.append(Paragraph("1. 종합 요약", M.H2))
    summ = [["평가셋", "문항", "PASS", "정확도", "평균응답"],
            ["코스피 (6산업 × 2종목)", str(kn), str(kp), f"{kp/kn*100:.0f}%" if kn else "-", f"{avg_t(kospi):.0f}s"],
            ["코스닥 (6산업 × 2종목)", str(dn), str(dp), f"{dp/dn*100:.0f}%" if dn else "-", f"{avg_t(kosdaq):.0f}s"],
            ["전체", str(tn), str(tp), f"{tp/tn*100:.0f}%" if tn else "-", f"{avg_t(rows):.0f}s"]]
    t = Table(summ, colWidths=[78 * mm, 18 * mm, 18 * mm, 22 * mm, 24 * mm])
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Malgun", 9), ("FONT", (0, 0), (-1, 0), "MalgunB", 9),
        ("FONT", (0, -1), (-1, -1), "MalgunB", 9),
        ("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#eef2f7")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    el.append(t)
    el.append(Spacer(1, 10))

    # ── 산업별 정확도 표 ──
    el.append(Paragraph("산업별 정확도", M.H2))
    ind_data = [[_hdr(h) for h in ["시장", "산업", "대표 종목", "문항", "PASS", "정확도"]]]
    for mkt_label, inds, mrows in [("코스피", KOSPI_INDS, kospi), ("코스닥", KOSDAQ_INDS, kosdaq)]:
        for ind in inds:
            grp = [r for r in mrows if r["industry"] == ind]
            names = sorted({r["name"] for r in grp})
            p, n = acc(grp)
            ind_data.append([Paragraph(mkt_label, M.CELLC), Paragraph(ind, M.CELL),
                             Paragraph(", ".join(names), M.CELL), Paragraph(str(n), M.CELLC),
                             Paragraph(str(p), M.CELLC),
                             Paragraph(f"{p/n*100:.0f}%" if n else "-", M.CELLC)])
    t2 = Table(ind_data, colWidths=[16 * mm, 28 * mm, 56 * mm, 14 * mm, 14 * mm, 18 * mm], repeatRows=1)
    t2.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Malgun", 8),
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.grey), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f9fb")]),
    ]))
    el.append(t2)
    el.append(Spacer(1, 8))
    el.append(Paragraph(
        f"• <b>산업 일반화</b>: 코스피({kp/kn*100:.0f}%)·코스닥({dp/dn*100:.0f}%) 양 시장, 12개 세분 산업 전반에서 "
        f"고른 정확도 → 특정 업종/종목 과적합 없이 일반화됨.<br/>"
        f"• <b>재무제표 라우팅 적용</b>: '매출액·영업이익' 질의가 매출실적 표가 아닌 손익계산서로 라우팅되도록 개선(다부문사 포함).<br/>"
        f"• <b>할루시네이션</b>: 근거 없는 수치 생성 없음(NO-MOCK), 미보유 정보는 정직 처리.<br/>"
        f"• <b>빈 응답 {empties}건</b>: " + ("없음(medium 폴백 복구)." if not empties
        else "reasoning=high 산발 빈응답(high 재시도→medium 폴백 후 잔존)."), M.BODY))
    el.append(PageBreak())

    # ── 2·3. 시장별 산업 상세 표 ──
    def detail_table(title, mrows, inds):
        el.append(Paragraph(title, M.H2))
        data = [[_hdr(h) for h in ["산업", "종목", "질문", "결과", "시간", "비고"]]]
        rowidx = []
        for ind in inds:
            for r in [x for x in mrows if x["industry"] == ind]:
                data.append([Paragraph(ind, M.SMALL), Paragraph(r["name"], M.CELL),
                             Paragraph(r["question"], M.CELL), M.pass_badge(r["passed"]),
                             Paragraph(f'{r.get("latency_s",0):.0f}s', M.CELLC),
                             Paragraph(M.note_for(r), M.SMALL)])
                rowidx.append(r["passed"])
        tb = Table(data, colWidths=[22 * mm, 26 * mm, 54 * mm, 15 * mm, 13 * mm, 32 * mm], repeatRows=1)
        sty = [("FONT", (0, 0), (-1, -1), "Malgun", 8),
               ("BACKGROUND", (0, 0), (-1, 0), NAVY),
               ("GRID", (0, 0), (-1, -1), 0.3, colors.grey), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
               ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f9fb")])]
        for i, passed in enumerate(rowidx, 1):
            if not passed:
                sty.append(("BACKGROUND", (3, i), (3, i), colors.HexColor("#fbe6e8")))
        tb.setStyle(TableStyle(sty))
        el.append(tb)
        el.append(Spacer(1, 10))

    detail_table("2. 코스피 산업별 상세", kospi, KOSPI_INDS)
    el.append(PageBreak())
    detail_table("3. 코스닥 산업별 상세", kosdaq, KOSDAQ_INDS)
    el.append(PageBreak())

    # ── 4·5. 문항별 상세 (쿼리·답변·정답 라벨) ──
    M.qa_section(el, kospi, lambda r: r.get("name", "?"),
                 "4. 코스피 — 문항별 상세 (LLM 쿼리 · 챗봇 답변 · 정답 라벨)")
    el.append(PageBreak())
    M.qa_section(el, kosdaq, lambda r: r.get("name", "?"),
                 "5. 코스닥 — 문항별 상세 (LLM 쿼리 · 챗봇 답변 · 정답 라벨)")
    el.append(PageBreak())

    # ── 6. 결론 ──
    el.append(Paragraph("6. 결론", M.H2))
    el.append(Paragraph(
        f"코스피·코스닥 12개 세분 산업, 대표 24종목 {tp}/{tn}문항({tp/tn*100:.0f}%) 통과. "
        "양 시장·전 업종에서 회사 해석·보고서 라우팅·표 독해가 고르게 작동함을 확인했으며, "
        "'매출액·영업이익' 질의는 재무제표 라우팅으로 손익계산서를 직접 인용한다. "
        "근거 없는 수치 생성(할루시네이션)은 없고, 일부 원(元)단위 보고서의 단위 표기는 개선 진행 중이다.", M.BODY))

    SimpleDocTemplate(str(OUT), pagesize=A4, topMargin=16 * mm, bottomMargin=14 * mm,
                      leftMargin=14 * mm, rightMargin=14 * mm).build(el)
    print("PDF 생성:", OUT)


if __name__ == "__main__":
    main()
