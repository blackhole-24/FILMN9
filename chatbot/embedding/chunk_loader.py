"""사업보고서 청크 jsonl 로드 + 전처리.

KOSPI/, KOSDAQ/ 폴더의 *_annual_chunks*.jsonl 파일을 스캔.
각 청크에 대해:
  - 메타데이터 정제 (회사·연도·섹션 추출)
  - 의미 없는 청크 필터링 (너무 짧거나 cover page)
  - corp_name 정규화 (보통주/우선주 suffix 제거)

산업 표본 점검 결과 (건설/IT/제약/금융/음식):
  - corp_name 변동: "현대건설보통주" vs "삼양식품" → 정규화 필요
  - cover page: 표지+제출정보 (chunk 00000~00003) section_main="(문서 본문)" 로 표준 스킵 가능
  - parse_mode: "strict" 정상, "recover" 면 XML 파싱 오류 발생 (메타로 유지)
  - section_path_str: 모든 산업 일관된 형식 ✓
  - 신용평가 미보유 회사 존재 (제약 등) — downstream RAG 책임

Returns:
    list[dict] — 임베딩 준비된 청크들
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterator

from .config import (
    KOSPI_DIR, KOSDAQ_DIR,
    MIN_CHAR_LEN, SKIP_SECTIONS,
)


# corp_name 끝의 주식 종류 suffix 정규식
# 예: "현대건설보통주" → "현대건설", "삼성전자우선주" → "삼성전자"
_CORP_NAME_SUFFIX_RE = re.compile(r"(보통주|우선주|1우B|1우|2우B|2우|종류우선주|전환우선주)$")


def _normalize_corp_name(name: str) -> str:
    """corp_name 정규화 — 주식 종류 suffix 제거.

    원본 jsonl 의 corp_name 은 발행 주식 종류에 따라 다음과 같이 다양:
      - "현대건설보통주", "삼성전자우선주", "현대차2우B"  (suffix 있음)
      - "삼양식품", "더존비즈온", "한올바이오파마"            (suffix 없음)

    검색·필터 일관성을 위해 suffix 를 제거한 깔끔한 회사명만 metadata 에 저장.
    """
    if not name:
        return ""
    return _CORP_NAME_SUFFIX_RE.sub("", name.strip())


def iter_chunk_files(markets: list[str] | None = None,
                     extra_dirs: list[Path] | None = None) -> Iterator[Path]:
    """KOSPI/KOSDAQ 폴더의 청크 jsonl 파일 경로 iterator.

    Args:
        markets: ['kospi'], ['kosdaq'], ['kospi','kosdaq'] 중 선택.
                 None 또는 ['all'] = KOSPI + KOSDAQ 둘 다 (기본).
        extra_dirs: 추가 폴더 (옵션)

    같은 ticker 에 대해 여러 버전 파일이 있으면 (예: _chunks.jsonl + _chunks_v3.jsonl)
    가장 최신(=정렬상 마지막) 파일만 사용. v3 가 v1·원본을 덮어씀.
    """
    # markets 파라미터 → 실제 디렉토리 매핑
    if markets is None or 'all' in markets:
        dirs = [KOSPI_DIR, KOSDAQ_DIR]
    else:
        dirs = []
        markets_lower = [m.lower() for m in markets]
        if 'kospi' in markets_lower:
            dirs.append(KOSPI_DIR)
        if 'kosdaq' in markets_lower:
            dirs.append(KOSDAQ_DIR)
    if extra_dirs:
        dirs.extend(extra_dirs)

    # ticker(앞 6자리 종목코드) 별로 가장 마지막 파일만 선택
    by_ticker: dict[str, Path] = {}
    for d in dirs:
        if not d.exists():
            continue
        for p in sorted(d.glob("*_annual_chunks*.jsonl")):
            ticker = p.name[:6]
            by_ticker[ticker] = p

    yield from sorted(by_ticker.values())


def _parse_chunk_metadata(raw: dict) -> dict:
    """원본 청크에서 메타데이터 정제."""
    section_path = raw.get("section_path", [])
    section_main = section_path[0] if len(section_path) > 0 else ""
    section_sub  = section_path[1] if len(section_path) > 1 else ""

    # fiscal_period: "2025-annual" → year 2025
    fp = raw.get("fiscal_period", "")
    year = None
    if fp:
        try:
            year = int(fp.split("-")[0])
        except (ValueError, IndexError):
            year = None

    return {
        "ticker":       raw.get("stock_code", ""),
        "corp_name":    _normalize_corp_name(raw.get("corp_name", "")),
        "corp_name_raw": raw.get("corp_name", ""),    # 원본 (디버깅용)
        "corp_code":    raw.get("corp_code", ""),
        "year":         year if year is not None else 0,
        "section_main": section_main,
        "section_sub":  section_sub,
        "section_path_str": raw.get("section_path_str", ""),
        "kind":         raw.get("kind", ""),
        "char_len":     int(raw.get("char_len", 0)),
        "rcept_no":     raw.get("rcept_no", ""),
        "rcept_dt":     raw.get("rcept_dt", ""),
        "parse_mode":   raw.get("parse_mode", "strict"),   # strict/recover (XML 파싱 모드)
    }


def _should_skip(raw: dict, meta: dict) -> bool:
    """이 청크를 임베딩에서 제외할지 판단."""
    # 너무 짧으면 제외
    if meta["char_len"] < MIN_CHAR_LEN:
        return True
    # 의미 없는 섹션 제외
    if meta["section_main"] in SKIP_SECTIONS and not meta["section_sub"]:
        return True
    # text 본문 비어있으면 제외
    text = raw.get("text", "")
    if not text or not text.strip():
        return True
    return False


def load_chunks_from_file(path: Path) -> list[dict]:
    """jsonl 1개 파일에서 청크 로드 + 전처리.

    Returns:
        [{
            "id":       청크 고유 ID (예: "000720-2025-annual-00010"),
            "text":     본문,
            "metadata": {...},
        }, ...]
    """
    chunks = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue

            meta = _parse_chunk_metadata(raw)
            if _should_skip(raw, meta):
                continue

            chunks.append({
                "id":       raw.get("id", ""),
                "text":     raw.get("text", "").strip(),
                "metadata": meta,
            })
    return chunks


def load_all_chunks(markets: list[str] | None = None,
                    extra_dirs: list[Path] | None = None,
                    verbose: bool = True) -> tuple[list[dict], dict]:
    """선택된 시장 (KOSPI/KOSDAQ) 청크 일괄 로드.

    Args:
        markets: ['kospi'], ['kosdaq'], ['kospi','kosdaq'] / None=둘 다.
        extra_dirs: 추가 폴더.
        verbose: 진행률 출력 여부.

    Returns:
        (chunks, stats)
    """
    all_chunks = []
    seen_ids: set[str] = set()    # ID 중복 방어 (jsonl 내부 중복 + 파일 간 중복)
    files = list(iter_chunk_files(markets=markets, extra_dirs=extra_dirs))
    stats = {"files": len(files), "raw_chunks": 0, "kept": 0,
             "skipped_short": 0, "skipped_meta": 0,
             "skipped_dup_id": 0, "errors": 0}

    if verbose:
        print(f"[chunk_loader] {len(files)}개 파일 발견")

    for i, p in enumerate(files, 1):
        try:
            with p.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        raw = json.loads(line)
                    except json.JSONDecodeError:
                        stats["errors"] += 1
                        continue

                    stats["raw_chunks"] += 1
                    meta = _parse_chunk_metadata(raw)

                    if meta["char_len"] < MIN_CHAR_LEN:
                        stats["skipped_short"] += 1
                        continue
                    if meta["section_main"] in SKIP_SECTIONS and not meta["section_sub"]:
                        stats["skipped_meta"] += 1
                        continue
                    text = raw.get("text", "")
                    if not text or not text.strip():
                        stats["skipped_meta"] += 1
                        continue

                    chunk_id = raw.get("id", "")
                    if not chunk_id or chunk_id in seen_ids:
                        stats["skipped_dup_id"] += 1
                        continue
                    seen_ids.add(chunk_id)

                    all_chunks.append({
                        "id":       chunk_id,
                        "text":     text.strip(),
                        "metadata": meta,
                    })
                    stats["kept"] += 1
        except Exception as e:
            stats["errors"] += 1
            if verbose:
                print(f"  [WARN] {p.name}: {e}")

        if verbose and i % 50 == 0:
            print(f"  [{i}/{len(files)}] 로드 중... 누적 {stats['kept']:,}개 청크")

    if verbose:
        print(f"[chunk_loader] 완료:")
        print(f"  파일       : {stats['files']:>7,}")
        print(f"  원본 청크  : {stats['raw_chunks']:>7,}")
        print(f"  유지       : {stats['kept']:>7,}")
        print(f"  너무 짧음   : {stats['skipped_short']:>7,}")
        print(f"  메타 부재  : {stats['skipped_meta']:>7,}")
        print(f"  중복 ID    : {stats['skipped_dup_id']:>7,}")
        print(f"  에러      : {stats['errors']:>7,}")

    return all_chunks, stats
