"""XBRL 통합 수집기 (팀원 fork + 자본·NCI·EPS 추가).

팀원의 xbrl_financials_v4.extract_company() 가 추출하는 기본 재무 필드에
v3 가치평가에 필요한 5개 필드를 추가 통합:

  추가 필드 (extract_balance_sheet.parse_xbrl_balance 활용):
    equity_total       — ifrs-full:Equity (자본총계 = 지배 + 비지배)
    equity_parent      — ifrs-full:EquityAttributableToOwnersOfParent (지배지분)
    minority_interest  — ifrs-full:NoncontrollingInterests (비지배지분)
    preferred_capital  — IssuedCapital + PreferenceSharesMember axis (우선주 자본금)
    basic_eps          — ifrs-full:BasicEarningsLossPerShare (XBRL 직접 보고 EPS)

저장 경로 통일:
  v3 표준: VAR/data/xbrl/<corp_name>_<year>.json
  팀원 옛: VAR/XBRL/xbrl_results_<year>/<corp_name>_<year>.json (호환 유지)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

_VAR_ROOT = Path(__file__).resolve().parent.parent
# 팀원 모듈 path
sys.path.insert(0, str(_VAR_ROOT / "XBRL"))

from xbrl_financials_v4 import extract_company as _team_extract_company
from .extract_balance_sheet import parse_xbrl_balance


# ─────────────────────────────────────────────────────────────
# 저장 경로 (통일)
# ─────────────────────────────────────────────────────────────
UNIFIED_XBRL_DIR = _VAR_ROOT / "data" / "xbrl"
UNIFIED_XBRL_DIR.mkdir(parents=True, exist_ok=True)
RAW_XBRL_DIR     = _VAR_ROOT / "xbrl_raw"


# ─────────────────────────────────────────────────────────────
# 자본·NCI·EPS 추출 — XBRL raw 가 있으면 즉시
# ─────────────────────────────────────────────────────────────
def _find_xbrl_raw_file(ticker: str, corp_name: str, year: int) -> Optional[Path]:
    """xbrl_raw 폴더에서 해당 회사·연도의 .xbrl 파일 찾기."""
    folder = RAW_XBRL_DIR / f"{ticker}_{corp_name}_{year}"
    if not folder.exists():
        return None
    candidates = list(folder.glob("*.xbrl"))
    return candidates[0] if candidates else None


def _download_xbrl_raw(ticker: str, corp_name: str, year: int,
                       rcept_no: str, reprt_code: str = "11011") -> Optional[Path]:
    """DART fnlttXbrl.xml 로 XBRL ZIP 을 받아 .xbrl 인스턴스 문서를
    xbrl_raw/<ticker>_<corp_name>_<year>/ 에 영구 저장 후 경로 반환.

    자본·NCI·EPS 추출에 필요한 raw 가 없을 때 호출 (POC 외 종목 자동 보강).
    실패 시 None (네트워크/권한/파일 부재 등 — 호출자가 None 처리).
    """
    import io
    import os
    import shutil
    import tempfile
    import zipfile
    import glob as _glob

    import requests
    from dotenv import load_dotenv

    if not rcept_no:
        return None
    load_dotenv(_VAR_ROOT / ".env")
    key = os.getenv("DART_API_KEY")
    if not key:
        return None

    try:
        res = requests.get(
            "https://opendart.fss.or.kr/api/fnlttXbrl.xml",
            params={"crtfc_key": key, "rcept_no": rcept_no, "reprt_code": reprt_code},
            timeout=120,
        )
        # 에러 응답은 XML 텍스트 (status 014 등) — ZIP 시그니처 검증
        if res.status_code != 200 or not (
            res.content[:2] == b"PK" or "zip" in res.headers.get("Content-Type", "")
        ):
            return None

        folder = RAW_XBRL_DIR / f"{ticker}_{corp_name}_{year}"
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            zipfile.ZipFile(io.BytesIO(res.content)).extractall(tmp)
            xbrls = _glob.glob(os.path.join(tmp, "**", "*.xbrl"), recursive=True)
            if not xbrls:
                return None
            src = max(xbrls, key=os.path.getsize)   # 메인 인스턴스 문서
            dst = folder / os.path.basename(src)
            shutil.copy(src, dst)
            return dst
    except Exception:
        return None


def _fetch_bs_from_fnltt(corp_code: str, year: int,
                         reprt_code: str = "11011") -> Optional[dict]:
    """표준 재무제표 API(fnlttSinglAcntAll)에서 자본·NCI·EPS 폴백 추출.

    xbrl_raw(.xbrl 인스턴스)가 없거나 다운로드 실패한 종목(첨부정정·미첨부 등)을 위해
    DART 정형 재무제표 JSON 에서 직접 자본총계/지배지분/비지배지분/기본EPS 를 파싱.
    연결(CFS) 우선, 없으면 별도(OFS). 실패 시 None.
    """
    import os
    import requests
    from dotenv import load_dotenv

    if not corp_code:
        return None
    load_dotenv(_VAR_ROOT / ".env")
    key = os.getenv("DART_API_KEY")
    if not key:
        return None

    def _amt(row):
        v = (row.get("thstrm_amount") or "").replace(",", "").strip()
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    for fs_div in ("CFS", "OFS"):
        try:
            r = requests.get(
                "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json",
                params={"crtfc_key": key, "corp_code": corp_code,
                        "bsns_year": str(year), "reprt_code": reprt_code,
                        "fs_div": fs_div}, timeout=60)
            d = r.json()
        except Exception:
            continue
        if d.get("status") != "000":
            continue
        rows = d.get("list", []) or []
        eq_total = eq_parent = nci = eps = None
        for x in rows:
            aid = (x.get("account_id") or "").strip()
            anm = (x.get("account_nm") or "").replace(" ", "")
            sj = x.get("sj_div")
            if sj == "BS":
                if aid == "ifrs-full_Equity" or anm == "자본총계":
                    eq_total = _amt(x)
                elif aid == "ifrs-full_EquityAttributableToOwnersOfParent" \
                        or ("지배기업" in anm and "소유주" in anm) or anm == "지배기업소유주지분":
                    eq_parent = _amt(x)
                elif aid == "ifrs-full_NoncontrollingInterests" or anm == "비지배지분":
                    nci = _amt(x)
            elif sj in ("IS", "CIS"):
                if aid == "ifrs-full_BasicEarningsLossPerShare" or anm in ("기본주당이익", "기본주당순이익"):
                    if eps is None:
                        eps = _amt(x)
        if eq_total is None and eq_parent is None:
            continue   # 이 fs_div 엔 BS 자본 항목 없음 → 다음 시도
        # 비지배지분 보강: 자본총계 − 지배지분
        if nci is None and eq_total is not None and eq_parent is not None:
            nci = eq_total - eq_parent
        return {"equity_total": eq_total, "equity_parent": eq_parent,
                "minority_interest": nci, "basic_eps": eps, "fs_div": fs_div}
    return None


def _enrich_with_balance_sheet(result: dict, year: int) -> dict:
    """결과 dict 에 자본·NCI·EPS 5개 필드 추가.

    1순위: xbrl_raw(.xbrl) 파싱. 없으면 다운로드 시도.
    2순위(폴백): 표준 재무제표 API(fnlttSinglAcntAll) 에서 자본·NCI·EPS 추출.
    둘 다 실패 시 None (필드는 항상 존재).
    """
    meta      = result.get("meta", {})
    ticker    = meta.get("stock_code", "")
    corp_name = meta.get("corp_name", "")

    xbrl_path = _find_xbrl_raw_file(ticker, corp_name, year)
    if xbrl_path is None:
        # 자본/NCI/EPS 는 멀티플·equity_value·implied_roic 에서 최신연도만 사용.
        # 과거 연도 raw 다운로드는 불필요 → 최신연도(max FISCAL_YEARS)일 때만 DART 호출.
        # (FCFF 정상화는 자본 필드를 안 쓰므로 과거 연도는 None 이어도 무방 → 첫 평가 속도 ↑)
        try:
            from .config import FISCAL_YEARS as _FY
            _is_latest = int(year) >= max(_FY)
        except Exception:
            _is_latest = True
        if _is_latest:
            xbrl_path = _download_xbrl_raw(
                ticker, corp_name, year,
                rcept_no=meta.get("rcept_no", ""),
                reprt_code=meta.get("reprt_code", "11011"),
            )
    if xbrl_path is None:
        # ★ 폴백: 표준 재무제표 API(fnlttSinglAcntAll)에서 자본·NCI·EPS 추출
        fb = _fetch_bs_from_fnltt(
            meta.get("corp_code", ""), year, meta.get("reprt_code", "11011"))
        if fb:
            result.setdefault("financials", {}).update({
                "equity_total":      fb["equity_total"],
                "equity_parent":     fb["equity_parent"],
                "minority_interest": fb["minority_interest"],
                "preferred_capital": 0,
                "basic_eps":         fb.get("basic_eps"),
                # D-8 신호 ②③ — fnltt 폴백엔 IS 지분법손익/세그먼트 부재 (graceful)
                "equity_method_income": None,
                "segment_revenues":  None,
                "balance_sheet_source": f"fnlttSinglAcntAll/{fb.get('fs_div')} (xbrl_raw 폴백)",
            })
            return result
        # 폴백도 실패 — 필드 None 으로 추가
        result.setdefault("financials", {}).update({
            "equity_total":      None,
            "equity_parent":     None,
            "minority_interest": None,
            "preferred_capital": None,
            "basic_eps":         None,
            "equity_method_income": None,
            "segment_revenues":  None,
            "balance_sheet_source": "missing (xbrl_raw·fnltt 모두 실패)",
        })
        return result

    try:
        bs = parse_xbrl_balance(xbrl_path, year=year)
        result.setdefault("financials", {}).update({
            "equity_total":      bs.get("equity_total"),
            "equity_parent":     bs.get("equity_parent"),
            "minority_interest": bs.get("minority_interest"),
            "preferred_capital": bs.get("preferred_capital", 0),
            "basic_eps":         bs.get("basic_eps"),
            # D-8 신호 ②: 손익계산서 지분법손익 (ifrs-full:ShareOfProfitLossOf...)
            "equity_method_income": bs.get("equity_method_income"),
            # D-8 신호 ③: OperatingSegments 차원의 부문 매출 매트릭스
            "segment_revenues":  bs.get("segment_revenues"),
            "balance_sheet_source": str(xbrl_path.name),
        })
    except Exception as e:
        result.setdefault("financials", {}).update({
            "equity_total":      None,
            "equity_parent":     None,
            "minority_interest": None,
            "preferred_capital": None,
            "basic_eps":         None,
            "equity_method_income": None,
            "segment_revenues":  None,
            "balance_sheet_source": f"parse_error: {e}",
        })

    return result


# ─────────────────────────────────────────────────────────────
# 통합 추출 (팀원 + 우리)
# ─────────────────────────────────────────────────────────────
def extract_company_v3(name_or_code: str,
                       year: int,
                       outdir: Optional[Path] = None,
                       save: bool = True,
                       verbose: bool = False) -> dict:
    """팀원 extract_company + 자본·NCI·EPS 통합 + 통일 경로 저장.

    Args:
        name_or_code: 회사명 (한글) 또는 종목코드 (6자리)
        year:         회계연도 (FY2021~FY2025)
        outdir:       저장 폴더 (기본: UNIFIED_XBRL_DIR)
        save:         JSON 저장 여부
        verbose:      진행상황 출력

    Returns:
        {
            "meta": {...},
            "financials": {기존 + equity_total/equity_parent/minority_interest/preferred_capital/basic_eps}
        }

    Raises:
        팀원 함수 실패 시 (corp_code 미발견 등) 그대로 전파.
    """
    outdir = outdir or UNIFIED_XBRL_DIR
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    # 1) 팀원 함수 호출 — 기존 필드
    result = _team_extract_company(
        name_or_code=name_or_code,
        year=year,
        outdir=None,    # 우리가 통일 경로에 저장
        save=False,
        verbose=verbose,
    )

    # 2) 자본·NCI·EPS 추가
    result = _enrich_with_balance_sheet(result, year)

    # 2.5) 지배지분(equity_parent) 폴백 — 별도재무제표/무NCI 회사는 지배지분 태그가
    #   없어 None/0 이 됨(케이씨텍 등). 지배지분 = 자본총계 − 비지배지분
    #   (NCI 없으면 = 자본총계). IC=지배자본+IBD−NOA 가 음수가 되는 결함 방지.
    _fin = result.get("financials", {})
    _ep, _et, _nci = _fin.get("equity_parent"), _fin.get("equity_total"), _fin.get("minority_interest")
    if (not _ep) and _et:
        _fin["equity_parent"] = _et - (_nci or 0)
        _fin["equity_parent_source"] = "derived: equity_total − NCI"

    # 2.6) IBD 정교화 — fnltt 표준계정 합산(주축) + 태그 교차검증(신뢰도).
    #   회사별 XBRL 택소노미 편차로 태그 IBD 가 ±28~48% 틀리는 문제를 표준계정명 합산으로 교정.
    try:
        from .ibd_extractor import compute_ibd
        _meta = result.get("meta", {})
        _cc = _meta.get("corp_code")
        if _cc:
            _ibd_res = compute_ibd(
                _cc, year, _meta.get("reprt_code", "11011"),
                tag_ibd=_fin.get("ibd"), ticker=_meta.get("stock_code"),
                corp_name=_meta.get("corp_name"))
            if _ibd_res.get("fnltt_ibd") is not None:
                _fin["ibd_tag"]         = _fin.get("ibd")          # 원 태그값 보존
                _fin["ibd"]             = _ibd_res["ibd"]           # fnltt 주축 교체
                _fin["ibd_method"]      = _ibd_res["ibd_method"]
                _fin["ibd_confidence"]  = _ibd_res["ibd_confidence"]
                _fin["ibd_fnltt_items"] = _ibd_res["fnltt_items"]
    except Exception:
        pass

    # 3) 통일 경로 저장
    if save:
        corp_name = result.get("meta", {}).get("corp_name", "unknown")
        out_path = outdir / f"{corp_name}_{year}.json"
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        if verbose:
            print(f"  ✓ 저장: {out_path}")
        # ★ DB 자동 적재 (파일 보존 + DB 동기화). 실패해도 파일 경로 영향 없음.
        _sync_financials_to_db(result, year)

    return result


def _sync_financials_to_db(result: dict, year: int) -> None:
    """{meta, financials} 를 DB financials 테이블에 upsert (guarded)."""
    try:
        sc = (result.get("meta", {}) or {}).get("stock_code")
        if not sc:
            return
        from valuation_engine import db
        db.save_financials(sc, int(year), result)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────
# 캐시 로드 — 통일 경로 + 팀원 옛 경로 모두 탐색
# ─────────────────────────────────────────────────────────────
def load_cached(corp_name: str, year: int) -> Optional[dict]:
    """캐시 JSON 로드 — 통일 경로 우선, 옛 경로 fallback.

    탐색 순서 (C-2 정리):
      1. UNIFIED_XBRL_DIR (현재 표준 — VAR/data/xbrl/)
      2. XBRL_LEGACY_DIRS (config 정의 — 팀원 옛 5개 경로)
      3. 우리 옛 경로 (valuation_engine/data/xbrl/) — 자동 migrate 대상

    Returns:
        dict | None.
    """
    # 0) DB 우선 (corp_name 매칭) — 미스 시 파일 폴백
    try:
        from valuation_engine import db
        row = db.store.query_one(
            "SELECT raw_json FROM financials WHERE corp_name=? AND fiscal_year=?",
            (corp_name, int(year)))
        if row and row.get("raw_json"):
            import json as _json
            return _json.loads(row["raw_json"])
    except Exception:
        pass

    # 1) 통일 경로 (가장 빠름)
    p = UNIFIED_XBRL_DIR / f"{corp_name}_{year}.json"
    if p.exists():
        try:
            with p.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    # 2) 팀원 옛 경로 (config.XBRL_LEGACY_DIRS — 5개 연도별)
    try:
        from .config import XBRL_LEGACY_DIRS
        for legacy_dir in XBRL_LEGACY_DIRS:
            p = legacy_dir / f"{corp_name}_{year}.json"
            if p.exists():
                try:
                    with p.open("r", encoding="utf-8") as f:
                        return json.load(f)
                except Exception:
                    continue
    except ImportError:
        pass

    # 3) 우리 옛 경로 (valuation_engine 내부 — 마이그레이션 미완료)
    p = _VAR_ROOT / "valuation_engine" / "data" / "xbrl" / f"{corp_name}_{year}.json"
    if p.exists():
        try:
            with p.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    return None


def has_balance_sheet_fields(data: dict) -> bool:
    """JSON 에 자본·NCI·EPS 필드가 **유효한 값**으로 존재하는지.

    이전: key 만 있으면 True → None 값도 통과 → 재추출 안 함.
    수정: equity_parent 또는 equity_total 둘 중 하나라도 정수면 True.
          (NCI 는 단독법인 0 정상이므로 단일 판정에서 제외)
    """
    fin = data.get("financials", {}) if data else {}
    if not all(k in fin for k in
               ["equity_total", "equity_parent", "minority_interest"]):
        return False
    return (fin.get("equity_parent") is not None
            or fin.get("equity_total") is not None)


def enrich_existing_cache(corp_name: str, year: int,
                          verbose: bool = False) -> bool:
    """이미 캐시된 JSON 에 자본·NCI·EPS 없으면 추가 — 통일 경로에 재저장.

    팀원 옛 데이터 일괄 보강용 헬퍼.
    Returns: True 면 보강 완료 또는 이미 보강됨, False 면 캐시 미발견.
    """
    data = load_cached(corp_name, year)
    if data is None:
        return False
    if has_balance_sheet_fields(data):
        return True   # 이미 v3

    # 보강
    data = _enrich_with_balance_sheet(data, year)
    out_path = UNIFIED_XBRL_DIR / f"{corp_name}_{year}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    if verbose:
        print(f"  ✓ 보강: {out_path.name}")
    return True


if __name__ == "__main__":
    # 단일 회사 테스트
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("name", help="회사명 또는 종목코드")
    parser.add_argument("year", type=int)
    args = parser.parse_args()
    r = extract_company_v3(args.name, args.year, verbose=True)
    print(json.dumps(r.get("financials", {}), ensure_ascii=False, indent=2, default=str))
