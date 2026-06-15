"""
DART OpenAPI fnlttSinglAcntAll 로 FY2025 재무제표 적재
- 3종목: 090430 아모레퍼시픽, 009150 삼성전기, 035420 NAVER
- statement_type: BS (재무상태표), CIS (포괄손익계산서), IS (손익계산서)
- statement_scope: 연결(CFS) + 별도(OFS)
"""
import os
import sys
import json
import sqlite3
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path

# ─── 환경 설정 ─────────────────────────────────────────────
ROOT = Path(__file__).resolve()   # 위치 무관: data/filmn9.db 있는 레포 루트까지 위로 탐색
while ROOT != ROOT.parent and not (ROOT / "data" / "filmn9.db").exists():
    ROOT = ROOT.parent
DB   = ROOT / "data" / "filmn9.db"
ENV  = ROOT / ".env"

# ─── .env 로드 ─────────────────────────────────────────────
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
if not DART_KEY:
    print("[ERR] DART_API_KEY 미설정")
    sys.exit(1)

# ─── 종목별 corp_code ─────────────────────────────────────
STOCKS = {
    "090430": ("00583424", "아모레퍼시픽"),
    "009150": ("00126371", "삼성전기"),
    "035420": ("00266961", "NAVER"),
}

# ─── DART API 호출 ─────────────────────────────────────────
def fetch_dart(corp_code: str, year: int, reprt_code: str = "11011", fs_div: str = "CFS") -> list:
    """
    fnlttSinglAcntAll: 단일회사 전체 재무제표
    - bsns_year: 사업연도 (2025 -> 2025년 12월 결산)
    - reprt_code: 11011=사업보고서, 11012=반기, 11013=1분기, 11014=3분기
    - fs_div: CFS=연결, OFS=별도
    """
    url = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
    params = {
        "crtfc_key": DART_KEY,
        "corp_code": corp_code,
        "bsns_year": str(year),
        "reprt_code": reprt_code,
        "fs_div": fs_div,
    }
    full_url = url + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(full_url, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))
        if data.get("status") != "000":
            print(f"  [SKIP] DART 응답: {data.get('status')} {data.get('message')}")
            return []
        return data.get("list", [])
    except Exception as e:
        print(f"  [ERR] DART 호출 실패: {e}")
        return []

# ─── 정규화 ────────────────────────────────────────────────
def normalize_amount(s):
    if s is None or s == "":
        return None
    try:
        return float(str(s).replace(",", ""))
    except:
        return None

# ─── DB 적재 ───────────────────────────────────────────────
def upsert_rows(con, rows: list):
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
    data = []
    for r in rows:
        data.append((
            r["stock_code"], r["fiscal_year"], r["statement_type"], r["account_id"],
            r["statement_scope"], r["account_nm"], r["amount"], r["unit"],
            r.get("display_order"), r["source"], now,
        ))
    con.executemany(sql, data)
    con.commit()
    return len(data)

# ─── 메인 ─────────────────────────────────────────────────
def process_stock(con, stock_code: str, corp_code: str, name: str):
    print(f"\n  [{stock_code}] {name}")
    total = 0
    for fs_div, scope_name in [("CFS", "연결"), ("OFS", "별도")]:
        items = fetch_dart(corp_code, 2025, "11011", fs_div)
        if not items:
            print(f"    {scope_name}: 데이터 없음")
            continue

        rows = []
        for i, it in enumerate(items):
            # sj_div: BS, CIS, IS, CF, SCE → 우리는 BS, CIS, IS만
            sj = it.get("sj_div", "")
            if sj not in ("BS", "CIS", "IS"):
                continue
            account_id = it.get("account_id") or ""
            if not account_id:
                continue
            # thstrm_amount: 당기 금액 (FY2025)
            amount = normalize_amount(it.get("thstrm_amount"))
            rows.append({
                "stock_code": stock_code,
                "fiscal_year": 2025,
                "statement_type": sj,
                "account_id": account_id,
                "statement_scope": scope_name,
                "account_nm": it.get("account_nm"),
                "amount": amount,
                "unit": "원",
                "display_order": it.get("ord", i),
                "source": "DART fnlttSinglAcntAll (FY2025)",
            })

        n = upsert_rows(con, rows)
        total += n
        print(f"    {scope_name}: {n}개 계정 적재")

    return total

def main():
    if not DB.exists():
        print(f"[ERR] DB 없음: {DB}")
        sys.exit(1)

    con = sqlite3.connect(DB)
    print("=" * 60)
    print("  FY2025 재무제표 적재 시작 (DART fnlttSinglAcntAll)")
    print("=" * 60)

    grand_total = 0
    for code, (corp, name) in STOCKS.items():
        n = process_stock(con, code, corp, name)
        grand_total += n

    con.close()

    print("\n" + "=" * 60)
    print(f"  완료. 총 {grand_total}개 행 적재")
    print("=" * 60)

if __name__ == "__main__":
    main()
