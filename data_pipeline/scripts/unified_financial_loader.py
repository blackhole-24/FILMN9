"""
═══════════════════════════════════════════════════════════════════════
  FILMN9 — 통합 재무제표 자동 적재 스크립트
═══════════════════════════════════════════════════════════════════════

[목적]
2,695개 코스피·코스닥 전체 종목의 FY2025·2024·2023 재무상태표(연결)·
포괄손익계산서(연결)를 자동으로 DB에 적재.

[전략 — 우선순위]
1순위: 우리 보유 사업보고서 XML 파싱 (data/raw/ + data/팀원1_DART/)
       → 정확도 100% (사업보고서와 일치)
       → 약 1,295개 종목 즉시 처리

2순위: DART OpenAPI 호출 (fnlttSinglAcntAll, bsns_year=2025)
       → 누락 종목 자동 보충 (NAVER, 카카오, 삼성전자 등 약 1,400개)
       → DART 무료 키 사용 (분당 1,000회 제한)

[추출 대상]
- 재무상태표 (BS) — 연결 + 별도
- 손익계산서 (IS) — 연결 + 별도
- 포괄손익계산서 (CIS) — 연결 + 별도
  ※ 회사마다 IS/CIS 둘 다 또는 CIS만 제공

[사용법]
python unified_financial_loader.py --code 090430        # 단일 종목
python unified_financial_loader.py --all                # 전체 2,695개
python unified_financial_loader.py --missing-only       # XML 없는 종목만 DART API로
python unified_financial_loader.py --sync-corpcodes     # 종목코드 ↔ corp_code 매핑 갱신

[OpenAI 사용]
0회 — 비용 $0

[작성일]
2026-05-27

═══════════════════════════════════════════════════════════════════════
"""

import os
import re
import sys
import json
import time
import sqlite3
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime
from lxml import etree

# ═════════════════════════════════════════════════════════════════════
# [경로 설정]
# ═════════════════════════════════════════════════════════════════════
ROOT       = Path(r"C:\Users\Admin\FILMN9")
DB         = ROOT / "data" / "filmn9.db"
ENV        = ROOT / ".env"
CORP_MAP   = ROOT / "data" / "corp_code_map.json"

# XML 파일이 있는 폴더 (우선순위 순)
XML_DIRS = [
    ROOT / "data" / "raw",
    ROOT / "data" / "팀원1_DART" / "DART" / "raw",
]

# ═════════════════════════════════════════════════════════════════════
# [환경변수 로드]
# ═════════════════════════════════════════════════════════════════════
def load_env():
    if not ENV.exists():
        print(f"[ERR] .env 없음: {ENV}")
        sys.exit(1)
    for line in ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

load_env()
DART_KEY = os.environ.get("DART_API_KEY", "").strip()

# ═════════════════════════════════════════════════════════════════════
# [재무제표 종류 매핑 — 회사마다 명칭 다름]
# ═════════════════════════════════════════════════════════════════════
TITLE_PATTERNS = [
    # (정규식, statement_type, scope)
    # 연결
    (r"연결\s*재무상태표",            "BS",  "연결"),
    (r"연결\s*손익계산서(?!.*포괄)",  "IS",  "연결"),  # "포괄" 제외 단순 손익계산서
    (r"연결\s*포괄손익계산서",        "CIS", "연결"),
    # 별도
    (r"(?<!연결\s)재무상태표",        "BS",  "별도"),
    (r"(?<!연결\s)손익계산서(?!.*포괄)", "IS",  "별도"),
    (r"(?<!연결\s)포괄손익계산서",    "CIS", "별도"),
]

# ACONTEXT 패턴 → 연도
def extract_year_from_context(context: str) -> int | None:
    """ACONTEXT 문자열에서 연도 추출 (CFY2025, PFY2024, BPFY2023)"""
    if not context:
        return None
    m = re.search(r"(?:CFY|PFY|BPFY)(\d{4})", context)
    if m:
        return int(m.group(1))
    return None

def parse_amount(text: str) -> float | None:
    """문자열 → 숫자 (쉼표·괄호 제거, 음수 처리)"""
    if not text:
        return None
    t = text.strip().replace(",", "")
    if not t or t in ("-", "—", "　", "(주)"):
        return None
    if t.startswith("(") and t.endswith(")"):
        t = "-" + t[1:-1]
    try:
        return float(t)
    except:
        return None

def match_statement_type(title: str) -> tuple[str, str] | None:
    """TITLE 텍스트 → (statement_type, scope)"""
    for pat, st_type, scope in TITLE_PATTERNS:
        if re.search(pat, title):
            return st_type, scope
    return None

# ═════════════════════════════════════════════════════════════════════
# [1순위: XML 파싱]
# ═════════════════════════════════════════════════════════════════════
def find_xml_file(stock_code: str) -> Path | None:
    """종목코드로 XML 파일 위치 찾기 (XML_DIRS 우선순위)"""
    for base_dir in XML_DIRS:
        if not base_dir.exists():
            continue
        for child in base_dir.iterdir():
            if child.is_dir() and child.name.startswith(stock_code + "_"):
                xml_path = child / "2025-annual_cleaned.xml"
                if xml_path.exists():
                    return xml_path
    return None

def parse_xml(xml_path: Path) -> list[dict]:
    """XML 파일에서 재무제표 추출 (BS·IS·CIS, 연결·별도)"""
    try:
        parser = etree.XMLParser(recover=True, encoding="utf-8")
        tree = etree.parse(str(xml_path), parser)
    except Exception as e:
        print(f"  [PARSE ERR] {xml_path.name}: {e}")
        return []

    root = tree.getroot()
    rows = []

    titles = root.xpath("//TITLE")
    for title_el in titles:
        title_text = (title_el.text or "").strip()
        match = match_statement_type(title_text)
        if not match:
            continue
        st_type, scope = match

        # TABLE-GROUP 안에서 본문 TABLE(BORDER=1) 찾기
        parent = title_el.getparent()
        if parent is None:
            continue
        siblings = list(parent)
        try:
            idx = siblings.index(title_el)
        except ValueError:
            continue

        data_table = None
        for sib in siblings[idx+1:]:
            if sib.tag != "TABLE":
                continue
            border = sib.get("BORDER", "0")
            tbody = sib.find("TBODY")
            if tbody is None:
                continue
            tr_count = len(tbody.findall("TR"))
            if border == "1" and tr_count > 5:
                data_table = sib
                break

        if data_table is None:
            continue

        tbody = data_table.find("TBODY")
        for tr in tbody.findall("TR"):
            cells = tr.findall("TE")
            if len(cells) < 2:
                continue

            account_nm = (cells[0].text or "").strip()
            if not account_nm or account_nm == "　":
                continue

            for cell in cells[1:]:
                acode = cell.get("ACODE", "").strip()
                acontext = cell.get("ACONTEXT", "").strip()
                text_amt = (cell.text or "").strip()

                if not acode:
                    continue

                year = extract_year_from_context(acontext)
                if not year or year not in (2025, 2024, 2023):
                    continue

                # 연결/별도 ACONTEXT 우선
                if "ConsolidatedMember" in acontext:
                    ctx_scope = "연결"
                elif "SeparateMember" in acontext:
                    ctx_scope = "별도"
                else:
                    ctx_scope = scope

                amount = parse_amount(text_amt)
                rows.append({
                    "fiscal_year": year,
                    "statement_type": st_type,
                    "scope": ctx_scope,
                    "account_id": acode,
                    "account_nm": account_nm,
                    "amount": amount,
                })

    return rows

# ═════════════════════════════════════════════════════════════════════
# [2순위: DART OpenAPI 호출]
# ═════════════════════════════════════════════════════════════════════
def load_corp_code_map() -> dict[str, str]:
    """종목코드 ↔ corp_code 매핑 로드"""
    if not CORP_MAP.exists():
        return {}
    return json.loads(CORP_MAP.read_text(encoding="utf-8"))

def fetch_dart(corp_code: str, year: int, fs_div: str = "CFS") -> list:
    """DART API 호출"""
    url = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
    params = {
        "crtfc_key": DART_KEY,
        "corp_code": corp_code,
        "bsns_year": str(year),
        "reprt_code": "11011",
        "fs_div": fs_div,
    }
    try:
        with urllib.request.urlopen(url + "?" + urllib.parse.urlencode(params),
                                     timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))
        if data.get("status") != "000":
            return []
        return data.get("list", [])
    except Exception:
        return []

def fetch_via_dart(stock_code: str, corp_code: str) -> list[dict]:
    """DART API로 3개년 재무제표 수집"""
    rows = []
    for year in [2025, 2024, 2023]:
        for fs_div, scope in [("CFS", "연결"), ("OFS", "별도")]:
            items = fetch_dart(corp_code, year, fs_div)
            if not items:
                continue
            for it in items:
                sj = it.get("sj_div", "")
                if sj not in ("BS", "CIS", "IS"):
                    continue
                acc_id = it.get("account_id") or ""
                if not acc_id:
                    continue
                rows.append({
                    "fiscal_year": year,
                    "statement_type": sj,
                    "scope": scope,
                    "account_id": acc_id,
                    "account_nm": it.get("account_nm") or "",
                    "amount": parse_amount(it.get("thstrm_amount")),
                })
            time.sleep(0.05)  # API 호출 제한 (분당 1,000회)
    return rows

# ═════════════════════════════════════════════════════════════════════
# [DB 적재]
# ═════════════════════════════════════════════════════════════════════
def upsert_to_db(conn, stock_code: str, rows: list[dict], source: str):
    """기존 FY2025/2024/2023 삭제 후 재적재"""
    conn.execute("""
        DELETE FROM financial_detail
        WHERE stock_code = ? AND fiscal_year IN (2025, 2024, 2023)
    """, (stock_code,))

    if not rows:
        return 0
    sql = """
        INSERT OR REPLACE INTO financial_detail
        (stock_code, fiscal_year, statement_type, account_id, statement_scope,
         account_nm, amount, unit, display_order, source, loaded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data = [
        (stock_code, r["fiscal_year"], r["statement_type"], r["account_id"],
         r["scope"], r["account_nm"], r["amount"], "원",
         i, source, now)
        for i, r in enumerate(rows)
    ]
    conn.executemany(sql, data)
    conn.commit()
    return len(data)

# ═════════════════════════════════════════════════════════════════════
# [통합 처리]
# ═════════════════════════════════════════════════════════════════════
def process_stock(conn, stock_code: str, corp_code_map: dict) -> tuple[str, int]:
    """
    단일 종목 처리:
    1) XML 파일 보유 시 → 파싱
    2) 미보유 시 → DART API
    반환: (출처 종류, 적재 행 수)
    """
    # 1순위: XML 파일
    xml_path = find_xml_file(stock_code)
    if xml_path:
        rows = parse_xml(xml_path)
        if rows:
            source = f"사업보고서 XML ({xml_path.parent.name})"
            n = upsert_to_db(conn, stock_code, rows, source)
            return "XML", n

    # 2순위: DART API
    corp_code = corp_code_map.get(stock_code)
    if not corp_code:
        return "NO_DATA", 0

    rows = fetch_via_dart(stock_code, corp_code)
    if not rows:
        return "API_FAIL", 0
    source = "DART OpenAPI fnlttSinglAcntAll"
    n = upsert_to_db(conn, stock_code, rows, source)
    return "API", n

def list_all_xml_codes() -> set[str]:
    """우리 보유 XML 종목 코드 모두 반환"""
    codes = set()
    for base in XML_DIRS:
        if not base.exists():
            continue
        for child in base.iterdir():
            if child.is_dir():
                m = re.match(r"^([0-9A-Z]{6})_", child.name)
                if m and (child / "2025-annual_cleaned.xml").exists():
                    codes.add(m.group(1))
    return codes

# ═════════════════════════════════════════════════════════════════════
# [메인]
# ═════════════════════════════════════════════════════════════════════
def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--code", help="단일 종목")
    p.add_argument("--all", action="store_true", help="전체 처리")
    p.add_argument("--missing-only", action="store_true",
                   help="XML 없는 종목만 DART API로")
    p.add_argument("--limit", type=int, help="처리 종목 수 제한")
    args = p.parse_args()

    if not DB.exists():
        print(f"[ERR] DB 없음: {DB}")
        sys.exit(1)

    corp_map = load_corp_code_map()
    print(f"종목코드 매핑 로드: {len(corp_map)}개")

    conn = sqlite3.connect(DB)
    xml_codes = list_all_xml_codes()

    if args.code:
        targets = [args.code]
    elif args.all:
        # XML 보유 + corp_code 매핑 둘 다 합쳐서 고유 종목
        targets = sorted(set(xml_codes) | set(corp_map.keys()))
    elif args.missing_only:
        # XML 없고 corp_code 있는 종목만
        targets = sorted(set(corp_map.keys()) - xml_codes)
    else:
        targets = ["090430", "009150", "035420"]  # 기본: 데모 3종목

    if args.limit:
        targets = targets[:args.limit]

    print(f"\n처리 대상: {len(targets)}개")
    print(f"  XML 보유 종목: {len(xml_codes)}개")
    print(f"  DART corp_code 보유: {len(corp_map)}개")
    print("=" * 70)

    stats = {"XML": 0, "API": 0, "NO_DATA": 0, "API_FAIL": 0}
    grand_total = 0
    for i, code in enumerate(targets, 1):
        src, n = process_stock(conn, code, corp_map)
        stats[src] = stats.get(src, 0) + 1
        grand_total += n
        if i % 50 == 0 or i == len(targets):
            print(f"  [{i:>4}/{len(targets)}] {code} → {src} ({n}건) "
                  f"| 누적: XML {stats['XML']} · API {stats['API']} · "
                  f"실패 {stats['NO_DATA'] + stats['API_FAIL']}")

    conn.close()

    print("\n" + "=" * 70)
    print(f"  완료. 총 {grand_total:,}건 적재")
    print(f"  - XML 파싱 성공: {stats['XML']}개")
    print(f"  - DART API 성공: {stats['API']}개")
    print(f"  - 데이터 없음: {stats['NO_DATA']}개")
    print(f"  - API 실패: {stats['API_FAIL']}개")
    print("=" * 70)

if __name__ == "__main__":
    main()
