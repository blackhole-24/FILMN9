"""
DART OpenAPI 클라이언트.

기능:
- _load_env()          : .env 자동 로드 (python-dotenv 의존성 X)
- get_corp_map()       : corpCode.xml 다운로드 + 종목코드↔corp_code 매핑
- fetch_reports()      : list.json 호출 → 회사별 보고서 rcept_no 조회
- download_document()  : document.xml ZIP → 본문 XML 추출

config.py 의 TARGET_FISCAL_YEAR / REPORT_TYPES 를 자동 인식.
"""
from __future__ import annotations
import io, json, os, ssl, time, zipfile
import urllib.parse, urllib.request
from datetime import datetime
from pathlib import Path
from typing import Optional

import config as cfg


# ─────────────────────────────────────────────────────────────────────────────
# .env 자동 로드 (python-dotenv 없이)
# ─────────────────────────────────────────────────────────────────────────────
def _load_env():
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip(); v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v
_load_env()

DART_API_KEY = os.environ.get("DART_API_KEY", "").strip()


# ─────────────────────────────────────────────────────────────────────────────
# HTTP 헬퍼
# ─────────────────────────────────────────────────────────────────────────────
_ctx = ssl.create_default_context()
_HEADERS = {"User-Agent": "DART-Collector/1.0"}


def _http_get(url, params=None, binary=False, retries=None, timeout=None):
    timeout = timeout or cfg.HTTP_TIMEOUT
    retries = retries or cfg.HTTP_RETRIES
    qs = urllib.parse.urlencode(params or {})
    full = f"{url}?{qs}" if params else url
    last = None
    for k in range(retries):
        try:
            req = urllib.request.Request(full, headers=_HEADERS)
            with urllib.request.urlopen(req, context=_ctx, timeout=timeout) as r:
                return r.read() if binary else r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            if e.code in (429, 503):
                time.sleep(2 ** k); last = e; continue
            raise
        except (urllib.error.URLError, TimeoutError) as e:
            last = e; time.sleep(1 + k)
    raise last


# DART status code 메시지
STATUS_MSG = {
    "000": "정상",
    "010": "등록되지 않은 키", "011": "사용할 수 없는 키",
    "012": "접근할 수 없는 IP", "013": "조회된 데이터 없음",
    "014": "파일이 존재하지 않음", "020": "요청 제한 초과",
    "021": "조회 가능 회사 개수 초과", "100": "필드의 부적절한 값",
    "800": "시스템 점검", "900": "정의되지 않은 오류",
}


# ─────────────────────────────────────────────────────────────────────────────
# 1. corpCode.xml — 종목코드 ↔ corp_code 매핑
# ─────────────────────────────────────────────────────────────────────────────
def get_corp_map(cache_path: Optional[Path] = None) -> dict:
    """
    Returns: {stock_code (6자리): {'corp_code': '8자리', 'corp_name': '...'}, ...}

    - 캐시가 있으면 즉시 로드 (corpCode.xml 약 3MB ZIP, 1회만 받으면 됨)
    - 없으면 DART corpCode.xml 다운로드
    """
    if cache_path is None:
        cfg.RAW_DIR.mkdir(parents=True, exist_ok=True)
        cache_path = cfg.RAW_DIR / "_corp_map.json"

    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))

    if not DART_API_KEY:
        raise RuntimeError("DART_API_KEY 미설정 (.env 또는 환경변수 등록 필요)")

    print("corpCode.xml 다운로드 중 (1회만)...")
    blob = _http_get(cfg.DART_CORP_URL, {"crtfc_key": DART_API_KEY}, binary=True)
    if blob[:2] != b"PK":
        raise RuntimeError(f"corpCode 다운로드 실패: {blob[:200]}")

    import lxml.etree as ET
    zf = zipfile.ZipFile(io.BytesIO(blob))
    inner = next(n for n in zf.namelist() if n.lower().endswith(".xml"))
    tree = ET.fromstring(zf.read(inner))

    stock_to_corp = {}
    for el in tree.findall(".//list"):
        sc = (el.findtext("stock_code") or "").strip()
        cc = (el.findtext("corp_code") or "").strip()
        nm = (el.findtext("corp_name") or "").strip()
        if sc and sc != " " and cc:
            stock_to_corp[sc] = {"corp_code": cc, "corp_name": nm}

    cache_path.write_text(json.dumps(stock_to_corp, ensure_ascii=False), encoding="utf-8")
    print(f"  → {len(stock_to_corp):,}개 매핑, 캐시: {cache_path}")
    return stock_to_corp


# ─────────────────────────────────────────────────────────────────────────────
# 2. 보고서 조회 (list.json) — 회사별 rcept_no 추출
# ─────────────────────────────────────────────────────────────────────────────
def fetch_reports(corp_code: str, report_types: Optional[list] = None) -> dict:
    """
    한 회사의 정기공시 (사업보고서·반기·분기) rcept_no 매핑.

    Args:
        corp_code: DART 8자리 corp_code
        report_types: cfg.REPORT_TYPES 의 부분집합. 기본=cfg.REPORT_TYPES

    Returns:
        {
          'annual': {'rcept_no': ..., 'rcept_dt': ..., 'report_nm': ...} | None,
          'Q1':     {...} | None,
          ...
          '_status': '000' | '013' | ...,
          '_error':  None | '...',
        }
    """
    if report_types is None:
        report_types = cfg.REPORT_TYPES

    bgn_de, end_de = cfg.get_search_window()
    raw = _http_get(cfg.DART_LIST_URL, {
        "crtfc_key":  DART_API_KEY,
        "corp_code":  corp_code,
        "bgn_de":     bgn_de,
        "end_de":     end_de,
        "pblntf_ty":  cfg.PUBLNTF_TY,
        "page_count": cfg.LIST_PAGE_COUNT,
    })
    data = json.loads(raw)
    status = data.get("status", "")
    out = {"_status": status, "_error": None}

    if status != "000":
        msg = STATUS_MSG.get(status, data.get("message", "?"))
        out["_error"] = f"{status}: {msg}"
        for rt in report_types:
            out[rt] = None
        return out

    items = data.get("list", []) or []

    for rt in report_types:
        pat = cfg.REPORT_PATTERNS[rt]
        expected = cfg.expected_report_label(rt)         # 예: "2024.12"
        keyword  = pat["keyword"]                         # 예: "사업보고서"

        # 정정 제외, keyword 포함, expected 라벨 우선
        cands = [it for it in items
                 if keyword in it.get("report_nm", "")
                 and "정정" not in it.get("report_nm", "")]
        chosen = next((it for it in cands if expected in it.get("report_nm", "")),
                      cands[0] if cands else None)
        out[rt] = chosen   # dict 또는 None

    return out


# ─────────────────────────────────────────────────────────────────────────────
# 3. document.xml — 본문 XML 다운로드
# ─────────────────────────────────────────────────────────────────────────────
def download_document(rcept_no: str) -> tuple:
    """
    Returns: (xml_text or None, error_msg or None)
    """
    blob = _http_get(cfg.DART_DOC_URL, {"crtfc_key": DART_API_KEY, "rcept_no": rcept_no},
                     binary=True)
    if blob[:2] != b"PK":
        try:
            err = json.loads(blob.decode("utf-8"))
            return None, f"{err.get('status')}: {err.get('message')}"
        except Exception:
            return None, f"unknown payload (size={len(blob)})"
    zf = zipfile.ZipFile(io.BytesIO(blob))
    xml_names = [n for n in zf.namelist() if n.lower().endswith(".xml")]
    if not xml_names:
        return None, "ZIP 내부에 .xml 없음"
    # 가장 큰 XML이 본문
    xml_names.sort(key=lambda n: zf.getinfo(n).file_size, reverse=True)
    xml_text = zf.read(xml_names[0]).decode("utf-8", errors="replace")
    return xml_text, None


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"DART_API_KEY: {'OK (len=%d)' % len(DART_API_KEY) if DART_API_KEY else 'MISSING'}")
    if DART_API_KEY:
        print("\n샘플: 삼성전자 (corp_code=00126380) 보고서 조회")
        result = fetch_reports("00126380")
        for rt, item in result.items():
            if rt.startswith("_"): continue
            if item:
                print(f"  {rt:<8} {item.get('report_nm')}  rcept_no={item.get('rcept_no')}")
            else:
                print(f"  {rt:<8} (조회 결과 없음)")
