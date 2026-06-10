# -*- coding: utf-8 -*-
"""특정 결과파일에서 현재 FAIL인 문항만 재실행 → 재채점 → 결과파일 갱신(in-place).

실행: python embedding/chatbot/eval/rerun_fails.py --golden golden_set.json --results results_broad.json
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path

EVAL = Path(__file__).resolve().parent
sys.path.insert(0, str(EVAL))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import run_eval as R


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--golden", default="golden_set.json")
    ap.add_argument("--results", default="results_broad.json")
    args = ap.parse_args()

    golden = {q["id"]: q for q in json.loads((EVAL / args.golden).read_text(encoding="utf-8"))["questions"]}
    blob = json.loads((EVAL / args.results).read_text(encoding="utf-8"))
    results = blob["results"]

    # 현재 FAIL 식별(현 채점기)
    fails = []
    for x in results:
        fake = {"answer": x.get("answer", ""), "sources": [{"report": r} for r in x.get("source_reports", [])],
                "meta": x.get("meta", {})}
        p, _ = R.score_one(golden[x["id"]], fake)
        if not p:
            fails.append(x["id"])
    print(f"재실행 대상(FAIL) {len(fails)}건: {fails}", flush=True)

    from embedding.chatbot import pipeline
    by_id = {x["id"]: x for x in results}
    flipped = []
    for i, fid in enumerate(fails, 1):
        q = golden[fid]
        t0 = time.time()
        try:
            r = pipeline.answer(q["question"], current_year=2026, ticker=q.get("ticker"))
        except Exception as e:
            r = {"answer": f"(에러: {e})", "sources": [], "meta": {}}
        dt = time.time() - t0
        fake = {"answer": r.get("answer", ""), "sources": r.get("sources", []), "meta": r.get("meta", {})}
        passed, checks = R.score_one(q, fake)
        old = by_id[fid]
        was = old.get("passed")
        # 결과 갱신
        old.update({
            "passed": passed, "checks": checks, "latency_s": round(dt, 1),
            "answer": r.get("answer", ""),
            "sources_n": len(r.get("sources") or []),
            "source_reports": [s.get("report", "") for s in (r.get("sources") or [])],
            "meta": {k: (r.get("meta", {}) or {}).get(k) for k in
                     ("corp_name", "ticker", "year", "period_label",
                      "intent", "search_query", "queries_used", "ontology_concepts")},
            "rerun": True,
        })
        mark = "✅PASS" if passed else "❌FAIL"
        if passed and not was:
            flipped.append(fid)
        print(f"[{i}/{len(fails)}] {mark} ({dt:.0f}s) {fid}: {q['question']}", flush=True)
        bad = [k for k, v in checks.items() if not v]
        if bad:
            print(f"        미충족: {bad}", flush=True)
        print(f"        답[:110]: {(r.get('answer') or '')[:110].replace(chr(10),' ')}", flush=True)

    # 전체 재집계 + 저장
    npass = 0
    for x in results:
        fake = {"answer": x.get("answer", ""), "sources": [{"report": r} for r in x.get("source_reports", [])],
                "meta": x.get("meta", {})}
        p, _ = R.score_one(golden[x["id"]], fake)
        npass += p
    blob["pass"] = npass
    blob["total"] = len(results)
    blob["rate"] = npass / len(results) * 100
    (EVAL / args.results).write_text(json.dumps(blob, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n=== 재실행 후: {npass}/{len(results)} PASS ({blob['rate']:.0f}%) | 새로 통과: {flipped} ===", flush=True)
    print(f"저장: {EVAL / args.results}", flush=True)


if __name__ == "__main__":
    main()
