# -*- coding: utf-8 -*-
"""신기능(1~3단계) 평가 → PDF 보고서 (산업별 보고서와 동일 v3 포맷).

results_features.json 을 단계별로 집계해 요약·단계별 상세표·문항별 상세(입력·답변·판정)로 정리.
스타일·포매터는 make_report.py 재사용.  실행: python embedding/chatbot/eval/make_report_features.py
"""
from __future__ import annotations
import json, sys
from pathlib import Path

EVAL = Path(__file__).resolve().parent
sys.path.insert(0, str(EVAL))
import make_report as M  # H1/H2/BODY/SMALL/CELL/CELLC/QH/QF + esc/fmt_answer/pass_badge

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, HRFlowable
from reportlab.lib.styles import ParagraphStyle

REPORT_DATE = "2026-06-05"
OUT = Path(r"C:\Users\Admin\Desktop\챗봇_신기능_평가보고서.pdf")
RESULTS = "results_features.json"
NAVY = colors.HexColor("#1f3a5f")
STAGES = ["1단계 지식폴백", "2단계 첨부 기본형", "3단계 첨부 확장"]


def _hdr(t):
    return Paragraph(t, ParagraphStyle("h", parent=M.CELLC, fontName="MalgunB", textColor=colors.white))


def fnote(r):
    m = r.get("meta") or {}
    bits = []
    if r["stage"].startswith("1"):
        if m.get("mode") == "general_knowledge":
            bits.append("일반지식 모드(⚠경고배지)")
        elif m.get("mode") is None:
            bits.append("정상 RAG(폴백 안함, 출처 %d건)" % r.get("sources_n", 0))
    else:
        if m.get("attach_kind"):
            bits.append("첨부:" + m["attach_kind"])
        if m.get("note"):
            bits.append(m["note"])
        if m.get("dart_compared"):
            bits.append("DART 대조✓")
    if not r["passed"]:
        bits.append("미충족")
    return " · ".join(bits) or "-"


def main():
    res = json.loads((EVAL / RESULTS).read_text(encoding="utf-8"))["results"]
    by = {s: [r for r in res if r["stage"] == s] for s in STAGES}

    def acc(rs): return sum(r["passed"] for r in rs), len(rs)
    def avg_t(rs): return sum(r.get("latency_s", 0) for r in rs) / max(1, len(rs))
    tp, tn = acc(res)

    el = []
    # 표지
    el += [Spacer(1, 100),
           Paragraph("DART 사업보고서 RAG 챗봇<br/>신기능(LLM 확장) 평가 보고서", M.H1), Spacer(1, 6),
           Paragraph(f"평가일: {REPORT_DATE} &nbsp;|&nbsp; 모델: gpt-5.4-mini (reasoning=high · 비전) &nbsp;|&nbsp; "
                     f"임베딩: BAAI/bge-m3", M.BODY),
           Paragraph("평가 대상: ① 지식 폴백(RAG 미검색→AI 일반지식) · ② 첨부 기본형(이미지·텍스트PDF) · "
                     "③ 첨부 확장(대용량PDF 첨부-RAG·스캔PDF 비전·첨부+DART 비교)", M.BODY),
           PageBreak()]

    # 1. 종합 요약
    el.append(Paragraph("1. 종합 요약", M.H2))
    summ = [["평가 단계", "테스트", "PASS", "정확도", "평균시간"]]
    for s in STAGES:
        p, n = acc(by[s])
        summ.append([s, str(n), str(p), f"{p/n*100:.0f}%" if n else "-", f"{avg_t(by[s]):.0f}s"])
    summ.append(["전체", str(tn), str(tp), f"{tp/tn*100:.0f}%" if tn else "-", f"{avg_t(res):.0f}s"])
    t = Table(summ, colWidths=[70 * mm, 22 * mm, 20 * mm, 24 * mm, 24 * mm])
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Malgun", 9), ("FONT", (0, 0), (-1, 0), "MalgunB", 9),
        ("FONT", (0, -1), (-1, -1), "MalgunB", 9),
        ("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#eef2f7")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    el.append(t)
    el.append(Spacer(1, 8))
    el.append(Paragraph(
        "• <b>지식 폴백</b>: DART에서 못 찾는 개념·전망·미보유 회사 질문에 AI 일반지식으로 답하되 "
        "'DART 근거 아님' 경고배지로 분리(NO-MOCK 유지). 검색 성공 질문은 기존 RAG로 동작(폴백 침범 없음).<br/>"
        "• <b>첨부파일</b>: 이미지·텍스트 PDF 직접 인식, 대용량 PDF는 첨부-RAG로 관련부분만, 스캔 PDF는 "
        "페이지 비전, '비교' 요청 시 첨부 수치와 실제 DART 보고서 수치를 대조.<br/>"
        "• <b>한계</b>: 저해상도 이미지의 일부 글자, 산발적 검색 불안정(재시작 필요)·응답 속도(reasoning=high).", M.BODY))
    el.append(PageBreak())

    # 2. 단계별 상세
    el.append(Paragraph("2. 단계별 상세", M.H2))
    data = [[_hdr(h) for h in ["단계", "기능", "입력", "질문", "결과", "시간", "비고"]]]
    flags = []
    for s in STAGES:
        for r in by[s]:
            data.append([Paragraph(s.split()[0], M.SMALL), Paragraph(r["feature"], M.CELL),
                         Paragraph(r["input"], M.SMALL), Paragraph(r["question"], M.CELL),
                         M.pass_badge(r["passed"]), Paragraph(f'{r.get("latency_s",0):.0f}s', M.CELLC),
                         Paragraph(fnote(r), M.SMALL)])
            flags.append(r["passed"])
    tb = Table(data, colWidths=[14 * mm, 30 * mm, 30 * mm, 42 * mm, 15 * mm, 12 * mm, 39 * mm], repeatRows=1)
    sty = [("FONT", (0, 0), (-1, -1), "Malgun", 7.5), ("BACKGROUND", (0, 0), (-1, 0), NAVY),
           ("GRID", (0, 0), (-1, -1), 0.3, colors.grey), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
           ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f9fb")])]
    for i, p in enumerate(flags, 1):
        if not p:
            sty.append(("BACKGROUND", (4, i), (4, i), colors.HexColor("#fbe6e8")))
    tb.setStyle(TableStyle(sty))
    el.append(tb)
    el.append(PageBreak())

    # 3. 문항별 상세 (입력·답변·판정)
    el.append(Paragraph("3. 문항별 상세 (입력 · 챗봇 답변 · 판정)", M.H2))
    el.append(Paragraph("각 테스트의 입력·처리방식·실제 답변. 답변은 실서버(/chat·/chat/attach) 응답 그대로.", M.SMALL))
    el.append(Spacer(1, 6))
    for r in res:
        col = "#0a7d28" if r["passed"] else "#c0152f"
        el.append(Paragraph(
            '<b>[%s · %s]</b> %s &nbsp; <font color="%s"><b>%s</b></font> <font color="#888">(%ds)</font>'
            % (M.esc(r["stage"]), M.esc(r["feature"]), M.esc(r["question"]), col,
               "PASS" if r["passed"] else "FAIL", r.get("latency_s", 0)), M.QH))
        el.append(Paragraph("<b>입력</b> · " + M.esc(r["input"]), M.QF))
        el.append(Paragraph("<b>처리</b> · " + M.esc(fnote(r)), M.QF))
        el.append(Paragraph("<b>챗봇 답변</b> · " + M.fmt_answer(r["answer"]), M.QF))
        el.append(HRFlowable(width="100%", thickness=0.4, color=colors.HexColor("#dddddd"),
                             spaceBefore=4, spaceAfter=8))

    # 4. 결론
    el.append(Paragraph("4. 결론", M.H2))
    el.append(Paragraph(
        f"신기능 3단계 {tp}/{tn}건 통과. 기존 DART RAG에 ① 미검색 질문의 AI 일반지식 폴백(경고배지 분리)과 "
        "② 첨부파일(이미지·PDF) 멀티모달 답변을 더해, 보고서 밖 질문과 사용자 자료까지 대응 범위를 넓혔다. "
        "대용량 PDF는 첨부-RAG로, 스캔본은 비전으로 처리하며, 첨부 수치를 실제 DART 보고서와 비교까지 한다. "
        "NO-MOCK 원칙은 폴백 경고배지·근거 표기로 유지된다.", M.BODY))

    SimpleDocTemplate(str(OUT), pagesize=A4, topMargin=16 * mm, bottomMargin=14 * mm,
                      leftMargin=14 * mm, rightMargin=14 * mm).build(el)
    print("PDF 생성:", OUT)


if __name__ == "__main__":
    main()
