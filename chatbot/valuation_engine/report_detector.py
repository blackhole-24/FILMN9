"""정기공시(분기·반기·사업보고서) 신규 감지 — Lazy 자동 업데이트의 토대.

설계 (사용자 결정: 1a TTM 하이브리드 / 2a Lazy on-demand / 3 신규 전체 임베딩):
  · DART list.json(pblntf_ty=A) 으로 종목의 정기공시 목록을 받아
  · report_nm "(사업|반기|분기)보고서 (YYYY.MM)" 을 파싱해 reprt_code·회계기간으로 분류
  · data/report_registry.json 에 종목별 '처리 완료' 보고서를 기록(멱등성)
  · registry 와 비교해 '신규/정정' 보고서만 증분 수집 대상으로 반환

report_nm → reprt_code 매핑 (DART fnlttXbrl 파라미터):
  (YYYY.03) 1분기 = 11013   (YYYY.06) 반기 = 11012
  (YYYY.09) 3분기 = 11014   (YYYY.12) 사업(연간) = 11011

정정 처리:
  같은 회계기간(period)에 [기재정정]/[첨부정정] 재공시되면 rcept_dt 최신본을 대표로 채택.
  (XBRL 수집 시 첨부정정 회피는 xbrl_financials_v4.get_rcept_no 가 별도 처리)
"""
from __future__ import annotations

import json
import os
import re
from datetime import date
from pathlib import Path
from typing import Optional

import requests

_VAR_ROOT = Path(__file__).resolve().parent.parent
_REGISTRY = _VAR_ROOT / "data" / "report_registry.json"
_DART_LIST = "https://opendart.fss.or.kr/api/list.json"

# 결산월(MM) → (보고서종류 라벨, reprt_code)
_MONTH_MAP = {
    "03": ("분기(1Q)", "11013"),
    "06": ("반기",     "11012"),
    "09": ("분기(3Q)", "11014"),
    "12": ("사업(연간)", "11011"),
}
_RE_REPORT = re.compile(
    r"(?:\[(기재정정|첨부정정)\])?\s*(사업|반기|분기)보고서\s*\((\d{4})\.(\d{2})\)")


def _classify(report_nm: str) -> Optional[dict]:
    """report_nm → {period, year, month, kind, reprt_code, is_correction}. 비정기공시는 None."""
    m = _RE_REPORT.search(report_nm or "")
    if not m:
        return None
    corr, _kind, yr, mm = m.groups()
    info = _MONTH_MAP.get(mm)
    if not info:
        return None
    return {
        "period":          f"{yr}.{mm}",      # 회계기간 키 (예: 2026.03)
        "year":            int(yr),
        "month":           mm,
        "kind":            info[0],
        "reprt_code":      info[1],
        "is_correction":   bool(corr),
        "correction_type": corr,
    }


def _dart_key() -> str:
    k = os.getenv("DART_API_KEY")
    if not k:
        raise RuntimeError("환경변수 'DART_API_KEY' 미설정")
    return k


def list_periodic_reports(corp_code: str,
                          bgn_de: Optional[str] = None,
                          end_de: Optional[str] = None) -> list[dict]:
    """DART 정기공시 목록 → 회계기간별 대표 보고서(정정 최신본) 리스트 (최신순)."""
    bgn_de = bgn_de or f"{date.today().year - 2}0101"
    end_de = end_de or f"{date.today().year}1231"
    r = requests.get(_DART_LIST, params={
        "crtfc_key": _dart_key(), "corp_code": corp_code, "pblntf_ty": "A",
        "bgn_de": bgn_de, "end_de": end_de, "page_count": "100"}, timeout=30)
    r.raise_for_status()
    data = r.json()
    if data.get("status") not in ("000", "013"):
        raise RuntimeError(f"DART list 오류: {data.get('status')} {data.get('message')}")

    by_period: dict[str, dict] = {}
    for it in data.get("list", []):
        c = _classify(it.get("report_nm", ""))
        if not c:
            continue
        rec = {**c, "rcept_no": it["rcept_no"], "rcept_dt": it["rcept_dt"],
               "report_nm": (it.get("report_nm") or "").strip()}
        p = c["period"]
        # 같은 회계기간 → rcept_dt 최신본(정정 반영)을 대표로
        if p not in by_period or it["rcept_dt"] > by_period[p]["rcept_dt"]:
            by_period[p] = rec
    return sorted(by_period.values(), key=lambda z: z["period"], reverse=True)


def load_registry() -> dict:
    if _REGISTRY.exists():
        try:
            return json.loads(_REGISTRY.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_registry(reg: dict) -> None:
    _REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    _REGISTRY.write_text(json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")


def _registry_reports(ticker: str) -> dict:
    """종목의 처리이력(reports) — DB 우선 + 파일 폴백 (이중소스 일원화).

    DB(report_registry 테이블)가 단일 진실원천. 미존재 시 파일(report_registry.json) 폴백.
    """
    try:
        from valuation_engine import db
        node = db.get_registry(ticker).get(str(ticker).zfill(6))
        if node and node.get("reports"):
            return node["reports"]
    except Exception:
        pass
    return load_registry().get(ticker, {}).get("reports", {})


def mark_processed(ticker: str, corp_code: str, rep: dict,
                   xbrl_done: bool = False, embed_done: bool = False) -> None:
    """보고서 1건 처리 완료 기록 (멱등성 — 다음 감지 시 재처리 안 함)."""
    from datetime import datetime
    reg = load_registry()
    node = reg.setdefault(ticker, {"corp_code": corp_code, "reports": {}})
    node["corp_code"] = corp_code
    prev = node["reports"].get(rep["period"], {})
    node["reports"][rep["period"]] = {
        "rcept_no":   rep["rcept_no"],
        "reprt_code": rep["reprt_code"],
        "kind":       rep["kind"],
        "rcept_dt":   rep["rcept_dt"],
        "xbrl_done":  xbrl_done or prev.get("xbrl_done", False),
        "embed_done": embed_done or prev.get("embed_done", False),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    save_registry(reg)
    # ★ DB write-through (DB 우선 일원화 + 파일은 폴백). 실패해도 파일 기록은 유지.
    try:
        from valuation_engine import db
        db.save_registry_entry(ticker, rep["period"],
                               {**node["reports"][rep["period"]], "corp_code": corp_code})
    except Exception:
        pass


def detect_new(ticker: str, corp_code: str) -> dict:
    """가용 정기공시 vs registry 비교 → 미처리/정정 보고서 목록.

    Returns:
        {
          "available": [전체 정기공시 대표 레코드],
          "new":       [registry 에 없거나 rcept_no 가 바뀐(정정) 레코드],
          "latest":    가장 최근 회계기간 레코드 (TTM 기준점),
        }
    """
    avail = list_periodic_reports(corp_code)
    reg_reports = _registry_reports(ticker)   # DB 우선 + 파일 폴백
    new = []
    for rep in avail:
        prev = reg_reports.get(rep["period"])
        if prev is None or prev.get("rcept_no") != rep["rcept_no"]:
            new.append(rep)
    return {"available": avail, "new": new, "latest": avail[0] if avail else None}


if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv
    load_dotenv(_VAR_ROOT / ".env")
    sys.path.insert(0, str(_VAR_ROOT / "XBRL"))
    cc = sys.argv[1] if len(sys.argv) > 1 else "00126371"   # 삼성전기 corp_code
    tk = sys.argv[2] if len(sys.argv) > 2 else "009150"
    res = detect_new(tk, cc)
    print(f"가용 정기공시 {len(res['available'])}건, 신규 {len(res['new'])}건")
    print(f"최신: {res['latest']['period']} {res['latest']['kind']} ({res['latest']['reprt_code']})")
    print("\n=== 신규(미처리) ===")
    for r in res["new"]:
        print(f"  {r['period']} {r['kind']:10s} reprt={r['reprt_code']} rcept={r['rcept_no']} {r['report_nm']}")
