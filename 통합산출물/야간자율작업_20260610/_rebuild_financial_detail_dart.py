# -*- coding: utf-8 -*-
"""21: financial_detail 전면 재구축 (DART API → 3년치 표준 재무제표).
기존 financial_detail은 챗봇 RAG 청크(JSONL_RAG_chunk) 출처라 연도누락·단위혼재·주석오염.
→ DART fnlttSinglAcntAll(2025 사업보고서, 11011)에서 당기/전기/전전기(2025/2024/2023)를
   계정별로 전부 추출. 원→백만원(÷1e6) 통일. BS/IS/CIS, 연결(CFS)+별도(OFS).
사용: python _rebuild_financial_detail_dart.py [--code 051910]  (--code 없으면 전체)
"""
import json, urllib.request, urllib.parse, re, sqlite3, psycopg, time, sys
from datetime import datetime
from pathlib import Path

ROOT = Path(r"C:\Users\Admin\FILMN9")
KEY = re.search(r"DART_API_KEY=(\S+)", (ROOT / ".env").read_text(encoding="utf-8")).group(1)
url = [l.split("=", 1)[1].strip() for l in (ROOT / ".env").read_text(encoding="utf-8", errors="ignore").splitlines()
       if l.strip().startswith("DATABASE_URL=")][0]
NOW = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
SRC = "DART fnlttSinglAcntAll(2025 11011)"
KEEP_SJ = ("BS", "IS", "CIS")          # 현금흐름표(CF)는 화면 미표시 → 제외
YEAR_FIELDS = [(2025, "thstrm_amount"), (2024, "frmtrm_amount"), (2023, "bfefrmtrm_amount")]
COLS = ("stock_code,fiscal_year,statement_type,account_id,account_nm,amount,unit,"
        "statement_scope,display_order,source,loaded_at")
NCOL = len(COLS.split(","))

argcode = None
if "--code" in sys.argv:
    argcode = sys.argv[sys.argv.index("--code") + 1]

def fetch(cc, fs):
    p = {"crtfc_key": KEY, "corp_code": cc, "bsns_year": "2025", "reprt_code": "11011", "fs_div": fs}
    try:
        d = json.loads(urllib.request.urlopen(
            "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json?" + urllib.parse.urlencode(p),
            timeout=15).read().decode("utf-8"))
        return d.get("list", []) if d.get("status") == "000" else []
    except Exception:
        return []

def build_rows(code, cc):
    """한 종목의 financial_detail 행 생성 (연결+별도, 3년치, 백만원)."""
    rows = []
    for fs, scope in (("CFS", "연결"), ("OFS", "별도")):
        lst = fetch(cc, fs)
        for it in lst:
            sj = it.get("sj_div")
            if sj not in KEEP_SJ:
                continue
            nm = (it.get("account_nm") or "").strip()
            if not nm:
                continue
            aid = it.get("account_id") or ""
            ordv = it.get("ord")
            try:
                ordv = int(ordv)
            except Exception:
                ordv = 0
            # 표준계정코드 미사용(커스텀)은 ord로 고유키 부여 (엔드포인트가 account_id로 dedup하므로)
            aid_key = aid if (aid and "미사용" not in aid) else f"custom_{sj}_{scope}_{ordv}"
            for yr, field in YEAR_FIELDS:
                raw = it.get(field)
                if raw is None or str(raw).strip() in ("", "-"):
                    continue
                try:
                    v = float(str(raw).replace(",", "")) / 1_000_000.0   # 원 → 백만원
                except Exception:
                    continue
                rows.append((code, yr, sj, aid_key, nm, round(v), "백만원",
                             scope, ordv, SRC, NOW))
    return rows

corp = json.load(open(ROOT / "data" / "corp_code_map.json", encoding="utf-8")).get("by_stock_code", {})
if argcode:
    targets = [argcode]
else:
    targets = [c for c in corp if len(c) == 6 and corp[c].get("corp_code")]
print(f"대상 {len(targets)}종 · financial_detail 재구축 시작 (DART 3년치)")

sq = sqlite3.connect(str(ROOT / "data" / "filmn9.db"))
pg = psycopg.connect(url, autocommit=True, connect_timeout=30)
ph_pg = ",".join(["%s"] * NCOL)
ph_sq = ",".join(["?"] * NCOL)

ok = empty = 0
t0 = time.time()
for i, code in enumerate(targets, 1):
    cc = corp.get(code, {}).get("corp_code")
    if not cc:
        continue
    rows = build_rows(code, cc)
    if not rows:
        empty += 1
        continue
    # 회사 단위로 교체 (fetch 성공 시에만 DELETE → 실패 시 기존 데이터 보존).
    # 라이브 백엔드가 읽는 중 → 트랜잭션으로 감싸 DELETE/INSERT 사이 빈 구간 제거.
    with sq:  # sqlite3: 컨텍스트 = 자동 commit/rollback
        sq.execute("DELETE FROM financial_detail WHERE stock_code=?", (code,))
        sq.executemany(f"INSERT INTO financial_detail ({COLS}) VALUES ({ph_sq})", rows)
    with pg.transaction():  # psycopg3: autocommit이어도 명시적 BEGIN/COMMIT
        pg.execute("DELETE FROM financial_detail WHERE stock_code=%s", (code,))
        with pg.cursor() as cur:
            cur.executemany(f"INSERT INTO financial_detail ({COLS}) VALUES ({ph_pg})", rows)
    ok += 1
    if i % 200 == 0:
        print(f"  {i}/{len(targets)} ... 적재 {ok} · 빈값 {empty} ({time.time()-t0:.0f}s)")

print(f"\n=== 완료: {ok}종 적재 · {empty}종 DART무응답 ({time.time()-t0:.0f}s) ===")
# 검증
for code in (targets[:1] if argcode else ['051910', '005930']):
    yrs = pg.execute("SELECT DISTINCT fiscal_year FROM financial_detail WHERE stock_code=%s ORDER BY 1 DESC", (code,)).fetchall()
    print(f"  {code} 연도: {[r[0] for r in yrs]}")
    for r in pg.execute("SELECT account_nm, fiscal_year, amount FROM financial_detail "
                        "WHERE stock_code=%s AND statement_type='BS' AND statement_scope='연결' "
                        "AND account_nm='자산총계' ORDER BY fiscal_year DESC", (code,)).fetchall():
        print(f"    자산총계 {r[1]} = {r[2]:,} 백만원")
sq.close(); pg.close()
print("완료.")
