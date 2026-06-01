"""
build_corp_code_map.py
======================
DART corpCode.xml (전체 법인 bulk) + 로컬 JSONL 파일명 매칭
→ data/corp_code_map.json 생성

구조
----
{
  "by_stock_code": {
    "090430": {
      "stock_code": "090430",
      "corp_code" : "00583424",
      "corp_name" : "아모레퍼시픽",
      "market"    : "KOSPI",
      "has_jsonl" : true,
      "jsonl_file": "090430_아모레퍼시픽_2025_annual_chunks.jsonl"
    }, ...
  },
  "by_name": {
    "아모레퍼시픽": "090430",   // 검색용 단순 역인덱스
    ...
  },
  "search_index": [           // 자동완성용 정렬 배열 (이름순)
    {
      "stock_code": "090430",
      "corp_name" : "아모레퍼시픽",
      "market"    : "KOSPI",
      "has_jsonl" : true
    }, ...
  ],
  "_meta": {
    "total": 2596,
    "dart_total": ...,
    "generated_at": "..."
  }
}

사용
----
  cd C:/Users/Admin/FILMN9/part_company_overview/재무정보
  python build_corp_code_map.py
"""

from __future__ import annotations

import io
import json
import sys
import re
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError

# ─── 경로 설정 ────────────────────────────────────────────────────────────────
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from src.app_config import DART_API_KEY, DART_BASE_URL, RAG_DIR

OUT_PATH = _ROOT / "data" / "corp_code_map.json"


# =============================================================================
# 1) DART corpCode.xml 다운로드 + 파싱
# =============================================================================

def fetch_dart_corp_codes() -> list[dict]:
    """
    DART /corpCode.xml API → 전체 법인 목록 반환.

    Returns list of:
      {"corp_code": str, "corp_name": str, "stock_code": str, "modify_date": str}

    stock_code 가 빈 문자열이면 비상장 법인.
    """
    url = f"{DART_BASE_URL}/corpCode.xml?crtfc_key={DART_API_KEY}"
    print(f"  DART corpCode.xml 다운로드 중... ({url[:60]}...)")

    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=30) as resp:
            raw = resp.read()
    except URLError as e:
        raise RuntimeError(f"DART 다운로드 실패: {e}")

    # 응답은 ZIP 바이너리
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
        xml_bytes = zf.read("CORPCODE.xml")
    except Exception as e:
        raise RuntimeError(f"ZIP 파싱 실패: {e}\n  (API 키 오류이거나 응답이 XML일 수 있음)")

    print(f"  XML 크기: {len(xml_bytes):,} bytes")
    root = ET.fromstring(xml_bytes)

    records = []
    for item in root.findall("list"):
        records.append({
            "corp_code"  : (item.findtext("corp_code") or "").strip(),
            "corp_name"  : (item.findtext("corp_name") or "").strip(),
            "stock_code" : (item.findtext("stock_code") or "").strip(),
            "modify_date": (item.findtext("modify_date") or "").strip(),
        })

    print(f"  총 법인 수: {len(records):,}개")
    return records


# =============================================================================
# 2) 로컬 JSONL 파일명 파싱
# =============================================================================

def parse_jsonl_files() -> dict[str, dict]:
    """
    RAG 폴더의 JSONL 파일명 파싱.
    파일명 형식: {종목코드}_{기업명}_{연도}_annual_chunks.jsonl

    Returns dict keyed by stock_code:
      {"090430": {"jsonl_file": "...", "corp_name_jsonl": "아모레퍼시픽"}}
    """
    result: dict[str, dict] = {}
    pattern = re.compile(r"^([A-Z0-9]{6})_(.+?)_\d{4}_annual_chunks\.jsonl$")

    for f in sorted(RAG_DIR.glob("*.jsonl")):
        m = pattern.match(f.name)
        if m:
            code = m.group(1)
            name = m.group(2)
            result[code] = {
                "jsonl_file"     : f.name,
                "corp_name_jsonl": name,
            }
        else:
            # 파일명 패턴 불일치 — 종목코드만 앞 6자리로 추출 시도
            stem = f.stem
            code = stem[:6]
            if re.match(r"^[A-Z0-9]{6}$", code):
                result[code] = {
                    "jsonl_file"     : f.name,
                    "corp_name_jsonl": stem[7:] if len(stem) > 7 else "",
                }

    print(f"  JSONL 파일: {len(result):,}개")
    return result


# =============================================================================
# 3) DART 법인 목록 × JSONL 매칭 → corp_code_map
# =============================================================================

# 시장 구분 (DART market 필드 없음 — 종목코드 패턴으로 추정)
def _guess_market(stock_code: str) -> str:
    """종목코드 패턴으로 시장 추정 (DART API 미제공)."""
    if not stock_code:
        return ""
    # 숫자 6자리
    if re.match(r"^\d{6}$", stock_code):
        prefix = int(stock_code[:3])
        # KOSPI: 000~009, 010~049, 051~089, 090~119 등 대략적 범위
        # KOSDAQ: 대부분 나머지
        # 단순 규칙: 앞 두 자리 00~09 → KOSPI 가능성 높음 (정확하지 않음)
        return "KOSPI/KOSDAQ"  # DART는 시장 구분 미제공
    # 영문 포함 → ETF/리츠 등
    return "기타"


def build_map(dart_records: list[dict], jsonl_map: dict[str, dict]) -> dict:
    """DART 레코드 × JSONL 매칭 → 최종 맵."""

    # DART 레코드 → stock_code 기준 dict (상장사만)
    dart_by_stock: dict[str, dict] = {}
    for r in dart_records:
        sc = r["stock_code"]
        if sc:  # 비상장 제외
            dart_by_stock[sc] = r

    by_stock_code: dict[str, dict] = {}
    by_name: dict[str, str] = {}
    search_index: list[dict] = []

    matched = 0
    jsonl_only = 0

    # JSONL 파일이 있는 종목 중심으로 구성
    for sc, jinfo in jsonl_map.items():
        dart = dart_by_stock.get(sc)

        if dart:
            corp_code = dart["corp_code"]
            corp_name = dart["corp_name"]
            matched += 1
        else:
            # DART 매칭 실패 → JSONL 파일명 기업명으로 대체
            corp_code = ""
            corp_name = jinfo["corp_name_jsonl"]
            jsonl_only += 1

        entry = {
            "stock_code" : sc,
            "corp_code"  : corp_code,
            "corp_name"  : corp_name,
            "market"     : _guess_market(sc),
            "has_jsonl"  : True,
            "jsonl_file" : jinfo["jsonl_file"],
        }
        by_stock_code[sc] = entry
        by_name[corp_name] = sc
        search_index.append({
            "stock_code": sc,
            "corp_code" : corp_code,
            "corp_name" : corp_name,
            "market"    : entry["market"],
            "has_jsonl" : True,
        })

    # DART 상장사 중 JSONL 없는 것도 by_stock_code에 추가 (검색 대상 확장)
    dart_no_jsonl = 0
    for sc, dart in dart_by_stock.items():
        if sc not in by_stock_code:
            corp_name = dart["corp_name"]
            entry = {
                "stock_code" : sc,
                "corp_code"  : dart["corp_code"],
                "corp_name"  : corp_name,
                "market"     : _guess_market(sc),
                "has_jsonl"  : False,
                "jsonl_file" : None,
            }
            by_stock_code[sc] = entry
            by_name[corp_name] = sc
            search_index.append({
                "stock_code": sc,
                "corp_code" : dart["corp_code"],
                "corp_name" : corp_name,
                "market"    : entry["market"],
                "has_jsonl" : False,
            })
            dart_no_jsonl += 1

    # 검색 인덱스 — 기업명 가나다순 정렬
    search_index.sort(key=lambda x: x["corp_name"])

    print(f"\n  매칭 결과:")
    print(f"    JSONL + DART 매칭: {matched:,}개")
    print(f"    JSONL만 (DART 없음): {jsonl_only:,}개")
    print(f"    DART만 (JSONL 없음): {dart_no_jsonl:,}개")
    print(f"    search_index 총: {len(search_index):,}개")

    return {
        "by_stock_code": by_stock_code,
        "by_name"      : by_name,
        "search_index" : search_index,
        "_meta": {
            "jsonl_count"  : len(jsonl_map),
            "dart_listed"  : len(dart_by_stock),
            "total_index"  : len(search_index),
            "matched"      : matched,
            "generated_at" : datetime.now().strftime("%Y-%m-%d %H:%M"),
        },
    }


# =============================================================================
# 4) 편의 함수 (FastAPI / build_overview.py 에서 import해서 사용)
# =============================================================================

_MAP_CACHE: dict | None = None

def load_map(path: Path = OUT_PATH) -> dict:
    """corp_code_map.json 로드 (메모리 캐시)."""
    global _MAP_CACHE
    if _MAP_CACHE is None:
        with open(path, encoding="utf-8") as f:
            _MAP_CACHE = json.load(f)
    return _MAP_CACHE


def lookup(stock_code: str) -> dict | None:
    """종목코드 → 법인 정보 dict (없으면 None)."""
    return load_map()["by_stock_code"].get(stock_code)


def search(query: str, limit: int = 10) -> list[dict]:
    """
    기업명 또는 종목코드 prefix 검색 → 자동완성 후보 반환.

    Examples
    --------
    search("삼성")  → 삼성전자, 삼성SDI, 삼성화재, ...
    search("005930") → 삼성전자
    """
    q = query.strip()
    if not q:
        return []

    index = load_map()["search_index"]
    results = []

    for item in index:
        name_match = q in item["corp_name"]
        code_match = item["stock_code"].startswith(q)
        if name_match or code_match:
            results.append(item)
        if len(results) >= limit:
            break

    return results


# =============================================================================
# 5) 메인
# =============================================================================

def main() -> None:
    print("\n=== build_corp_code_map.py ===")

    print("\n[1/3] DART corpCode.xml 다운로드...")
    dart_records = fetch_dart_corp_codes()

    print("\n[2/3] JSONL 파일 파싱...")
    jsonl_map = parse_jsonl_files()

    print("\n[3/3] 매핑 테이블 생성...")
    corp_map = build_map(dart_records, jsonl_map)

    # 저장
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(corp_map, f, ensure_ascii=False, indent=2)

    size_kb = OUT_PATH.stat().st_size / 1024
    print(f"\n  저장: {OUT_PATH}")
    print(f"  크기: {size_kb:,.1f} KB")

    # 검증: 아모레퍼시픽
    ap = corp_map["by_stock_code"].get("090430")
    print(f"\n  [검증] 090430 아모레퍼시픽: {ap}")

    # 검증: 삼성 검색
    print(f"\n  [검증] '삼성' 검색 결과 (상위 5개):")
    _MAP_CACHE_bak = None
    # 직접 search 함수 테스트 (캐시 로드)
    global _MAP_CACHE
    _MAP_CACHE = corp_map
    for r in search("삼성", limit=5):
        jsonl_mark = "[JSONL]" if r["has_jsonl"] else "      "
        print(f"    {jsonl_mark} {r['stock_code']} {r['corp_name']}")

    print("\n[OK] corp_code_map.json 생성 완료")


if __name__ == "__main__":
    main()
