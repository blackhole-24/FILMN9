"""
DART 원본 XML → 표준 XML 파서가 받아들일 수 있는 정제본으로 변환.

DART XML 의 흔한 비정상 패턴:
1. `&` 가 이스케이프 안 됨 ("R&D" → 표준 XML 파서는 entity 로 오인)
2. 본문에 literal "<…>" 가 들어있음 (예: "<ACI 세미나>") — 진짜 태그로 오인
3. 속성값 따옴표 누락 등

해결:
- clean_xml(text): & + 잘못된 < 자동 정제 (정규식 v3)
- parse_with_fallback(cleaned): strict 파서 → 실패 시 lxml recover 모드
"""
from __future__ import annotations
import re
import lxml.etree as ET


# ─────────────────────────────────────────────────────────────────────────────
# 정제 v3
# ─────────────────────────────────────────────────────────────────────────────
# 진짜 XML 태그·구문 매칭 — 이 외의 < 는 모두 본문 글자로 간주
_NAME = r"[A-Za-z_][A-Za-z0-9_\-]*(?::[A-Za-z_][A-Za-z0-9_\-]*)?"
_VALID_TAG_RE = re.compile(
    rf'<\?[\s\S]*?\?>'                                              # PI
    rf'|<!--[\s\S]*?-->'                                            # comment
    rf'|<!\[CDATA\[[\s\S]*?\]\]>'                                  # CDATA
    rf'|<!DOCTYPE[^>]*>'                                           # DOCTYPE
    rf'|</{_NAME}\s*>'                                              # end tag
    rf'|<{_NAME}(?:\s+{_NAME}\s*=\s*(?:"[^"]*"|\'[^\']*\'))*\s*/?>'  # start tag
)


def clean_xml(text: str) -> str:
    """
    1) `&` 가 valid entity ref (`&amp;`, `&lt;` 등) 가 아닌 경우 → `&amp;` 로 escape
    2) `<` 가 valid 태그 시작이 아니면 → `&lt;` 로 escape
    """
    # 1) & 정제
    text = re.sub(r"&(?!(amp|lt|gt|quot|apos|#\d+|#x[0-9A-Fa-f]+);)", "&amp;", text)
    # 2) < 정제 — valid 태그만 통과, 나머지 < 는 escape
    out, last = [], 0
    for m in _VALID_TAG_RE.finditer(text):
        out.append(text[last:m.start()].replace("<", "&lt;"))
        out.append(m.group(0))
        last = m.end()
    out.append(text[last:].replace("<", "&lt;"))
    return "".join(out)


# ─────────────────────────────────────────────────────────────────────────────
# 파서 + recover fallback
# ─────────────────────────────────────────────────────────────────────────────
def parse_with_fallback(cleaned_text: str) -> tuple:
    """
    strict 파서 우선, 실패 시 lxml recover 모드.

    Returns:
        (root, mode)
          mode = "strict"        : 깔끔하게 파싱됨
          mode = "recover (...)" : 일부 malformed 부분 skip 후 파싱 (사유 포함)
    """
    try:
        parser = ET.XMLParser(huge_tree=True, recover=False)
        return ET.fromstring(cleaned_text.encode("utf-8"), parser), "strict"
    except ET.XMLSyntaxError as e:
        parser = ET.XMLParser(huge_tree=True, recover=True)
        msg = e.msg.split(",")[0] if hasattr(e, "msg") else str(e)
        return ET.fromstring(cleaned_text.encode("utf-8"), parser), f"recover ({msg})"


if __name__ == "__main__":
    # 자기 테스트
    sample = '''<?xml version="1.0"?>
<doc>
  <P>R&D 비용은 약 1,000억원입니다.</P>
  <P>< TV 시장점유율 추이 ></P>
  <P>D&M Holdings & Sons Ltd</P>
</doc>'''
    cleaned = clean_xml(sample)
    print("── 정제 후 ──")
    print(cleaned)
    root, mode = parse_with_fallback(cleaned)
    print(f"\n파싱 mode: {mode}")
    print(f"P 태그 수: {len(root.findall('.//P'))}")
