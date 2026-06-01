"""브리핑 자동 생성 (1pass + 2pass 통합).

흐름:
  1. companies.json 로드 (KRX 종목 + WICS)
  2. data/rag/ 에서 JSONL 매칭
  3. 각 종목 처리:
     - 청크 추출 (business / MDA / segments / price)
     - LLM 호출 → 브리핑 JSON
     - 저장 (data/briefs_1pass/ 또는 data/briefs_2pass/)
  4. 비용 추적 + 진행 로그

모드:
  --pass 1   1pass: 전체 종목 생성 (gpt-5-mini)
  --pass 2   2pass: 저점수 종목만 재생성 (gpt-5.4-mini)
             → eval_1pass 결과에서 overall_score < LOW_SCORE_THRESHOLD 인 종목만

사용:
  python -m code.generate_briefs --pass 1
  python -m code.generate_briefs --pass 1 --limit 5      # 처음 5개만 테스트
  python -m code.generate_briefs --pass 2                # 저점수 종목 재생성
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from . import config as cfg
from .helpers import extraction
from .helpers.llm_client import generate_brief, validate_brief, UsageTracker

sys.stdout.reconfigure(encoding="utf-8")


# ─── 데이터 로드 ─────────────────────────────────────────────────────────────
def load_companies() -> list[dict]:
    """data/companies.json 로드."""
    path = cfg.LOCAL_DATA_DIR / "companies.json"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} 없음. 'python -m code.update_companies' 먼저 실행."
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["companies"]


def get_jsonl_map() -> dict[str, str]:
    """data/rag/ 의 JSONL 파일들을 종목코드로 매핑."""
    files = glob.glob(str(cfg.LOCAL_RAG_DIR / "*.jsonl"))
    return {os.path.basename(f)[:6]: f for f in files}


def get_low_score_codes(threshold: int) -> set[str]:
    """eval_1pass 폴더에서 overall_score < threshold 인 종목 추출."""
    codes = set()
    if not cfg.LOCAL_EVAL_1PASS_DIR.exists():
        return codes
    for f in cfg.LOCAL_EVAL_1PASS_DIR.glob("*.json"):
        if f.name.startswith("_"):
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            if d.get("overall_score", 100) < threshold:
                codes.add(d["stock_code"])
        except Exception:
            pass
    return codes


# ─── 한 종목 처리 ────────────────────────────────────────────────────────────
def process_one(co: dict, jsonl_path: str, model: str, output_dir: Path,
                tracker: UsageTracker) -> dict:
    """한 종목 처리: 추출 → LLM → 저장."""
    corp_name  = co["name"]
    stock_code = co["stock_code"]
    market     = co["market"]
    wics       = co.get("wics") or "기타"

    # JSONL 로드
    chunks = []
    try:
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                try:
                    chunks.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except FileNotFoundError:
        return {"status": "skip", "reason": "JSONL 없음"}

    # 텍스트 추출
    corp_type = extraction.detect_corp_type(corp_name, wics)
    biz_text  = extraction.auto_build_business_text(chunks, corp_type=corp_type)
    mda_text  = extraction.build_mda_text(chunks)
    seg       = extraction.resolve_business_segments(chunks, corp_name, corp_type)
    price_ctx = extraction.auto_build_price_context(chunks)

    # LLM 호출
    result = generate_brief(
        model                 = model,
        corp_name             = corp_name,
        stock_code            = stock_code,
        industry              = wics,
        gics_sector           = wics,
        business_report_text  = biz_text,
        mda_text              = mda_text,
        performance_context   = seg["data"],
        price_factors_context = price_ctx,
        tier_instruction      = extraction.TIER_INSTRUCTION[seg["tier"]],
    )

    if result is None:
        return {"status": "fail", "reason": "LLM 호출 실패"}

    usage = result.pop("_usage", {})
    tracker.add(usage)

    warns = validate_brief(result)

    # 저장
    safe_name = re.sub(r'[\\/:*?"<>|]', "_", corp_name)
    save_path = output_dir / f"{stock_code}_{safe_name}.json"
    save_path.write_text(json.dumps({
        "stock_code":    stock_code,
        "corp_name":     corp_name,
        "_llm_model":    model,
        "_generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "meta": {
            "wics":             wics,
            "market":           market,
            "has_revenue_data": seg["tier"] <= 2,
            "tier":             seg["tier"],
            "tier_mode":        seg["mode"],
            "corp_type":        corp_type,
        },
        "brief":    result,
        "usage":    usage,
        "warnings": warns,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"status": "ok", "tier": seg["tier"],
            "confidence": result.get("confidence", "N/A")}


# ─── 메인 ────────────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--pass", dest="pass_num", type=int, choices=[1, 2], default=1,
                   help="1=gpt-5-mini 전체, 2=gpt-5.4-mini 저점수 종목만")
    p.add_argument("--limit", type=int, default=None, help="처음 N개만 (테스트)")
    p.add_argument("--no-skip", action="store_true", help="기존 파일도 덮어쓰기")
    args = p.parse_args()

    cfg.ensure_dirs()

    # 모드 설정
    if args.pass_num == 1:
        model      = cfg.LLM_MODEL_1PASS
        output_dir = cfg.LOCAL_BRIEFS_1PASS_DIR
        filter_low = False
    else:
        model      = cfg.LLM_MODEL_2PASS
        output_dir = cfg.LOCAL_BRIEFS_2PASS_DIR
        filter_low = True
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"{'='*70}")
    print(f"  브리핑 생성 (pass {args.pass_num}: {model})")
    print(f"{'='*70}")
    print(f"  출력      : {output_dir}")
    print(f"  저점수만  : {filter_low}")
    print()

    # 종목 로드
    companies = load_companies()
    jsonl_map = get_jsonl_map()
    existing  = {f.stem.split("_")[0] for f in output_dir.glob("*.json")}

    # 대상 필터
    targets = []
    for co in companies:
        sc = co["stock_code"]
        if sc not in jsonl_map:
            continue
        if not co.get("wics"):
            continue
        if not args.no_skip and sc in existing:
            continue
        targets.append({**co, "jsonl_path": jsonl_map[sc]})

    if filter_low:
        low_codes = get_low_score_codes(cfg.LOW_SCORE_THRESHOLD)
        targets = [t for t in targets if t["stock_code"] in low_codes]
        print(f"  저점수(<{cfg.LOW_SCORE_THRESHOLD}) 종목: {len(low_codes)}개")

    if args.limit:
        targets = targets[: args.limit]

    print(f"  처리 대상 : {len(targets):,}개\n")

    if not targets:
        print("처리할 종목 없음. 종료.")
        return

    # 처리
    tracker = UsageTracker(model)
    t_start = time.time()
    n_ok = n_skip = n_fail = 0

    for i, co in enumerate(targets, 1):
        sc = co["stock_code"]
        print(f"[{i}/{len(targets)}] {co['name']} ({sc}) | {co.get('wics', '?')}")
        try:
            r = process_one(co, co["jsonl_path"], model, output_dir, tracker)
            msg = r.get("reason", "") or f"tier {r.get('tier', '?')}"
            print(f"  → {r['status']}  {msg}")
            if r["status"] == "ok":
                n_ok += 1
            elif r["status"] == "skip":
                n_skip += 1
            else:
                n_fail += 1
        except Exception as e:
            print(f"  ❌ 예외: {type(e).__name__}: {e}")
            n_fail += 1

        if i % 20 == 0 or i == len(targets):
            print(f"  {tracker.summary()}\n")

    elapsed = time.time() - t_start
    print(f"\n{'='*70}")
    print(f"완료: ok={n_ok}  skip={n_skip}  fail={n_fail}  ({elapsed/60:.1f}분)")
    print(f"  {tracker.summary()}")


if __name__ == "__main__":
    main()
