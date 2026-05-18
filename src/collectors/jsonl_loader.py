"""
collectors/jsonl_loader.py
──────────────────────────
아모레퍼시픽(090430) JSONL → 섹션별 청크 로드 + 테이블 청크 병합.

주요 함수
─────────
load_chunks(jsonl_path, section_filter, kind)
    → 특정 section_path_str 포함 청크 리스트 반환

merge_table_chunks(chunks)
    → [표] 제목 기준으로 분할된 청크들을 하나의 텍스트로 합치기
    → 반환: [{"title": str, "header_hint": str, "merged_text": str}, ...]

get_section(stock_code, section_key)
    → app_config.SECTION 키로 한 번에 로드+병합
    → 반환: 위와 동일

사용 예시
─────────
from src.collectors.jsonl_loader import get_section
tables = get_section("090430", "요약재무정보")
for t in tables:
    print(t["title"], "→ 행 수:", t["merged_text"].count("\\n"))
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Literal

# ─────────────────────────────────────────────────────────────────────────────
# 경로 설정 (이 파일이 src/collectors/ 안에 있음)
# ─────────────────────────────────────────────────────────────────────────────
_HERE = Path(__file__).resolve()
_ROOT = _HERE.parent.parent.parent          # C:/Users/Admin/FILMN9

if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.app_config import RAG_DIR, SECTION, SAMPLE


# ─────────────────────────────────────────────────────────────────────────────
# 1) 기본 로더 — JSONL 전체 읽기
# ─────────────────────────────────────────────────────────────────────────────

def load_all(jsonl_path: str | Path) -> list[dict]:
    """JSONL 파일 전체를 딕셔너리 리스트로 반환."""
    path = Path(jsonl_path)
    if not path.exists():
        raise FileNotFoundError(f"JSONL 파일 없음: {path}")
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


# ─────────────────────────────────────────────────────────────────────────────
# 2) 섹션 필터링
# ─────────────────────────────────────────────────────────────────────────────

def load_chunks(
    jsonl_path: str | Path,
    section_filter: str,
    kind: Literal["table", "prose", "all"] = "all",
) -> list[dict]:
    """
    section_path_str 에 section_filter 문자열이 포함된 청크만 반환.

    Parameters
    ----------
    jsonl_path     : JSONL 파일 경로
    section_filter : 검색할 섹션 경로 (부분 일치)
                     예) "III. 재무에 관한 사항 > 1. 요약재무정보"
    kind           : "table" | "prose" | "all"

    Returns
    -------
    청크 딕셔너리 리스트 (원본 순서 유지)
    """
    all_chunks = load_all(jsonl_path)
    result = [
        c for c in all_chunks
        if section_filter in c.get("section_path_str", "")
    ]
    if kind != "all":
        result = [c for c in result if c.get("kind") == kind]
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 3) 테이블 청크 병합
#    — 같은 [표] 제목을 가진 분할 청크들을 하나의 마크다운 텍스트로 합침
# ─────────────────────────────────────────────────────────────────────────────

_TABLE_TITLE_RE = re.compile(r"^\[표\]\s*(.+)")          # [표] 제목 행
_HEADER_HINT_RE = re.compile(r"^\(상위 헤더:\s*(.+)\)")  # (상위 헤더: ...) 행
_UNIT_RE        = re.compile(r"^\(단위\s*:\s*.+\)")       # (단위 : 원) 행
_SEP_RE         = re.compile(r"^\|\s*-+")                 # | --- | 구분 행


def _extract_table_lines(text: str) -> tuple[str, str, list[str]]:
    """
    청크 텍스트에서 (제목, 헤더힌트, 마크다운_행_리스트) 를 추출.

    반환
    ----
    title       : "[표] ..." 줄의 제목 (없으면 "")
    header_hint : "(상위 헤더: ...)" 내용 (없으면 "")
    md_lines    : "| ... |" 형태의 행 리스트
    """
    lines = text.splitlines()
    title = ""
    header_hint = ""
    md_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        m_title = _TABLE_TITLE_RE.match(stripped)
        m_hint  = _HEADER_HINT_RE.match(stripped)
        m_unit  = _UNIT_RE.match(stripped)

        if m_title:
            title = m_title.group(1).strip()
        elif m_hint:
            header_hint = m_hint.group(1).strip()
        elif m_unit:
            pass                            # 단위 행은 별도 보관하지 않음
        elif stripped.startswith("|"):
            md_lines.append(stripped)

    return title, header_hint, md_lines


def merge_table_chunks(chunks: list[dict]) -> list[dict]:
    """
    table 종류 청크들을 [표] 제목 기준으로 그룹핑하여 병합.

    같은 제목의 청크가 여러 개이면 마크다운 행을 이어 붙임.
    (중복 구분선 | --- | 은 첫 번째만 유지)

    Parameters
    ----------
    chunks : load_chunks()로 얻은 청크 리스트

    Returns
    -------
    [
      {
        "title"       : str,   # [표] 제목
        "header_hint" : str,   # 상위 헤더 힌트 (컬럼명 유추용)
        "merged_text" : str,   # 병합된 전체 마크다운 텍스트
        "chunk_count" : int,   # 병합에 사용된 청크 수
        "source_chunks": list, # 원본 청크 딕셔너리들
      },
      ...
    ]
    """
    # (title → group) 순서 보존 딕셔너리
    groups: dict[str, dict] = {}

    for chunk in chunks:
        if chunk.get("kind") != "table":
            continue

        title, header_hint, md_lines = _extract_table_lines(chunk["text"])
        key = title if title else "__no_title__"

        if key not in groups:
            groups[key] = {
                "title"        : title,
                "header_hint"  : header_hint,
                "all_lines"    : [],
                "has_sep"      : False,         # 구분선 추가 여부
                "chunk_count"  : 0,
                "source_chunks": [],
            }

        grp = groups[key]

        # header_hint 는 처음 만나면 저장
        if not grp["header_hint"] and header_hint:
            grp["header_hint"] = header_hint

        for line in md_lines:
            is_sep = bool(_SEP_RE.match(line))
            if is_sep:
                if not grp["has_sep"]:        # 구분선은 처음 한 번만
                    grp["all_lines"].append(line)
                    grp["has_sep"] = True
            else:
                grp["all_lines"].append(line)

        grp["chunk_count"] += 1
        grp["source_chunks"].append(chunk)

    # 최종 텍스트 조합
    result = []
    for grp in groups.values():
        merged = "\n".join(grp["all_lines"])
        result.append({
            "title"        : grp["title"],
            "header_hint"  : grp["header_hint"],
            "merged_text"  : merged,
            "chunk_count"  : grp["chunk_count"],
            "source_chunks": grp["source_chunks"],
        })
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 4) 메인 진입점 — app_config.SECTION 키로 한 번에 처리
# ─────────────────────────────────────────────────────────────────────────────

def get_section(
    stock_code: str,
    section_key: str,
    kind: Literal["table", "prose", "all"] = "table",
    jsonl_filename: str | None = None,
) -> list[dict]:
    """
    stock_code 의 JSONL 파일에서 section_key 에 해당하는 테이블 청크를 로드하고 병합.

    Parameters
    ----------
    stock_code    : 종목코드 (예: "090430")
    section_key   : app_config.SECTION 딕셔너리의 키
                    예) "요약재무정보", "연결재무제표", "별도재무제표", "임원현황"
    kind          : "table" | "prose" | "all"
    jsonl_filename: None 이면 data/RAG/ 에서 stock_code 로 시작하는 파일 자동 탐색

    Returns
    -------
    merge_table_chunks() 결과 리스트
    """
    # JSONL 파일 경로 결정
    if jsonl_filename:
        jsonl_path = RAG_DIR / jsonl_filename
    else:
        # stock_code 로 시작하는 파일 자동 탐색
        matches = list(RAG_DIR.glob(f"{stock_code}_*_annual_chunks.jsonl"))
        if not matches:
            raise FileNotFoundError(
                f"RAG 폴더에서 '{stock_code}' 로 시작하는 JSONL 없음\n"
                f"경로: {RAG_DIR}"
            )
        jsonl_path = matches[0]

    # section_path_str 필터값 결정
    section_path = SECTION.get(section_key)
    if section_path is None:
        raise KeyError(
            f"app_config.SECTION 에 '{section_key}' 키 없음.\n"
            f"사용 가능: {list(SECTION.keys())}"
        )

    chunks = load_chunks(jsonl_path, section_path, kind=kind)

    if kind == "table":
        return merge_table_chunks(chunks)
    return chunks


# ─────────────────────────────────────────────────────────────────────────────
# 5) 편의 함수 — 모든 섹션 한꺼번에 로드
# ─────────────────────────────────────────────────────────────────────────────

def load_all_sections(stock_code: str = SAMPLE["stock_code"]) -> dict[str, list[dict]]:
    """
    app_config.SECTION 에 정의된 모든 섹션을 한 번에 로드.

    Returns
    -------
    {
      "요약재무정보"  : [...merged tables...],
      "연결재무제표"  : [...merged tables...],
      "별도재무제표"  : [...merged tables...],
      "임원현황"     : [...merged tables...],
    }
    """
    return {key: get_section(stock_code, key) for key in SECTION}


# ─────────────────────────────────────────────────────────────────────────────
# 동작 확인 (python -m src.collectors.jsonl_loader)
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("FILMN9 jsonl_loader 검증")
    print("=" * 60)

    stock = SAMPLE["stock_code"]
    name  = SAMPLE["name"]

    for sec_key in SECTION:
        tables = get_section(stock, sec_key)
        print(f"\n[{sec_key}] — {len(tables)}개 테이블")
        for t in tables:
            row_count = len([l for l in t["merged_text"].splitlines() if l.startswith("|")])
            print(
                f"  제목: '{t['title']}'"
                f"  청크수: {t['chunk_count']}"
                f"  병합행수: {row_count}"
            )
            if t["header_hint"]:
                cols = [c.strip() for c in t["header_hint"].split("/")]
                print(f"  상위헤더({len(cols)}개): {cols[:5]} ...")

    print("\n" + "=" * 60)
    print("✅ jsonl_loader 검증 완료")
