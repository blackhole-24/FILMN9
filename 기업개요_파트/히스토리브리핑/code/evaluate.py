"""브리핑 4-Phase 품질 평가.

Phase 구성:
  A. 수치 일치     (무료) — business_model 의 숫자가 원본에 존재하는가
  B. Citation 검증 (무료) — key_evidence 가 원본에 존재하는가
  C. RAGAS 충실도  (LLM)  — claim 추출 → 원문 근거 여부
  D. LLM Judge     (LLM)  — 5축 종합 평가 (사실성/구조/유용성 등)

집계:
  overall_score = A*0.40 + B*0.25 + C*0.25 + D*0.10
  (None Phase 는 가중치 재분배)

사용:
  python -m code.evaluate --pass 1               # 1pass 평가
  python -m code.evaluate --pass 2               # 2pass 평가
  python -m code.evaluate --pass 1 --limit 5     # 처음 5개만
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from openai import OpenAI

from . import config as cfg
from .helpers import extraction

sys.stdout.reconfigure(encoding="utf-8")

# ─── OpenAI 클라이언트 ───────────────────────────────────────────────────────
_client = None

def _get_client():
    global _client
    if _client is None:
        _client = OpenAI(api_key=cfg.OPENAI_API_KEY)
    return _client


# ═══════════════════════════════════════════════════════════════════════════
# Phase A: 수치 일치 (무료)
# ═══════════════════════════════════════════════════════════════════════════
NUMBER_PATTERNS = [
    r"(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*%",
    r"(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*억",
    r"(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*조",
]


def extract_numbers(text: str) -> list[str]:
    nums = []
    for p in NUMBER_PATTERNS:
        nums.extend(re.findall(p, text))
    return list(set(nums))


def run_phase_a(brief: dict, source_text: str) -> dict:
    bm = brief.get("brief", {}).get("business_model", "")
    numbers = extract_numbers(bm)
    if not numbers:
        return {"score": None, "note": "no_numbers", "total": 0, "found": 0, "missing": []}
    found   = [n for n in numbers if n in source_text]
    missing = [n for n in numbers if n not in source_text]
    return {
        "score":   round(len(found) / len(numbers), 4),
        "total":   len(numbers),
        "found":   len(found),
        "missing": missing,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Phase B: Citation 검증 (무료)
# ═══════════════════════════════════════════════════════════════════════════
def run_phase_b(brief: dict, source_text: str) -> dict:
    evidences = brief.get("brief", {}).get("key_evidence", [])
    if not evidences:
        return {"score": 0.0, "total": 0, "matched": 0, "failures": []}
    matched, failures = 0, []
    for ev in evidences:
        target = ev.get("evidence_text", "").strip()
        if not target:
            continue
        if target in source_text:
            matched += 1
        else:
            failures.append({"field": ev.get("field"), "evidence_text": target})
    return {
        "score":    round(matched / len(evidences), 4),
        "total":    len(evidences),
        "matched":  matched,
        "failures": failures,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Phase C: RAGAS Faithfulness (LLM)
# ═══════════════════════════════════════════════════════════════════════════
RAGAS_SYSTEM = "당신은 텍스트 충실도 평가 전문가입니다. 기업 분석(answer)의 각 문장이 원문 자료(context)에 근거하는지 평가하세요."

RAGAS_USER = """[원문 자료]
{context}

[AI 생성 분석]
{answer}

위 분석에서 사실적 주장(claim)을 추출하고, 각 claim이 원문 자료에 근거하는지 판단하세요.

응답 형식 (JSON):
{{
  "claims": [{{"claim": "주장 내용", "supported": true}}],
  "faithfulness_score": 0.0
}}"""


def run_phase_c(brief: dict, context: str, judge_model: str) -> dict:
    """RAGAS LLM 호출."""
    b = brief.get("brief", {})
    answer = ((b.get("company_overview", "") or "") + "\n\n" + (b.get("business_model", "") or "")).strip()
    context_trim = (context or "")[:6000]
    if not answer or not context_trim:
        return {"score": None, "note": "empty_context_or_answer"}

    try:
        client = _get_client()
        resp = client.chat.completions.create(
            model=judge_model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": RAGAS_SYSTEM},
                {"role": "user",   "content": RAGAS_USER.format(context=context_trim, answer=answer)},
            ],
        )
        parsed = json.loads(resp.choices[0].message.content)
        usage  = resp.usage
        return {
            "score":  parsed.get("faithfulness_score", 0),
            "claims": parsed.get("claims", []),
            "usage": {
                "input_tokens":  usage.prompt_tokens,
                "output_tokens": usage.completion_tokens,
            },
        }
    except Exception as e:
        return {"score": None, "error": f"{type(e).__name__}: {e}"}


# ═══════════════════════════════════════════════════════════════════════════
# Phase D: LLM Judge (LLM)
# ═══════════════════════════════════════════════════════════════════════════
JUDGE_SYSTEM = "당신은 기업 분석 품질 평가 전문가입니다. 사업보고서 원문을 바탕으로 AI가 생성한 기업 분석을 5가지 기준으로 평가하세요."

JUDGE_USER = """[사업보고서 원문]
{source}

[AI 생성 기업 분석]
{generated}

아래 5가지 기준으로 각각 1~5점을 부여하세요.
1. 사실 일치성: 원문에 없는 내용이 들어갔는지
2. 핵심 정보 포함: 사업 내용, 주요 제품, 고객, 매출 비율 등
3. 불필요한 정보 제거: 장황하거나 반복이 있는지
4. 구조·가독성: 문단 구조와 표현이 읽기 쉬운지
5. 투자자 관점 유용성: 일반 투자자에게 도움이 되는지

응답 형식 (JSON):
{{
  "scores": {{"사실일치성":1,"핵심정보포함":1,"불필요정보제거":1,"구조가독성":1,"투자자유용성":1}},
  "average": 0.0,
  "verdict": "pass",
  "hallucinations": [],
  "reasoning": ""
}}"""


def run_phase_d(brief: dict, source_text: str, judge_model: str) -> dict:
    b = brief.get("brief", {})
    generated = json.dumps({
        k: b.get(k, "") for k in ["company_overview", "business_model", "main_customers", "price_factors"]
    }, ensure_ascii=False, indent=2)
    src_trim = (source_text or "")[:8000]
    if not src_trim:
        return {"score": None, "note": "empty_source"}

    try:
        client = _get_client()
        resp = client.chat.completions.create(
            model=judge_model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM},
                {"role": "user",   "content": JUDGE_USER.format(source=src_trim, generated=generated)},
            ],
        )
        parsed = json.loads(resp.choices[0].message.content)
        usage  = resp.usage
        return {
            "score":          parsed.get("average", 0),
            "scores":         parsed.get("scores", {}),
            "verdict":        parsed.get("verdict", ""),
            "hallucinations": parsed.get("hallucinations", []),
            "usage": {
                "input_tokens":  usage.prompt_tokens,
                "output_tokens": usage.completion_tokens,
            },
        }
    except Exception as e:
        return {"score": None, "error": f"{type(e).__name__}: {e}"}


# ═══════════════════════════════════════════════════════════════════════════
# 집계
# ═══════════════════════════════════════════════════════════════════════════
W_A, W_B, W_C, W_D = 0.40, 0.25, 0.25, 0.10


def aggregate(pa: dict, pb: dict, pc: dict, pd: dict) -> tuple[float, str, dict]:
    """가중 평균 → overall_score (0~100)."""
    # 각 Phase 점수 (0~100)
    a = pa.get("score")
    b = pb.get("score")
    c = pc.get("score")
    d = pd.get("score")

    sa = round(a * 100, 1) if a is not None else None
    sb = round(b * 100, 1) if b is not None else None
    sc = round(c * 100, 1) if c is not None else None
    sd = round((d / 5) * 100, 1) if d is not None else None

    pairs = []
    if sa is not None: pairs.append((sa, W_A))
    if sb is not None: pairs.append((sb, W_B))
    if sc is not None: pairs.append((sc, W_C))
    if sd is not None: pairs.append((sd, W_D))
    if not pairs:
        return 0.0, "low", {}

    total_w = sum(w for _, w in pairs)
    overall = round(sum(v * w / total_w for v, w in pairs), 2)
    level   = "high" if overall >= 85 else "medium" if overall >= 70 else "low"

    metrics = {
        "numerical_match":    sa,
        "citation_check":     sb,
        "ragas_faithfulness": sc,
        "llm_judge":          sd,
    }
    return overall, level, metrics


# ═══════════════════════════════════════════════════════════════════════════
# 한 종목 평가
# ═══════════════════════════════════════════════════════════════════════════
def evaluate_one(brief_path: Path, jsonl_map: dict, judge_model: str) -> dict | None:
    data = json.loads(brief_path.read_text(encoding="utf-8"))
    code = data["stock_code"]

    if code not in jsonl_map:
        return None

    source_text = Path(jsonl_map[code]).read_text(encoding="utf-8")

    # 컨텍스트 재추출 (Phase C/D 용)
    chunks = []
    for line in source_text.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            chunks.append(json.loads(line))
        except json.JSONDecodeError:
            pass

    wics = data.get("meta", {}).get("wics", "")
    corp_name = data.get("corp_name", "")
    corp_type = extraction.detect_corp_type(corp_name, wics)
    biz_text  = extraction.auto_build_business_text(chunks, corp_type=corp_type)
    mda_text  = extraction.build_mda_text(chunks)
    context   = (biz_text + "\n\n" + mda_text).strip()

    pa = run_phase_a(data, source_text)
    pb = run_phase_b(data, source_text)
    pc = run_phase_c(data, context, judge_model)
    pd = run_phase_d(data, source_text, judge_model)

    overall, level, metrics = aggregate(pa, pb, pc, pd)

    return {
        "stock_code":    code,
        "overall_score": overall,
        "level":         level,
        "metrics":       metrics,
        "details": {
            "phase_a": pa, "phase_b": pb, "phase_c": pc, "phase_d": pd,
        },
        "tested_at":   datetime.now().strftime("%Y-%m-%d %H:%M"),
        "judge_model": judge_model,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 메인
# ═══════════════════════════════════════════════════════════════════════════
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--pass", dest="pass_num", type=int, choices=[1, 2], default=1)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--no-skip", action="store_true")
    args = p.parse_args()

    cfg.ensure_dirs()

    briefs_dir = cfg.get_briefs_dir(args.pass_num)
    eval_dir   = cfg.get_eval_dir(args.pass_num)
    eval_dir.mkdir(parents=True, exist_ok=True)
    judge_model = cfg.LLM_MODEL_2PASS  # 평가는 항상 5.4-mini (좀 더 강한 모델)

    print(f"{'='*70}")
    print(f"  품질 평가 (pass {args.pass_num})")
    print(f"{'='*70}")
    print(f"  브리핑 디렉토리 : {briefs_dir}")
    print(f"  평가 출력       : {eval_dir}")
    print(f"  Judge 모델      : {judge_model}")
    print()

    brief_files = sorted([f for f in briefs_dir.glob("*.json") if not f.name.startswith("_")])
    if not brief_files:
        print(f"[FAIL] 브리핑 파일 없음. generate_briefs.py 먼저 실행.")
        return

    import glob
    jsonl_map = {os.path.basename(f)[:6]: f
                 for f in glob.glob(str(cfg.LOCAL_RAG_DIR / "*.jsonl"))}

    existing = {f.stem for f in eval_dir.glob("*.json") if not f.name.startswith("_")}
    if not args.no_skip:
        brief_files = [f for f in brief_files
                       if f.stem.split("_")[0] not in existing]

    if args.limit:
        brief_files = brief_files[: args.limit]

    print(f"  평가 대상       : {len(brief_files):,}개\n")

    t_start = time.time()
    n_ok = n_fail = 0

    for i, bp in enumerate(brief_files, 1):
        code = bp.stem.split("_")[0]
        print(f"[{i}/{len(brief_files)}] {bp.stem}")
        try:
            result = evaluate_one(bp, jsonl_map, judge_model)
            if result is None:
                print(f"  [SKIP] JSONL 매칭 실패")
                continue
            (eval_dir / f"{code}.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"  → {result['level']}  ({result['overall_score']:.1f}점)  "
                  f"A={result['metrics']['numerical_match']} "
                  f"B={result['metrics']['citation_check']} "
                  f"C={result['metrics']['ragas_faithfulness']} "
                  f"D={result['metrics']['llm_judge']}")
            n_ok += 1
        except Exception as e:
            print(f"  ❌ 예외: {type(e).__name__}: {e}")
            n_fail += 1

    elapsed = time.time() - t_start
    print(f"\n{'='*70}")
    print(f"완료: ok={n_ok}  fail={n_fail}  ({elapsed/60:.1f}분)")


if __name__ == "__main__":
    main()
