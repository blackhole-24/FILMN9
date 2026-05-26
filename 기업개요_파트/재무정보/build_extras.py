"""
build_extras.py
================
Tab1 신규 데이터 수집기 (주주·경영인·공시·재무상세)

사용법
------
cd C:/Users/Admin/FILMN9
python 기업개요_파트/재무정보/build_extras.py 090430
python 기업개요_파트/재무정보/build_extras.py 090430 --year 2025

DART OpenAPI 엔드포인트
----------------------
- 주주          : hyslrSttus.json   (대량보유자 / 최대주주)
- 경영인        : exctvSttus.json
- 공시          : list.json
- 재무상세      : fnlttSinglAcntAll.json  (단일회사 전체 재무제표)

산출
----
data/parsed/{stock_code}/
  ├── shareholders.json
  ├── executives.json
  ├── disclosures.json
  └── financial_detail.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DATA = ROOT / "data"
PARSED = DATA / "parsed"


def _load_env() -> None:
    env_path = ROOT / ".env"
    if env_path.exists():
        with env_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_env()
DART_API_KEY = os.environ.get("DART_API_KEY", "").strip()
if not DART_API_KEY:
    sys.exit("[ERR] DART_API_KEY 미설정 (.env 확인)")


# ─── 헬퍼 ─────────────────────────────────────────────────────────────────────

def _load_corp_map() -> dict:
    p = DATA / "corp_code_map.json"
    return json.loads(p.read_text(encoding="utf-8"))


def _corp_code(stock_code: str) -> str:
    m = _load_corp_map()
    by_stock = m.get("by_stock_code", {})
    entry = by_stock.get(stock_code)
    if not entry:
        raise KeyError(f"corp_code 매핑 실패: {stock_code}")
    return entry["corp_code"]


def _dart_get(endpoint: str, params: dict, retries: int = 3) -> dict:
    """DART OpenAPI 호출 → JSON 반환."""
    url = f"https://opendart.fss.or.kr/api/{endpoint}"
    qs = urllib.parse.urlencode({"crtfc_key": DART_API_KEY, **params})
    full = f"{url}?{qs}"
    last_err = None
    for i in range(retries):
        try:
            req = urllib.request.Request(full, headers={"User-Agent": "FILMN9/1.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            last_err = e
            time.sleep(0.5 * (i + 1))
    raise RuntimeError(f"DART {endpoint} 호출 실패: {last_err}")


def _save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ─── 1) 주주 ─────────────────────────────────────────────────────────────────

def fetch_shareholders(corp_code: str, year: int) -> list[dict]:
    """최대주주 + 대량보유자(5% 이상) 리스트."""
    items: list[dict] = []
    rank = 1

    # 1-A) 최대주주 (hyslrSttus.json)
    try:
        # bsns_year + reprt_code 11011=사업보고서
        r = _dart_get("hyslrSttus.json", {
            "corp_code": corp_code,
            "bsns_year": str(year),
            "reprt_code": "11011",
        })
        if r.get("status") == "000":
            for it in r.get("list", []):
                items.append({
                    "rank": rank,
                    "name": (it.get("nm") or "").strip(),
                    "relation": (it.get("relate") or "").strip() or "최대주주",
                    "shares": _safe_int(it.get("trmend_posesn_stock_co")),
                    "ratio": _safe_float(it.get("trmend_posesn_stock_qota_rt")),
                })
                rank += 1
    except Exception as e:
        print(f"  [WARN] hyslrSttus 실패: {e}")

    # 1-B) 5% 이상 대량보유자 (majorShareholder.json)
    try:
        r = _dart_get("majorstock.json", {"corp_code": corp_code})
        if r.get("status") == "000":
            seen = {x["name"] for x in items}
            for it in r.get("list", [])[:5]:
                nm = (it.get("repror") or "").strip()
                if nm and nm not in seen:
                    items.append({
                        "rank": rank,
                        "name": nm,
                        "relation": "5% 이상 보유",
                        "shares": _safe_int(it.get("stkqy")),
                        "ratio": _safe_float(it.get("stkrt")),
                    })
                    rank += 1
    except Exception as e:
        print(f"  [WARN] majorstock 실패: {e}")

    return items


# ─── 2) 경영인 ───────────────────────────────────────────────────────────────

def fetch_executives(corp_code: str, year: int) -> list[dict]:
    """등기·미등기 임원."""
    items: list[dict] = []
    try:
        r = _dart_get("exctvSttus.json", {
            "corp_code": corp_code,
            "bsns_year": str(year),
            "reprt_code": "11011",
        })
        if r.get("status") == "000":
            for i, it in enumerate(r.get("list", []), 1):
                items.append({
                    "rank": i,
                    "name": (it.get("nm") or "").strip(),
                    "position": (it.get("ofcps") or "").strip(),
                    "role": (it.get("rgist_exctv_at") or "").strip()
                            + " / "
                            + (it.get("fte_at") or "").strip(),
                    "birth_year": (it.get("birth_ym") or "")[:4],
                    "career": (it.get("main_career") or "").strip()[:200],
                    "shares": None,
                    "appointed_at": (it.get("hffc_pd") or "").strip(),
                    "term_end": None,
                })
    except Exception as e:
        print(f"  [WARN] exctvSttus 실패: {e}")
    return items


# ─── 3) 공시 ─────────────────────────────────────────────────────────────────

def fetch_disclosures(corp_code: str, months: int = 6, limit: int = 30) -> list[dict]:
    """최근 N개월 공시 리스트."""
    end = datetime.now()
    start = end - timedelta(days=30 * months)
    try:
        r = _dart_get("list.json", {
            "corp_code": corp_code,
            "bgn_de": start.strftime("%Y%m%d"),
            "end_de": end.strftime("%Y%m%d"),
            "page_count": str(limit),
        })
        if r.get("status") == "000":
            out = []
            for it in r.get("list", [])[:limit]:
                rno = (it.get("rcept_no") or "").strip()
                out.append({
                    "rcept_no": rno,
                    "report_nm": (it.get("report_nm") or "").strip(),
                    "flr_nm": (it.get("flr_nm") or "").strip(),
                    "rcept_dt": _fmt_date(it.get("rcept_dt")),
                    "rm": (it.get("rm") or "").strip(),
                    "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rno}" if rno else "",
                })
            return out
    except Exception as e:
        print(f"  [WARN] list.json 실패: {e}")
    return []


# ─── 4) 재무상세 (B/S + I/S 전체) ────────────────────────────────────────────

def fetch_financial_detail(corp_code: str, year: int) -> list[dict]:
    """단일회사 전체 재무제표 (계정과목 전체)."""
    items: list[dict] = []
    try:
        r = _dart_get("fnlttSinglAcntAll.json", {
            "corp_code": corp_code,
            "bsns_year": str(year),
            "reprt_code": "11011",
            "fs_div": "CFS",  # 연결재무제표
        })
        if r.get("status") != "000":
            # 연결 실패 시 별도(OFS) 재시도
            r = _dart_get("fnlttSinglAcntAll.json", {
                "corp_code": corp_code,
                "bsns_year": str(year),
                "reprt_code": "11011",
                "fs_div": "OFS",
            })

        if r.get("status") == "000":
            order = 0
            for it in r.get("list", []):
                sj = (it.get("sj_div") or "").strip()  # BS / IS / CIS / CF / SCE
                # B/S, I/S만 (Tab1 화면에 필요)
                if sj not in ("BS", "IS", "CIS"):
                    continue
                order += 1
                items.append({
                    "fiscal_year": year,
                    "statement_type": "BS" if sj == "BS" else "IS",
                    "account_id": (it.get("account_id") or "").strip(),
                    "account_nm": (it.get("account_nm") or "").strip(),
                    "amount": _safe_float(it.get("thstrm_amount")),
                    "statement_scope": "연결" if r.get("list")[0].get("fs_div") == "CFS" else "별도",
                    "display_order": order,
                })
    except Exception as e:
        print(f"  [WARN] fnlttSinglAcntAll 실패: {e}")
    return items


# ─── 안전 변환 ────────────────────────────────────────────────────────────────

def _safe_int(v) -> int | None:
    if v is None or v == "" or v == "-":
        return None
    try:
        return int(str(v).replace(",", "").replace(" ", ""))
    except (ValueError, TypeError):
        return None


def _safe_float(v) -> float | None:
    if v is None or v == "" or v == "-":
        return None
    try:
        return float(str(v).replace(",", "").replace(" ", "").replace("%", ""))
    except (ValueError, TypeError):
        return None


def _fmt_date(s: str | None) -> str:
    """20260520 → 2026-05-20"""
    if not s or len(s) != 8:
        return s or ""
    return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"


# ─── 메인 ─────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Tab1 신규 데이터 수집 (주주·경영인·공시·재무상세)")
    p.add_argument("stock_code", help="6자리 종목코드")
    p.add_argument("--year", type=int, default=2024,
                   help="대상 회계연도 (기본 2024; 2025 사업보고서는 미발표 가능)")
    args = p.parse_args()

    code = args.stock_code.strip()
    year = args.year

    print(f"\n{'='*60}")
    print(f"  build_extras  {code}  FY{year}")
    print(f"{'='*60}")

    corp_code = _corp_code(code)
    print(f"  corp_code: {corp_code}")

    out_dir = PARSED / code
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = {"stock_code": code, "fiscal_year": year,
            "generated_at": datetime.now().isoformat()}

    # 1) 주주
    print(f"  1) 주주        ...", end="", flush=True)
    sh = fetch_shareholders(corp_code, year)
    _save_json(out_dir / "shareholders.json", {**meta, "items": sh})
    print(f" OK ({len(sh)}명)")

    # 2) 경영인
    print(f"  2) 경영인      ...", end="", flush=True)
    ex = fetch_executives(corp_code, year)
    _save_json(out_dir / "executives.json", {**meta, "items": ex})
    print(f" OK ({len(ex)}명)")

    # 3) 공시
    print(f"  3) 공시        ...", end="", flush=True)
    dc = fetch_disclosures(corp_code, months=6, limit=30)
    _save_json(out_dir / "disclosures.json", {**meta, "items": dc})
    print(f" OK ({len(dc)}건)")

    # 4) 재무상세 (3년)
    print(f"  4) 재무상세    ...", end="", flush=True)
    fd_all: list[dict] = []
    for y in (year - 2, year - 1, year):
        fd_all.extend(fetch_financial_detail(corp_code, y))
    _save_json(out_dir / "financial_detail.json", {**meta, "items": fd_all})
    print(f" OK ({len(fd_all)}행, 3년치)")

    print(f"\n[DONE] {out_dir}/")


if __name__ == "__main__":
    main()
