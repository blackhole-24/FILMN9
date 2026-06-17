# -*- coding: utf-8 -*-
"""신기능(1~3단계) 평가 하네스 — 실서버(/chat·/chat/attach)에 9개 테스트, 문항별 즉시 저장+재개.

1단계 지식폴백 / 2단계 첨부 기본형 / 3단계 첨부 확장. 결과 → results_features.json
"""
import base64, io, json, re, sys, time
from pathlib import Path
import requests
from PIL import Image, ImageDraw

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

EVAL = Path(__file__).resolve().parent
OUT = EVAL / "results_features.json"
BASE = "http://127.0.0.1:8000"
DESK = Path(r"C:\Users\Admin\Desktop")
VAR = Path(r"C:\Users\Admin\Desktop\VAR")


def img_png(lines):
    img = Image.new("RGB", (560, 28 + 34 * len(lines)), "white")
    d = ImageDraw.Draw(img)
    for i, l in enumerate(lines):
        d.text((16, 12 + 34 * i), l, fill="black")
    b = io.BytesIO(); img.save(b, format="PNG"); return b.getvalue()


def has_num(a): return bool(re.search(r"\d{3,}|\d+조|\d+억", a or ""))


# (id, 단계, 기능, 질문, 입력설명, 호출종류, payload, 합격조건)
def chat(msg, ticker=None):
    return ("chat", {"message": msg, **({"ticker": ticker} if ticker else {})})
def attach(msg, fname, content, mime):
    return ("attach", {"message": msg, "fname": fname, "content": content, "mime": mime})


TESTS = [
    ("f1", "1단계 지식폴백", "보고서 밖 개념", "PER이 뭐야?", "회사·DART 무관 개념",
     chat("주가수익비율(PER)이 뭐야?"),
     lambda r: (r["meta"].get("mode") == "general_knowledge") and bool(r["answer"].strip())),
    ("f2", "1단계 지식폴백", "산업 전망", "반도체 업황 전망", "보고서 범위 밖",
     chat("반도체 업황 전망을 알려줘"),
     lambda r: (r["meta"].get("mode") == "general_knowledge") and bool(r["answer"].strip())),
    ("f3", "1단계 지식폴백", "미상장/미보유 회사", "테슬라 주가 전망", "DB에 없는 회사",
     chat("테슬라 주가 전망은 어때?"),
     lambda r: (r["meta"].get("mode") == "general_knowledge") and bool(r["answer"].strip())),
    ("f4", "1단계 지식폴백", "정상 RAG 대조군", "삼성전자 주요 사업", "검색 성공 → 폴백 안함",
     chat("삼성전자 주요 사업은 무엇인가요?", "005930"),
     lambda r: (r["meta"].get("mode") is None) and r["sources_n"] > 0),
    ("f5", "2단계 첨부 기본형", "이미지 판독", "표의 영업이익·당기순이익은?", "텍스트 든 PNG",
     attach("표의 영업이익과 당기순이익을 단위까지 알려줘", "table.png",
            img_png(["[손익계산서 요약]", "매출액 12,345  영업이익 2,100", "당기순이익 1,580 (단위: 억원)"]), "image/png"),
     lambda r: (r["meta"].get("attach_kind") == "이미지") and has_num(r["answer"])),
    ("f6", "2단계 첨부 기본형", "텍스트 PDF 요약", "이 문서 한 문장 요약", "텍스트 PDF",
     attach("이 문서가 무엇에 관한 것인지 한 문장으로 요약해줘", "techdoc.pdf",
            (DESK / "DART_RAG_챗봇_기술문서.pdf").read_bytes(), "application/pdf"),
     lambda r: (r["meta"].get("attach_kind") == "PDF") and bool(r["answer"].strip())),
    ("f7", "3단계 첨부 확장", "대용량 PDF 첨부-RAG", "32p 문서에서 WACC 산출법", "대용량 텍스트 PDF",
     attach("WACC는 어떻게 산출하나요?", "valdoc.pdf",
            (VAR / "한국주식_가치평가시스템_기술문서.pdf").read_bytes(), "application/pdf"),
     lambda r: ("첨부 RAG" in (r["meta"].get("note") or "")) and bool(r["answer"].strip())),
    ("f8", "3단계 첨부 확장", "스캔 PDF 비전", "스캔본 수치 인식", "이미지-only PDF",
     attach("이 문서의 매출과 영업이익을 알려줘", "scan.pdf",
            (DESK / "_scan_test.pdf").read_bytes(), "application/pdf"),
     lambda r: (r["meta"].get("attach_kind") == "스캔PDF") and bool(r["answer"].strip())),
    ("f9", "3단계 첨부 확장", "첨부 + DART 비교", "첨부 수치 vs 보고서", "이미지 + 비교 의도",
     attach("이 이미지의 매출액을 삼성전자 사업보고서 수치와 비교해줘", "est.png",
            img_png(["삼성전자 2025 매출액", "300조원 (내부 추정)"]), "image/png"),
     lambda r: (r["meta"].get("dart_compared") is True) and bool(r["answer"].strip())),
]


def call(kind, payload):
    if kind == "chat":
        body = {k: v for k, v in payload.items()}
        return requests.post(BASE + "/chat", json=body, timeout=300).json()
    files = {"file": (payload["fname"], io.BytesIO(payload["content"]), payload["mime"])}
    data = {"message": payload.get("message", "")}
    return requests.post(BASE + "/chat/attach", data=data, files=files, timeout=300).json()


def main():
    done = {}
    if OUT.exists():
        try:
            done = {x["id"]: x for x in json.loads(OUT.read_text(encoding="utf-8")).get("results", [])}
        except Exception:
            done = {}
    print(f"=== 신기능 평가 — 완료 {len(done)}/{len(TESTS)} ===", flush=True)
    for tid, stage, feat, qshort, indesc, (kind, payload), check in TESTS:
        if tid in done:
            continue
        t0 = time.time()
        try:
            r = call(kind, payload)
        except Exception as e:
            r = {"answer": f"(요청 실패: {e})", "meta": {}, "sources": []}
        dt = time.time() - t0
        meta = r.get("meta") or {}
        rec = {"id": tid, "stage": stage, "feature": feat, "question": qshort, "input": indesc,
               "answer": r.get("answer", "") or "", "sources_n": len(r.get("sources") or []),
               "meta": {"mode": meta.get("mode"), "attach_kind": meta.get("attach_kind"),
                        "note": meta.get("note"), "dart_compared": meta.get("dart_compared"),
                        "filename": meta.get("filename")},
               "latency_s": round(dt, 1)}
        try:
            rec["passed"] = bool(check({**rec, "meta": rec["meta"]}))
        except Exception:
            rec["passed"] = False
        done[tid] = rec
        ordered = [done[t[0]] for t in TESTS if t[0] in done]
        npass = sum(1 for x in ordered if x["passed"])
        OUT.write_text(json.dumps({"pass": npass, "total": len(TESTS), "results": ordered},
                                  ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[{len(done)}/{len(TESTS)}] {'✅' if rec['passed'] else '❌'} ({dt:.0f}s) {tid} {stage} · {feat}", flush=True)
        print(f"        답[:90]: {rec['answer'][:90].replace(chr(10),' ')}", flush=True)
    npass = sum(1 for x in done.values() if x["passed"])
    print(f"=== 완료: {npass}/{len(TESTS)} PASS ===", flush=True)


if __name__ == "__main__":
    main()
