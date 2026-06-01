"""신규 보고서 본문 → 청크 → BGE-M3 임베딩 → ChromaDB 증분 upsert (4단계).

설계 (사용자 결정 3: 신규 보고서 전체 임베딩):
  · DART document.xml(원본 보고서, dart4.xsd) 다운로드 → lxml 파싱
  · 섹션 계층: SECTION-1(대분류) > SECTION-2(중분류) > TITLE/P(본문)/TABLE(표)
  · 팀원 사업보고서 청크와 동일한 metadata 스키마로 청크화
      (ticker, corp_name, corp_code, year, section_main/sub/path_str, kind, char_len, rcept_no, rcept_dt)
  · embedding.embedder.embed_texts + vector_store.add_batch 재사용 (BGE-M3, collection="annual_reports")
  · 청크 id = "<ticker>-<year>-<period_label>-<seq>"  (예: 009150-2026-q1-00001)
  · report_detector.mark_processed 로 처리 완료 기록 (멱등성)
"""
from __future__ import annotations

import io
import os
import re
import sys
import zipfile
from pathlib import Path
from typing import Optional

import requests
from lxml import etree

_VAR_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_VAR_ROOT))

_DOC_API = "https://opendart.fss.or.kr/api/document.xml"
_MIN_CHAR_LEN = 30                       # 팀원 config 와 동일 (짧은 청크 제외)
_MAX_CHARS = 1800                        # 너무 긴 본문은 분할 (임베딩 토큰 안정)
_PERIOD_LABEL = {"03": "q1", "06": "q2", "09": "q3", "12": "annual"}


def _dart_key() -> str:
    k = os.getenv("DART_API_KEY")
    if not k:
        raise RuntimeError("환경변수 'DART_API_KEY' 미설정")
    return k


def download_document(rcept_no: str, timeout: int = 60) -> str:
    """DART document.xml(ZIP) 다운로드 → 원본 XML 문자열."""
    r = requests.get(_DOC_API, params={"crtfc_key": _dart_key(), "rcept_no": rcept_no},
                     timeout=timeout)
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    return z.read(z.namelist()[0]).decode("utf-8", errors="replace")


def _text_of(el) -> str:
    """엘리먼트 하위 모든 텍스트를 공백 정리해 추출."""
    txt = "".join(el.itertext())
    return re.sub(r"[ \t]+", " ", re.sub(r"\s*\n\s*", "\n", txt)).strip()


def _table_text(el) -> str:
    """TABLE 엘리먼트 → 행별 ' | ' 구분 텍스트 (표 구조 보존)."""
    rows = []
    for tr in el.iter("TR"):
        cells = [_text_of(td).replace("\n", " ") for td in tr.iter("TD", "TH", "TE")]
        cells = [c for c in cells if c]
        if cells:
            rows.append(" | ".join(cells))
    return "\n".join(rows)


def parse_chunks(xml_text: str, meta: dict) -> list[dict]:
    """DART document.xml → 청크 리스트 (팀원 스키마 호환).

    meta: {ticker, corp_name, corp_code, year, rcept_no, rcept_dt, period_label}
    """
    parser = etree.XMLParser(recover=True, huge_tree=True)
    root = etree.fromstring(xml_text.encode("utf-8"), parser=parser)
    if root is None:
        return []

    chunks: list[dict] = []
    seq = 0

    def _emit(text: str, kind: str, sec_main: str, sec_sub: str):
        nonlocal seq
        text = (text or "").strip()
        if len(text) < _MIN_CHAR_LEN:
            return
        # 긴 본문 분할 (문단 경계 우선)
        parts = [text]
        if len(text) > _MAX_CHARS and kind == "text":
            parts = _split_long(text, _MAX_CHARS)
        for p in parts:
            if len(p.strip()) < _MIN_CHAR_LEN:
                continue
            seq += 1
            path = [s for s in (sec_main, sec_sub) if s]
            cid = f"{meta['ticker']}-{meta['year']}-{meta['period_label']}-{seq:05d}"
            chunks.append({
                "id": cid,
                "text": p.strip(),
                "metadata": {
                    "ticker":           meta["ticker"],
                    "corp_name":        meta["corp_name"],
                    "corp_name_raw":    meta["corp_name"],
                    "corp_code":        meta["corp_code"],
                    "year":             int(meta["year"]),
                    "section_main":     sec_main,
                    "section_sub":      sec_sub,
                    "section_path_str": " > ".join(path),
                    "kind":             kind,
                    "char_len":         len(p.strip()),
                    "rcept_no":         meta["rcept_no"],
                    "rcept_dt":         meta["rcept_dt"],
                    "parse_mode":       "ingest_v1",
                },
            })

    # SECTION-1(대분류) → SECTION-2(중분류) 순회하며 섹션 경로 추적
    for s1 in root.iter("SECTION-1"):
        s1_title = _first_title(s1)
        s2_list = list(s1.iter("SECTION-2"))
        if not s2_list:
            _walk_body(s1, s1_title, "", _emit)
        else:
            for s2 in s2_list:
                s2_title = _first_title(s2)
                _walk_body(s2, s1_title, s2_title, _emit)
    return chunks


def _first_title(el) -> str:
    t = el.find(".//TITLE")
    return _text_of(t)[:120] if t is not None else ""


def _walk_body(sec_el, sec_main: str, sec_sub: str, emit) -> None:
    """섹션 내 P(문단 누적) + TABLE(별도 청크) 추출."""
    buf: list[str] = []
    for el in sec_el.iter():
        tag = el.tag if isinstance(el.tag, str) else ""
        if tag == "P":
            t = _text_of(el)
            if t:
                buf.append(t)
        elif tag == "TABLE":
            if buf:
                emit("\n".join(buf), "text", sec_main, sec_sub); buf = []
            emit(_table_text(el), "table", sec_main, sec_sub)
    if buf:
        emit("\n".join(buf), "text", sec_main, sec_sub)


def _split_long(text: str, limit: int) -> list[str]:
    out, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) > limit and cur:
            out.append(cur); cur = line
        else:
            cur = (cur + "\n" + line) if cur else line
    if cur:
        out.append(cur)
    return out


def ingest_report(ticker: str, corp_code: str, corp_name: str, rep: dict,
                  skip_existing: bool = True, verbose: bool = True) -> dict:
    """보고서 1건: download → parse → embed → ChromaDB upsert → registry 기록.

    rep: report_detector 레코드 ({rcept_no, rcept_dt, period, month, ...})
    """
    from embedding.embedder import embed_texts
    from embedding.vector_store import add_batch, get_existing_ids

    period_label = _PERIOD_LABEL.get(rep["month"], rep["month"])
    meta = {"ticker": ticker, "corp_name": corp_name, "corp_code": corp_code,
            "year": rep["year"], "rcept_no": rep["rcept_no"],
            "rcept_dt": rep["rcept_dt"], "period_label": period_label}

    if verbose:
        print(f"  [ingest] {ticker} {rep['period']} {rep['kind']} (rcept {rep['rcept_no']}) 다운로드…")
    xml = download_document(rep["rcept_no"])
    chunks = parse_chunks(xml, meta)
    if verbose:
        n_tbl = sum(1 for c in chunks if c["metadata"]["kind"] == "table")
        print(f"  [ingest] 청크 {len(chunks)}개 (표 {n_tbl}) 생성")
    if not chunks:
        return {"chunks": 0, "embedded": 0}

    # 증분 — 이미 있는 id 제외
    if skip_existing:
        try:
            existing = set(get_existing_ids([c["id"] for c in chunks]))
            chunks = [c for c in chunks if c["id"] not in existing]
        except Exception:
            pass
    if not chunks:
        if verbose:
            print(f"  [ingest] 신규 청크 없음 (이미 임베딩됨)")
        return {"chunks": 0, "embedded": 0}

    texts = [c["text"] for c in chunks]
    embs = embed_texts(texts, show_progress=verbose)
    add_batch([c["id"] for c in chunks], texts,
              [e.tolist() for e in embs], [c["metadata"] for c in chunks])
    if verbose:
        print(f"  [ingest] {len(chunks)}개 임베딩 → ChromaDB upsert 완료")
    return {"chunks": len(chunks), "embedded": len(chunks)}


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(_VAR_ROOT / ".env")
    sys.path.insert(0, str(_VAR_ROOT / "XBRL"))
    from xbrl_financials_v4 import get_corp_code
    from valuation_engine.report_detector import detect_new, mark_processed

    tk = sys.argv[1] if len(sys.argv) > 1 else "009150"
    cc = get_corp_code(tk)
    cc = cc.get("corp_code") if isinstance(cc, dict) else cc
    det = detect_new(tk, cc)
    latest = det["latest"]
    print(f"최신 공시: {latest['period']} {latest['kind']}")
    name = "삼성전기" if tk == "009150" else tk
    res = ingest_report(tk, cc, name, latest, verbose=True)
    if res["embedded"]:
        mark_processed(tk, cc, latest, embed_done=True)
    print("결과:", res)
