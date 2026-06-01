# -*- coding: utf-8 -*-
"""D-8 신호 ②(지분법손익) + ③(세그먼트) — 추출 방법 비교 검증.

방법 A) FNLTT 한글 키워드 매칭
    DART fnlttSinglAcntAll.json 응답에서 'account_nm' (한글) 에 '지분법' 키워드 포함된
    IS/CIS 항목 값 추출.

방법 B) XBRL raw 태그 매칭
    xbrl_raw/<ticker>_<corp>_<year>/*.xbrl 인스턴스 문서에서 ifrs-full 태그 직접 추출.

비교 대상: 두산(000150) 복합 / GS(078930) 지주 / CJ제일제당(097950) operating.

용도: 일회성 검증 — 결과만 출력. 운영 코드 아님.

실행:
    python -m valuation_engine.tests._d8_signal_validation
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

_VAR_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_VAR_ROOT))

from valuation_engine.extract_balance_sheet import (
    _parse_xbrl, _extract_equity_method_income, _extract_segment_revenues,
)

load_dotenv(_VAR_ROOT / ".env")
_DART_KEY = os.getenv("DART_API_KEY")

TARGETS = [
    ("000150", "두산",       "00117212", "복합기업"),
    ("078930", "GS",         "00500254", "순수지주"),
    ("097950", "CJ제일제당", "00635134", "operating"),
]
YEAR = 2025
REPRT = "11011"


def _fmt_won(v):
    if v is None:
        return "       —"
    sign = "-" if v < 0 else " "
    a = abs(v)
    if a >= 1e12: return f"{sign}{a/1e12:6.2f}조"
    if a >= 1e8:  return f"{sign}{a/1e8:6.0f}억"
    return f"{sign}{a:>8.0f}"


# ─────────────────────────────────────────────────────────────
# 방법 A: FNLTT 한글 키워드
# ─────────────────────────────────────────────────────────────
def fetch_fnltt(corp_code: str, year: int, reprt: str = REPRT) -> list:
    """fnlttSinglAcntAll(연결) → list of rows. 실패 시 빈 list."""
    if not _DART_KEY:
        return []
    rows = []
    for fs_div in ("CFS", "OFS"):
        try:
            r = requests.get(
                "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json",
                params={"crtfc_key": _DART_KEY, "corp_code": corp_code,
                        "bsns_year": str(year), "reprt_code": reprt,
                        "fs_div": fs_div}, timeout=60)
            d = r.json()
        except Exception as e:
            print(f"  [warn] fnltt {fs_div} 실패: {e}")
            continue
        if d.get("status") == "000" and d.get("list"):
            rows.extend([{**x, "_fs_div": fs_div} for x in d["list"]])
    return rows


def _amt(row):
    v = (row.get("thstrm_amount") or "").replace(",", "").strip()
    try: return float(v)
    except (ValueError, TypeError): return None


def fnltt_equity_method_income(rows: list) -> tuple:
    """한글 키워드 매칭 — '지분법' 포함된 IS/CIS 항목 추출.

    여러 hit 가능 (관계기업 vs 공동기업 별도 보고). 모두 반환.
    """
    out = []
    for x in rows:
        sj  = x.get("sj_div", "")
        if sj not in ("IS", "CIS"):
            continue
        nm  = (x.get("account_nm") or "").replace(" ", "")
        aid = (x.get("account_id") or "").strip()
        # 한글 키워드
        kw_hit = "지분법" in nm
        # 영문 account_id 도 같이 기록 (참조)
        id_hit = "ShareOfProfitLoss" in aid and "Associates" in aid
        if kw_hit or id_hit:
            out.append({"sj": sj, "fs_div": x.get("_fs_div"),
                        "account_nm": x.get("account_nm"),
                        "account_id": aid, "value": _amt(x), "kw_hit": kw_hit,
                        "id_hit": id_hit})
    return out


def fnltt_operating_income(rows: list) -> float | None:
    """fnltt 에서 영업이익 (연결 우선)."""
    for fs in ("CFS", "OFS"):
        for x in rows:
            if x.get("_fs_div") != fs:
                continue
            if x.get("sj_div") not in ("IS", "CIS"):
                continue
            nm  = (x.get("account_nm") or "").replace(" ", "")
            aid = (x.get("account_id") or "")
            if nm == "영업이익" or aid == "dart_OperatingIncomeLoss":
                v = _amt(x)
                if v is not None:
                    return v
    return None


def fnltt_segments(corp_code: str, year: int) -> list:
    """fnltt 에 사업부문 매출이 들어 있는지 별도 확인.

    fnltt 표준재무제표는 회사 합계만 보고 — 세그먼트는 대체로 부재.
    부재 시 빈 list 반환 (그게 결론).
    """
    return []   # 표준 fnltt API 엔드포인트엔 세그먼트 매출 없음. (별도 사업의보고서 본문 텍스트 필요)


# ─────────────────────────────────────────────────────────────
# 방법 B: XBRL raw 태그
# ─────────────────────────────────────────────────────────────
def xbrl_path_for(ticker: str, corp_name: str, year: int) -> Path | None:
    p = _VAR_ROOT / "xbrl_raw" / f"{ticker}_{corp_name}_{year}"
    if not p.exists():
        return None
    fs = list(p.glob("*.xbrl"))
    return fs[0] if fs else None


def xbrl_operating_income(tree, nsmap, year: int) -> float | None:
    """dart:OperatingIncomeLoss 연결·당기."""
    from valuation_engine.extract_balance_sheet import _resolve_tag
    for el in tree.iterfind(f".//{_resolve_tag('dart:OperatingIncomeLoss', nsmap)}"):
        ctx = el.get("contextRef", "")
        if f"CFY{year}dFY" in ctx and "ConsolidatedMember" in ctx \
           and "SegmentConsolidationItemsAxis" not in ctx \
           and "SeparateMember" not in ctx:
            try: return float(el.text)
            except (TypeError, ValueError): pass
    return None


# ─────────────────────────────────────────────────────────────
# 검증 메인
# ─────────────────────────────────────────────────────────────
def main():
    print("\n" + "="*88)
    print(" D-8 신호 ②③ 추출 — FNLTT 한글 키워드 vs XBRL ifrs-full 태그 비교")
    print("="*88)
    print(f" 회계연도 FY{YEAR}, 보고서 {REPRT} (사업보고서)\n")

    for ticker, corp_name, corp_code, type_tag in TARGETS:
        print(f"\n  ─── [{ticker}] {corp_name} ({type_tag}) ───")

        # 방법 A — FNLTT
        rows = fetch_fnltt(corp_code, YEAR)
        em_fnltt   = fnltt_equity_method_income(rows)
        ebit_fnltt = fnltt_operating_income(rows)

        # 방법 B — XBRL raw
        xpath = xbrl_path_for(ticker, corp_name, YEAR)
        if xpath is None:
            print(f"    [-] xbrl_raw 없음 — XBRL 방법 검증 불가")
            continue
        tree, nsmap = _parse_xbrl(xpath)
        em_xbrl    = _extract_equity_method_income(tree, nsmap, YEAR)
        seg_xbrl   = _extract_segment_revenues(tree, nsmap, YEAR)
        ebit_xbrl  = xbrl_operating_income(tree, nsmap, YEAR)

        # 비교: 영업이익
        print(f"    영업이익            FNLTT: {_fmt_won(ebit_fnltt)}     "
              f"XBRL: {_fmt_won(ebit_xbrl)}     "
              f"{'OK' if (ebit_fnltt and ebit_xbrl and abs(ebit_fnltt-ebit_xbrl)/abs(ebit_xbrl) < 0.02) else '⚠'}")

        # 비교: 신호 ② 지분법손익
        em_fnltt_sum = sum(x["value"] or 0 for x in em_fnltt)
        print(f"    지분법손익(②)      FNLTT: {_fmt_won(em_fnltt_sum) if em_fnltt else '   부재'}     "
              f"XBRL: {_fmt_won(em_xbrl)}     "
              f"{'OK' if (em_fnltt_sum and em_xbrl and abs(em_fnltt_sum-em_xbrl)/max(abs(em_xbrl),1) < 0.05) else '⚠ 불일치/부재'}")
        if em_fnltt:
            for h in em_fnltt:
                print(f"      · fnltt[{h['sj']}/{h['fs_div']}] "
                      f"\"{h['account_nm']}\" = {_fmt_won(h['value'])} "
                      f"(kw_hit={h['kw_hit']}, id_hit={h['id_hit']})")
        if em_xbrl is not None and ebit_xbrl:
            ratio = abs(em_xbrl) / abs(ebit_xbrl)
            sig2 = "✓ HOLDING신호" if ratio > 0.50 else "operating"
            print(f"      · 신호 ② 비율: |지분법손익|/|영업이익| = {ratio*100:.1f}%  → {sig2}")

        # 비교: 신호 ③ 세그먼트 — fnltt 부재, XBRL 만 비교
        print(f"    세그먼트(③)        FNLTT: {'    부재 (표준 API 미포함)'}     "
              f"XBRL: {seg_xbrl['n_segments']}개 부문")
        if seg_xbrl["n_segments"] > 0:
            sig3 = "✓ 복합기업" if (seg_xbrl["top_share"] < 0.60 and seg_xbrl["n_segments"] >= 3) \
                  else "단일/지배사업"
            print(f"      · 1위 {seg_xbrl['top_share']*100:.1f}%  HHI {seg_xbrl['hhi']:.3f}  → {sig3}")
            for s in seg_xbrl["segments"][:6]:
                print(f"        - {s['label'][:35]:<35s} {s['share']*100:5.1f}%  "
                      f"{_fmt_won(s['revenue'])}")

    print("\n" + "="*88)


if __name__ == "__main__":
    main()
