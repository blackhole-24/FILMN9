"""
DART XML root → 임베딩용 JSONL 청크 리스트.

특징:
- 표·문장 인식 청킹 (검색 정확도 ↑)
- 표 직전 P 가 짧으면 캡션으로 결합
- "(단위 : 백만원)" 행은 prefix 로 항상 동행
- 분할 시 매 조각에 캡션·단위·헤더 재삽입
- 단일 셀에 본문이 통째로 들어간 "레이아웃 표" 는 텍스트로 변환
- 한국어 문장 경계 splitter (안전망)

청크 1개 = 임베딩 1건. JSONL 한 줄 = 청크 1개.
"""
from __future__ import annotations
import re
from typing import Optional

import config as cfg


# ─────────────────────────────────────────────────────────────────────────────
# 정규식
# ─────────────────────────────────────────────────────────────────────────────
CELL_TAGS    = {"TH", "TD", "TE"}
SECTION_TAGS = {"SECTION-1", "SECTION-2", "SECTION-3"}

CAPTION_RE = re.compile(r"(추이|현황|내역|목록|구성|요약|총괄|분포|통계|구분|상세|개요|비교|규모|실적)\s*$")
SENT_RE    = re.compile(r"(?<=[다요음])\s+|(?<=[\.\?\!])\s+|\n\n")


# ─────────────────────────────────────────────────────────────────────────────
# 보조 함수
# ─────────────────────────────────────────────────────────────────────────────
def text_of(el) -> str:
    return " ".join(s.strip() for s in el.itertext() if s.strip())


def heading_of_section(sec) -> str:
    t = sec.find("./TITLE")
    return text_of(t)[:120] if t is not None else ""


def get_cells(tr) -> list:
    return [(ch.tag, text_of(ch)) for ch in tr if ch.tag in CELL_TAGS]


def looks_like_caption(t: str) -> bool:
    t = t.strip()
    if not t or len(t) > 150: return False
    if t.startswith(("[", "<", "(", "「", "【")): return True
    return len(t) < 40 or bool(CAPTION_RE.search(t))


# ─────────────────────────────────────────────────────────────────────────────
# 표 파싱
# ─────────────────────────────────────────────────────────────────────────────
def parse_table(tbl) -> dict:
    raw_rows = []
    theads = tbl.findall("./THEAD"); tbodies = tbl.findall("./TBODY")
    if theads or tbodies:
        for th in theads:
            for tr in th.findall(".//TR"):
                c = get_cells(tr); raw_rows.append((True, c)) if c else None
        for tb in tbodies:
            for tr in tb.findall(".//TR"):
                c = get_cells(tr); raw_rows.append((None, c)) if c else None
        for tr in tbl.findall("./TR"):
            c = get_cells(tr); raw_rows.append((None, c)) if c else None
    else:
        for tr in tbl.iter("TR"):
            c = get_cells(tr); raw_rows.append((None, c)) if c else None

    unit, cleaned = None, []
    for hh, cells in raw_rows:
        texts  = [t for _, t in cells]
        joined = " ".join(texts).strip()
        if "단위" in joined and len(joined) < 60 and (":" in joined or "：" in joined):
            unit = re.sub(r"\s+", " ", joined); continue
        if not any(t.strip() for t in texts): continue
        if hh is True:
            cleaned.append(("H", texts))
        else:
            thn = sum(1 for tg, _ in cells if tg == "TH")
            cleaned.append(("H" if thn >= len(cells)*0.5 and thn >= 1 else "B", texts))

    hdr, body, sb = [], [], False
    for k, t in cleaned:
        if k == "H" and not sb: hdr.append(t)
        else: sb = True; body.append(t)
    return {"header_rows": hdr, "body_rows": body, "unit": unit}


def is_prose_table(t: dict) -> bool:
    rows = t["header_rows"] + t["body_rows"]
    if not rows: return False
    if any(len(c) > cfg.PROSE_CELL_THRESHOLD for r in rows for c in r): return True
    mc = max(len(r) for r in rows)
    if len(rows) <= 2 and mc <= 2 and sum(len(c) for r in rows for c in r) > cfg.PROSE_TABLE_TOTAL:
        return True
    return False


def table_to_prose(t: dict, caption: Optional[str]) -> str:
    parts = []
    if caption:    parts.append(caption)
    if t["unit"]: parts.append(t["unit"])
    for r in t["header_rows"] + t["body_rows"]:
        line = " ".join(c for c in r if c.strip())
        if line: parts.append(line)
    return "\n\n".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# 안전망 splitter
# ─────────────────────────────────────────────────────────────────────────────
def hard_split(text: str, limit: Optional[int] = None,
               overlap: Optional[int] = None) -> list:
    limit   = limit   or cfg.CHAR_LIMIT
    overlap = overlap or cfg.OVERLAP
    if len(text) <= limit: return [text]
    out, i = [], 0
    while i < len(text):
        end = min(len(text), i + limit)
        if end < len(text):
            nl = text.rfind("\n\n", i, end)
            if nl > i + int(limit*0.5):
                end = nl
            else:
                last_m = None
                for mm in SENT_RE.finditer(text, i, end):
                    last_m = mm
                if last_m and last_m.start() > i + int(limit*0.4):
                    end = last_m.start()
        out.append(text[i:end].strip())
        if end >= len(text): break
        i = max(end - overlap, i + 1)
    return [c for c in out if c]


# ─────────────────────────────────────────────────────────────────────────────
# 표 → 청크 (캡션·단위·헤더 prefix 복제)
# ─────────────────────────────────────────────────────────────────────────────
def render_table_chunks(t: dict, caption: Optional[str]) -> list:
    hdr, body, unit = t["header_rows"], t["body_rows"], t["unit"]
    all_rows = hdr + body
    if not all_rows: return []
    mc  = max(len(r) for r in all_rows)
    pad = lambda r: r + [""] * (mc - len(r))
    hdr  = [pad(r) for r in hdr]
    body = [pad(r) for r in body]

    pl = []
    if caption: pl.append(f"[표] {caption}")
    if unit:    pl.append(unit)
    if hdr:
        if len(hdr) > 1:
            ctx = " | ".join(" / ".join(c for c in row if c.strip())
                             for row in hdr[:-1] if any(c.strip() for c in row))
            if ctx: pl.append(f"(상위 헤더: {ctx})")
        pl.append("| " + " | ".join(hdr[-1]) + " |")
        pl.append("| " + " | ".join(["---"] * mc) + " |")
    prefix = "\n".join(pl)

    body_lines = ["| " + " | ".join(r) + " |" for r in body]
    if not body_lines:
        return [prefix] if prefix else []

    full = prefix + ("\n" if prefix else "") + "\n".join(body_lines)
    if len(full) <= cfg.CHAR_LIMIT:
        return [full]

    chunks, cur, cur_len = [], [], len(prefix) + 1
    for ln in body_lines:
        if cur and cur_len + len(ln) + 1 > cfg.CHAR_LIMIT:
            chunks.append(prefix + "\n" + "\n".join(cur))
            cur, cur_len = [ln], len(prefix) + 1 + len(ln) + 1
        else:
            cur.append(ln); cur_len += len(ln) + 1
    if cur: chunks.append(prefix + "\n" + "\n".join(cur))
    out = []
    for c in chunks:
        out.extend(hard_split(c) if len(c) > cfg.CHAR_LIMIT else [c])
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 메인 — XML root → 청크 리스트
# ─────────────────────────────────────────────────────────────────────────────
def build_chunks(root, meta: dict) -> list:
    """
    Args:
        root: lxml Element (정제된 DART XML)
        meta: 각 청크에 부착할 메타데이터 dict
              (예: stock_code, name, report_kind, fiscal_period, source_url, ...)

    Returns:
        list of dict — 각 dict 가 JSONL 한 줄
    """
    items = []

    def walk(el, path):
        tag = el.tag
        if tag in SECTION_TAGS:
            h = heading_of_section(el)
            np_ = path + [h] if h else list(path)
            for ch in el: walk(ch, np_)
            return
        if tag == "TITLE": return
        if tag == "P":
            t = text_of(el)
            if t: items.append({"kind": "p", "path": list(path), "text": t})
            return
        if tag == "TABLE":
            td = parse_table(el)
            if td["header_rows"] or td["body_rows"]:
                items.append({"kind": "table", "path": list(path),
                              "data": td, "caption": None})
            return
        for ch in el: walk(ch, path)

    walk(root, [])

    # 표 직전 짧은 P → 캡션으로 결합
    ni = []
    for it in items:
        if it["kind"] == "table" and ni and ni[-1]["kind"] == "p" \
           and ni[-1]["path"] == it["path"] and looks_like_caption(ni[-1]["text"]):
            it["caption"] = ni.pop()["text"]
        ni.append(it)
    items = ni

    # prose-table → text
    items = [
        {"kind": "p", "path": it["path"], "text": table_to_prose(it["data"], it.get("caption"))}
        if it["kind"] == "table" and is_prose_table(it["data"]) else it
        for it in items
    ]

    # 같은 path 내 P 들은 묶어서 chunk + 표는 별도 청크
    chunks, pbuf, ppath = [], [], None
    def flush():
        nonlocal pbuf, ppath
        if not pbuf or ppath is None: pbuf = []; return
        full = "\n\n".join(pbuf).strip()
        if full:
            for piece in hard_split(full):
                chunks.append({"path": list(ppath), "text": piece, "kind": "text"})
        pbuf = []

    for it in items:
        p = tuple(it["path"]) if it["path"] else ("(문서 본문)",)
        if it["kind"] == "p":
            if ppath is None: ppath = p
            if p != ppath: flush(); ppath = p
            pbuf.append(it["text"])
        else:
            if pbuf: flush()
            ppath = p
            for txt in render_table_chunks(it["data"], it.get("caption")):
                for piece in (hard_split(txt) if len(txt) > cfg.CHAR_LIMIT else [txt]):
                    chunks.append({"path": list(it["path"]) or ["(문서 본문)"],
                                   "text": piece, "kind": "table"})
    flush()

    # 메타데이터 부착
    return [
        {
            "id": f"{meta['stock_code']}-{meta['report_kind']}-{i:05d}",
            **meta,
            "kind":             c["kind"],
            "section_path":     c["path"],
            "section_path_str": " > ".join(c["path"]),
            "char_len":         len(c["text"]),
            "text":             c["text"],
        }
        for i, c in enumerate(chunks)
    ]


if __name__ == "__main__":
    print("chunker.py — 단독 실행 X. pipeline.py 또는 pipeline.ipynb 에서 호출됨.")
