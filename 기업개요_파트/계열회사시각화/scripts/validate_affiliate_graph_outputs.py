from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


def find_project_root(start: Path) -> Path:
    for path in (start, *start.parents):
        if (path / "output" / "affiliate_visualization").exists() or (path / "RAG").exists():
            return path
    return start


ROOT = find_project_root(Path(__file__).resolve().parents[1])
DEFAULT_VISUAL_DIR = ROOT / "output" / "affiliate_visualization"
DEFAULT_STRUCTURE_DIR = ROOT / "output" / "affiliate_structure_batch"
DEFAULT_REPORT_JSON = ROOT / "output" / "affiliate_validation_report.json"
DEFAULT_ISSUES_CSV = ROOT / "output" / "affiliate_validation_issues.csv"

KNOWN_SOURCE_TYPES = {
    "original_dart_image",
    "generated_ownership_graph",
    "generated_control_investment_graph",
    "generated_investment_note_graph",
    "generated_subsidiary_graph",
    "generated_numeric_subsidiary_graph",
    "generated_plain_subsidiary_graph",
    "generated_affiliate_directory",
    "insufficient_data",
}

UI_LABELS = {
    "",
    "관계",
    "50% 이상",
    "20~50%",
    "20% 미만",
    "20% 미만/관계",
    "지분율 미확인",
    "기타 관계기업",
}

SVG_FRAGMENT_ONLY_REASONS = {
    "bare_legal_suffix",
    "truncated_company_name",
    "single_character_label",
}

NOISE_KEYWORDS = (
    "본문으로 이동",
    "상위 헤더",
    "합 계",
    "합계",
    "수량",
    "금액",
    "법인명",
    "회사명",
    "상장여부",
)

BARE_LEGAL_SUFFIX_RE = re.compile(
    r"^(?:co\.?|co\.?,?\s*ltd\.?|ltd\.?|limited|inc\.?|corp\.?|corporation|company)$",
    flags=re.I,
)


def configure_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def resolve_path(path_value: str | None, base_dir: Path = ROOT) -> Path | None:
    if not path_value:
        return None
    path = Path(path_value)
    if path.is_absolute():
        return path
    return base_dir / path


def normalize_label(value: str) -> str:
    value = html.unescape(str(value or ""))
    value = re.sub(r"<[^>]+>", "", value)
    return re.sub(r"\s+", " ", value).strip()


def bare_company_text(value: str) -> str:
    value = normalize_label(value)
    value = re.sub(r"\(주\)|㈜|주식회사|유한회사|회사|법인", "", value, flags=re.I)
    value = re.sub(
        r"(?i)[\s.,]*(?:company|co|ltd|limited|inc|corp|corporation|llc|l\.l\.c|gmbh)\.?,?$",
        "",
        value,
    )
    return re.sub(r"[^가-힣A-Za-z0-9]", "", value)


def suspicious_label_reason(value: str) -> str | None:
    label = normalize_label(value)
    if label in UI_LABELS:
        return None
    if any(keyword in label for keyword in NOISE_KEYWORDS):
        return "noise_text"
    if "\ufffd" in label or "�" in label:
        return "replacement_character"
    if re.fullmatch(r"[-\d.,()%\s]+", label):
        return None
    if re.search(r"\d+(?:\.\d+)?\s*%|\d{1,2}월|지분율|자기주식|당기 중|매입하였습니다|의결권 주식", label):
        return "table_text_leak"
    if BARE_LEGAL_SUFFIX_RE.fullmatch(label):
        return "bare_legal_suffix"
    if (
        re.match(r"^[a-z]", label)
        and re.search(r"Company|Corporation|GmbH|LLC|AG|Partnership|Inc\.?|Ltd\.?", label, flags=re.I)
        and len(bare_company_text(label)) <= 3
    ):
        return "truncated_company_name"

    bare = bare_company_text(label)
    if len(bare) <= 1 and re.search(r"\(주\)|㈜|co|ltd|inc|corp|company", label, flags=re.I):
        return "truncated_company_name"
    if len(label) == 1 and re.search(r"[가-힣A-Za-z]", label):
        return "single_character_label"
    return None


def issue(scope: str, code: str, message: str, path: Path | None = None, severity: str = "error") -> dict[str, str]:
    return {
        "severity": severity,
        "scope": scope,
        "code": code,
        "message": message,
        "path": str(path or ""),
    }


def record_matches_stock(record: dict[str, Any], stock_code: str | None) -> bool:
    return not stock_code or str(record.get("stock_code", "")) == stock_code


def validate_visual_metadata(metadata_path: Path, stock_code: str | None) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    try:
        metadata = load_json(metadata_path)
    except Exception as exc:
        return [issue("visual", "invalid_metadata_json", f"{type(exc).__name__}: {exc}", metadata_path)]

    if not record_matches_stock(metadata, stock_code):
        return []

    source_type = str(metadata.get("source_type", ""))
    if source_type not in KNOWN_SOURCE_TYPES:
        issues.append(issue("visual", "unknown_source_type", source_type, metadata_path))

    visual_path = resolve_path(str(metadata.get("visual_path") or ""), ROOT)
    if source_type != "insufficient_data":
        if visual_path is None or not visual_path.exists():
            issues.append(issue("visual", "missing_visual_file", str(metadata.get("visual_path") or ""), metadata_path))

    data_path = resolve_path(str(metadata.get("extracted_data_path") or ""), ROOT)
    if data_path is None or not data_path.exists():
        issues.append(issue("visual", "missing_extracted_data", str(metadata.get("extracted_data_path") or ""), metadata_path))

    nodes = metadata.get("nodes") or []
    edges = metadata.get("edges") or []
    affiliates = metadata.get("affiliate_companies") or []

    if source_type.startswith("generated_") and source_type != "generated_affiliate_directory" and not edges:
        issues.append(issue("visual", "generated_graph_without_edges", source_type, metadata_path))
    if source_type == "generated_affiliate_directory" and not affiliates:
        issues.append(issue("visual", "directory_without_affiliates", source_type, metadata_path))
    if source_type == "original_dart_image" and not metadata.get("has_original_image"):
        issues.append(issue("visual", "original_image_flag_mismatch", "has_original_image is false", metadata_path))

    if metadata.get("visual_edges_total") is not None and int(metadata.get("visual_edges_total") or 0) != len(edges):
        issues.append(
            issue(
                "visual",
                "edge_count_mismatch",
                f"visual_edges_total={metadata.get('visual_edges_total')} actual={len(edges)}",
                metadata_path,
                severity="warning",
            )
        )

    labels: list[tuple[str, str]] = []
    for node in nodes:
        labels.append(("node", str(node.get("name") or node.get("id") or "")))
    for edge in edges:
        labels.append(("edge_from", str(edge.get("from") or "")))
        labels.append(("edge_to", str(edge.get("to") or "")))
    for company in affiliates:
        labels.append(("affiliate", str(company.get("name") or "")))

    for label_type, label in labels:
        reason = suspicious_label_reason(label)
        if reason:
            issues.append(issue("visual", reason, f"{label_type}: {label}", metadata_path))

    return issues


def extract_svg_texts(svg_path: Path) -> list[str]:
    try:
        text = svg_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = svg_path.read_text(encoding="utf-8", errors="replace")
    matches = re.findall(r"<text\b[^>]*>(.*?)</text>", text, flags=re.I | re.S)
    return [normalize_label(match) for match in matches]


def validate_structure_record(data_path: Path, stock_code: str | None) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    try:
        data = load_json(data_path)
    except Exception as exc:
        return [issue("structure", "invalid_visual_data_json", f"{type(exc).__name__}: {exc}", data_path)]

    target = data.get("target") or {}
    if stock_code and str(target.get("code", "")) != stock_code:
        return []

    edges = data.get("edges") or []
    meta = data.get("meta") or {}
    status = str(data.get("status") or "")

    if status == "generated_structure_diagram" and not edges:
        issues.append(issue("structure", "structure_without_edges", status, data_path))
    if meta.get("shown_edges") is not None and int(meta.get("shown_edges") or 0) != len(edges):
        issues.append(
            issue(
                "structure",
                "shown_edges_mismatch",
                f"shown_edges={meta.get('shown_edges')} actual={len(edges)}",
                data_path,
                severity="warning",
            )
        )

    for edge in edges:
        for field in ("source", "target"):
            label = str(edge.get(field) or "")
            reason = suspicious_label_reason(label)
            if reason:
                issues.append(issue("structure", reason, f"{field}: {label}", data_path))

    svg_path = resolve_path(str((data.get("files") or {}).get("structure_svg") or ""), ROOT)
    if status == "generated_structure_diagram":
        if svg_path is None or not svg_path.exists():
            issues.append(issue("structure", "missing_structure_svg", str(svg_path or ""), data_path))
        else:
            for label in extract_svg_texts(svg_path):
                reason = suspicious_label_reason(label)
                if reason in SVG_FRAGMENT_ONLY_REASONS:
                    continue
                if reason:
                    issues.append(issue("structure_svg", reason, f"text: {label}", svg_path))

    return issues


def iter_structure_data_paths(structure_dir: Path) -> list[Path]:
    return sorted(path for path in structure_dir.glob("*/*_visual_data.json") if path.is_file())


def write_csv(path: Path, issues: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["severity", "scope", "code", "message", "path"]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(issues)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate affiliate visualization and structure graph outputs.")
    parser.add_argument("--visual-dir", default=str(DEFAULT_VISUAL_DIR), help="affiliate_visualization output directory")
    parser.add_argument("--structure-dir", default=str(DEFAULT_STRUCTURE_DIR), help="affiliate_structure_batch output directory")
    parser.add_argument("--stock-code", default=None, help="Validate one stock code only")
    parser.add_argument("--json-out", default=str(DEFAULT_REPORT_JSON), help="Validation report JSON path")
    parser.add_argument("--csv-out", default=str(DEFAULT_ISSUES_CSV), help="Validation issues CSV path")
    parser.add_argument("--no-write", action="store_true", help="Do not write report files")
    parser.add_argument("--strict", action="store_true", help="Exit with code 1 when any error issue exists")
    return parser.parse_args()


def main() -> int:
    configure_stdout()
    args = parse_args()
    visual_dir = Path(args.visual_dir)
    structure_dir = Path(args.structure_dir)

    visual_metadata_paths = sorted(visual_dir.glob("*/affiliate_visual_metadata.json"))
    structure_data_paths = iter_structure_data_paths(structure_dir)

    issues: list[dict[str, str]] = []
    for metadata_path in visual_metadata_paths:
        issues.extend(validate_visual_metadata(metadata_path, args.stock_code))
    for data_path in structure_data_paths:
        issues.extend(validate_structure_record(data_path, args.stock_code))

    severity_counts = Counter(item["severity"] for item in issues)
    code_counts = Counter(item["code"] for item in issues)
    report = {
        "generated_at": now_iso(),
        "stock_code": args.stock_code or "",
        "visual_records_checked": len(visual_metadata_paths) if not args.stock_code else "filtered",
        "structure_records_checked": len(structure_data_paths) if not args.stock_code else "filtered",
        "issues_total": len(issues),
        "severity_counts": dict(severity_counts),
        "code_counts": dict(code_counts.most_common()),
        "issues": issues,
    }

    if not args.no_write:
        json_path = Path(args.json_out)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        write_csv(Path(args.csv_out), issues)

    print(f"issues_total: {len(issues)}")
    print("severity_counts:")
    for key, value in severity_counts.items():
        print(f"  {key}: {value}")
    if code_counts:
        print("top_issue_codes:")
        for key, value in code_counts.most_common(10):
            print(f"  {key}: {value}")
    if not args.no_write:
        print(f"report_json: {Path(args.json_out)}")
        print(f"issues_csv: {Path(args.csv_out)}")

    has_error = any(item["severity"] == "error" for item in issues)
    return 1 if args.strict and has_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
