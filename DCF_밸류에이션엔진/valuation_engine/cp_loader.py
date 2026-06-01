"""KOFIA CP시가평가수익률 CSV 파서 — Kd 변환용.

설계:
  - 종류:     CP (기업어음 = 무담보 단기증권 자체가 무보증)
  - 등급 행:  A1, A2+, A2, A2-, A3+, A3, A3-, B+, B, B-, C, D
  - 기관명:   "5사 평균" 행만 사용 (회사채 CSV의 "평가사 평균" 과 동일 정책)
  - 만기 컬럼: 7일, 15일, 1월, 3월, 6월, 1년

CSV 파일 경로 검색 우선순위:
  1) VAR/cp_수익률_<YYYYMMDD>.csv      → 파일명에서 as_of 추출
  2) VAR/cp_수익률.csv                  → 파일 mtime → as_of (경고)
  3) (CSV 부재) → cp_yield_data.py 의 하드코드 fallback (캡처 기반)

호출:
  >>> info = get_cp_yield("A1", "1년")
  >>> info["yield"]          # 0.0315
  >>> info["source"]         # "CSV" 또는 "hardcoded fallback"
  >>> info["as_of"]          # "2026-05-18"
"""
from __future__ import annotations

import csv
import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from .cp_yield_data import (
    KOFIA_CP_REFERENCE, KOFIA_CP_AS_OF, KOFIA_CP_SOURCE,
    VALID_CP_RATINGS,
)

_VAR_ROOT = Path(__file__).resolve().parent.parent

# CP 만기 컬럼 헤더 (KOFIA 표 표준)
CP_MATURITIES = ("7일", "15일", "1월", "3월", "6월", "1년")

# 기관명 컬럼에서 평균 행 식별용 (회사채 CSV는 "평가사 평균(`23.1.9~)" 패턴)
_AVG_AGENCY_KEYWORDS = ("5사 평균", "평가사 평균", "5社 평균", "평균")


def _find_cp_csv() -> Optional[tuple[Path, date, bool]]:
    """CP CSV 파일 검색.

    Returns:
        (path, as_of, has_date_in_name)  또는  None (파일 없음).
    """
    candidates = sorted(_VAR_ROOT.glob("cp_수익률*.csv"))
    if not candidates:
        return None

    # 날짜 접미사가 있는 파일 우선
    for p in reversed(candidates):
        m = re.search(r"(\d{8})", p.stem)
        if m:
            try:
                as_of = datetime.strptime(m.group(1), "%Y%m%d").date()
                return p, as_of, True
            except ValueError:
                continue

    # 날짜 없으면 mtime 사용
    p = candidates[-1]
    as_of = date.fromtimestamp(p.stat().st_mtime)
    return p, as_of, False


def _detect_columns(header: list[str]) -> dict[str, int]:
    """헤더에서 등급/기관명/만기 컬럼 인덱스 자동 탐지.

    유연 대응:
      - 등급 컬럼: "신용등급" | "등급"
      - 기관명: "기관명" | "고시기관"
      - 만기: "7일", "15일", "1월", "3월", "6월", "1년" (그대로)
    """
    idx: dict[str, int] = {}

    # 등급 컬럼
    for cand in ("신용등급", "등급"):
        if cand in header:
            idx["rating"] = header.index(cand)
            break
    if "rating" not in idx:
        raise RuntimeError(
            f"CP CSV 헤더에서 신용등급 컬럼을 찾지 못함: {header}\n"
            f"  허용 헤더: '신용등급' | '등급'"
        )

    # 기관명 컬럼
    for cand in ("기관명", "고시기관"):
        if cand in header:
            idx["agency"] = header.index(cand)
            break
    if "agency" not in idx:
        raise RuntimeError(
            f"CP CSV 헤더에서 기관명 컬럼을 찾지 못함: {header}\n"
            f"  허용 헤더: '기관명' | '고시기관'"
        )

    # 만기 컬럼들
    for mat in CP_MATURITIES:
        if mat in header:
            idx[f"mat_{mat}"] = header.index(mat)
    if not any(k.startswith("mat_") for k in idx):
        raise RuntimeError(
            f"CP CSV 헤더에서 만기 컬럼을 하나도 못 찾음: {header}\n"
            f"  허용 만기: {CP_MATURITIES}"
        )

    return idx


def _is_average_agency(agency_value: str) -> bool:
    """기관명 셀이 '5사 평균' 류인지 판정."""
    v = agency_value.strip().replace(" ", "")
    for kw in _AVG_AGENCY_KEYWORDS:
        if kw.replace(" ", "") in v:
            return True
    return False


def load_cp_yields_from_csv(path: Optional[Path] = None) -> Optional[dict]:
    """CP CSV에서 5사 평균 yield 추출.

    Returns:
        성공: {"as_of_date": "...", "source_file": "...", "rates": {등급: {만기: yield}}, ...}
        실패: None (파일 없음 / 파싱 실패)
    """
    if path is None:
        found = _find_cp_csv()
        if found is None:
            return None
        path, as_of, has_date = found
    else:
        path = Path(path)
        m = re.search(r"(\d{8})", path.stem)
        if m:
            as_of = datetime.strptime(m.group(1), "%Y%m%d").date()
            has_date = True
        else:
            as_of = date.fromtimestamp(path.stat().st_mtime)
            has_date = False

    rates: dict[str, dict[str, float]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        idx = _detect_columns(header)

        for row in reader:
            if len(row) <= idx["agency"]:
                continue
            if not _is_average_agency(row[idx["agency"]]):
                continue   # 평균 행만 사용
            rating = row[idx["rating"]].strip()
            if rating not in VALID_CP_RATINGS:
                continue

            tier: dict[str, float] = {}
            for mat in CP_MATURITIES:
                key = f"mat_{mat}"
                if key not in idx:
                    continue
                val = row[idx[key]].strip()
                if val in ("-", "", "n/a", "N/A"):
                    continue
                try:
                    tier[mat] = float(val.replace(",", "")) / 100.0   # % → 소수
                except ValueError:
                    continue
            if tier:
                rates[rating] = tier

    if not rates:
        return None   # 평균 행이 하나도 없음 → CSV 부적합

    return {
        "as_of_date":        as_of.isoformat(),
        "source_file":       path.name,
        "filename_has_date": has_date,
        "rates":             rates,
    }


def get_cp_yield(cp_rating: str, maturity: str = "1년") -> dict:
    """CP yield 단일값 조회 (CSV 우선, 없으면 하드코드 fallback).

    Returns:
        {"yield": 0.0315, "source": "CSV"|"hardcoded fallback",
         "as_of": "2026-05-18", "source_detail": "..."}
    """
    if cp_rating not in VALID_CP_RATINGS:
        raise KeyError(
            f"CP 등급 '{cp_rating}' 이 KOFIA 정확 표기 아님.\n"
            f"  허용: {VALID_CP_RATINGS}"
        )

    table = load_cp_yields_from_csv()
    if table is not None and cp_rating in table["rates"]:
        tier = table["rates"][cp_rating]
        if maturity not in tier:
            raise KeyError(
                f"CSV에 CP {cp_rating} 등급의 '{maturity}' 만기 데이터 없음.\n"
                f"  존재 만기: {sorted(tier.keys())}"
            )
        return {
            "yield":         tier[maturity],
            "source":        "CSV",
            "as_of":         table["as_of_date"],
            "source_detail": f"CSV({table['source_file']})",
            "filename_has_date": table["filename_has_date"],
        }

    # CSV 미보유 또는 해당 등급 없음 → 하드코드 fallback
    if cp_rating not in KOFIA_CP_REFERENCE:
        raise KeyError(
            f"CP 등급 '{cp_rating}' 데이터를 어디서도 찾을 수 없음.\n"
            f"  CSV: {'있으나 등급 부재' if table else '없음'}\n"
            f"  하드코드 fallback: {sorted(KOFIA_CP_REFERENCE.keys())} 만 수록\n"
            f"  → KOFIA에서 CP CSV를 다운받아 "
            f"   VAR/cp_수익률_YYYYMMDD.csv 로 저장하세요."
        )
    tier = KOFIA_CP_REFERENCE[cp_rating]
    if maturity not in tier:
        raise KeyError(
            f"하드코드 fallback에 CP {cp_rating} '{maturity}' 만기 없음. "
            f"가능: {sorted(tier.keys())}"
        )
    return {
        "yield":         tier[maturity],
        "source":        "hardcoded fallback",
        "as_of":         KOFIA_CP_AS_OF,
        "source_detail": KOFIA_CP_SOURCE,
        "filename_has_date": True,   # 하드코드는 시점 명시되어 있음
    }


if __name__ == "__main__":
    # 모든 CP 등급 × 모든 만기 dump
    found = _find_cp_csv()
    if found:
        path, as_of, has_date = found
        print(f"CSV 발견: {path.name}  (as_of {as_of}, 파일명_날짜={has_date})")
    else:
        print(f"CSV 없음 → 하드코드 fallback ({KOFIA_CP_AS_OF}, "
              f"수록 등급 {sorted(KOFIA_CP_REFERENCE.keys())})")

    print(f"\n{'등급':5s} | " + "  ".join(f"{m:>6s}" for m in CP_MATURITIES))
    print("-" * 60)
    for r in VALID_CP_RATINGS:
        try:
            row = []
            for m in CP_MATURITIES:
                info = get_cp_yield(r, m)
                row.append(f"{info['yield']*100:5.3f}%")
            print(f"{r:5s} | " + "  ".join(row))
        except KeyError:
            print(f"{r:5s} | (데이터 없음)")
