from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from collections import defaultdict, deque
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any


def find_project_root(start: Path) -> Path:
    for path in (start, *start.parents):
        if (path / "output" / "affiliate_visualization").exists():
            return path
    return start


ROOT = find_project_root(Path(__file__).resolve().parents[1])
VISUAL_DIR = ROOT / "output" / "affiliate_visualization"
OUT_DIR = ROOT / "output" / "affiliate_visualization_graphviz_samples"

TARGETS = {
    "000070": "삼양홀딩스",
    "005930": "삼성전자",
    "028260": "삼성물산",
    "096770": "SK이노베이션",
    "005490": "POSCO홀딩스",
}


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    rate: float | None
    relation_type: str
    purpose: str | None = None
    aggregate: bool = False


def load_company_data(stock_code: str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    matches = sorted(VISUAL_DIR.glob(f"{stock_code}_*/affiliate_visual_data.json"))
    if not matches:
        raise FileNotFoundError(f"No affiliate visual data for {stock_code}")
    data_path = matches[0]
    meta_path = data_path.with_name("affiliate_visual_metadata.json")
    data = json.loads(data_path.read_text(encoding="utf-8"))
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    return data_path.parent, data, meta


def clean_name(value: str) -> str:
    value = re.sub(r"\s*\(주\d+\)\s*", "", value or "").strip()
    value = re.sub(r"\s+", " ", value)
    return value


def select_root(nodes: list[dict[str, Any]], edges: list[Edge], fallback: str) -> str:
    for node in nodes:
        if node.get("role") == "reporting_company":
            return clean_name(str(node.get("name") or node.get("id") or fallback))
    sources = {edge.source for edge in edges}
    targets = {edge.target for edge in edges}
    roots = sorted(sources - targets)
    return roots[0] if roots else fallback


def to_edges(raw_edges: list[dict[str, Any]]) -> list[Edge]:
    result: list[Edge] = []
    for item in raw_edges:
        source = clean_name(str(item.get("from") or ""))
        target = clean_name(str(item.get("to") or ""))
        if not source or not target or source == target:
            continue
        rate = item.get("ownership_rate")
        try:
            rate = float(rate) if rate is not None and rate != "" else None
        except (TypeError, ValueError):
            rate = None
        result.append(
            Edge(
                source=source,
                target=target,
                rate=rate,
                relation_type=str(item.get("relation_type") or "investment"),
                purpose=item.get("purpose"),
            )
        )
    return result


def edge_sort_key(edge: Edge) -> tuple[int, float, str]:
    has_rate = 1 if edge.rate is not None else 0
    return (has_rate, edge.rate or -1.0, edge.target)


def build_focus_edges(root: str, all_edges: list[Edge]) -> tuple[list[Edge], dict[str, int]]:
    by_source: dict[str, list[Edge]] = defaultdict(list)
    for edge in all_edges:
        by_source[edge.source].append(edge)
    for source in by_source:
        by_source[source].sort(key=edge_sort_key, reverse=True)

    max_direct = 24
    max_child = 4
    selected: list[Edge] = []
    omitted = {"direct": 0, "child": 0}

    direct_edges = by_source.get(root, [])
    selected.extend(direct_edges[:max_direct])
    if len(direct_edges) > max_direct:
        omitted["direct"] = len(direct_edges) - max_direct
        selected.append(Edge(root, f"기타 직접 투자 {omitted['direct']}개", None, "summary", aggregate=True))

    selected_targets = {edge.target for edge in selected if not edge.aggregate}
    for parent in sorted(selected_targets):
        child_edges = [edge for edge in by_source.get(parent, []) if edge.target != root]
        if not child_edges:
            continue
        selected.extend(child_edges[:max_child])
        if len(child_edges) > max_child:
            count = len(child_edges) - max_child
            omitted["child"] += count
            selected.append(Edge(parent, f"{parent} 기타 {count}개", None, "summary", aggregate=True))

    if len(all_edges) <= 45:
        seen = {(edge.source, edge.target) for edge in selected}
        for edge in all_edges:
            if (edge.source, edge.target) not in seen:
                selected.append(edge)
                seen.add((edge.source, edge.target))

    deduped: list[Edge] = []
    seen_edges: set[tuple[str, str]] = set()
    for edge in selected:
        key = (edge.source, edge.target)
        if key in seen_edges:
            continue
        seen_edges.add(key)
        deduped.append(edge)
    return deduped, omitted


def levels_for(root: str, edges: list[Edge]) -> dict[str, int]:
    children: dict[str, list[str]] = defaultdict(list)
    nodes = {root}
    for edge in edges:
        children[edge.source].append(edge.target)
        nodes.add(edge.source)
        nodes.add(edge.target)

    levels = {root: 0}
    queue: deque[str] = deque([root])
    while queue:
        node = queue.popleft()
        for child in children.get(node, []):
            if child in levels:
                continue
            levels[child] = levels[node] + 1
            queue.append(child)

    for node in sorted(nodes):
        levels.setdefault(node, 1)
    return levels


def wrap_label(text: str, max_chars: int = 13, max_lines: int = 3) -> list[str]:
    text = clean_name(text)
    if len(text) <= max_chars:
        return [text]

    parts: list[str] = []
    current = ""
    tokens = re.split(r"([ \-/·])", text)
    for token in tokens:
        if not token:
            continue
        if len(current) + len(token) <= max_chars:
            current += token
        else:
            if current:
                parts.append(current.strip())
            current = token.strip()
    if current:
        parts.append(current.strip())

    lines: list[str] = []
    for part in parts:
        while len(part) > max_chars:
            lines.append(part[:max_chars])
            part = part[max_chars:]
        if part:
            lines.append(part)

    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][: max_chars - 1] + "…"
    return lines


def node_style(node: str, root: str, outgoing: set[str], aggregate_nodes: set[str]) -> tuple[str, str, str, str]:
    if node == root:
        return "#1f3a5f", "#1f3a5f", "#ffffff", "root"
    if node in aggregate_nodes:
        return "#fff7d6", "#d4a72c", "#4b5563", "aggregate"
    if node in outgoing:
        return "#e3f1df", "#7aa36f", "#111827", "parent"
    return "#ffffff", "#b8c2cc", "#111827", "child"


def edge_style(edge: Edge) -> tuple[str, float, str]:
    if edge.aggregate:
        return "#9ca3af", 1.4, "6 4"
    if edge.rate is None:
        return "#9ca3af", 1.4, "5 3"
    if edge.rate >= 50:
        return "#1d4ed8", 3.0, ""
    if edge.rate >= 20:
        return "#3b82f6", 2.2, ""
    return "#9ca3af", 1.4, ""


def edge_label(edge: Edge) -> str:
    if edge.aggregate:
        return "요약"
    if edge.rate is None:
        return edge.purpose or "관계"
    return f"{edge.rate:g}%"


def build_svg(title: str, root: str, edges: list[Edge], omitted: dict[str, int]) -> str:
    levels = levels_for(root, edges)
    by_level: dict[int, list[str]] = defaultdict(list)
    nodes = sorted({root} | {edge.source for edge in edges} | {edge.target for edge in edges})
    rate_by_target = {edge.target: edge.rate or -1 for edge in edges}
    for node in nodes:
        by_level[levels[node]].append(node)
    for level, items in by_level.items():
        by_level[level] = sorted(items, key=lambda x: (x != root, -rate_by_target.get(x, -1), x))

    node_w = 190
    node_h = 58
    gap_x = 42
    gap_y = 90
    margin_x = 48
    margin_top = 106
    max_cols = 7

    positions: dict[str, tuple[float, float]] = {}
    canvas_w = 0
    y = margin_top
    for level in sorted(by_level):
        items = by_level[level]
        rows = math.ceil(len(items) / max_cols)
        for row in range(rows):
            chunk = items[row * max_cols : (row + 1) * max_cols]
            row_w = len(chunk) * node_w + max(0, len(chunk) - 1) * gap_x
            canvas_w = max(canvas_w, row_w + margin_x * 2)
            start_x = margin_x + (max(0, max_cols - len(chunk)) * (node_w + gap_x) / 2)
            for idx, node in enumerate(chunk):
                positions[node] = (start_x + idx * (node_w + gap_x), y)
            y += node_h + (gap_y * 0.62 if row < rows - 1 else gap_y)
    canvas_w = max(canvas_w, 980)
    canvas_h = y + 38

    outgoing = {edge.source for edge in edges}
    aggregate_nodes = {edge.target for edge in edges if edge.aggregate}

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{canvas_w:.0f}" height="{canvas_h:.0f}" viewBox="0 0 {canvas_w:.0f} {canvas_h:.0f}">',
        "<defs>",
        '<marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto" markerUnits="strokeWidth">',
        '<path d="M0,0 L8,4 L0,8 z" fill="#6b7280"/>',
        "</marker>",
        '<filter id="shadow" x="-10%" y="-10%" width="120%" height="120%">',
        '<feDropShadow dx="0" dy="2" stdDeviation="2" flood-color="#000000" flood-opacity="0.13"/>',
        "</filter>",
        "</defs>",
        '<rect width="100%" height="100%" fill="#f8fafc"/>',
        f'<text x="48" y="42" font-family="Malgun Gothic, Arial, sans-serif" font-size="24" font-weight="700" fill="#111827">{escape(title)} 관계기업 구조 예시</text>',
        '<text x="48" y="70" font-family="Malgun Gothic, Arial, sans-serif" font-size="13" fill="#64748b">Graphviz dot 적용 방향: rankdir=TB, 지분율별 선 두께, 원본 이미지 없을 때 생성형 SVG</text>',
    ]
    if omitted.get("direct") or omitted.get("child"):
        text = f"표시 축약: 직접 {omitted.get('direct', 0)}개, 하위 {omitted.get('child', 0)}개"
        parts.append(
            f'<text x="{canvas_w - 48:.0f}" y="70" text-anchor="end" font-family="Malgun Gothic, Arial, sans-serif" font-size="12" fill="#64748b">{escape(text)}</text>'
        )

    for edge in edges:
        x1, y1 = positions[edge.source]
        x2, y2 = positions[edge.target]
        sx = x1 + node_w / 2
        sy = y1 + node_h
        tx = x2 + node_w / 2
        ty = y2
        color, width, dash = edge_style(edge)
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        curve = max(42, min(95, (ty - sy) * 0.48))
        path = f"M {sx:.1f},{sy:.1f} C {sx:.1f},{sy + curve:.1f} {tx:.1f},{ty - curve:.1f} {tx:.1f},{ty:.1f}"
        parts.append(
            f'<path d="{path}" fill="none" stroke="{color}" stroke-width="{width}"{dash_attr} marker-end="url(#arrow)" opacity="0.9"/>'
        )
        label_x = tx
        label_y = ty - 10
        label = edge_label(edge)
        label_w = max(34, min(86, len(label) * 7 + 12))
        parts.append(
            f'<rect x="{label_x - label_w / 2:.1f}" y="{label_y - 13:.1f}" width="{label_w}" height="16" rx="8" fill="#f8fafc" opacity="0.88"/>'
        )
        parts.append(
            f'<text x="{label_x:.1f}" y="{label_y:.1f}" text-anchor="middle" font-family="Arial, sans-serif" font-size="11" font-weight="700" fill="{color}">{escape(label)}</text>'
        )

    for node in nodes:
        x, y_pos = positions[node]
        fill, stroke, text_color, kind = node_style(node, root, outgoing, aggregate_nodes)
        dash = ' stroke-dasharray="6 4"' if kind == "aggregate" else ""
        parts.append(
            f'<rect x="{x:.1f}" y="{y_pos:.1f}" width="{node_w}" height="{node_h}" rx="6" fill="{fill}" stroke="{stroke}" stroke-width="1.4"{dash} filter="url(#shadow)"/>'
        )
        lines = wrap_label(node)
        start_y = y_pos + 24 - (len(lines) - 1) * 8
        for idx, line in enumerate(lines):
            parts.append(
                f'<text x="{x + node_w / 2:.1f}" y="{start_y + idx * 16:.1f}" text-anchor="middle" font-family="Malgun Gothic, Arial, sans-serif" font-size="13" font-weight="700" fill="{text_color}">{escape(line)}</text>'
            )

    legend_y = canvas_h - 26
    parts.extend(
        [
            f'<line x1="48" y1="{legend_y}" x2="92" y2="{legend_y}" stroke="#1d4ed8" stroke-width="3"/>',
            f'<text x="100" y="{legend_y + 4}" font-family="Malgun Gothic, Arial, sans-serif" font-size="12" fill="#64748b">50% 이상</text>',
            f'<line x1="190" y1="{legend_y}" x2="234" y2="{legend_y}" stroke="#3b82f6" stroke-width="2.2"/>',
            f'<text x="242" y="{legend_y + 4}" font-family="Malgun Gothic, Arial, sans-serif" font-size="12" fill="#64748b">20~50%</text>',
            f'<line x1="324" y1="{legend_y}" x2="368" y2="{legend_y}" stroke="#9ca3af" stroke-width="1.4"/>',
            f'<text x="376" y="{legend_y + 4}" font-family="Malgun Gothic, Arial, sans-serif" font-size="12" fill="#64748b">20% 미만/관계</text>',
        ]
    )
    parts.append("</svg>")
    return "\n".join(parts)


def quote_dot(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def build_dot(title: str, root: str, edges: list[Edge]) -> str:
    nodes = sorted({root} | {edge.source for edge in edges} | {edge.target for edge in edges})
    outgoing = {edge.source for edge in edges}
    aggregate_nodes = {edge.target for edge in edges if edge.aggregate}
    lines = [
        "digraph affiliate_structure {",
        "  graph [rankdir=TB, splines=ortho, bgcolor=\"#f8fafc\", pad=0.35, nodesep=0.45, ranksep=0.85];",
        "  node [shape=box, style=\"rounded,filled\", fontname=\"Malgun Gothic\", margin=\"0.12,0.08\"];",
        "  edge [fontname=\"Malgun Gothic\", fontsize=10, arrowsize=0.7];",
        f"  label={quote_dot(title + ' 관계기업 구조 예시')};",
        "  labelloc=t;",
    ]
    for node in nodes:
        fill, stroke, text_color, kind = node_style(node, root, outgoing, aggregate_nodes)
        style = "rounded,filled,dashed" if kind == "aggregate" else "rounded,filled"
        lines.append(
            f"  {quote_dot(node)} [label={quote_dot(node)}, fillcolor={quote_dot(fill)}, color={quote_dot(stroke)}, fontcolor={quote_dot(text_color)}, style={quote_dot(style)}];"
        )
    for edge in edges:
        color, width, dash = edge_style(edge)
        style = "dashed" if dash else "solid"
        lines.append(
            f"  {quote_dot(edge.source)} -> {quote_dot(edge.target)} [label={quote_dot(edge_label(edge))}, color={quote_dot(color)}, penwidth={width:.1f}, style={quote_dot(style)}];"
        )
    lines.append("}")
    return "\n".join(lines)


def render_with_dot(dot_path: Path, svg_path: Path) -> bool:
    dot = shutil.which("dot")
    if not dot:
        return False
    subprocess.run([dot, "-Tsvg", str(dot_path), "-o", str(svg_path)], check=True)
    return True


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    summary: list[dict[str, Any]] = []
    for stock_code, title in TARGETS.items():
        company_dir, data, meta = load_company_data(stock_code)
        all_edges = to_edges(data.get("edges") or [])
        root = select_root(data.get("nodes") or [], all_edges, title)
        focus_edges, omitted = build_focus_edges(root, all_edges)
        base_name = f"{stock_code}_{title}_graphviz_style"
        dot_path = OUT_DIR / f"{base_name}.dot"
        svg_path = OUT_DIR / f"{base_name}.svg"
        fallback_path = OUT_DIR / f"{base_name}.fallback.svg"
        dot_path.write_text(build_dot(title, root, focus_edges), encoding="utf-8")
        used_dot = render_with_dot(dot_path, svg_path)
        if not used_dot:
            svg_path.write_text(build_svg(title, root, focus_edges, omitted), encoding="utf-8")
            fallback_path.write_text(svg_path.read_text(encoding="utf-8"), encoding="utf-8")
        summary.append(
            {
                "stock_code": stock_code,
                "title": title,
                "source_dir": str(company_dir),
                "source_type": meta.get("source_type"),
                "total_edges": len(all_edges),
                "shown_edges": len(focus_edges),
                "omitted": omitted,
                "dot_path": str(dot_path),
                "svg_path": str(svg_path),
                "used_graphviz_dot": used_dot,
            }
        )
        print(f"[{stock_code}] {title}: {len(focus_edges)}/{len(all_edges)} edges -> {svg_path}")
    (OUT_DIR / "_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
