# -*- coding: utf-8 -*-
"""야간 1번: 3,000 전수 검수 — 기능 모듈별 데이터 존재 전수 검사.
모듈 ID = 데이터 원천 지도 번호. 각 종목이 어느 기능 모듈의 데이터를 갖췄는지 매트릭스화.
산출: 검수_매트릭스.csv (종목×모듈) + 검수_리포트.html (대시보드). 로컬 SQLite/파일/Mongo 직접 조회(빠름)."""
import sqlite3, json, csv, time
from pathlib import Path
from datetime import datetime

ROOT = Path(r"C:\Users\Admin\FILMN9")
OUT = ROOT / "통합산출물" / "야간_전수검수_20260614"
OUT.mkdir(parents=True, exist_ok=True)
db = sqlite3.connect(str(ROOT / "data" / "filmn9.db"))
db.row_factory = sqlite3.Row
c = db.cursor()

def codeset(q):
    return {r[0] for r in c.execute(q).fetchall()}

print("원천별 보유 종목 집합 로딩...")
companies = [(r["stock_code"], r["corp_name"], r["market"], r["sector"])
             for r in c.execute("SELECT stock_code, corp_name, market, sector FROM company_info WHERE length(stock_code)=6 ORDER BY stock_code")]
S = {}
S["재무하이라이트"] = codeset("SELECT DISTINCT stock_code FROM financials WHERE revenue IS NOT NULL OR op_income IS NOT NULL")
S["재무제표3년"]   = codeset("SELECT stock_code FROM financial_detail GROUP BY stock_code HAVING COUNT(DISTINCT fiscal_year)>=3")
S["재무제표1년+"]  = codeset("SELECT DISTINCT stock_code FROM financial_detail")
S["주가"]          = codeset("SELECT DISTINCT stock_code FROM ohlcv")
S["경영인"]        = codeset("SELECT DISTINCT stock_code FROM executives")
S["주주구성"]      = codeset("SELECT DISTINCT stock_code FROM shareholders")
S["밸류에이션"]    = codeset("SELECT stock_code FROM valuation_summary")
# 손익흐름도(파일)
S["손익흐름도"] = {p.stem.replace("_sankey", "") for p in (ROOT / "outputs" / "sankey").glob("*_sankey.html")}
# 밸류 합본 JSON(파일)
vinbox = ROOT / "data" / "valuation_inbox" / "repr20_export" / "data"
S["밸류상세JSON"] = {p.stem.split("_")[0] for p in vinbox.glob("*.json")} if vinbox.exists() else set()
vres = ROOT / "data" / "valuation_results"
if vres.exists():
    S["밸류상세JSON"] |= {p.name.split("_")[0] for p in vres.iterdir() if p.is_dir()}

# 히스토리브리핑 (MongoDB) — 실패해도 진행
S["히스토리브리핑"] = set()
mongo_status = "skip"
try:
    import pymongo
    env = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8", errors="ignore").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1); env[k.strip()] = v.strip().strip('"').strip("'")
    cli = pymongo.MongoClient(env.get("MONGO_URI"), serverSelectionTimeoutMS=8000)
    coll = cli[env.get("MONGO_DB", "filmn9")][env.get("MONGO_COLLECTION", "histories")]
    S["히스토리브리핑"] = {d.get("stock_code") for d in coll.find({}, {"stock_code": 1})}
    mongo_status = f"OK ({len(S['히스토리브리핑'])}건)"
except Exception as e:
    mongo_status = f"실패: {str(e)[:50]}"
print("히스토리브리핑(Mongo):", mongo_status)

# 검사할 모듈 순서 (핵심=대부분 종목 보유 기대 / 부분=일부만)
CORE = ["재무하이라이트", "재무제표1년+", "주가", "손익흐름도", "주주구성", "경영인"]
PARTIAL = ["재무제표3년", "히스토리브리핑", "밸류에이션", "밸류상세JSON"]
MODS = CORE + PARTIAL

# 매트릭스 CSV
rows = []
for code, name, market, sector in companies:
    row = {"종목코드": code, "회사명": name, "시장": market or "", "업종": sector or ""}
    for m in MODS:
        row[m] = "O" if code in S[m] else "X"
    row["핵심누락수"] = sum(1 for m in CORE if code not in S[m])
    rows.append(row)

with open(OUT / "검수_매트릭스.csv", "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["종목코드", "회사명", "시장", "업종"] + MODS + ["핵심누락수"])
    w.writeheader(); w.writerows(rows)

# 집계
total = len(companies)
cov = {m: sum(1 for r in rows if r[m] == "O") for m in MODS}
# 핵심 모듈 누락 종목 (시장 '기타'=스팩/코넥스 분리)
def is_normal(r): return r["시장"] not in ("기타", "")
prob_core = [r for r in rows if r["핵심누락수"] > 0 and is_normal(r)]
prob_core.sort(key=lambda r: -r["핵심누락수"])

NOW = datetime.now().strftime("%Y-%m-%d %H:%M")
print(f"\n전체 {total}종 검수. 핵심모듈 누락(정상시장) {len(prob_core)}종")
for m in MODS:
    print(f"  {m}: {cov[m]} / {total}  ({cov[m]*100//total}%)")

db.close()
# 결과를 다음 단계(HTML 생성)에서 쓰도록 JSON 저장
summary = {"now": NOW, "total": total, "cov": cov, "mods": MODS, "core": CORE, "partial": PARTIAL,
           "mongo": mongo_status, "prob_core_n": len(prob_core),
           "prob_core": [{"code": r["종목코드"], "name": r["회사명"], "market": r["시장"],
                          "miss": [m for m in CORE if r[m] == "X"]} for r in prob_core[:300]]}
(OUT / "_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
print("저장:", OUT / "검수_매트릭스.csv", "+ _summary.json")
