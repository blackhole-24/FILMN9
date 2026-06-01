"""KOFIA "채권시가평가기준수익률" CSV 파서 — Kd 산정용.

설계:
  - 종류: 회사채 I(공모사채)
  - 종류명: 무보증
  - 만기: 5년
  - 행: 신용등급별 (AAA, AA+, AA0, AA-, A+, A0, A-, BBB+, BBB0, BBB-)

파일 위치 (둘 다 지원):
  1) VAR/채권시가평가기준수익률_<YYYYMMDD>.csv  → 파일명에서 as_of 추출
  2) VAR/채권시가평가기준수익률.csv               → 파일 mtime → as_of (경고)

호출:
  >>> info = get_kd_by_rating("AA0")
  >>> info["kd"]          # 0.04495
  >>> info["as_of_date"]  # "2026-05-18"
"""
from __future__ import annotations

import csv
import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional

_VAR_ROOT = Path(__file__).resolve().parent.parent

# KOFIA 정확 표기 (엄격 매칭)
VALID_RATINGS = ("AAA", "AA+", "AA0", "AA-",
                 "A+",  "A0",  "A-",
                 "BBB+", "BBB0", "BBB-")

BOND_TYPE = "회사채 I(공모사채)"   # 종류 컬럼 값
BOND_GUARANTEE = "무보증"           # 종류명 컬럼 값
MATURITY_COL = "5년"                # 만기 컬럼 헤더


def _find_kofia_file() -> tuple[Path, date, bool]:
    """KOFIA CSV 파일 검색.

    Returns:
        (path, as_of, has_date_in_name)
    """
    candidates = sorted(_VAR_ROOT.glob("채권시가평가기준수익률*.csv"))
    if not candidates:
        raise FileNotFoundError(
            f"KOFIA CSV 파일이 없습니다.\n"
            f"  검색 경로: {_VAR_ROOT}/채권시가평가기준수익률*.csv\n"
            f"  → KOFIA에서 받아 위 경로에 저장하세요. "
            f"  권장 파일명: 채권시가평가기준수익률_YYYYMMDD.csv"
        )

    # 파일명에 YYYYMMDD 가 포함된 것을 우선
    for p in reversed(candidates):
        m = re.search(r"(\d{8})", p.stem)
        if m:
            yyyymmdd = m.group(1)
            try:
                as_of = datetime.strptime(yyyymmdd, "%Y%m%d").date()
                return p, as_of, True
            except ValueError:
                continue

    # 파일명에 날짜가 없는 경우 — mtime 사용
    p = candidates[-1]
    as_of = date.fromtimestamp(p.stat().st_mtime)
    return p, as_of, False


def load_corp_bond_yields_5y(path: Optional[Path] = None) -> dict:
    """회사채 I(공모사채) 무보증 5년 수익률 — 신용등급별 dict 반환.

    Returns:
        {
            "as_of_date": "2026-05-18",
            "source_file": "채권시가평가기준수익률.csv",
            "bond_type": "회사채 I(공모사채)",
            "guarantee": "무보증",
            "maturity":  "5년",
            "rates": {"AAA": 0.04338, "AA+": 0.04429, "AA0": 0.04495, ...},
            "filename_has_date": bool,
        }
    """
    if path is None:
        path, as_of, has_date = _find_kofia_file()
    else:
        path = Path(path)
        m = re.search(r"(\d{8})", path.stem)
        if m:
            as_of = datetime.strptime(m.group(1), "%Y%m%d").date()
            has_date = True
        else:
            as_of = date.fromtimestamp(path.stat().st_mtime)
            has_date = False

    rates: dict[str, float] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)

        try:
            idx_type     = header.index("종류")
            idx_subtype  = header.index("종류명")
            idx_rating   = header.index("신용등급")
            idx_maturity = header.index(MATURITY_COL)
        except ValueError as e:
            raise RuntimeError(
                f"KOFIA CSV 헤더가 예상과 다릅니다: {header}\n  원인: {e}"
            ) from e

        for row in reader:
            if len(row) <= max(idx_type, idx_subtype, idx_rating, idx_maturity):
                continue
            if row[idx_type].strip() != BOND_TYPE:
                continue
            if row[idx_subtype].strip() != BOND_GUARANTEE:
                continue
            rating = row[idx_rating].strip()
            if rating not in VALID_RATINGS:
                continue
            val = row[idx_maturity].strip()
            if val in ("-", "", "n/a", "N/A"):
                continue
            try:
                pct = float(val.replace(",", ""))
            except ValueError:
                continue
            rates[rating] = pct / 100.0   # % → 소수

    if not rates:
        raise RuntimeError(
            f"{path.name} 에서 '{BOND_TYPE} {BOND_GUARANTEE} {MATURITY_COL}' "
            f"데이터를 찾지 못했습니다."
        )

    return {
        "as_of_date":  as_of.isoformat(),
        "source_file": path.name,
        "bond_type":   BOND_TYPE,
        "guarantee":   BOND_GUARANTEE,
        "maturity":    MATURITY_COL,
        "rates":       rates,
        "filename_has_date": has_date,
    }


def get_kd_by_rating(rating: str, path: Optional[Path] = None) -> dict:
    """신용등급 → Kd (소수) + 메타데이터.

    Args:
        rating: KOFIA 정확 표기. 예: "AA0", "AA+", "A-"
                (RAG에서 "AA" 가 와도 본 함수에서는 자동 변환 안 함 — fetch_credit_rating 측에서 정규화)

    Raises:
        KeyError: rating 이 VALID_RATINGS 에 없거나 KOFIA 표에 해당 등급 누락.
    """
    table = load_corp_bond_yields_5y(path)
    if rating not in table["rates"]:
        raise KeyError(
            f"신용등급 '{rating}' 에 해당하는 Kd를 찾을 수 없습니다.\n"
            f"  사용 가능 등급: {sorted(table['rates'].keys())}\n"
            f"  KOFIA 정확 표기 요구 (예: AA0, AA+, A-)"
        )
    return {
        "kd":             table["rates"][rating],
        "kd_pct":         table["rates"][rating] * 100,
        "rating":         rating,
        "kofia_as_of":    table["as_of_date"],
        "kofia_source":   table["source_file"],
        "bond_type":      table["bond_type"],
        "guarantee":      table["guarantee"],
        "maturity":       table["maturity"],
        "filename_has_date": table["filename_has_date"],
    }


if __name__ == "__main__":
    t = load_corp_bond_yields_5y()
    print(f"as_of: {t['as_of_date']}  (filename_has_date={t['filename_has_date']})")
    print(f"source: {t['source_file']}")
    print(f"{t['bond_type']} {t['guarantee']} {t['maturity']}:")
    for r in VALID_RATINGS:
        v = t["rates"].get(r)
        if v is not None:
            print(f"  {r:5s}  {v*100:.3f}%")
