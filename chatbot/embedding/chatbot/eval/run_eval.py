# -*- coding: utf-8 -*-
"""챗봇 답변 정확도 회귀 평가 harness (#8 골든질문 자동채점).

golden_set.json의 각 질문을 pipeline.answer()로 실행해 기대 조건을 채점한다.
기존 챗봇 코드는 전혀 수정하지 않는 '읽기 전용' 평가 도구.

채점 기준(질문별 expect 에 명시된 것만 평가):
  - found        : 답변이 '찾을 수 없음'류가 아님 (또는 negative 케이스면 반대)
  - keywords[]   : 해당 문자열이 답변에 포함
  - numbers[]    : 실측 수치 문자열이 답변에 정확히 포함 (NO-MOCK 검증 숫자)
  - numeric      : 답변에 숫자(천단위 콤마 또는 4자리+)가 1개 이상
  - report_contains : 보고서 라벨('1분기'/'사업보고서')이 답변/출처/메타에 표기

모든 조건 충족 시 PASS. 변경 전/후 비교로 개선을 숫자로 증명(데모 신뢰성).

실행:
  python embedding/chatbot/eval/run_eval.py            # 전체
  python embedding/chatbot/eval/run_eval.py --limit 3  # 앞 3개만(빠른 점검)
  python embedding/chatbot/eval/run_eval.py --tag before   # 결과를 results_before.json 으로 저장
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# embedding/ 패키지를 담은 디렉터리(저장소의 chatbot/ 또는 로컬 VAR/)를 경로에 추가 — 이식성.
#   run_eval.py = .../embedding/chatbot/eval/run_eval.py → parents[3] 가 그 루트.
_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT))

EVAL_DIR = Path(__file__).resolve().parent
GOLDEN = EVAL_DIR / "golden_set.json"

NOT_FOUND_MARKERS = ["찾을 수 없", "정보가 없", "해당 정보를 찾을 수", "확인되지 않습니다", "찾지 못",
                     "기재되어 있지 않", "기재돼 있지 않", "기재되지 않", "나와 있지 않",
                     "포함되어 있지 않", "제공되지 않", "확인할 수 없"]
_NUM_RE = re.compile(r"\d{1,3}(?:,\d{3})+|\d{4,}")


def _num_present(num_str: str, ans: str) -> bool:
    """기대 수치(백만원 단위 콤마표기)가 답변에 있는지 — 단위 재포맷 관용적 매칭.

    LLM 이 '43,601,051 백만원'을 '43조 6,011억원'처럼 조/억으로 바꿔 써도 정답 인정.
    """
    if num_str in ans:
        return True
    digits = num_str.replace(",", "")
    if digits in ans.replace(",", ""):
        return True
    # 조/억 재포맷 매칭 (입력이 백만원 단위라고 가정: 1조원=1,000,000백만원, 1억원=100백만원)
    try:
        v = int(digits)
        jo = v // 1_000_000
        eok = round((v % 1_000_000) / 100)
        if jo > 0:
            m = re.search(rf"{jo}\s*조\s*([\d,]+)\s*억", ans)
            if m and abs(int(m.group(1).replace(",", "")) - eok) <= 5:
                return True
    except Exception:
        pass
    return False


def score_one(q: dict, res: dict) -> tuple[bool, dict]:
    exp = q.get("expect", {})
    ans = res.get("answer") or ""
    sources = res.get("sources") or []
    meta = res.get("meta") or {}
    src_reports = " ".join(str(s.get("report", "")) for s in sources)
    blob_report = f"{ans} {src_reports} {meta.get('period_label','')} {meta.get('report_kind','')}"

    # 'found' = 답변이 '전체 거부'가 아님. 하위 항목 일부를 정직하게 '찾을 수 없음'으로
    # 표기한 정상 답변(예: 영업이익은 주고 EBITDA만 없음)은 found=True 로 인정.
    # 거부 판정: 답변 도입부(앞 50자)가 거부 문구이거나, 답변이 짧은데(<80자) 거부 문구 포함.
    head = ans.strip()[:120]
    has_num = bool(_NUM_RE.search(ans))
    is_refusal = any(m in head for m in NOT_FOUND_MARKERS) or \
                 (not has_num and any(m in ans for m in NOT_FOUND_MARKERS))
    found = not is_refusal
    checks: dict = {}

    if "found" in exp:
        checks["found"] = (found == exp["found"])
    for kw in exp.get("keywords", []):
        checks[f"kw:{kw}"] = (kw in ans)
    for num in exp.get("numbers", []):
        checks[f"num:{num}"] = _num_present(num, ans)
    if exp.get("numeric"):
        checks["numeric"] = bool(_NUM_RE.search(ans))
    rc = exp.get("report_contains")
    if rc:
        checks[f"report:{rc}"] = (rc in blob_report)
    # 단위 검증: '단위 미확인'이 없고, 금액 단위(백만원/조/억/원/%)가 실제로 표기됨
    if exp.get("unit_ok"):
        # 백만원/천원/조/억/% 또는 '숫자+원'(POSCO 등 원단위 보고서)도 단위로 인정
        has_unit = bool(re.search(r"백만원|천원|억원|조원|[0-9]\s*조|[0-9]\s*억|[0-9][\d,]*\s*원|%|％", ans))
        checks["unit_ok"] = ("단위 미확인" not in ans) and has_unit

    passed = all(checks.values()) if checks else found
    return passed, checks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="앞 N개만 실행")
    ap.add_argument("--tag", default="", help="결과 파일 태그 (results_<tag>.json)")
    args = ap.parse_args()

    from embedding.chatbot import pipeline

    data = json.loads(GOLDEN.read_text(encoding="utf-8"))
    questions = data["questions"]
    if args.limit > 0:
        questions = questions[:args.limit]

    print(f"=== 챗봇 평가 시작: {len(questions)}문항 ===\n", flush=True)
    results = []
    n_pass = 0
    t_all = time.time()
    for i, q in enumerate(questions, 1):
        t0 = time.time()
        try:
            res = pipeline.answer(q["question"], current_year=2026, ticker=q.get("ticker"))
        except Exception as e:
            res = {"status": "error", "answer": f"(에러: {e})", "sources": [], "meta": {}}
        dt = time.time() - t0
        passed, checks = score_one(q, res)
        n_pass += int(passed)
        mark = "✅PASS" if passed else "❌FAIL"
        failed_checks = [k for k, v in checks.items() if not v]
        print(f"[{i}/{len(questions)}] {mark} ({dt:.0f}s) {q['id']}: \"{q['question']}\"", flush=True)
        if failed_checks:
            print(f"        실패조건: {failed_checks}", flush=True)
        print(f"        답변[:120]: {(res.get('answer') or '').replace(chr(10),' ')[:120]}", flush=True)
        results.append({
            "id": q["id"], "question": q["question"], "passed": passed,
            "checks": checks, "latency_s": round(dt, 1),
            "answer": res.get("answer", ""),
            "sources_n": len(res.get("sources") or []),
            "source_reports": [s.get("report", "") for s in (res.get("sources") or [])],
            "meta": {k: res.get("meta", {}).get(k) for k in ("corp_name", "ticker", "year", "period_label")},
        })

    elapsed = time.time() - t_all
    rate = n_pass / len(questions) * 100 if questions else 0
    print(f"\n=== 결과: {n_pass}/{len(questions)} PASS ({rate:.0f}%) · 총 {elapsed:.0f}s · 평균 {elapsed/len(questions):.0f}s/문항 ===", flush=True)

    tag = f"_{args.tag}" if args.tag else ""
    out = EVAL_DIR / f"results{tag}.json"
    out.write_text(json.dumps({"pass": n_pass, "total": len(questions), "rate": rate,
                               "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"저장: {out}", flush=True)


if __name__ == "__main__":
    main()
