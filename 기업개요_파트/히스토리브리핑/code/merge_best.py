"""Best-of-Two: 1pass vs 2pass 점수 비교 → 더 좋은 브리핑 채택.

흐름:
  1. eval_1pass + eval_2pass 점수 로드
  2. 종목별: max(score) 선택
  3. 해당 brief 파일을 data/briefs/ 에 복사
  4. 요약 + selection_detail.csv 저장

사용:
  python -m code.merge_best
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import config as cfg

sys.stdout.reconfigure(encoding="utf-8")


def load_scores(eval_dir: Path) -> dict[str, float]:
    """eval 폴더에서 stock_code → overall_score 매핑."""
    out = {}
    if not eval_dir.exists():
        return out
    for f in eval_dir.glob("*.json"):
        if f.name.startswith("_"):
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            out[d["stock_code"]] = d.get("overall_score", 0)
        except Exception:
            pass
    return out


def map_briefs(folder: Path) -> dict[str, Path]:
    """stock_code → JSON 경로."""
    return {f.stem.split("_")[0]: f
            for f in folder.glob("*.json") if not f.name.startswith("_")}


def main():
    cfg.ensure_dirs()
    out_dir = cfg.LOCAL_BRIEFS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    scores_1 = load_scores(cfg.LOCAL_EVAL_1PASS_DIR)
    scores_2 = load_scores(cfg.LOCAL_EVAL_2PASS_DIR)
    briefs_1 = map_briefs(cfg.LOCAL_BRIEFS_1PASS_DIR)
    briefs_2 = map_briefs(cfg.LOCAL_BRIEFS_2PASS_DIR)

    print(f"{'='*60}")
    print(f"  Best-of-Two 통합")
    print(f"{'='*60}")
    print(f"  1pass 평가 : {len(scores_1):,}개")
    print(f"  2pass 평가 : {len(scores_2):,}개")
    print(f"  1pass 브리핑: {len(briefs_1):,}개")
    print(f"  2pass 브리핑: {len(briefs_2):,}개")
    print()

    results = []
    for code in sorted(briefs_1):
        s1 = scores_1.get(code)
        s2 = scores_2.get(code)
        if s2 is not None and s1 is not None and s2 > s1:
            adopt = "2pass"
            src   = briefs_2[code]
            chosen = s2
        else:
            adopt = "1pass"
            src   = briefs_1[code]
            chosen = s1

        dst = out_dir / src.name
        shutil.copy(src, dst)
        results.append({
            "code":         code,
            "adopt":        adopt,
            "score_1pass":  s1,
            "score_2pass":  s2,
            "chosen_score": chosen,
        })

    df = pd.DataFrame(results)
    df.to_csv(out_dir / "_selection_detail.csv", index=False, encoding="utf-8-sig")

    summary = {
        "total":           int(len(df)),
        "adopted_1pass":   int((df["adopt"] == "1pass").sum()),
        "adopted_2pass":   int((df["adopt"] == "2pass").sum()),
        "avg_score_1pass": float(df["score_1pass"].dropna().mean()) if df["score_1pass"].notna().any() else None,
        "avg_score_best":  float(df["chosen_score"].dropna().mean()) if df["chosen_score"].notna().any() else None,
        "generated_at":    datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    (out_dir / "_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"통합 완료: {len(df):,}개 → {out_dir}")
    print()
    print(f"  채택 1pass : {summary['adopted_1pass']:,}")
    print(f"  채택 2pass : {summary['adopted_2pass']:,}")
    if summary["avg_score_1pass"]:
        print(f"  평균 1pass : {summary['avg_score_1pass']:.1f}")
    if summary["avg_score_best"]:
        print(f"  평균 best  : {summary['avg_score_best']:.1f}")


if __name__ == "__main__":
    main()
