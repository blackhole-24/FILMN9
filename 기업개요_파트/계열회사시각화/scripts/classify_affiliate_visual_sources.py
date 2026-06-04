from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path


def find_project_root(start: Path) -> Path:
    for path in (start, *start.parents):
        if (path / "RAG").exists():
            return path
    return start


ROOT = find_project_root(Path(__file__).resolve().parents[1])
RAG_DIR = ROOT / "RAG"
OUT_DIR = ROOT / "output" / "affiliate_visualization"

VISUAL_RE = re.compile(
    r"소유지분도|소유\s*지분도|출자계통도|출자\s*계통도|계열회사\s*계통도|계통도|지배구조도|지분도|그림"
)
MATRIX_RE = re.compile(
    r"출자현황|출자\s*현황|출자사|피출자|투자회사|피투자|주요주주|지분율|소유|보유|출자\s*비율|지배\s*종속"
)
DIRECT_MATRIX_RE = re.compile(r"출자사\s*[\\＼/]\s*피출자사|피출자사")
AFFILIATE_RE = re.compile(
    r"계열회사 현황\(상세\)|상장여부\s*\|\s*회사수\s*\|\s*기업명\s*\|\s*법인등록번호|소속 회사의 명칭|계열회사의 현황"
)
INVESTMENT_RE = re.compile(r"타법인출자 현황\(상세\)|타법인 출자현황|타법인출자 현황")
INVESTMENT_DETAIL_RE = re.compile(
    r"타법인출자 현황\(상세\)|법인명\s*/\s*상장여부\s*/\s*최초취득일자\s*/\s*출자목적|\|\s*법인명\s*\|\s*최초취득일자\s*\|\s*출자목적"
)


def is_relevant(path: str, text: str) -> bool:
    haystack = f"{path}\n{text}"
    return bool(
        re.search(r"계열회사|상세표|타법인출자", path)
        or re.search(r"계열회사|타법인출자|출자현황|계통도|소유지분도", haystack)
    )


def classify_file(path: Path) -> dict[str, object]:
    meta: dict[str, object] = {}
    visual_ids: list[str] = []
    matrix_ids: list[str] = []
    direct_matrix_ids: list[str] = []
    affiliate_ids: list[str] = []
    investment_ids: list[str] = []
    investment_detail_ids: list[str] = []
    relevant_chunks = 0
    relevant_table_chunks = 0
    relevant_chars = 0

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not meta:
                meta = obj

            section_path = str(obj.get("section_path_str") or "")
            text = str(obj.get("text") or "")
            kind = str(obj.get("kind") or "")
            if not is_relevant(section_path, text):
                continue

            relevant_chunks += 1
            relevant_chars += len(text)
            if kind == "table":
                relevant_table_chunks += 1

            scope = f"{section_path}\n{text}"
            chunk_id = str(obj.get("id") or "")
            if VISUAL_RE.search(scope):
                visual_ids.append(chunk_id)
            if kind == "table" and "|" in text and MATRIX_RE.search(scope):
                matrix_ids.append(chunk_id)
            if kind == "table" and "|" in text and DIRECT_MATRIX_RE.search(text):
                direct_matrix_ids.append(chunk_id)
            if AFFILIATE_RE.search(scope):
                affiliate_ids.append(chunk_id)
            if INVESTMENT_RE.search(scope):
                investment_ids.append(chunk_id)
            if kind == "table" and INVESTMENT_DETAIL_RE.search(scope):
                investment_detail_ids.append(chunk_id)

    has_visual = bool(visual_ids)
    has_matrix = bool(matrix_ids)
    has_direct_matrix = bool(direct_matrix_ids)
    has_affiliate = bool(affiliate_ids)
    has_investment = bool(investment_ids)
    has_investment_detail = bool(investment_detail_ids)

    if has_visual and has_direct_matrix:
        classification = "도식신호+계통도표"
    elif has_visual:
        classification = "도식신호_원본확인필요"
    elif has_direct_matrix:
        classification = "계통도표_그래프생성최상"
    elif has_investment_detail:
        classification = "타법인출자표_스타그래프가능"
    elif has_affiliate or has_investment:
        classification = "계열회사목록_그룹시각화가능"
    elif has_matrix:
        classification = "출자요약표_보조정보가능"
    elif relevant_chunks:
        classification = "계열섹션있지만_근거약함"
    else:
        classification = "계열데이터_부족"

    return {
        "stock_code": meta.get("stock_code", ""),
        "corp_name": meta.get("corp_name", path.stem),
        "rcept_no": meta.get("rcept_no", ""),
        "source_url": meta.get("source_url", ""),
        "file_name": path.name,
        "classification": classification,
        "has_visual_signal": has_visual,
        "has_matrix_table": has_matrix,
        "has_direct_ownership_matrix": has_direct_matrix,
        "has_affiliate_detail": has_affiliate,
        "has_investment_detail": has_investment,
        "has_investment_detail_table": has_investment_detail,
        "relevant_chunks": relevant_chunks,
        "relevant_table_chunks": relevant_table_chunks,
        "relevant_chars": relevant_chars,
        "visual_sample_ids": ";".join(visual_ids[:3]),
        "matrix_sample_ids": ";".join(matrix_ids[:3]),
        "direct_matrix_sample_ids": ";".join(direct_matrix_ids[:3]),
        "affiliate_sample_ids": ";".join(affiliate_ids[:3]),
        "investment_sample_ids": ";".join(investment_ids[:3]),
        "investment_detail_sample_ids": ";".join(investment_detail_ids[:3]),
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = [classify_file(path) for path in sorted(RAG_DIR.glob("*.jsonl"))]
    rows.sort(key=lambda row: (str(row["classification"]), str(row["stock_code"])))

    csv_path = OUT_DIR / "affiliate_visual_classification.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    counts = Counter(str(row["classification"]) for row in rows)
    summary_path = OUT_DIR / "affiliate_visual_classification_summary.json"
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "total_files": len(rows),
                "classification_counts": dict(counts.most_common()),
                "csv_path": str(csv_path),
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    print(f"total_files: {len(rows)}")
    for name, count in counts.most_common():
        print(f"{name}: {count}")
    print(f"csv_path: {csv_path}")
    print(f"summary_path: {summary_path}")


if __name__ == "__main__":
    main()
