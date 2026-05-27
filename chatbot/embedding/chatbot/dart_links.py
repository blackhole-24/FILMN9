"""DART 사업보고서 섹션 deep-link 생성.

DART 보고서 페이지(dsaf001/main.do?rcpNo=...)에는 목차(TOC) 트리가 JS 로 들어있고,
각 노드가 뷰어 점프에 필요한 파라미터를 갖는다:

    node2['text']  = "1. 회사의 개요";
    node2['dcmNo'] = "11104488";  node2['eleId'] = "4";
    node2['offset']= "6176";      node2['length']= "45026";
    node2['dtd']   = "dart4.xsd";

이를 파싱해 섹션 제목 → 뷰어 URL 매핑을 만든다(보고서당 1회 fetch + 캐싱).
청크의 section_main / section_sub 를 트리 노드와 매칭해 섹션 deep-link 를 만들고,
fetch/파싱/매칭 실패 시에는 보고서 첫 화면 URL 로 안전하게 폴백한다.

* 네트워크 의존: 보고서별 첫 호출에서만 DART 를 fetch(이후 메모리+디스크 캐시).
  DART 가 느리거나 막혀도 짧은 타임아웃 후 폴백하므로 답변 생성은 멈추지 않는다.
"""
from __future__ import annotations

import json
import re
import threading
import urllib.request
from typing import Optional

from .config import (
    ENABLE_DART_DEEPLINK, DART_FETCH_TIMEOUT, DART_TOC_CACHE_PATH,
)

DART_MAIN = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={}"
DART_VIEWER = ("https://dart.fss.or.kr/report/viewer.do"
               "?rcpNo={rcpNo}&dcmNo={dcmNo}&eleId={eleId}"
               "&offset={offset}&length={length}&dtd={dtd}")

# node<depth>['key'] = "value";
_NODE_RE = re.compile(r"""node(\d+)\['(\w+)'\]\s*=\s*"?([^"\n;]*)"?\s*;""")
# 로마숫자 대섹션 (I. / II. ...)
_ROMAN_RE = re.compile(r"^\s*[IVXLCDM]+\.\s")

_VIEWER_KEYS = ("rcpNo", "dcmNo", "eleId", "offset", "length", "dtd")

_TOC_CACHE: dict[str, list[dict]] = {}
_LOCK = threading.Lock()
_DISK_LOADED = False

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def report_url(rcept_no: str) -> Optional[str]:
    """보고서 첫 화면 URL (폴백용)."""
    return DART_MAIN.format(rcept_no) if rcept_no else None


def _load_disk_cache() -> None:
    global _DISK_LOADED
    if _DISK_LOADED:
        return
    _DISK_LOADED = True
    try:
        if DART_TOC_CACHE_PATH.exists():
            data = json.loads(DART_TOC_CACHE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                _TOC_CACHE.update(data)
    except Exception:
        pass


def _save_disk_cache() -> None:
    try:
        DART_TOC_CACHE_PATH.write_text(
            json.dumps(_TOC_CACHE, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _parse_nodes(html: str) -> list[dict]:
    """TOC 트리 노드들을 순서대로 파싱.

    'text' 키가 새 노드의 시작. depth(변수 숫자)로 대섹션(main)을 추적해
    각 노드에 main(소속 대섹션 제목)을 부여한다.
    """
    nodes: list[dict] = []
    cur: Optional[dict] = None
    current_main = ""

    for m in _NODE_RE.finditer(html):
        depth = int(m.group(1))
        key, val = m.group(2), m.group(3).strip()
        if key == "text":
            if cur:
                nodes.append(cur)
            cur = {"text": val, "depth": depth}
            # 대섹션(로마숫자 또는 최상위 depth) 추적
            if _ROMAN_RE.match(val) or depth == 1:
                current_main = val
            cur["main"] = current_main
        elif cur is not None:
            cur[key] = val
    if cur:
        nodes.append(cur)
    return nodes


def _fetch_toc(rcept_no: str) -> list[dict]:
    url = DART_MAIN.format(rcept_no)
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=DART_FETCH_TIMEOUT) as resp:
            html = resp.read().decode("utf-8", "replace")
    except Exception:
        return []
    return _parse_nodes(html)


def _get_toc(rcept_no: str) -> list[dict]:
    _load_disk_cache()
    with _LOCK:
        if rcept_no in _TOC_CACHE:
            return _TOC_CACHE[rcept_no]
    nodes = _fetch_toc(rcept_no)              # 네트워크는 락 밖에서
    with _LOCK:
        _TOC_CACHE[rcept_no] = nodes          # 빈 리스트도 캐싱(재시도 폭주 방지)
        if nodes:
            _save_disk_cache()
    return nodes


def _viewer_url(node: dict) -> Optional[str]:
    if not all(node.get(k) for k in _VIEWER_KEYS):
        return None
    return DART_VIEWER.format(**{k: node[k] for k in _VIEWER_KEYS})


def section_url(rcept_no: str,
                section_main: Optional[str] = None,
                section_sub: Optional[str] = None) -> Optional[str]:
    """섹션 deep-link URL. 매칭 실패/비활성 시 보고서 첫 화면 URL 폴백."""
    if not rcept_no:
        return None
    if not ENABLE_DART_DEEPLINK:
        return report_url(rcept_no)

    nodes = _get_toc(rcept_no)
    if not nodes:
        return report_url(rcept_no)

    sub = (section_sub or "").strip()
    main = (section_main or "").strip()

    # 1) (대섹션 + 소섹션) 정확 매칭 — 소섹션 번호 중복(대섹션마다 1.,2.) 대응
    if sub:
        for n in nodes:
            if n.get("text", "").strip() == sub and n.get("main", "").strip() == main:
                u = _viewer_url(n)
                if u:
                    return u
        # 2) 소섹션만 매칭
        for n in nodes:
            if n.get("text", "").strip() == sub:
                u = _viewer_url(n)
                if u:
                    return u
    # 3) 대섹션 매칭
    if main:
        for n in nodes:
            if n.get("text", "").strip() == main:
                u = _viewer_url(n)
                if u:
                    return u
    return report_url(rcept_no)
