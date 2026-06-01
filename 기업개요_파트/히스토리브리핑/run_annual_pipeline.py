"""연간 통합 파이프라인 오케스트레이터.

매년 4월 1일 자동 실행 — DART 수집부터 MongoDB 적재까지 일괄 처리.

실행 단계:
  1. 종목 목록 갱신          (code/update_companies.py)
  2. DART 사업보고서 수집     (code/collect_dart.py)
  3. 브리핑 생성 1pass        (code/generate_briefs.py)        # Phase 4 작성 예정
  4. 품질 평가 1pass          (code/evaluate.py)               # Phase 4 작성 예정
  5. 브리핑 재생성 2pass      (code/regenerate.py)             # Phase 4 작성 예정
  6. 품질 평가 2pass          (code/evaluate.py --pass 2)      # Phase 4 작성 예정
  7. best-of-two 통합        (code/merge_best.py)             # Phase 4 작성 예정
  8. MongoDB 적재             (code/load_mongo.py)             # Phase 4 작성 예정

사용:
  python run_annual_pipeline.py                  # 전체 실행 (strict mode)
  python run_annual_pipeline.py --continue-on-error
  python run_annual_pipeline.py --skip-steps 1,2
  python run_annual_pipeline.py --only-steps 1
  python run_annual_pipeline.py --dry-run
"""
import sys
import argparse
import subprocess
import time
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

AUTO_DIR = Path(__file__).parent.resolve()
LOG_DIR  = AUTO_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

PYTHON_EXE = sys.executable


# ─── 파이프라인 단계 (모듈명 기준) ──────────────────────────────────────────
STEPS = [
    {"id": 1, "name": "종목 목록 갱신 (KOSPI + KOSDAQ + WICS)",
     "module": "code.update_companies"},
    {"id": 2, "name": "DART 사업보고서 수집 → JSONL",
     "module": "code.collect_dart"},
    {"id": 3, "name": "브리핑 생성 1pass (gpt-5-mini)",
     "module": "code.generate_briefs", "args": ["--pass", "1"]},
    {"id": 4, "name": "품질 평가 1pass (4-Phase)",
     "module": "code.evaluate", "args": ["--pass", "1"]},
    {"id": 5, "name": "브리핑 재생성 2pass (gpt-5.4-mini, 저점수)",
     "module": "code.generate_briefs", "args": ["--pass", "2"]},
    {"id": 6, "name": "품질 평가 2pass",
     "module": "code.evaluate", "args": ["--pass", "2"]},
    {"id": 7, "name": "best-of-two 통합",
     "module": "code.merge_best"},
    {"id": 8, "name": "MongoDB Atlas 적재",
     "module": "code.load_mongo"},
]


def run_step(step: dict, log_file, dry_run: bool) -> dict:
    name   = step["name"]
    module = step["module"]
    extra  = step.get("args", [])

    msg = f"[STEP {step['id']}/{len(STEPS)}] {name}"
    print(msg)
    log_file.write(f"\n{'='*70}\n{msg}\n{'='*70}\n")

    if dry_run:
        log_file.write(f"  (DRY-RUN: 실행 안 함 — python -m {module} {' '.join(extra)})\n")
        return {"step": step["id"], "name": name, "status": "dry_run"}

    t0 = time.time()
    cmd = [PYTHON_EXE, "-m", module, *extra]
    log_file.write(f"  명령: {' '.join(cmd)}\n")
    log_file.flush()

    result = subprocess.run(
        cmd,
        cwd=str(AUTO_DIR),
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    elapsed = time.time() - t0
    status = "ok" if result.returncode == 0 else "fail"
    log_file.write(f"  → 종료 코드: {result.returncode}  소요: {elapsed:.0f}초  상태: {status}\n")
    return {"step": step["id"], "name": name, "status": status,
            "return_code": result.returncode, "elapsed": elapsed}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--continue-on-error", action="store_true")
    p.add_argument("--skip-steps", type=str, default="")
    p.add_argument("--only-steps", type=str, default="")
    p.add_argument("--dry-run",    action="store_true")
    args = p.parse_args()

    skip = set(int(x) for x in args.skip_steps.split(",") if x.strip().isdigit())
    only = set(int(x) for x in args.only_steps.split(",") if x.strip().isdigit())

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"run_{ts}.log"

    with open(log_path, "w", encoding="utf-8") as log:
        log.write(f"FILMN9 연간 파이프라인\n")
        log.write(f"시작: {datetime.now().isoformat()}\n")
        log.write(f"옵션: continue_on_error={args.continue_on_error} "
                  f"skip={skip} only={only} dry_run={args.dry_run}\n\n")

        results = []
        for step in STEPS:
            if step["id"] in skip:
                print(f"[SKIP] STEP {step['id']}: {step['name']}")
                log.write(f"\n[SKIP] STEP {step['id']}\n")
                results.append({"step": step["id"], "name": step["name"], "status": "skipped"})
                continue
            if only and step["id"] not in only:
                continue

            r = run_step(step, log, args.dry_run)
            results.append(r)
            log.flush()

            if r["status"] == "fail" and not args.continue_on_error and not args.dry_run:
                print(f"[ABORT] STEP {step['id']} 실패. 중단.")
                log.write(f"\n[ABORT] STEP {step['id']} 실패. 중단.\n")
                break

        # 요약
        log.write(f"\n{'='*70}\n파이프라인 종료: {datetime.now().isoformat()}\n{'='*70}\n\n")
        for r in results:
            log.write(f"  STEP {r['step']:>2}  {r['status']:>10}  {r['name']}\n")

        print(f"\n{'='*60}\n파이프라인 종료\n{'='*60}")
        for r in results:
            print(f"  STEP {r['step']:>2}  {r['status']:>10}  {r['name']}")
        print(f"\n로그: {log_path}")


if __name__ == "__main__":
    main()
