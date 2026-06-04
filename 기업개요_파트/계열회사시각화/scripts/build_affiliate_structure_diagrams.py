from __future__ import annotations

import argparse
import csv
import json
import math
import re
import shutil
import subprocess
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, asdict
from html import escape
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import networkx as nx
import plotly.graph_objects as go

plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False


def find_project_root(start: Path) -> Path:
    for path in (start, *start.parents):
        if (path / "output" / "affiliate_visualization").exists():
            return path
    return start


ROOT = find_project_root(Path(__file__).resolve().parents[1])
SOURCE_DIR = ROOT / "output" / "affiliate_visualization"
OUT_DIR = ROOT / "output" / "affiliate_structure_samples"
BATCH_OUT_DIR = ROOT / "output" / "affiliate_structure_batch"

SAMSUNG_CODES = [
    "005930",  # 삼성전자
    "028260",  # 삼성물산
    "009150",  # 삼성전기
    "006400",  # 삼성SDI
    "018260",  # 삼성SDS
    "032830",  # 삼성생명
    "000810",  # 삼성화재
    "028050",  # 삼성E&A
    "207940",  # 삼성바이오로직스
]

SAMSUNG_CORE_COMPANY_ALIASES = [
    ["삼성전자", "삼성전자㈜"],
    ["삼성물산", "삼성물산㈜"],
    ["삼성생명보험", "삼성생명보험㈜"],
    ["삼성화재해상보험", "삼성화재"],
    ["삼성바이오로직스", "삼성바이오로직스㈜"],
    ["삼성에피스홀딩스", "삼성에피스홀딩스㈜"],
    ["삼성바이오에피스", "삼성바이오에피스㈜"],
    ["삼성SDI", "삼성에스디아이", "삼성SDI㈜", "삼성에스디아이㈜"],
    ["삼성에스디에스", "삼성SDS", "삼성에스디에스㈜"],
    ["삼성이앤에이", "삼성E&A", "삼성E&A(구, 삼성엔지니어링)"],
    ["삼성전기", "삼성전기㈜"],
    ["삼성중공업", "삼성중공업㈜"],
    ["삼성증권", "삼성증권㈜"],
    ["삼성카드", "삼성카드㈜"],
    ["삼성디스플레이", "삼성디스플레이㈜"],
    ["삼성글로벌리서치", "삼성글로벌리서치 (구, 삼성경제연구소)"],
    ["호텔신라", "㈜호텔신라", "(주)호텔신라"],
    ["에스원", "㈜에스원", "(주)에스원"],
    ["제일기획", "㈜제일기획", "(주)제일기획"],
]

TARGETS = [
    {"slug": "005930_samsung_electronics", "title": "삼성전자", "mode": "group", "highlight": "삼성전자"},
    {"slug": "028260_samsung_ct", "title": "삼성물산", "mode": "group", "highlight": "삼성물산"},
    {"slug": "000070_samyang_holdings", "title": "삼양홀딩스", "mode": "single", "code": "000070", "highlight": "삼양홀딩스"},
    {"slug": "096770_sk_innovation", "title": "SK이노베이션", "mode": "single", "code": "096770", "highlight": "SK이노베이션"},
    {"slug": "005490_posco_holdings", "title": "POSCO홀딩스", "mode": "single", "code": "005490", "highlight": "POSCO홀딩스"},
]


@dataclass
class Edge:
    source: str
    target: str
    rate: float | None
    relation_type: str
    purpose: str | None = None
    sources: list[str] | None = None
    aggregate: bool = False
    virtual: bool = False


def clean_name(value: str) -> str:
    value = value or ""
    value = value.replace("\u3000", " ")
    value = re.sub(r"\s*\(주\d+\)\s*", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def key_name(value: str) -> str:
    value = clean_name(value)
    value = value.replace("㈜", "")
    value = re.sub(r"^\(주\)", "", value)
    value = re.sub(r"주식회사\s*", "", value)
    value = value.replace("(주)", "")
    value = value.replace("보통주", "")
    value = value.replace("_", " ")
    value = re.sub(r"[\s·.,]", "", value)
    return value.lower()


SAMSUNG_CORE_RANK_BY_KEY = {
    key_name(alias): rank
    for rank, aliases in enumerate(SAMSUNG_CORE_COMPANY_ALIASES)
    for alias in aliases
}


def samsung_core_rank(name: str) -> int | None:
    return SAMSUNG_CORE_RANK_BY_KEY.get(key_name(name))


def is_samsung_core_company(name: str) -> bool:
    return samsung_core_rank(name) is not None


def display_name(value: str) -> str:
    value = clean_name(value)
    value = value.replace("주식회사 ", "")
    value = value.replace("㈜", "")
    value = re.sub(r"^\(주\)", "", value)
    value = value.replace("(주)", "")
    return value.strip()


def is_noise_company_name(value: str) -> bool:
    key = key_name(value)
    if not key:
        return True
    return key in {"☞본문위치로이동", "본문위치로이동", "본문으로이동"}


def load_data_by_code(code: str) -> tuple[Path, dict[str, Any]]:
    matches = sorted(SOURCE_DIR.glob(f"{code}_*/affiliate_visual_data.json"))
    if not matches:
        raise FileNotFoundError(f"No affiliate data for {code}")
    path = matches[0]
    return path.parent, json.loads(path.read_text(encoding="utf-8"))


def load_data_by_source_path(source_path: Path) -> tuple[Path, dict[str, Any]]:
    data_path = source_path / "affiliate_visual_data.json"
    if not data_path.exists():
        raise FileNotFoundError(f"No affiliate data: {data_path}")
    return source_path, json.loads(data_path.read_text(encoding="utf-8"))


def load_metadata(source_path: Path) -> dict[str, Any]:
    metadata_path = source_path / "affiliate_visual_metadata.json"
    if not metadata_path.exists():
        return {}
    try:
        return json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"metadata_error": str(exc), "metadata_path": str(metadata_path)}


def split_source_dir_name(source_path: Path) -> tuple[str, str]:
    if "_" not in source_path.name:
        return source_path.name, source_path.name
    code, title = source_path.name.split("_", 1)
    return code, title


def common_share_base(title: str) -> str:
    return re.sub(r"(보통주|우선주)$", "", title).strip()


def excluded_security_reason(source_path: Path, common_bases: set[str]) -> str:
    _, title = split_source_dir_name(source_path)
    normalized = re.sub(r"\s+", "", title)
    upper = normalized.upper()
    if "스팩" in normalized or "SPAC" in upper:
        return "spac"
    if "우선" in normalized:
        return "preferred_stock"
    if re.search(r"\d+우[BC]?$", normalized) or re.search(r"우[BC]$", normalized):
        return "preferred_stock"
    if normalized.endswith("우") and normalized[:-1] in common_bases:
        return "preferred_stock"
    return ""


def source_dir_to_target(source_path: Path) -> dict[str, Any]:
    code, title = split_source_dir_name(source_path)
    if code in set(SAMSUNG_CODES):
        try:
            _, data = load_data_by_source_path(source_path)
            root = find_reporting_root(data, raw_edges_to_edges(data), title)
        except Exception:
            root = title
        return {
            "slug": source_path.name,
            "title": root,
            "mode": "group",
            "code": code,
            "highlight": root,
            "source_path": str(source_path),
        }
    return {
        "slug": source_path.name,
        "title": title,
        "mode": "single_path",
        "code": code,
        "highlight": title,
        "source_path": str(source_path),
    }


def has_original_visual(source_path: Path, metadata: dict[str, Any]) -> bool:
    return bool(metadata.get("has_original_image") or metadata.get("source_type") == "original_dart_image")


def original_visual_path(source_path: Path, metadata: dict[str, Any]) -> str:
    visual_path = str(metadata.get("visual_path") or "")
    if has_original_visual(source_path, metadata) and visual_path:
        return visual_path
    return ""


def raw_edges_to_edges(data: dict[str, Any]) -> list[Edge]:
    edges: list[Edge] = []
    for item in data.get("edges") or []:
        source = display_name(str(item.get("from") or ""))
        target = display_name(str(item.get("to") or ""))
        if (
            not source
            or not target
            or is_noise_company_name(source)
            or is_noise_company_name(target)
            or key_name(source) == key_name(target)
        ):
            continue
        rate = item.get("ownership_rate")
        try:
            rate = float(rate) if rate is not None and rate != "" else None
        except (TypeError, ValueError):
            rate = None
        edges.append(
            Edge(
                source=source,
                target=target,
                rate=rate,
                relation_type=str(item.get("relation_type") or "investment"),
                purpose=item.get("purpose"),
                sources=[str(item.get("source_chunk_id") or "")],
            )
        )
    return edges


def merge_edges(edges: list[Edge]) -> list[Edge]:
    merged: dict[tuple[str, str], Edge] = {}
    display: dict[str, str] = {}
    for edge in edges:
        source_key = key_name(edge.source)
        target_key = key_name(edge.target)
        display.setdefault(source_key, edge.source)
        display.setdefault(target_key, edge.target)
        key = (source_key, target_key)
        if key not in merged:
            merged[key] = Edge(
                source=display[source_key],
                target=display[target_key],
                rate=edge.rate,
                relation_type=edge.relation_type,
                purpose=edge.purpose,
                sources=list(edge.sources or []),
            )
            continue
        current = merged[key]
        if edge.rate is not None and (current.rate is None or edge.rate > current.rate):
            current.rate = edge.rate
        if edge.sources:
            current.sources = sorted(set((current.sources or []) + edge.sources))
    return list(merged.values())


def source_roots(edges: list[Edge]) -> list[str]:
    sources = Counter(edge.source for edge in edges)
    targets = {edge.target for edge in edges}
    roots = [source for source, _ in sources.most_common() if key_name(source) not in {key_name(t) for t in targets}]
    return roots or [source for source, _ in sources.most_common()]


def find_reporting_root(data: dict[str, Any], edges: list[Edge], fallback: str) -> str:
    for node in data.get("nodes") or []:
        if node.get("role") == "reporting_company":
            return display_name(str(node.get("name") or node.get("id") or fallback))
    return source_roots(edges)[0] if edges else fallback


def edge_priority(edge: Edge) -> tuple[int, float, str]:
    if edge.virtual:
        return (3, 1000, edge.target)
    if edge.aggregate:
        return (0, 0, edge.target)
    if edge.rate is None:
        return (1, 0, edge.target)
    return (2, edge.rate, edge.target)


def top_edges(edges: list[Edge], limit: int) -> tuple[list[Edge], int]:
    ordered = sorted(edges, key=edge_priority, reverse=True)
    return ordered[:limit], max(0, len(ordered) - limit)


def valid_affiliate_company_names(data: dict[str, Any], root: str) -> list[str]:
    affiliates = data.get("affiliate_companies") or []
    names: list[str] = []
    seen: set[str] = set()
    for item in affiliates:
        name = display_name(str(item.get("name") or ""))
        if not name:
            continue
        name_key = key_name(name)
        if is_noise_company_name(name) or not name_key or name_key == key_name(root) or name_key in seen:
            continue
        seen.add(name_key)
        names.append(name)
    return names


def affiliate_directory_edges(data: dict[str, Any], root: str, limit: int = 24) -> list[Edge]:
    names = valid_affiliate_company_names(data, root)
    edges: list[Edge] = []
    for name in names[:limit]:
        edges.append(Edge(root, name, None, "affiliate", purpose="계열회사"))
    valid_count = len(names)
    omitted = max(0, valid_count - len(edges))
    if omitted:
        edges.append(Edge(root, f"기타 계열회사 {omitted}개", None, "summary", aggregate=True))
    return edges


def build_single_graph_from_data(source_path: Path, data: dict[str, Any], title: str, code: str | None = None) -> tuple[str, list[Edge], dict[str, Any]]:
    all_edges = merge_edges(raw_edges_to_edges(data))
    root = find_reporting_root(data, all_edges, title)
    source_mode = "single_company"

    if not all_edges:
        metadata = load_metadata(source_path)
        valid_affiliates_count = len(valid_affiliate_company_names(data, root))
        selected = affiliate_directory_edges(data, root)
        if selected:
            source_mode = "affiliate_directory"
        elif metadata.get("source_type") == "insufficient_data" or metadata.get("errors"):
            source_mode = "insufficient_data"
        else:
            source_mode = "no_affiliates"
        meta = {
            "source_mode": source_mode,
            "source_code": code,
            "source_path": str(source_path),
            "total_edges": len(all_edges),
            "shown_edges": len(merge_edges(selected)),
            "affiliate_companies_count": len(data.get("affiliate_companies") or []),
            "valid_affiliate_companies_count": valid_affiliates_count,
        }
        return root, merge_edges(selected), meta

    by_source: dict[str, list[Edge]] = defaultdict(list)
    for edge in all_edges:
        by_source[key_name(edge.source)].append(edge)

    direct, omitted_direct = top_edges(by_source.get(key_name(root), []), 10)
    selected = list(direct)
    for edge in direct:
        children, omitted = top_edges(by_source.get(key_name(edge.target), []), 3)
        selected.extend(children)
        if omitted:
            selected.append(
                Edge(edge.target, f"기타 하위 {omitted}개", None, "summary", aggregate=True)
            )
    if omitted_direct:
        selected.append(Edge(root, f"기타 직접 투자 {omitted_direct}개", None, "summary", aggregate=True))

    if len(all_edges) <= 34:
        selected = all_edges

    meta = {
        "source_mode": source_mode,
        "source_code": code,
        "source_path": str(source_path),
        "total_edges": len(all_edges),
        "shown_edges": len(merge_edges(selected)),
        "affiliate_companies_count": len(data.get("affiliate_companies") or []),
    }
    return root, merge_edges(selected), meta


def build_single_graph(code: str, title: str) -> tuple[str, list[Edge], dict[str, Any]]:
    source_path, data = load_data_by_code(code)
    return build_single_graph_from_data(source_path, data, title, code)


def build_single_graph_from_source_path(source_path: Path, title: str) -> tuple[str, list[Edge], dict[str, Any]]:
    loaded_path, data = load_data_by_source_path(source_path)
    code, _ = split_source_dir_name(source_path)
    return build_single_graph_from_data(loaded_path, data, title, code)


def build_samsung_group_graph(highlight: str) -> tuple[str, list[Edge], dict[str, Any]]:
    all_edges: list[Edge] = []
    reporting_roots: list[str] = []
    source_paths: list[str] = []
    for code in SAMSUNG_CODES:
        try:
            source_path, data = load_data_by_code(code)
        except FileNotFoundError:
            continue
        edges = raw_edges_to_edges(data)
        root = find_reporting_root(data, edges, code)
        reporting_roots.append(root)
        source_paths.append(str(source_path))
        all_edges.extend(edges)

    all_edges = merge_edges(all_edges)
    by_source: dict[str, list[Edge]] = defaultdict(list)
    for edge in all_edges:
        by_source[key_name(edge.source)].append(edge)

    root = "삼성그룹"
    core_edges = [
        edge
        for edge in all_edges
        if is_samsung_core_company(edge.source) and is_samsung_core_company(edge.target)
    ]
    core_by_source: dict[str, list[Edge]] = defaultdict(list)
    for edge in core_edges:
        core_by_source[key_name(edge.source)].append(edge)

    preferred = [
        highlight,
        "삼성전자",
        "삼성물산",
        "삼성생명보험",
        "삼성SDI",
        "삼성전기",
        "삼성화재해상보험",
        "삼성바이오로직스",
    ]
    available = {key_name(source): source for source in reporting_roots}
    for edge in core_edges:
        available.setdefault(key_name(edge.source), edge.source)
    major_sources: list[str] = []
    for name in preferred:
        match = available.get(key_name(name))
        if match and match not in major_sources and core_by_source.get(key_name(match)):
            major_sources.append(match)
    for source, _ in Counter(edge.source for edge in core_edges).most_common():
        if len(major_sources) >= 8:
            break
        if source not in major_sources:
            major_sources.append(source)

    selected: list[Edge] = []
    for source in major_sources:
        selected.append(Edge(root, source, None, "group_member", virtual=True))
        selected.extend(sorted(core_by_source.get(key_name(source), []), key=edge_priority, reverse=True))
        non_core_count = len(by_source.get(key_name(source), [])) - len(core_by_source.get(key_name(source), []))
        if non_core_count > 0:
            selected.append(Edge(source, f"기타 비핵심 관계 {non_core_count}개", None, "summary", aggregate=True))

    meta = {
        "source_mode": "samsung_group_core_matrix",
        "source_codes": SAMSUNG_CODES,
        "source_paths": source_paths,
        "highlight": highlight,
        "total_edges": len(all_edges),
        "core_edges": len(core_edges),
        "shown_edges": len(merge_edges(selected)),
    }
    return root, merge_edges(selected), meta


def wrap_label(text: str, max_chars: int = 11, max_lines: int = 3) -> list[str]:
    text = display_name(text)
    if len(text) <= max_chars:
        return [text]
    lines: list[str] = []
    current = ""
    for token in re.split(r"([ \-/·])", text):
        if not token:
            continue
        if len(current) + len(token) <= max_chars:
            current += token
        else:
            if current.strip():
                lines.append(current.strip())
            current = token.strip()
    if current.strip():
        lines.append(current.strip())
    split_lines: list[str] = []
    for line in lines:
        while len(line) > max_chars:
            split_lines.append(line[:max_chars])
            line = line[max_chars:]
        if line:
            split_lines.append(line)
    if len(split_lines) > max_lines:
        split_lines = split_lines[:max_lines]
        split_lines[-1] = split_lines[-1][: max_chars - 1] + "…"
    return split_lines


def rate_label(edge: Edge) -> str:
    if edge.virtual:
        return "계열"
    if edge.aggregate:
        return "요약"
    if edge.rate is None:
        return edge.purpose or "관계"
    return f"{edge.rate:g}%"


def line_style(edge: Edge) -> tuple[str, float, str]:
    if edge.virtual:
        return "#64748b", 1.6, "6 4"
    if edge.aggregate:
        return "#94a3b8", 1.5, "6 4"
    if edge.rate is None:
        return "#64748b", 1.4, "4 3"
    if edge.rate >= 50:
        return "#0646ff", 3.0, ""
    if edge.rate >= 20:
        return "#dc2626", 2.2, ""
    return "#16a34a", 1.5, ""


def node_colors(node: str, root: str, highlight: str, aggregate_nodes: set[str], parent_nodes: set[str]) -> tuple[str, str, str]:
    if key_name(node) == key_name(root):
        return "#102f5f", "#102f5f", "#ffffff"
    if key_name(node) == key_name(highlight):
        return "#dff2d9", "#2f7d32", "#111827"
    if node in aggregate_nodes:
        return "#fff7d6", "#d4a72c", "#4b5563"
    if node in parent_nodes:
        return "#e8f4e4", "#8bb47d", "#111827"
    return "#ffffff", "#9aa8b6", "#111827"


def make_columns(root: str, edges: list[Edge]) -> list[tuple[Edge, list[Edge]]]:
    direct = [edge for edge in edges if key_name(edge.source) == key_name(root)]
    by_source: dict[str, list[Edge]] = defaultdict(list)
    for edge in edges:
        by_source[key_name(edge.source)].append(edge)
    columns: list[tuple[Edge, list[Edge]]] = []
    for edge in sorted(direct, key=edge_priority, reverse=True):
        children = [child for child in by_source.get(key_name(edge.target), []) if key_name(child.target) != key_name(root)]
        columns.append((edge, sorted(children, key=edge_priority, reverse=True)))
    return columns


def draw_grid_structure_svg(title: str, root: str, edges: list[Edge], highlight: str, out_path: Path, meta: dict[str, Any]) -> None:
    columns = make_columns(root, edges)
    if not columns:
        columns = [(Edge(root, edge.target, edge.rate, edge.relation_type), []) for edge in edges[:12]]

    child_edges_by_source: dict[str, list[Edge]] = defaultdict(list)
    for edge in edges:
        if key_name(edge.source) != key_name(root):
            child_edges_by_source[key_name(edge.source)].append(edge)
    for source_key in child_edges_by_source:
        child_edges_by_source[source_key].sort(key=edge_priority, reverse=True)

    max_branch_depth = 2
    has_descendants = any(child_edges_by_source.get(key_name(edge.target)) for edge, _ in columns)
    cols_per_row = min(max(5 if has_descendants else 7, len(columns)), 7 if has_descendants else 12)
    col_w = 585 if has_descendants else 245
    node_w = 188
    node_h = 56
    row_gap = 330
    child_gap = 78
    margin_x = 52
    title_h = 92
    root_y = 104
    bus_offset = 108

    def branch_rows(node: str, depth: int = 1, seen: set[str] | None = None) -> int:
        if depth > max_branch_depth:
            return 0
        seen = set(seen or set())
        node_key = key_name(node)
        if node_key in seen:
            return 0
        seen.add(node_key)
        children = [
            child
            for child in child_edges_by_source.get(node_key, [])
            if key_name(child.target) not in seen and key_name(child.target) != key_name(root)
        ]
        rows = 0
        for child in children:
            rows += max(1, branch_rows(child.target, depth + 1, set(seen)))
        return rows

    row_count = max(1, math.ceil(len(columns) / cols_per_row))
    width = max(1320, margin_x * 2 + cols_per_row * col_w)
    max_rows_by_row: list[int] = []
    for row in range(row_count):
        chunk = columns[row * cols_per_row : (row + 1) * cols_per_row]
        max_rows_by_row.append(max([branch_rows(edge.target) for edge, _ in chunk] + [0]))
    height = title_h + 120 + sum(row_gap + max(0, row_count_value - 1) * child_gap for row_count_value in max_rows_by_row) + 128

    positions: dict[str, tuple[float, float]] = {}
    root_x = width / 2 - node_w / 2
    positions[root] = (root_x, root_y)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" viewBox="0 0 {width:.0f} {height:.0f}">',
        "<defs>",
        '<marker id="arrowBlue" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L8,4 L0,8 z" fill="#0646ff"/></marker>',
        '<marker id="arrowRed" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L8,4 L0,8 z" fill="#dc2626"/></marker>',
        '<marker id="arrowGreen" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L8,4 L0,8 z" fill="#16a34a"/></marker>',
        '<marker id="arrowGray" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L8,4 L0,8 z" fill="#64748b"/></marker>',
        '<filter id="shadow" x="-10%" y="-10%" width="120%" height="130%"><feDropShadow dx="0" dy="2" stdDeviation="2" flood-color="#000000" flood-opacity="0.16"/></filter>',
        "</defs>",
        '<rect width="100%" height="100%" fill="#f8fafc"/>',
        f'<text x="{margin_x}" y="38" font-family="Malgun Gothic, Arial, sans-serif" font-size="26" font-weight="800" fill="#07111f">{escape(title)} 관계기업 구조도</text>',
        f'<text x="{margin_x}" y="66" font-family="Malgun Gothic, Arial, sans-serif" font-size="13" fill="#52637a">계열회사 구조도: 상단 기준회사, 지분 연결선, 지분율 라벨, 복잡 관계는 요약 노드로 접기</text>',
        f'<text x="{width - margin_x}" y="66" text-anchor="end" font-family="Malgun Gothic, Arial, sans-serif" font-size="12" fill="#52637a">총 edge {meta.get("total_edges")}개 중 표시 {len(edges)}개</text>',
    ]

    parent_nodes = {edge.source for edge in edges}
    aggregate_nodes = {edge.target for edge in edges if edge.aggregate}

    def draw_node(node: str, x: float, y: float) -> None:
        fill, stroke, text_color = node_colors(node, root, highlight, aggregate_nodes, parent_nodes)
        dash = ' stroke-dasharray="6 4"' if node in aggregate_nodes else ""
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{node_w}" height="{node_h}" rx="4" fill="{fill}" stroke="{stroke}" stroke-width="1.5"{dash} filter="url(#shadow)"/>'
        )
        lines = wrap_label(node)
        start_y = y + 24 - (len(lines) - 1) * 7
        for idx, line in enumerate(lines):
            parts.append(
                f'<text x="{x + node_w / 2:.1f}" y="{start_y + idx * 15:.1f}" text-anchor="middle" font-family="Malgun Gothic, Arial, sans-serif" font-size="13" font-weight="700" fill="{text_color}">{escape(line)}</text>'
            )

    def draw_edge(edge: Edge, source: str, target: str, label: str | None = None) -> None:
        x1, y1 = positions[source]
        x2, y2 = positions[target]
        sx = x1 + node_w / 2
        sy = y1 + node_h
        tx = x2 + node_w / 2
        ty = y2
        color, width_line, dash = line_style(edge)
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        marker = {
            "#0646ff": "url(#arrowBlue)",
            "#dc2626": "url(#arrowRed)",
            "#16a34a": "url(#arrowGreen)",
        }.get(color, "url(#arrowGray)")
        mid_y = (sy + ty) / 2
        path = f"M {sx:.1f},{sy:.1f} V {mid_y:.1f} H {tx:.1f} V {ty:.1f}"
        parts.append(
            f'<path d="{path}" fill="none" stroke="{color}" stroke-width="{width_line}"{dash_attr} marker-end="{marker}" opacity="0.96"/>'
        )
        text = label or rate_label(edge)
        label_x = tx
        label_y = ty - 8
        label_w = max(34, min(92, len(text) * 7 + 12))
        parts.append(
            f'<rect x="{label_x - label_w / 2:.1f}" y="{label_y - 13:.1f}" width="{label_w}" height="16" rx="8" fill="#f8fafc" opacity="0.9"/>'
        )
        parts.append(
            f'<text x="{label_x:.1f}" y="{label_y:.1f}" text-anchor="middle" font-family="Arial, sans-serif" font-size="11" font-weight="700" fill="{color}">{escape(text)}</text>'
        )

    def draw_branch_edge(edge: Edge, x1: float, y1: float, x2: float, y2: float, label_x: float, label_y: float) -> None:
        color, width_line, dash = line_style(edge)
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        marker = {
            "#0646ff": "url(#arrowBlue)",
            "#dc2626": "url(#arrowRed)",
            "#16a34a": "url(#arrowGreen)",
        }.get(color, "url(#arrowGray)")
        parts.append(
            f'<path d="M {x1:.1f},{y1:.1f} H {x2:.1f}" fill="none" stroke="{color}" stroke-width="{width_line}"{dash_attr} marker-end="{marker}" opacity="0.96"/>'
        )
        text = rate_label(edge)
        label_w = max(34, min(92, len(text) * 7 + 12))
        parts.append(
            f'<rect x="{label_x - label_w / 2:.1f}" y="{label_y - 13:.1f}" width="{label_w}" height="16" rx="8" fill="#f8fafc" opacity="0.92"/>'
        )
        parts.append(
            f'<text x="{label_x:.1f}" y="{label_y:.1f}" text-anchor="middle" font-family="Arial, sans-serif" font-size="11" font-weight="700" fill="{color}">{escape(text)}</text>'
        )

    def render_branch_children(parent: str, start_y: float, depth: int = 1, seen: set[str] | None = None) -> int:
        if depth > max_branch_depth:
            return 0
        seen = set(seen or set())
        parent_key = key_name(parent)
        if parent_key in seen:
            return 0
        seen.add(parent_key)
        children = [
            child
            for child in child_edges_by_source.get(parent_key, [])
            if key_name(child.target) not in seen and key_name(child.target) != key_name(root)
        ]
        if not children:
            return 0

        parent_x, parent_y = positions[parent]
        if depth == 1:
            trunk_x = parent_x + node_w / 2
            child_x = parent_x + node_w / 2 + 44
            trunk_top = parent_y + node_h
        else:
            trunk_x = parent_x + node_w + 22
            child_x = trunk_x + 36
            trunk_top = parent_y + node_h / 2
            parts.append(
                f'<path d="M {parent_x + node_w:.1f},{parent_y + node_h / 2:.1f} H {trunk_x:.1f}" fill="none" stroke="#64748b" stroke-width="1.4" opacity="0.7"/>'
            )

        child_mid_ys: list[float] = []
        row_cursor = 0
        for child in children:
            child_y = start_y + row_cursor * child_gap
            child_mid_ys.append(child_y + node_h / 2)
            positions[child.target] = (child_x, child_y)
            used_rows = max(1, branch_rows(child.target, depth + 1, set(seen)))
            row_cursor += used_rows

        trunk_bottom = max(child_mid_ys)
        parts.append(
            f'<path d="M {trunk_x:.1f},{trunk_top:.1f} V {trunk_bottom:.1f}" fill="none" stroke="#64748b" stroke-width="1.4" opacity="0.75"/>'
        )

        row_cursor = 0
        for child in children:
            child_y = start_y + row_cursor * child_gap
            child_mid_y = child_y + node_h / 2
            child_x, _ = positions[child.target]
            draw_branch_edge(child, trunk_x, child_mid_y, child_x, child_mid_y, child_x - 20, child_mid_y - 8)
            draw_node(child.target, child_x, child_y)
            used_rows = max(1, render_branch_children(child.target, child_y, depth + 1, set(seen)))
            row_cursor += used_rows
        return row_cursor

    draw_node(root, root_x, root_y)

    current_y = root_y + bus_offset
    for row in range(row_count):
        chunk = columns[row * cols_per_row : (row + 1) * cols_per_row]
        row_width = len(chunk) * col_w
        start_x = width / 2 - row_width / 2 + (col_w - node_w) / 2
        bus_y = current_y
        header_y = bus_y + 48
        if chunk:
            first_x = start_x + node_w / 2
            last_x = start_x + (len(chunk) - 1) * col_w + node_w / 2
            root_center = root_x + node_w / 2
            parts.append(
                f'<path d="M {root_center:.1f},{root_y + node_h:.1f} V {bus_y:.1f}" fill="none" stroke="#0646ff" stroke-width="2.6"/>'
            )
            parts.append(
                f'<path d="M {first_x:.1f},{bus_y:.1f} H {last_x:.1f}" fill="none" stroke="#0646ff" stroke-width="2.6"/>'
            )
        for idx, (edge, children) in enumerate(chunk):
            x = start_x + idx * col_w
            positions[edge.target] = (x, header_y)
            color, width_line, dash = line_style(edge)
            dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
            marker = {
                "#0646ff": "url(#arrowBlue)",
                "#dc2626": "url(#arrowRed)",
                "#16a34a": "url(#arrowGreen)",
            }.get(color, "url(#arrowGray)")
            cx = x + node_w / 2
            parts.append(
                f'<path d="M {cx:.1f},{bus_y:.1f} V {header_y:.1f}" fill="none" stroke="{color}" stroke-width="{width_line}"{dash_attr} marker-end="{marker}"/>'
            )
            parts.append(
                f'<text x="{cx:.1f}" y="{header_y - 10:.1f}" text-anchor="middle" font-family="Arial, sans-serif" font-size="11" font-weight="700" fill="{color}">{escape(rate_label(edge))}</text>'
            )
            draw_node(edge.target, x, header_y)
            render_branch_children(edge.target, header_y + node_h + 46)
        current_y += row_gap + max(0, max_rows_by_row[row] - 1) * child_gap

    legend_y = height - 44
    parts.extend(
        [
            f'<line x1="{margin_x}" y1="{legend_y}" x2="{margin_x + 42}" y2="{legend_y}" stroke="#0646ff" stroke-width="3"/>',
            f'<text x="{margin_x + 52}" y="{legend_y + 4}" font-family="Malgun Gothic, Arial, sans-serif" font-size="12" fill="#52637a">50% 이상</text>',
            f'<line x1="{margin_x + 150}" y1="{legend_y}" x2="{margin_x + 192}" y2="{legend_y}" stroke="#dc2626" stroke-width="2.2"/>',
            f'<text x="{margin_x + 202}" y="{legend_y + 4}" font-family="Malgun Gothic, Arial, sans-serif" font-size="12" fill="#52637a">20~50%</text>',
            f'<line x1="{margin_x + 300}" y1="{legend_y}" x2="{margin_x + 342}" y2="{legend_y}" stroke="#16a34a" stroke-width="1.5"/>',
            f'<text x="{margin_x + 352}" y="{legend_y + 4}" font-family="Malgun Gothic, Arial, sans-serif" font-size="12" fill="#52637a">20% 미만</text>',
            f'<line x1="{margin_x + 450}" y1="{legend_y}" x2="{margin_x + 492}" y2="{legend_y}" stroke="#64748b" stroke-width="1.4" stroke-dasharray="6 4"/>',
            f'<text x="{margin_x + 502}" y="{legend_y + 4}" font-family="Malgun Gothic, Arial, sans-serif" font-size="12" fill="#52637a">관계/요약</text>',
            f'<rect x="{width - 255}" y="{legend_y - 18}" width="18" height="18" rx="3" fill="#dff2d9" stroke="#2f7d32"/>',
            f'<text x="{width - 228}" y="{legend_y - 4}" font-family="Malgun Gothic, Arial, sans-serif" font-size="12" fill="#52637a">조회 기업 강조</text>',
        ]
    )
    parts.append("</svg>")
    out_path.write_text("\n".join(parts), encoding="utf-8")


def build_dot(title: str, root: str, edges: list[Edge], highlight: str) -> str:
    nodes = sorted({root} | {edge.source for edge in edges} | {edge.target for edge in edges})
    parent_nodes = {edge.source for edge in edges}
    aggregate_nodes = {edge.target for edge in edges if edge.aggregate}
    lines = [
        "digraph affiliate_structure {",
        '  graph [rankdir=TB, splines=ortho, bgcolor="#f8fafc", pad=0.35, nodesep=0.45, ranksep=0.9];',
        '  node [shape=box, style="rounded,filled", fontname="Malgun Gothic", margin="0.12,0.08"];',
        '  edge [fontname="Malgun Gothic", fontsize=10, arrowsize=0.7];',
        f'  label="{title} 관계기업 구조도";',
        "  labelloc=t;",
    ]
    for node in nodes:
        fill, stroke, text = node_colors(node, root, highlight, aggregate_nodes, parent_nodes)
        style = "rounded,filled,dashed" if node in aggregate_nodes else "rounded,filled"
        lines.append(f'  "{node}" [fillcolor="{fill}", color="{stroke}", fontcolor="{text}", style="{style}"];')
    for edge in edges:
        color, width, dash = line_style(edge)
        style = "dashed" if dash else "solid"
        lines.append(
            f'  "{edge.source}" -> "{edge.target}" [label="{rate_label(edge)}", color="{color}", penwidth={width:.1f}, style="{style}"];'
        )
    lines.append("}")
    return "\n".join(lines)


def draw_branch_structure_svg(title: str, root: str, edges: list[Edge], highlight: str, out_path: Path, meta: dict[str, Any]) -> None:
    by_source: dict[str, list[Edge]] = defaultdict(list)
    for edge in edges:
        by_source[key_name(edge.source)].append(edge)
    root_key = key_name(root)
    for source_key in by_source:
        if source_key != root_key:
            by_source[source_key].sort(key=edge_priority, reverse=True)

    direct_edges = [edge for edge in by_source.get(root_key, [])]
    if not direct_edges:
        direct_edges = [Edge(root, edge.target, edge.rate, edge.relation_type) for edge in edges[:12]]
    direct_root_keys = {key_name(edge.target) for edge in direct_edges}

    max_depth = 3
    node_w = 188
    node_h = 56
    level_gap = 86
    row_gap = 84
    group_gap = 34
    margin_x = 54
    margin_top = 96
    root_x = margin_x + 28
    root_y = margin_top
    child_x_gap = node_w + level_gap

    def children_of(node: str, depth: int, seen: set[str]) -> list[Edge]:
        if depth >= max_depth:
            return []
        node_key = key_name(node)
        if depth > 1 and node_key in direct_root_keys:
            return []
        return [
            child
            for child in by_source.get(node_key, [])
            if key_name(child.target) not in seen and key_name(child.target) != key_name(root)
        ]

    def rows_for(node: str, depth: int, seen: set[str] | None = None) -> int:
        seen = set(seen or set())
        node_key = key_name(node)
        if node_key in seen:
            return 1
        seen.add(node_key)
        children = children_of(node, depth, seen)
        if not children:
            return 1
        return max(1, sum(rows_for(child.target, depth + 1, set(seen)) for child in children))

    total_rows = sum(rows_for(edge.target, 1, {key_name(root)}) for edge in direct_edges)
    height = margin_top + node_h + 96 + max(1, total_rows) * row_gap + len(direct_edges) * group_gap + 112
    width = margin_x * 2 + node_w + (max_depth + 1) * (node_w + level_gap) + 240

    positions: dict[str, tuple[float, float]] = {root: (root_x, root_y)}
    parent_nodes = {edge.source for edge in edges}
    aggregate_nodes = {edge.target for edge in edges if edge.aggregate}

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" viewBox="0 0 {width:.0f} {height:.0f}">',
        "<defs>",
        '<marker id="arrowBlue" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L8,4 L0,8 z" fill="#0646ff"/></marker>',
        '<marker id="arrowRed" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L8,4 L0,8 z" fill="#dc2626"/></marker>',
        '<marker id="arrowGreen" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L8,4 L0,8 z" fill="#16a34a"/></marker>',
        '<marker id="arrowGray" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L8,4 L0,8 z" fill="#64748b"/></marker>',
        '<filter id="shadow" x="-10%" y="-10%" width="120%" height="130%"><feDropShadow dx="0" dy="2" stdDeviation="2" flood-color="#000000" flood-opacity="0.16"/></filter>',
        "</defs>",
        '<rect width="100%" height="100%" fill="#f8fafc"/>',
        f'<text x="{margin_x}" y="38" font-family="Malgun Gothic, Arial, sans-serif" font-size="26" font-weight="800" fill="#07111f">{escape(title)} 관계기업 구조도</text>',
        f'<text x="{margin_x}" y="66" font-family="Malgun Gothic, Arial, sans-serif" font-size="13" fill="#52637a">Branch layout: 세로 기준선에서 자회사로 분기, 하위 자회사는 오른쪽 화살표로 확장</text>',
        f'<text x="{width - margin_x}" y="66" text-anchor="end" font-family="Malgun Gothic, Arial, sans-serif" font-size="12" fill="#52637a">총 edge {meta.get("total_edges")}개 중 표시 {len(edges)}개</text>',
    ]

    def draw_node(node: str, x: float, y: float) -> None:
        fill, stroke, text_color = node_colors(node, root, highlight, aggregate_nodes, parent_nodes)
        dash = ' stroke-dasharray="6 4"' if node in aggregate_nodes else ""
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{node_w}" height="{node_h}" rx="5" fill="{fill}" stroke="{stroke}" stroke-width="1.5"{dash} filter="url(#shadow)"/>'
        )
        lines = wrap_label(node)
        start_y = y + 24 - (len(lines) - 1) * 7
        for idx, line in enumerate(lines):
            parts.append(
                f'<text x="{x + node_w / 2:.1f}" y="{start_y + idx * 15:.1f}" text-anchor="middle" font-family="Malgun Gothic, Arial, sans-serif" font-size="13" font-weight="700" fill="{text_color}">{escape(line)}</text>'
            )

    def draw_h_arrow(edge: Edge, x1: float, y: float, x2: float) -> None:
        color, width_line, dash = line_style(edge)
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        marker = {
            "#0646ff": "url(#arrowBlue)",
            "#dc2626": "url(#arrowRed)",
            "#16a34a": "url(#arrowGreen)",
        }.get(color, "url(#arrowGray)")
        parts.append(
            f'<path d="M {x1:.1f},{y:.1f} H {x2:.1f}" fill="none" stroke="{color}" stroke-width="{width_line}"{dash_attr} marker-end="{marker}" opacity="0.96"/>'
        )
        label = rate_label(edge)
        label_w = max(34, min(92, len(label) * 7 + 12))
        label_x = x1 + max(18, min(54, (x2 - x1) * 0.45))
        parts.append(
            f'<rect x="{label_x - label_w / 2:.1f}" y="{y - 21:.1f}" width="{label_w}" height="16" rx="8" fill="#f8fafc" opacity="0.92"/>'
        )
        parts.append(
            f'<text x="{label_x:.1f}" y="{y - 9:.1f}" text-anchor="middle" font-family="Arial, sans-serif" font-size="11" font-weight="700" fill="{color}">{escape(label)}</text>'
        )

    def render_subtree(edge: Edge, node: str, depth: int, x: float, start_y: float, seen: set[str]) -> int:
        row_count = rows_for(node, depth, set(seen))
        node_y = start_y
        positions[node] = (x, node_y)
        draw_node(node, x, node_y)

        children = children_of(node, depth, seen | {key_name(node)})
        if not children:
            return row_count

        trunk_x = x + node_w + 28
        child_x = x + child_x_gap
        parent_mid_y = node_y + node_h / 2
        child_mid_ys: list[float] = []
        cursor = start_y
        child_layout: list[tuple[Edge, float, int]] = []
        for child in children:
            used_rows = rows_for(child.target, depth + 1, seen | {key_name(node)})
            child_layout.append((child, cursor, used_rows))
            child_mid_ys.append(cursor + node_h / 2)
            cursor += used_rows * row_gap

        parts.append(
            f'<path d="M {x + node_w:.1f},{parent_mid_y:.1f} H {trunk_x:.1f}" fill="none" stroke="#64748b" stroke-width="1.4" opacity="0.78"/>'
        )
        parts.append(
            f'<path d="M {trunk_x:.1f},{parent_mid_y:.1f} V {max(child_mid_ys):.1f}" fill="none" stroke="#64748b" stroke-width="1.4" opacity="0.78"/>'
        )

        for child, child_y, _ in child_layout:
            child_mid_y = child_y + node_h / 2
            draw_h_arrow(child, trunk_x, child_mid_y, child_x)
            render_subtree(child, child.target, depth + 1, child_x, child_y, seen | {key_name(node)})
        return row_count

    draw_node(root, root_x, root_y)
    trunk_x = root_x + node_w / 2
    direct_x = root_x + child_x_gap
    start_y = root_y + node_h + 72
    cursor_y = start_y
    root_branch_layout: list[tuple[Edge, float, int]] = []
    direct_mid_ys: list[float] = []
    for edge in direct_edges:
        used_rows = rows_for(edge.target, 1, {key_name(root)})
        root_branch_layout.append((edge, cursor_y, used_rows))
        direct_mid_ys.append(cursor_y + node_h / 2)
        cursor_y += used_rows * row_gap + group_gap

    parts.append(
        f'<path d="M {trunk_x:.1f},{root_y + node_h:.1f} V {max(direct_mid_ys):.1f}" fill="none" stroke="#111827" stroke-width="1.8" opacity="0.82"/>'
    )
    for edge, direct_y, _ in root_branch_layout:
        direct_mid_y = direct_y + node_h / 2
        draw_h_arrow(edge, trunk_x, direct_mid_y, direct_x)
        render_subtree(edge, edge.target, 1, direct_x, direct_y, {key_name(root)})

    legend_y = height - 44
    parts.extend(
        [
            f'<line x1="{margin_x}" y1="{legend_y}" x2="{margin_x + 42}" y2="{legend_y}" stroke="#0646ff" stroke-width="3"/>',
            f'<text x="{margin_x + 52}" y="{legend_y + 4}" font-family="Malgun Gothic, Arial, sans-serif" font-size="12" fill="#52637a">50% 이상</text>',
            f'<line x1="{margin_x + 150}" y1="{legend_y}" x2="{margin_x + 192}" y2="{legend_y}" stroke="#dc2626" stroke-width="2.2"/>',
            f'<text x="{margin_x + 202}" y="{legend_y + 4}" font-family="Malgun Gothic, Arial, sans-serif" font-size="12" fill="#52637a">20~50%</text>',
            f'<line x1="{margin_x + 300}" y1="{legend_y}" x2="{margin_x + 342}" y2="{legend_y}" stroke="#16a34a" stroke-width="1.5"/>',
            f'<text x="{margin_x + 352}" y="{legend_y + 4}" font-family="Malgun Gothic, Arial, sans-serif" font-size="12" fill="#52637a">20% 미만</text>',
            f'<line x1="{margin_x + 450}" y1="{legend_y}" x2="{margin_x + 492}" y2="{legend_y}" stroke="#64748b" stroke-width="1.4" stroke-dasharray="6 4"/>',
            f'<text x="{margin_x + 502}" y="{legend_y + 4}" font-family="Malgun Gothic, Arial, sans-serif" font-size="12" fill="#52637a">관계/요약</text>',
            f'<rect x="{width - 255}" y="{legend_y - 18}" width="18" height="18" rx="3" fill="#dff2d9" stroke="#2f7d32"/>',
            f'<text x="{width - 228}" y="{legend_y - 4}" font-family="Malgun Gothic, Arial, sans-serif" font-size="12" fill="#52637a">조회 기업 강조</text>',
        ]
    )
    parts.append("</svg>")
    out_path.write_text("\n".join(parts), encoding="utf-8")


def render_graphviz(dot_path: Path, svg_path: Path) -> bool:
    dot = shutil.which("dot")
    if not dot:
        return False
    subprocess.run([dot, "-Tsvg", str(dot_path), "-o", str(svg_path)], check=True)
    return True


def hierarchy_positions(root: str, edges: list[Edge]) -> dict[str, tuple[float, float]]:
    graph = defaultdict(list)
    nodes = {root}
    for edge in edges:
        graph[edge.source].append(edge.target)
        nodes.add(edge.source)
        nodes.add(edge.target)
    levels = {root: 0}
    q: deque[str] = deque([root])
    while q:
        node = q.popleft()
        for child in graph.get(node, []):
            if child not in levels:
                levels[child] = levels[node] + 1
                q.append(child)
    for node in nodes:
        levels.setdefault(node, 1)
    by_level: dict[int, list[str]] = defaultdict(list)
    for node, level in levels.items():
        by_level[level].append(node)
    pos: dict[str, tuple[float, float]] = {}
    for level, level_nodes in by_level.items():
        level_nodes.sort()
        denom = max(1, len(level_nodes) - 1)
        for idx, node in enumerate(level_nodes):
            pos[node] = (idx / denom if denom else 0.5, -level)
    return pos


def draw_networkx_png(title: str, root: str, edges: list[Edge], highlight: str, out_path: Path) -> None:
    by_source: dict[str, list[Edge]] = defaultdict(list)
    for edge in edges:
        by_source[key_name(edge.source)].append(edge)
    root_key = key_name(root)
    for source_key in by_source:
        if source_key != root_key:
            by_source[source_key].sort(key=edge_priority, reverse=True)

    direct_edges = list(by_source.get(root_key, []))
    if not direct_edges:
        direct_edges = [Edge(root, edge.target, edge.rate, edge.relation_type) for edge in edges[:8]]

    graph = nx.DiGraph()
    labels: dict[str, str] = {"root": "\n".join(wrap_label(root, 9, 2))}
    display_for_node: dict[str, str] = {"root": root}
    edge_ref: dict[tuple[str, str], Edge] = {}
    pos: dict[str, tuple[float, float]] = {}

    source_gap = 3.2
    row_gap = 1.05
    max_children = 1
    root_x = (len(direct_edges) - 1) * source_gap / 2
    pos["root"] = (root_x, 1.7)

    for source_idx, edge in enumerate(direct_edges):
        source_id = f"source:{source_idx}"
        source_x = source_idx * source_gap
        pos[source_id] = (source_x, 0.15)
        labels[source_id] = "\n".join(wrap_label(edge.target, 9, 2))
        display_for_node[source_id] = edge.target
        graph.add_edge("root", source_id)
        edge_ref[("root", source_id)] = edge

        children = [
            child
            for child in by_source.get(key_name(edge.target), [])
            if key_name(child.target) != key_name(root)
        ]
        max_children = max(max_children, len(children))
        for child_idx, child in enumerate(children):
            child_id = f"child:{source_idx}:{child_idx}"
            pos[child_id] = (source_x, -0.95 - child_idx * row_gap)
            labels[child_id] = "\n".join(wrap_label(child.target, 9, 2))
            display_for_node[child_id] = child.target
            graph.add_edge(source_id, child_id)
            edge_ref[(source_id, child_id)] = child

    aggregate_nodes = {
        display
        for display in display_for_node.values()
        if any(edge.aggregate and key_name(edge.target) == key_name(display) for edge in edges)
    }
    parent_displays = {edge.source for edge in edges}
    node_colors_list = [
        node_colors(display_for_node[node], root, highlight, aggregate_nodes, parent_displays)[0]
        for node in graph.nodes
    ]
    edge_colors = [line_style(edge_ref[(source, target)])[0] for source, target in graph.edges]
    edge_widths = [line_style(edge_ref[(source, target)])[1] for source, target in graph.edges]
    edge_labels = {(source, target): rate_label(edge) for (source, target), edge in edge_ref.items()}

    fig_w = max(15, len(direct_edges) * 2.5)
    fig_h = max(8, 3.2 + max_children * 0.75)
    plt.figure(figsize=(fig_w, fig_h), facecolor="#f8fafc")
    ax = plt.gca()
    ax.set_facecolor("#f8fafc")
    nx.draw_networkx_edges(
        graph,
        pos,
        ax=ax,
        edge_color=edge_colors,
        arrows=True,
        arrowsize=16,
        width=edge_widths,
        connectionstyle="arc3,rad=0.02",
    )
    nx.draw_networkx_nodes(graph, pos, ax=ax, node_color=node_colors_list, edgecolors="#64748b", node_size=2500)
    nx.draw_networkx_labels(graph, pos, labels=labels, font_family="Malgun Gothic", font_size=8, font_weight="bold")
    nx.draw_networkx_edge_labels(
        graph,
        pos,
        edge_labels=edge_labels,
        font_size=7,
        font_color="#334155",
        font_family="Malgun Gothic",
        rotate=False,
    )
    ax.set_title(f"{title} NetworkX 분기형 비교 시각화", fontdict={"fontsize": 18, "fontweight": "bold"})
    ax.axis("off")
    plt.tight_layout()
    plt.savefig(out_path, dpi=170)
    plt.close()


def draw_sankey_html(title: str, root: str, edges: list[Edge], out_path: Path) -> None:
    nodes = sorted({root} | {edge.source for edge in edges} | {edge.target for edge in edges})
    index = {node: idx for idx, node in enumerate(nodes)}
    values = []
    colors = []
    for edge in edges:
        values.append(max(edge.rate or 5, 5))
        colors.append(line_style(edge)[0])
    fig = go.Figure(
        data=[
            go.Sankey(
                arrangement="snap",
                node={"label": nodes, "pad": 18, "thickness": 16, "color": "#dbeafe"},
                link={
                    "source": [index[edge.source] for edge in edges],
                    "target": [index[edge.target] for edge in edges],
                    "value": values,
                    "label": [rate_label(edge) for edge in edges],
                    "color": colors,
                },
            )
        ]
    )
    fig.update_layout(title_text=f"{title} Plotly Sankey 비교 시각화", font_size=11)
    fig.write_html(str(out_path), include_plotlyjs="cdn", full_html=True)


def build_one(
    target: dict[str, Any],
    out_base_dir: Path = OUT_DIR,
    include_experiments: bool = True,
) -> dict[str, Any]:
    if target["mode"] == "group":
        root, edges, meta = build_samsung_group_graph(target["highlight"])
    elif target["mode"] == "single_path":
        root, edges, meta = build_single_graph_from_source_path(Path(target["source_path"]), target["title"])
    else:
        root, edges, meta = build_single_graph(target["code"], target["title"])

    out_dir = out_base_dir / target["slug"]
    out_dir.mkdir(parents=True, exist_ok=True)
    structure_svg = out_dir / f"{target['slug']}_affiliate_structure.svg"
    dot_path = out_dir / f"{target['slug']}_graphviz.dot"
    graphviz_svg = out_dir / f"{target['slug']}_graphviz.svg"
    networkx_png = out_dir / f"{target['slug']}_networkx.png"
    sankey_html = out_dir / f"{target['slug']}_sankey.html"
    data_json = out_dir / f"{target['slug']}_visual_data.json"

    if not edges:
        status = "no_affiliates" if meta.get("source_mode") == "no_affiliates" else "skipped_insufficient_data"
        for stale_path in (structure_svg, dot_path, graphviz_svg, networkx_png, sankey_html):
            if stale_path.exists():
                stale_path.unlink()
        payload = {
            "target": target,
            "root": root,
            "meta": meta,
            "edges": [],
            "files": {},
            "status": status,
            "used_graphviz_dot": False,
        }
        data_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    draw_branch_structure_svg(target["title"], root, edges, target["highlight"], structure_svg, meta)
    files = {"structure_svg": str(structure_svg)}
    used_dot = False
    if include_experiments:
        dot_path.write_text(build_dot(target["title"], root, edges, target["highlight"]), encoding="utf-8")
        used_dot = render_graphviz(dot_path, graphviz_svg)
        draw_networkx_png(target["title"], root, edges, target["highlight"], networkx_png)
        draw_sankey_html(target["title"], root, edges, sankey_html)
        files.update(
            {
                "graphviz_dot": str(dot_path),
                "graphviz_svg": str(graphviz_svg) if used_dot else "",
                "networkx_png": str(networkx_png),
                "sankey_html": str(sankey_html),
            }
        )
    payload = {
        "target": target,
        "root": root,
        "meta": meta,
        "edges": [asdict(edge) for edge in edges],
        "files": files,
        "status": "generated_structure_diagram",
        "used_graphviz_dot": used_dot,
    }
    data_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def payload_summary(payload: dict[str, Any]) -> dict[str, Any]:
    target = payload["target"]
    return {
        "slug": target["slug"],
        "stock_code": target.get("code", ""),
        "title": target["title"],
        "root": payload.get("root", ""),
        "mode": target["mode"],
        "status": payload.get("status", ""),
        "source_mode": payload.get("meta", {}).get("source_mode", ""),
        "total_edges": payload.get("meta", {}).get("total_edges"),
        "shown_edges": len(payload.get("edges") or []),
        "has_original_image": False,
        "original_visual_path": "",
        "structure_svg": payload.get("files", {}).get("structure_svg", ""),
        "visual_data_json": "",
        "error": payload.get("error", ""),
    }


def write_summary(out_dir: Path, records: list[dict[str, Any]], name: str = "_summary") -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{name}.json"
    csv_path = out_dir / f"{name}.csv"
    json_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    if not records:
        csv_path.write_text("", encoding="utf-8")
        return
    fields = list(records[0].keys())
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)


def source_dirs_for_batch(codes: list[str] | None = None) -> list[Path]:
    source_dirs = sorted(path for path in SOURCE_DIR.iterdir() if path.is_dir() and (path / "affiliate_visual_data.json").exists())
    if not codes:
        return source_dirs
    code_set = set(codes)
    return [path for path in source_dirs if split_source_dir_name(path)[0] in code_set]


def run_samples(out_dir: Path, include_experiments: bool) -> list[dict[str, Any]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = []
    for target in TARGETS:
        payload = build_one(target, out_base_dir=out_dir, include_experiments=include_experiments)
        record = payload_summary(payload)
        summary.append(record)
        print(f"[{target['title']}] {record['shown_edges']}/{record['total_edges']} edges -> {record['structure_svg']}")
    write_summary(out_dir, summary)
    return summary


def run_batch(args: argparse.Namespace) -> list[dict[str, Any]]:
    out_dir = args.out_dir or BATCH_OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    all_source_dirs = source_dirs_for_batch()
    source_dirs = source_dirs_for_batch(args.code)
    common_bases = {
        common_share_base(split_source_dir_name(path)[1])
        for path in all_source_dirs
        if common_share_base(split_source_dir_name(path)[1])
    }
    if args.limit is not None:
        source_dirs = source_dirs[: args.limit]

    total = len(source_dirs)
    for idx, source_path in enumerate(source_dirs, start=1):
        target = source_dir_to_target(source_path)
        metadata = load_metadata(source_path)
        try:
            excluded_reason = excluded_security_reason(source_path, common_bases)
            if excluded_reason and not args.include_excluded:
                has_original = has_original_visual(source_path, metadata)
                stale_dir = out_dir / target["slug"]
                if stale_dir.exists():
                    shutil.rmtree(stale_dir)
                record = {
                    "slug": target["slug"],
                    "stock_code": target.get("code", ""),
                    "title": target["title"],
                    "root": target["title"],
                    "mode": target["mode"],
                    "status": "excluded_security_type",
                    "source_mode": excluded_reason,
                    "total_edges": "",
                    "shown_edges": "",
                    "has_original_image": has_original,
                    "original_visual_path": original_visual_path(source_path, metadata) if has_original else "",
                    "structure_svg": "",
                    "visual_data_json": "",
                    "error": "",
                }
                records.append(record)
                print(f"[{idx}/{total}] {target['slug']} -> excluded ({excluded_reason})")
                continue

            if has_original_visual(source_path, metadata) and not args.redraw_original:
                stale_dir = out_dir / target["slug"]
                if stale_dir.exists():
                    shutil.rmtree(stale_dir)
                record = {
                    "slug": target["slug"],
                    "stock_code": target.get("code", ""),
                    "title": target["title"],
                    "root": target["title"],
                    "mode": target["mode"],
                    "status": "original_image_reused",
                    "source_mode": metadata.get("source_type", "original_dart_image"),
                    "total_edges": "",
                    "shown_edges": "",
                    "has_original_image": True,
                    "original_visual_path": original_visual_path(source_path, metadata),
                    "structure_svg": "",
                    "visual_data_json": "",
                    "error": metadata.get("metadata_error", ""),
                }
                records.append(record)
                print(f"[{idx}/{total}] {target['slug']} -> original image")
                continue

            payload = build_one(target, out_base_dir=out_dir, include_experiments=args.with_experiments)
            record = payload_summary(payload)
            record["visual_data_json"] = str(out_dir / target["slug"] / f"{target['slug']}_visual_data.json")
            records.append(record)
            print(f"[{idx}/{total}] {target['slug']} -> {record['status']} ({record['shown_edges']} edges)")
        except Exception as exc:
            record = {
                "slug": target["slug"],
                "stock_code": target.get("code", ""),
                "title": target["title"],
                "root": "",
                "mode": target["mode"],
                "status": "error",
                "source_mode": "",
                "total_edges": "",
                "shown_edges": "",
                "has_original_image": False,
                "original_visual_path": "",
                "structure_svg": "",
                "visual_data_json": "",
                "error": str(exc),
            }
            records.append(record)
            print(f"[{idx}/{total}] {target['slug']} -> error: {exc}")

    write_summary(out_dir, records)
    return records


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="계열회사 구조도 샘플/전체 배치 생성")
    parser.add_argument("--all", action="store_true", help="output/affiliate_visualization 전체 종목을 배치 처리")
    parser.add_argument("--limit", type=int, default=None, help="--all 실행 시 처리할 최대 종목 수")
    parser.add_argument("--code", action="append", help="특정 종목코드만 처리. 여러 번 지정 가능")
    parser.add_argument("--out-dir", type=Path, default=None, help="출력 폴더. 기본: 샘플은 affiliate_structure_samples, 전체 배치는 affiliate_structure_batch")
    parser.add_argument("--redraw-original", action="store_true", help="DART 원본 이미지가 있어도 계열회사 구조도를 새로 생성")
    parser.add_argument("--include-excluded", action="store_true", help="우선주/스팩도 제외하지 않고 처리")
    parser.add_argument("--with-experiments", action="store_true", help="NetworkX/Sankey/Graphviz 보조 산출물도 함께 생성")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.all or args.code:
        records = run_batch(args)
        out_dir = args.out_dir or BATCH_OUT_DIR
        generated = sum(1 for record in records if record["status"] == "generated_structure_diagram")
        reused = sum(1 for record in records if record["status"] == "original_image_reused")
        no_affiliates = sum(1 for record in records if record["status"] == "no_affiliates")
        skipped = sum(1 for record in records if record["status"] == "skipped_insufficient_data")
        excluded = sum(1 for record in records if record["status"] == "excluded_security_type")
        errors = sum(1 for record in records if record["status"] == "error")
        print(
            f"완료: generated={generated}, original={reused}, no_affiliates={no_affiliates}, "
            f"skipped={skipped}, excluded={excluded}, errors={errors}"
        )
        print(f"summary: {out_dir / '_summary.json'}")
        return

    out_dir = args.out_dir or OUT_DIR
    records = run_samples(out_dir, include_experiments=True)
    print(f"완료: samples={len(records)}")
    print(f"summary: {out_dir / '_summary.json'}")


if __name__ == "__main__":
    main()
