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

# 실데이터 100% 정책 — fallback 하드코드 모두 제거 (옵션 A)
# - CSV 미존재 → FileNotFoundError 그대로 전파
# - KOFIA 표 외 등급(BB+ 이하) → KeyError 그대로 전파
# 사용자에게 데이터 부족을 명시적으로 알림 + 시스템이 임의값으로 진행 안 함


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

    캐시 정책 (실데이터 100%):
      - VAR/채권시가평가기준수익률_<YYYYMMDD>.csv 필수
      - CSV 미존재 시 FileNotFoundError 발생 (임의값 사용 안 함)

    Returns:
        {
            "as_of_date": "2026-05-18",
            "source_file": "채권시가평가기준수익률.csv",
            "bond_type": "회사채 I(공모사채)",
            "guarantee": "무보증",
            "maturity":  "5년",
            "rates": {"AAA": 0.04338, "AA+": 0.04429, "AA0": 0.04495, ...},
            "filename_has_date": bool,
            "is_fallback": False,   # 실데이터 100% 정책 (옛 잔재 호환만)
        }
    """
    if path is None:
        # 실데이터 정책 — CSV 미존재 시 FileNotFoundError 그대로 전파
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
        "is_fallback": False,
    }


def normalize_rating(rating: str) -> str:
    """신용등급 표기 정규화 — RAG/시장 관행 다양한 표기 → KOFIA 정확 표기.

    변환 규칙:
      - 공백·하이픈 정리 ("AA 0" → "AA0", "AA -" → "AA-")
      - 0 생략 표기 → 정확 표기:  "AA" → "AA0",  "A" → "A0",  "BBB" → "BBB0"
                                  "BB" → "BB0",  "B"  → "B0"  (KOFIA 표 외 등급도 대비)
      - 대소문자 통일:  "aa" → "AA"
      - 한글 등급 표기:  "에이에이" → "AA0" (드물지만 RAG 결과 대응)

    Returns:
        KOFIA 정확 표기 (예: "AA0"). 매핑 실패 시 원본 그대로 반환.
    """
    if not rating:
        return rating

    # 1) 공백·하이픈 정리 + 대문자
    r = "".join(rating.split()).upper()

    # 2) 한글 표기 처리 (선택적)
    KOR_TO_LETTER = {
        "트리플에이": "AAA", "더블에이": "AA", "싱글에이": "A",
        "트리플비": "BBB",
    }
    for k, v in KOR_TO_LETTER.items():
        if k in r:
            r = v
            break

    # 3) 이미 정확 표기면 즉시 반환
    if r in VALID_RATINGS:
        return r

    # 4) 0 생략 표기 → 0 추가
    #    "AA" → "AA0"  /  "A" → "A0"  /  "BBB" → "BBB0"
    #    단, "AAA" 는 그대로 (AAA0 아님), "AA+"/"AA-" 같은 +/- 도 그대로
    if r and r[-1] not in "+-0":
        cand = r + "0"
        if cand in VALID_RATINGS:
            return cand

    # 5) 그래도 매핑 안 되면 원본 반환 (호출 측에서 KeyError or fallback)
    return r


def get_kd_by_rating(rating: str, path: Optional[Path] = None) -> dict:
    """신용등급 → Kd (소수) + 메타데이터.

    Args:
        rating: 신용등급 (자동 정규화 — "AA" 입력 → "AA0" 매핑).
                지원 입력 형식: "AA0", "AA", "AA+", "AA-", "aa", "에이에이", "AA " 등.

    Raises:
        KeyError: 정규화 후에도 매핑 실패한 경우.
    """
    table = load_corp_bond_yields_5y(path)

    # ★ 등급 정규화 ("AA" → "AA0" 등)
    normalized = normalize_rating(rating)
    if normalized != rating:
        # 호출 측에서 "어떤 매핑이 됐는지" 알 수 있게 정보 보존
        pass

    # 실데이터 정책 — KOFIA 표 외 등급(BB+ 이하)도 추정값 사용 금지
    if normalized not in table["rates"]:
        raise KeyError(
            f"신용등급 '{rating}' (정규화: '{normalized}') 매핑 실패.\n"
            f"  KOFIA 표 수록 등급: {sorted(table['rates'].keys())}\n"
            f"  표기 점검 권장 (예: AA0, AA+, A-, BBB-) — 추정값 사용 안 함."
        )

    return {
        "kd":             table["rates"][normalized],
        "kd_pct":         table["rates"][normalized] * 100,
        "rating":         normalized,     # ★ 정규화된 등급 반환
        "rating_input":   rating,         # 원본 입력도 보존 (UI 디버깅용)
        "rating_normalized": (normalized != rating),   # 정규화 여부 flag
        "kofia_as_of":    table["as_of_date"],
        "kofia_source":   table["source_file"],
        "bond_type":      table["bond_type"],
        "guarantee":      table["guarantee"],
        "maturity":       table["maturity"],
        "filename_has_date": table["filename_has_date"],
        "is_fallback":    table.get("is_fallback", False),
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
