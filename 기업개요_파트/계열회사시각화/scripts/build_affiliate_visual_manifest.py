from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


def find_project_root(start: Path) -> Path:
    for path in (start, *start.parents):
        if (path / "RAG").exists() or (path / "output" / "affiliate_visualization").exists():
            return path
    return start


ROOT = find_project_root(Path(__file__).resolve().parents[1])
DEFAULT_VISUAL_DIR = ROOT / "output" / "affiliate_visualization"
DEFAULT_CLASSIFICATION_CSV = DEFAULT_VISUAL_DIR / "affiliate_visual_classification.csv"


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_classification(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    rows: dict[str, dict[str, str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            stock_code = row.get("stock_code", "")
            if stock_code:
                rows[stock_code] = row
    return rows


def rel_path(path_value: str | None, base_dir: Path) -> str | None:
    if not path_value:
        return None
    path = Path(path_value)
    try:
        return str(path.relative_to(base_dir))
    except ValueError:
        try:
            return str(path.relative_to(ROOT))
        except ValueError:
            return str(path)


def make_frontend_url(path_value: str | None, visual_dir: Path) -> str | None:
    relative = rel_path(path_value, visual_dir)
    if not relative:
        return None
    return "/static/affiliate_visualization/" + relative.replace("\\", "/")


def compact_record(metadata: dict[str, Any], visual_dir: Path, classification: dict[str, str] | None) -> dict[str, Any]:
    stock_code = str(metadata.get("stock_code", ""))
    source_type = str(metadata.get("source_type", ""))
    visual_path = metadata.get("visual_path")
    has_original_image = bool(metadata.get("has_original_image"))
    has_ownership_rate = metadata.get("has_ownership_rate")
    class_name = classification.get("classification", "") if classification else ""
    needs_original_image_check = (
        not has_original_image
        and ("도식신호" in class_name or str(classification.get("has_visual_signal", "")).lower() == "true")
        if classification
        else False
    )

    return {
        "stock_code": stock_code,
        "corp_name": metadata.get("display_corp_name") or metadata.get("corp_name", ""),
        "raw_corp_name": metadata.get("corp_name", ""),
        "corp_code": metadata.get("corp_code", ""),
        "report_nm": metadata.get("report_nm", ""),
        "report_kind": metadata.get("report_kind", ""),
        "rcept_no": metadata.get("rcept_no", ""),
        "rcept_dt": metadata.get("rcept_dt", ""),
        "source_type": source_type,
        "has_original_image": has_original_image,
        "has_ownership_rate": has_ownership_rate,
        "visual_file_type": metadata.get("visual_file_type"),
        "visual_path": rel_path(str(visual_path) if visual_path else None, ROOT),
        "visual_url": make_frontend_url(str(visual_path) if visual_path else None, visual_dir),
        "metadata_path": rel_path(str(metadata.get("metadata_path", "")), ROOT),
        "extracted_data_path": rel_path(str(metadata.get("extracted_data_path", "")), ROOT),
        "source_url": metadata.get("source_url", ""),
        "dart_section_url": metadata.get("dart_section_url", ""),
        "dart_image_url": metadata.get("dart_image_url", ""),
        "nodes_count": len(metadata.get("nodes", [])),
        "edges_count": len(metadata.get("edges", [])),
        "affiliate_companies_count": len(metadata.get("affiliate_companies", [])),
        "investment_edges_total": metadata.get("investment_edges_total", 0),
        "structural_investment_edges_total": metadata.get("structural_investment_edges_total", 0),
        "excluded_investment_edges_total": metadata.get("excluded_investment_edges_total", 0),
        "visual_edges_total": metadata.get("visual_edges_total", len(metadata.get("edges", []))),
        "classification": class_name,
        "needs_original_image_check": needs_original_image_check,
        "errors_count": len(metadata.get("errors", [])),
        "created_at": metadata.get("created_at", ""),
    }


def build_manifest(visual_dir: Path, classification_csv: Path) -> dict[str, Any]:
    classifications = load_classification(classification_csv)
    records: list[dict[str, Any]] = []
    failed_metadata: list[str] = []

    for metadata_path in sorted(visual_dir.glob("*/affiliate_visual_metadata.json")):
        try:
            metadata = load_json(metadata_path)
        except Exception:
            failed_metadata.append(str(metadata_path))
            continue
        stock_code = str(metadata.get("stock_code", ""))
        records.append(compact_record(metadata, visual_dir, classifications.get(stock_code)))

    source_counts = Counter(record["source_type"] for record in records)
    classification_counts = Counter(record["classification"] or "미분류" for record in records)
    original_candidates = [record for record in records if record["needs_original_image_check"]]

    return {
        "generated_at": now_iso(),
        "visual_dir": str(visual_dir),
        "total_records": len(records),
        "source_type_counts": dict(source_counts.most_common()),
        "classification_counts": dict(classification_counts.most_common()),
        "original_image_candidates_count": len(original_candidates),
        "failed_metadata": failed_metadata,
        "records": records,
    }


def write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    if not records:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(records[0].keys()))
        writer.writeheader()
        writer.writerows(records)


def write_candidate_csv(path: Path, records: list[dict[str, Any]]) -> None:
    fields = ["stock_code", "corp_name", "source_type", "classification", "rcept_no", "source_url"]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for record in records:
            if record["needs_original_image_check"]:
                writer.writerow({field: record.get(field, "") for field in fields})


def write_confirmed_original_csv(path: Path, records: list[dict[str, Any]]) -> None:
    fields = [
        "stock_code",
        "corp_name",
        "source_type",
        "visual_file_type",
        "visual_path",
        "visual_url",
        "dart_image_url",
        "rcept_no",
        "source_url",
        "created_at",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for record in records:
            if record.get("source_type") == "original_dart_image":
                writer.writerow({field: record.get(field, "") for field in fields})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="계열회사 시각화 결과 manifest 생성")
    parser.add_argument("--visual-dir", default=str(DEFAULT_VISUAL_DIR), help="계열회사 시각화 결과 폴더")
    parser.add_argument("--classification-csv", default=str(DEFAULT_CLASSIFICATION_CSV), help="분류 CSV 경로")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    visual_dir = Path(args.visual_dir)
    classification_csv = Path(args.classification_csv)
    manifest = build_manifest(visual_dir, classification_csv)
    records = manifest["records"]

    manifest_path = visual_dir / "_manifest.json"
    manifest_csv_path = visual_dir / "_manifest.csv"
    candidate_path = visual_dir / "_original_image_candidates.csv"
    confirmed_original_path = visual_dir / "_original_image_confirmed.csv"

    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    write_csv(manifest_csv_path, records)
    write_candidate_csv(candidate_path, records)
    write_confirmed_original_csv(confirmed_original_path, records)

    print(f"total_records: {manifest['total_records']}")
    print("source_type_counts:")
    for key, value in manifest["source_type_counts"].items():
        print(f"  {key}: {value}")
    print(f"original_image_candidates_count: {manifest['original_image_candidates_count']}")
    print(f"manifest_json: {manifest_path}")
    print(f"manifest_csv: {manifest_csv_path}")
    print(f"candidate_csv: {candidate_path}")
    print(f"confirmed_original_csv: {confirmed_original_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
