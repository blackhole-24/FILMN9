"""
사업보고서 XML 파일에서 재무제표 자동 추출 + DB 적재
========================================================

[입력]
data/raw/{stock_code}_{name}/2025-annual_cleaned.xml
data/팀원1_DART/DART/raw/{stock_code}_{name}/2025-annual_cleaned.xml

[추출 대상]
- 2-1. 연결 재무상태표 (BS, 연결)
- 2-2. 연결 포괄손익계산서 (CIS, 연결)
- 4-1. 재무상태표 (BS, 별도)
- 4-2. 포괄손익계산서 (CIS, 별도)

[연도 매핑]
- 제 N 기 (당기) = 2025
- 제 N-1 기 (전기) = 2024
- 제 N-2 기 (전전기) = 2023

[XBRL 정보]
- ACODE: XBRL 태그명 (예: ifrs-full_CashAndCashEquivalents)
- ACONTEXT: 시점 + 연결/별도 컨텍스트
  - CFY2025 = 당기, PFY2024 = 전기, BPFY2023 = 전전기
  - ConsolidatedMember = 연결, SeparateMember = 별도

[출력]
SQLite financial_detail 테이블에 upsert
- DART API 호출 0회
- OpenAI 사용 0회
- 비용 $0
"""

import os
import re
import sys
import sqlite3
from pathlib import Path
from datetime import datetime
from lxml import etree

# ─── 경로 ─────────────────────────────────────────────────
ROOT = Path(r"C:\Users\Admin\FILMN9")
DB   = ROOT / "data" / "filmn9.db"
DATA_DIRS = [
    ROOT / "data" / "raw",
    ROOT / "data" / "팀원1_DART" / "DART" / "raw",
]

# ─── 테이블 제목 → (statement_type, scope) 매핑 ─────────
TITLE_PATTERNS = [
    # (정규식, statement_type, scope)
    (r"연결\s*재무상태표",          "BS",  "연결"),
    (r"연결\s*포괄손익계산서",      "CIS", "연결"),
    (r"연결\s*손익계산서",          "IS",  "연결"),
    (r"(?<!연결\s)재무상태표",      "BS",  "별도"),
    (r"(?<!연결\s)포괄손익계산서",  "CIS", "별도"),
    (r"(?<!연결\s)손익계산서",      "IS",  "별도"),
]

# ─── ACONTEXT → 연도 매핑 ────────────────────────────────
# 당기(CFY) = 2025, 전기(PFY) = 2024, 전전기(BPFY) = 2023
YEAR_PATTERNS = {
    "CFY":  2025,
    "PFY":  2024,
    "BPFY": 2023,
}

# ─── 파서 ─────────────────────────────────────────────────
def parse_amount(text: str) -> float | None:
    """문자열 → 숫자 (쉼표·괄호 제거, 음수 처리)"""
    if not text:
        return None
    t = text.strip().replace(",", "")
    if not t or t in ("-", "—", "　"):
        return None
    # 괄호로 둘러싸인 음수: (1,000) → -1000
    if t.startswith("(") and t.endswith(")"):
        t = "-" + t[1:-1]
    try:
        return float(t)
    except:
        return None

def find_year_from_context(context: str) -> int | None:
    """ACONTEXT 문자열에서 연도 추출"""
    if not context:
        return None
    # CFY2025, PFY2024, BPFY2023 패턴 직접 추출
    m = re.search(r"(CFY|PFY|BPFY)(\d{4})", context)
    if m:
        return int(m.group(2))
    return None

def match_statement_type(title: str) -> tuple[str, str] | None:
    """테이블 제목 → (statement_type, scope)"""
    for pat, st_type, scope in TITLE_PATTERNS:
        if re.search(pat, title):
            return st_type, scope
    return None

def extract_financial_tables(xml_path: Path) -> list[dict]:
    """
    XML 파일에서 재무제표 4종 추출.
    반환: [{stock_code, fiscal_year, statement_type, scope, account_id, account_nm, amount}, ...]
    """
    try:
        parser = etree.XMLParser(recover=True, encoding="utf-8")
        tree = etree.parse(str(xml_path), parser)
    except Exception as e:
        print(f"  [PARSE ERR] {xml_path.name}: {e}")
        return []

    root = tree.getroot()
    rows = []

    # 모든 TITLE 찾기
    titles = root.xpath("//TITLE")
    for title_el in titles:
        title_text = (title_el.text or "").strip()
        match = match_statement_type(title_text)
        if not match:
            continue
        st_type, scope = match

        # TITLE 의 부모(TABLE-GROUP) 안에서 다음 형제 TABLE 찾기
        parent = title_el.getparent()
        if parent is None:
            continue

        # 부모 자식 리스트에서 TITLE 위치 찾기
        siblings = list(parent)
        try:
            idx = siblings.index(title_el)
        except ValueError:
            continue

        # TITLE 다음 형제 노드 중 TABLE 찾기 — 본문 TABLE 우선 (BORDER=1)
        data_table = None
        for sib in siblings[idx+1:]:
            if sib.tag != "TABLE":
                continue
            border = sib.get("BORDER", "0")
            tbody = sib.find("TBODY")
            if tbody is None:
                continue
            tr_count = len(tbody.findall("TR"))
            # 본문 TABLE: BORDER=1 + TR 5개 초과
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

            # 첫 셀: 계정명
            account_nm = (cells[0].text or "").strip()
            if not account_nm or account_nm == "　":
                continue

            # 나머지 셀: 연도별 금액
            for cell in cells[1:]:
                acode = cell.get("ACODE", "").strip()
                acontext = cell.get("ACONTEXT", "").strip()
                text_amt = (cell.text or "").strip()

                if not acode:
                    continue

                # 연도 추출
                year = find_year_from_context(acontext)
                if not year or year not in (2025, 2024, 2023):
                    continue

                # 연결/별도 검증 (ACONTEXT 우선, TITLE 기반 fallback)
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

# ─── DB 적재 ───────────────────────────────────────────────
def upsert_to_db(conn, stock_code: str, rows: list[dict], source_path: str) -> int:
    """financial_detail 테이블에 upsert"""
    if not rows:
        return 0
    sql = """
        INSERT OR REPLACE INTO financial_detail
        (stock_code, fiscal_year, statement_type, account_id, statement_scope,
         account_nm, amount, unit, display_order, source, loaded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    source = f"사업보고서 XML 파싱 ({source_path})"
    data = []
    for i, r in enumerate(rows):
        data.append((
            stock_code, r["fiscal_year"], r["statement_type"], r["account_id"],
            r["scope"], r["account_nm"], r["amount"], "원",
            i, source, now,
        ))
    conn.executemany(sql, data)
    conn.commit()
    return len(data)

# ─── 메인 ─────────────────────────────────────────────────
def find_xml_file(stock_code: str) -> Path | None:
    """두 위치에서 종목 XML 파일 찾기"""
    for base_dir in DATA_DIRS:
        if not base_dir.exists():
            continue
        for child in base_dir.iterdir():
            if child.is_dir() and child.name.startswith(stock_code + "_"):
                xml_path = child / "2025-annual_cleaned.xml"
                if xml_path.exists():
                    return xml_path
    return None

def list_all_stocks() -> dict[str, Path]:
    """모든 종목 XML 파일 경로 매핑: {stock_code: path}"""
    stocks = {}
    for base_dir in DATA_DIRS:
        if not base_dir.exists():
            continue
        for child in base_dir.iterdir():
            if not child.is_dir():
                continue
            m = re.match(r"^([0-9A-Z]{6})_", child.name)
            if not m:
                continue
            code = m.group(1)
            xml_path = child / "2025-annual_cleaned.xml"
            if xml_path.exists() and code not in stocks:
                stocks[code] = xml_path
    return stocks

def process_one(conn, stock_code: str, xml_path: Path) -> int:
    rows = extract_financial_tables(xml_path)
    if not rows:
        return 0
    # 기존 FY2025/2024/2023 데이터 삭제 후 재적재
    conn.execute("""
        DELETE FROM financial_detail
        WHERE stock_code = ? AND fiscal_year IN (2025, 2024, 2023)
    """, (stock_code,))
    n = upsert_to_db(conn, stock_code, rows,
                     str(xml_path).replace(str(ROOT) + "\\", ""))
    return n

def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--code", help="단일 종목 (예: 009150)")
    p.add_argument("--all", action="store_true", help="모든 종목 일괄 처리")
    p.add_argument("--demo3", action="store_true", help="3종목만 (090430·009150·035420)")
    args = p.parse_args()

    if not DB.exists():
        print(f"[ERR] DB 없음: {DB}")
        sys.exit(1)
    conn = sqlite3.connect(DB)

    if args.code:
        codes = [args.code]
        targets = {args.code: find_xml_file(args.code)}
    elif args.demo3:
        targets = {}
        for c in ["090430", "009150", "035420"]:
            p_xml = find_xml_file(c)
            if p_xml:
                targets[c] = p_xml
            else:
                print(f"  [SKIP] {c}: XML 없음")
    elif args.all:
        targets = list_all_stocks()
    else:
        # 기본: 3종목
        targets = {}
        for c in ["090430", "009150", "035420"]:
            p_xml = find_xml_file(c)
            if p_xml:
                targets[c] = p_xml

    print("=" * 70)
    print(f"  사업보고서 XML 파싱 시작")
    print(f"  대상 종목: {len(targets)}개")
    print("=" * 70)

    grand_total = 0
    success = 0
    for i, (code, xml_path) in enumerate(targets.items(), 1):
        n = process_one(conn, code, xml_path)
        if n > 0:
            success += 1
            grand_total += n
            print(f"  [{i:4}/{len(targets)}] [{code}] {n:>4}건 적재 ← {xml_path.parent.name}")
        else:
            print(f"  [{i:4}/{len(targets)}] [{code}] ❌ 데이터 없음")

    print("=" * 70)
    print(f"  완료. 성공 {success}/{len(targets)} 종목 · 총 {grand_total}건")
    print("=" * 70)
    conn.close()

if __name__ == "__main__":
    main()
