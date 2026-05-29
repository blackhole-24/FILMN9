"""
DART 원본 XML → 표준 XML 파서가 받아들일 수 있는 정제본 (v4.1).

v4.1 변경:
- ":" 포함 토큰 (예: <ME:I>, <IS:SUE>) 무조건 본문 글자로 처리 (DART 미사용 namespace)
- 모호한 짧은 태그 (`<A>`) 는 속성 없이 등장하면 본문으로 escape 처리
  (DART 정상은 <A REFNO="...">목차</A> 형태)
"""
from __future__ import annotations
import re
import lxml.etree as ET


KNOWN_DART_TAGS = {
    "DOCUMENT", "LIBRARY", "BODY", "COVER", "COVER-TITLE", "SUMMARY",
    "DOCUMENT-NAME", "COMPANY-NAME", "FORMULA-VERSION", "EXTRACTION",
    "SECTION-1", "SECTION-2", "SECTION-3", "SECTION-4",
    "TITLE", "SUBTITLE", "PGBRK",
    "P", "BR", "HR", "SPAN", "FONT",
    "B", "I", "U", "STRONG", "EM", "SUP", "SUB",
    "TABLE", "TABLE-GROUP", "THEAD", "TBODY", "TFOOT",
    "TR", "TH", "TD", "TE", "TU",
    "COLGROUP", "COL", "CAPTION",
    "OL", "UL", "LI", "DL", "DT", "DD",
    "A", "IMG", "IMAGE", "IMG-CAPTION", "OBJECT", "EMBED",
    "DIV", "BLOCKQUOTE", "CITE", "CODE", "PRE", "Q",
}

# 모호한 짧은 태그 — 속성 없이 등장하면 본문 글자로 처리
AMBIGUOUS_REQUIRES_ATTR = {"A"}

_NAME = r"[A-Za-z_][A-Za-z0-9_\-]*(?::[A-Za-z_][A-Za-z0-9_\-]*)?"
_VALID_TAG_RE = re.compile(
    r'<\?[\s\S]*?\?>'
    r'|<!--[\s\S]*?-->'
    r'|<!\[CDATA\[[\s\S]*?\]\]>'
    r'|<!DOCTYPE[^>]*>'
    rf'|</(?P<close>{_NAME})\s*>'
    rf'|<(?P<open>{_NAME})(?:\s+{_NAME}\s*=\s*(?:"[^"]*"|\'[^\']*\'))*\s*/?>'
)


def _is_known_tag(tag_name: str) -> bool:
    """DART 는 namespace 미사용 → ':' 포함 토큰은 본문 글자로 처리."""
    if not tag_name:
        return False
    if ":" in tag_name:
        return False
    return tag_name.upper() in KNOWN_DART_TAGS


def clean_xml(text: str, *, log_unknown: bool = False) -> str:
    """
    1) `&` 가 valid entity ref 가 아니면 → `&amp;`
    2) `<` 가 화이트리스트 태그가 아니면 → `&lt;`
    3) <A> (속성 없음) 같은 모호한 태그도 본문으로 escape
    """
    text = re.sub(r"&(?!(amp|lt|gt|quot|apos|#\d+|#x[0-9A-Fa-f]+);)", "&amp;", text)

    out, last = [], 0
    unknown_seen = set()

    for m in _VALID_TAG_RE.finditer(text):
        try:
            tag_name = m.group("open") or m.group("close")
        except IndexError:
            tag_name = None

        # 1) 화이트리스트 검증
        if tag_name and not _is_known_tag(tag_name):
            unknown_seen.add(tag_name)
            continue

        # 2) AMBIGUOUS: <A> 가 속성 없으면 본문으로
        if tag_name and tag_name.upper() in AMBIGUOUS_REQUIRES_ATTR:
            is_open = bool(m.groupdict().get("open"))
            if is_open and "=" not in m.group(0):
                unknown_seen.add(f"{tag_name}(no-attr)")
                continue

        out.append(text[last:m.start()].replace("<", "&lt;"))
        out.append(m.group(0))
        last = m.end()

    out.append(text[last:].replace("<", "&lt;"))

    if log_unknown and unknown_seen:
        import sys
        sample = sorted(unknown_seen)[:20]
        print(f"[clean_xml v4.1] escaped unknown: {len(unknown_seen)} kinds, "
              f"sample={sample}", file=sys.stderr)

    return "".join(out)


def parse_with_fallback(cleaned_text: str) -> tuple:
    """strict 파서 우선, 실패 시 lxml recover 모드."""
    try:
        parser = ET.XMLParser(huge_tree=True, recover=False)
        return ET.fromstring(cleaned_text.encode("utf-8"), parser), "strict"
    except ET.XMLSyntaxError as e:
        parser = ET.XMLParser(huge_tree=True, recover=True)
        msg = e.msg.split(",")[0] if hasattr(e, "msg") else str(e)
        return ET.fromstring(cleaned_text.encode("utf-8"), parser), f"recover ({msg})"


if __name__ == "__main__":
    sample = '''<?xml version="1.0"?>
<DOCUMENT>
  <P>그룹 <ME:I>가 데뷔. <IS:SUE> 도 활동.</P>
  <P>본문 <A>#(KJ)#(HBA)<A>#(RE.3)</P>
  <P>이건 진짜 anchor: <A REFNO="section-1">목차</A></P>
  <P>제품 <ARpedia> 도 escape.</P>
  <TABLE><TR><TD>일반 셀</TD></TR></TABLE>
</DOCUMENT>'''
    cleaned = clean_xml(sample, log_unknown=True)
    print("── cleaned ──")
    print(cleaned)
    root, mode = parse_with_fallback(cleaned)
    print(f"\nmode: {mode}")
    print(f"A 태그 (실제 anchor): {len(root.findall('.//A'))}")
    print(f"TABLE 태그: {len(root.findall('.//TABLE'))}")
