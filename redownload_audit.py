"""
감사보고서로 잘못 받은 종목들 재다운로드
1. data/raw/{종목}/2025-annual_cleaned.xml 헤더 검사
2. ACODE="00760"(감사보고서) 인 종목 식별
3. 정확한 사업보고서 rcept_no 조회 (필터링 강화)
4. document.xml 재다운로드 (사업보고서만!)
"""
import os
import re
import sys
import json
import time
import zipfile
import urllib.request
import urllib.parse
from io import BytesIO
from pathlib import Path
from datetime import datetime

ROOT = Path(r"C:\Users\Admin\FILMN9")
ENV  = ROOT / ".env"
RAW  = ROOT / "data" / "raw"
CORP_MAP = ROOT / "data" / "corp_code_map.json"
LOG  = ROOT / "redownload_log.txt"

def load_env():
    for line in ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

load_env()
DART_KEY = os.environ.get("DART_API_KEY", "").strip()

def log(msg):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")

# 1. 감사보고서 종목 식별
def find_audit_only_stocks():
    audit_codes = []
    for child in RAW.iterdir():
        if not child.is_dir():
            continue
        m = re.match(r"^([0-9A-Z]{6})_", child.name)
        if not m:
            continue
        xml = child / "2025-annual_cleaned.xml"
        if not xml.exists():
            continue
        with open(xml, "rb") as f:
            head = f.read(2000).decode("utf-8", errors="ignore")
        if 'ACODE="00760"' in head and "감사보고서" in head:
            audit_codes.append((m.group(1), child.name))
    return audit_codes

# 2. 정확한 사업보고서 rcept_no 조회 (필터링 강화)
def get_business_report_rcept_no(corp_code: str) -> str | None:
    """report_nm 에 '사업보고서' 명시 포함된 것만 매칭"""
    url = "https://opendart.fss.or.kr/api/list.json"
    params = {
        "crtfc_key": DART_KEY,
        "corp_code": corp_code,
        "bgn_de": "20260101",
        "end_de": "20260630",
        "pblntf_detail_ty": "A001",  # 정기공시
        "page_count": "100",  # 최대한 많이
    }
    try:
        full = url + "?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(full, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))
        if data.get("status") != "000":
            return None

        # 강화된 필터링: report_nm 에 '사업보고서' 정확히 포함 + '감사' 제외
        for item in data.get("list", []):
            nm = item.get("report_nm", "")
            if "사업보고서" in nm and "감사" not in nm and "내부회계" not in nm:
                # 2025 사업보고서 또는 (2025.12) 명시
                if "2025" in nm or "(2025" in nm:
                    return item.get("rcept_no")

        # 위 조건 못 찾으면 사업보고서만이라도
        for item in data.get("list", []):
            nm = item.get("report_nm", "")
            if "사업보고서" in nm and "감사" not in nm:
                return item.get("rcept_no")
    except Exception as e:
        log(f"  [list.json ERR] {corp_code}: {e}")
    return None

def download_and_extract(rcept_no: str, target_dir: Path) -> bool:
    """document.xml ZIP 다운 + XML 추출"""
    url = f"https://opendart.fss.or.kr/api/document.xml?crtfc_key={DART_KEY}&rcept_no={rcept_no}"
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            zip_bytes = r.read()
        with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
            for name in zf.namelist():
                if name.lower().endswith(".xml"):
                    xml_bytes = zf.read(name)
                    # 검증: 사업보고서인지
                    head = xml_bytes[:2000].decode("utf-8", errors="ignore")
                    if 'ACODE="11011"' not in head:
                        return False  # 사업보고서 아님
                    target_dir.mkdir(parents=True, exist_ok=True)
                    (target_dir / "2025-annual_cleaned.xml").write_bytes(xml_bytes)
                    return True
    except Exception as e:
        log(f"  [download ERR] {rcept_no}: {e}")
    return False

def main():
    LOG.unlink(missing_ok=True)
    log("=" * 70)
    log("  감사보고서 → 사업보고서 재다운로드")
    log("=" * 70)

    audit_stocks = find_audit_only_stocks()
    log(f"감사보고서로 잘못 받은 종목: {len(audit_stocks)}개")
    log("=" * 70)

    corp_map_raw = json.loads(CORP_MAP.read_text(encoding="utf-8"))
    corp_map = corp_map_raw.get("by_stock_code", {})

    stats = {"OK": 0, "NO_RCEPT": 0, "FAIL": 0}
    start = time.time()

    for i, (code, folder_name) in enumerate(audit_stocks, 1):
        info = corp_map.get(code, {})
        corp_code = info.get("corp_code")
        if not corp_code:
            stats["NO_RCEPT"] += 1
            continue

        rcept_no = get_business_report_rcept_no(corp_code)
        time.sleep(0.1)
        if not rcept_no:
            stats["NO_RCEPT"] += 1
            if i <= 5 or i % 20 == 0:
                log(f"  [{i:>3}/{len(audit_stocks)}] {code} → 사업보고서 없음")
            continue

        target_dir = RAW / folder_name
        ok = download_and_extract(rcept_no, target_dir)
        time.sleep(0.1)
        if ok:
            stats["OK"] += 1
        else:
            stats["FAIL"] += 1

        if i % 20 == 0 or i == len(audit_stocks):
            elapsed = time.time() - start
            rate = i / elapsed if elapsed > 0 else 0
            eta = (len(audit_stocks) - i) / rate / 60 if rate > 0 else 0
            log(f"  [{i:>3}/{len(audit_stocks)}] OK {stats['OK']} | "
                f"NO_RCEPT {stats['NO_RCEPT']} | FAIL {stats['FAIL']} | "
                f"ETA {eta:.1f}분")

    log("=" * 70)
    log(f"  완료 — 소요 {(time.time()-start)/60:.1f}분")
    log(f"  OK: {stats['OK']} | NO_RCEPT: {stats['NO_RCEPT']} | FAIL: {stats['FAIL']}")
    log("=" * 70)

if __name__ == "__main__":
    main()
