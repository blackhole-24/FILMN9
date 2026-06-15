"""
═══════════════════════════════════════════════════════════════════════
  FILMN9 — 누락 종목 XML 자동 다운로드 (무인 진행)
═══════════════════════════════════════════════════════════════════════

[목적]
data/raw/ + data/팀원1_DART/DART/raw/ 에 XML 없는 종목들의
2025년 사업보고서 XML을 DART API로 자동 다운로드.

[흐름]
1. corp_code_map.json 로드 (전체 종목 매핑)
2. 현재 보유 XML 종목 코드 수집
3. 누락 종목 식별
4. 각 누락 종목에 대해:
   a) DART API list.json → 2025 사업보고서 rcept_no 조회
   b) DART API document.xml → XML zip 다운로드
   c) zip 압축 해제 → data/raw/{code}_{name}/2025-annual_cleaned.xml 저장
5. 진행률 + 에러 로그 자동 기록

[OpenAI 사용]
0회 — $0

[DART API 호출 제한]
분당 1,000회 — 0.1초 간격 호출로 안전 운영

[로그]
download_log.txt: 진행 상황·에러 자동 기록
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

# ═══════════════════════════════════════════════════════════════════
# 경로
# ═══════════════════════════════════════════════════════════════════
ROOT     = Path(r"C:\Users\Admin\FILMN9")
DATA_DIR = ROOT / "data"
RAW_DIR  = DATA_DIR / "raw"
TEAM_DIR = DATA_DIR / "팀원1_DART" / "DART" / "raw"
CORP_MAP = DATA_DIR / "corp_code_map.json"
ENV      = ROOT / ".env"
LOG      = ROOT / "download_log.txt"

# ═══════════════════════════════════════════════════════════════════
# .env 로드
# ═══════════════════════════════════════════════════════════════════
def load_env():
    if not ENV.exists():
        return
    for line in ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

load_env()
DART_KEY = os.environ.get("DART_API_KEY", "").strip()
if not DART_KEY:
    print("[ERR] DART_API_KEY 미설정")
    sys.exit(1)

# ═══════════════════════════════════════════════════════════════════
# 로그
# ═══════════════════════════════════════════════════════════════════
def log(msg):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")

# ═══════════════════════════════════════════════════════════════════
# 보유 종목 식별
# ═══════════════════════════════════════════════════════════════════
def list_existing_xml_codes() -> set[str]:
    codes = set()
    for base in [RAW_DIR, TEAM_DIR]:
        if not base.exists():
            continue
        for child in base.iterdir():
            if child.is_dir():
                m = re.match(r"^([0-9A-Z]{6})_", child.name)
                if m and (child / "2025-annual_cleaned.xml").exists():
                    codes.add(m.group(1))
    return codes

# ═══════════════════════════════════════════════════════════════════
# DART API: 2025 사업보고서 rcept_no 조회
# ═══════════════════════════════════════════════════════════════════
def get_2025_annual_rcept_no(corp_code: str) -> str | None:
    """
    DART list.json — 회사별 공시검색
    2025 사업보고서 (pblntf_detail_ty=A001, bsns_year=2025) 검색
    """
    url = "https://opendart.fss.or.kr/api/list.json"
    params = {
        "crtfc_key": DART_KEY,
        "corp_code": corp_code,
        "bgn_de": "20260101",   # 2026년 초 (2025 사업보고서 제출일)
        "end_de": "20260630",   # 2026년 6월말 (제출 마감 후)
        "pblntf_detail_ty": "A001",  # 사업보고서
        "page_count": "10",
    }
    try:
        full_url = url + "?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(full_url, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))
        if data.get("status") != "000":
            return None
        for item in data.get("list", []):
            report_nm = item.get("report_nm", "")
            if "사업보고서" in report_nm and "2025" in report_nm:
                return item.get("rcept_no")
        # 그래도 못 찾으면 첫 항목
        if data.get("list"):
            return data["list"][0].get("rcept_no")
    except Exception as e:
        log(f"  [list.json ERR] {corp_code}: {e}")
    return None

# ═══════════════════════════════════════════════════════════════════
# DART API: 사업보고서 XML 다운로드 (document.xml)
# ═══════════════════════════════════════════════════════════════════
def download_document_xml(rcept_no: str) -> bytes | None:
    """DART document.xml — 사업보고서 본문 XML (ZIP)"""
    url = f"https://opendart.fss.or.kr/api/document.xml?crtfc_key={DART_KEY}&rcept_no={rcept_no}"
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            return r.read()
    except Exception as e:
        log(f"  [document.xml ERR] {rcept_no}: {e}")
        return None

def extract_xml_from_zip(zip_bytes: bytes) -> bytes | None:
    """ZIP에서 .xml 파일 추출"""
    try:
        with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
            for name in zf.namelist():
                if name.lower().endswith(".xml"):
                    return zf.read(name)
    except Exception as e:
        log(f"  [unzip ERR] {e}")
    return None

# ═══════════════════════════════════════════════════════════════════
# 종목 코드 매핑 로드
# ═══════════════════════════════════════════════════════════════════
def load_corp_codes() -> dict[str, dict]:
    """
    corp_code_map.json 구조:
    {
      "by_stock_code": {"000020": {"stock_code", "corp_code", "corp_name", ...}, ...}
    }
    """
    with open(CORP_MAP, encoding="utf-8") as f:
        raw = json.load(f)
    by_stock = raw.get("by_stock_code", {})
    # 6자리 영숫자 패턴만
    return {
        k: v for k, v in by_stock.items()
        if re.match(r"^[0-9A-Z]{6}$", k)
    }

# ═══════════════════════════════════════════════════════════════════
# 메인 처리
# ═══════════════════════════════════════════════════════════════════
def process_stock(stock_code: str, info: dict) -> tuple[str, str | None]:
    """
    단일 종목 처리.
    반환: (상태, 에러 메시지)
    """
    corp_code = info.get("corp_code")
    corp_name = info.get("corp_name", "Unknown")
    if not corp_code:
        return "NO_CORP_CODE", None

    # 1) rcept_no 조회
    rcept_no = get_2025_annual_rcept_no(corp_code)
    time.sleep(0.1)  # API 호출 제한
    if not rcept_no:
        return "NO_RCEPT", None

    # 2) document.xml 다운로드
    zip_bytes = download_document_xml(rcept_no)
    time.sleep(0.1)
    if not zip_bytes:
        return "DOWNLOAD_FAIL", None

    # 3) ZIP 풀어서 XML 추출
    xml_bytes = extract_xml_from_zip(zip_bytes)
    if not xml_bytes:
        return "EXTRACT_FAIL", None

    # 4) 폴더 생성 + 저장
    folder_name = f"{stock_code}_{corp_name}"
    # 특수문자 제거
    folder_name = re.sub(r'[<>:"/\\|?*]', '', folder_name)
    target_dir = RAW_DIR / folder_name
    target_dir.mkdir(parents=True, exist_ok=True)

    xml_path = target_dir / "2025-annual_cleaned.xml"
    xml_path.write_bytes(xml_bytes)
    return "OK", str(xml_path.relative_to(ROOT))

def main():
    log("=" * 70)
    log("  DART API 누락 XML 자동 다운로드 시작")
    log("=" * 70)

    # 로드
    corp_map = load_corp_codes()
    log(f"전체 종목 매핑: {len(corp_map):,}개")

    existing = list_existing_xml_codes()
    log(f"기존 XML 보유: {len(existing):,}개")

    missing = sorted(set(corp_map.keys()) - existing)
    log(f"누락 종목: {len(missing):,}개")
    log("=" * 70)

    if not missing:
        log("✅ 누락 종목 없음. 종료.")
        return

    # 처리
    stats = {"OK": 0, "NO_RCEPT": 0, "DOWNLOAD_FAIL": 0,
             "EXTRACT_FAIL": 0, "NO_CORP_CODE": 0, "ERR": 0}
    start_time = time.time()

    for i, stock_code in enumerate(missing, 1):
        info = corp_map.get(stock_code, {})
        try:
            status, detail = process_stock(stock_code, info)
        except Exception as e:
            status, detail = "ERR", str(e)

        stats[status] = stats.get(status, 0) + 1

        # 진행률 로그 (10개마다)
        if i % 10 == 0 or i == len(missing) or status == "OK":
            elapsed = time.time() - start_time
            rate = i / elapsed if elapsed > 0 else 0
            eta_sec = (len(missing) - i) / rate if rate > 0 else 0
            eta_min = int(eta_sec / 60)
            corp_name = info.get("corp_name", "?")[:12]
            log(f"  [{i:>4}/{len(missing)}] {stock_code} {corp_name:<13} → {status} "
                f"(OK {stats['OK']} | 진행률 {i/len(missing)*100:.1f}% | ETA {eta_min}분)")

    # 최종 요약
    log("=" * 70)
    log("  완료")
    log("=" * 70)
    elapsed_min = (time.time() - start_time) / 60
    log(f"  총 소요: {elapsed_min:.1f}분")
    log(f"  성공: {stats['OK']:,}개")
    log(f"  rcept_no 없음: {stats['NO_RCEPT']:,}개")
    log(f"  다운로드 실패: {stats['DOWNLOAD_FAIL']:,}개")
    log(f"  XML 추출 실패: {stats['EXTRACT_FAIL']:,}개")
    log(f"  corp_code 없음: {stats['NO_CORP_CODE']:,}개")
    log(f"  기타 에러: {stats['ERR']:,}개")
    log("=" * 70)

if __name__ == "__main__":
    main()
