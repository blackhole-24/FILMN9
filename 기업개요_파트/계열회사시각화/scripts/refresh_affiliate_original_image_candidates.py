from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path


def find_project_root(start: Path) -> Path:
    for path in (start, *start.parents):
        if (path / "RAG").exists() or (path / "output" / "affiliate_visualization").exists():
            return path
    return start


ROOT = find_project_root(Path(__file__).resolve().parents[1])
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_SCRIPTS = ROOT / "scripts"
for scripts_dir in (SCRIPT_DIR, ROOT_SCRIPTS):
    if scripts_dir.exists() and str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))

from build_affiliate_visual_manifest import DEFAULT_VISUAL_DIR  # noqa: E402
from build_affiliate_visualization import build_for_target  # noqa: E402


DEFAULT_CANDIDATE_CSV = DEFAULT_VISUAL_DIR / "_original_image_candidates.csv"
DEFAULT_MANIFEST = DEFAULT_VISUAL_DIR / "_manifest.json"


def load_candidates(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"후보 CSV를 찾지 못했습니다: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return [row for row in csv.DictReader(f) if row.get("stock_code")]


def load_manifest_targets(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"manifest를 찾지 못했습니다: {path}")
    with path.open("r", encoding="utf-8") as f:
        manifest = json.load(f)

    targets: list[dict[str, str]] = []
    for record in manifest.get("records", []):
        stock_code = str(record.get("stock_code", ""))
        source_type = str(record.get("source_type", ""))
        if not stock_code or source_type == "original_dart_image":
            continue
        targets.append(
            {
                "stock_code": stock_code,
                "corp_name": str(record.get("corp_name", "")),
                "classification": str(record.get("classification", "")),
                "source_type": source_type,
            }
        )
    return targets


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="원본 DART 이미지 후보 또는 manifest 대상 종목 순차 refresh")
    parser.add_argument(
        "--source",
        choices=["candidate-csv", "manifest"],
        default="candidate-csv",
        help="candidate-csv는 후보 CSV만, manifest는 아직 원본 이미지가 아닌 전체 manifest 대상을 확인",
    )
    parser.add_argument("--candidate-csv", default=str(DEFAULT_CANDIDATE_CSV), help="원본 이미지 후보 CSV")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="전체 manifest JSON")
    parser.add_argument("--output-dir", default=str(DEFAULT_VISUAL_DIR), help="계열회사 시각화 결과 폴더")
    parser.add_argument("--stock-code", default=None, help="특정 종목코드만 실행")
    parser.add_argument("--limit", type=int, default=None, help="앞에서부터 N개만 실행")
    parser.add_argument("--start", type=int, default=0, help="0-based 시작 위치")
    parser.add_argument("--sleep", type=float, default=0.25, help="종목 사이 대기 초")
    parser.add_argument("--progress-every", type=int, default=50, help="진행 상황 출력 간격")
    parser.add_argument("--verbose", action="store_true", help="종목별 결과를 모두 출력")
    parser.add_argument("--dry-run", action="store_true", help="실행 대상만 출력")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.source == "manifest":
        candidates = load_manifest_targets(Path(args.manifest))
    else:
        candidates = load_candidates(Path(args.candidate_csv))
    if args.stock_code:
        candidates = [row for row in candidates if row.get("stock_code") == args.stock_code]
    end = None if args.limit is None else args.start + args.limit
    selected = candidates[args.start:end]
    print(f"source: {args.source}")
    print(f"candidate_total: {len(candidates)}")
    print(f"selected: {len(selected)} / start={args.start} / limit={args.limit}")

    if args.dry_run:
        for row in selected[:30]:
            print(
                f"{row.get('stock_code')} {row.get('corp_name')} "
                f"{row.get('source_type', '')} {row.get('classification')}"
            )
        if len(selected) > 30:
            print(f"... 외 {len(selected) - 30}개")
        return 0

    output_dir = Path(args.output_dir)
    success = 0
    original_image = 0
    fallback = 0
    failed = 0

    for index, row in enumerate(selected, start=args.start + 1):
        stock_code = row["stock_code"]
        corp_name = row.get("corp_name", "")
        try:
            result = build_for_target(stock_code, out_base_dir=output_dir, try_dart_image=True, refresh=True)
            success += 1
            if result.get("source_type") == "original_dart_image":
                original_image += 1
                status = "original"
            else:
                fallback += 1
                status = str(result.get("source_type"))
            if args.verbose:
                print(f"[{index}/{len(candidates)}] {stock_code} {corp_name} -> {status}")
        except Exception as exc:
            failed += 1
            print(f"[{index}/{len(candidates)}] {stock_code} {corp_name} -> FAIL {type(exc).__name__}: {exc}")
        done = index - args.start
        if not args.verbose and (done % args.progress_every == 0 or done == len(selected)):
            print(
                f"progress {done}/{len(selected)} "
                f"(original={original_image}, fallback={fallback}, failed={failed})"
            )
        if args.sleep > 0:
            time.sleep(args.sleep)

    print("\n완료")
    print(f"success: {success}")
    print(f"original_image: {original_image}")
    print(f"fallback: {fallback}")
    print(f"failed: {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
