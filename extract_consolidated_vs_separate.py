# -*- coding: utf-8 -*-
"""연결<별도 55개 이상 종목 상세 데이터 추출 — AI 진단용 CSV"""
import sqlite3
import csv
from pathlib import Path

DB = Path(r"C:\Users\Admin\FILMN9\data\filmn9.db")
SRC_CSV = Path(r"C:\Users\Admin\FILMN9\auto_reports\06_연결별도_이상_종목.csv")
OUT_DIR = Path(r"C:\Users\Admin\FILMN9\handover")
OUT_DIR.mkdir(exist_ok=True)

# 1) 이상 종목 코드 수집
with open(SRC_CSV, encoding="utf-8-sig") as f:
    rdr = csv.DictReader(f)
    abnormal_rows = list(rdr)

codes = sorted(set(r["stock_code"] for r in abnormal_rows))
print(f"이상 종목: {len(codes)}개 / 이상 행: {len(abnormal_rows)}개")

# 2) 회사명 + 핵심 BS 행 추출 (자산·부채·자본 총계, 연결·별도, 3개년)
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

out_rows = []
for code in codes:
    name = ""  # corp_name 컬럼 없음, 생략

    # BS 핵심 계정
    rows = conn.execute("""
        SELECT fiscal_year, statement_scope, account_id, account_nm, amount, source
        FROM financial_detail
        WHERE stock_code = ?
          AND statement_type = 'BS'
          AND (account_nm LIKE '%자산총계%'
               OR account_nm LIKE '%부채총계%'
               OR account_nm LIKE '%자본총계%')
        ORDER BY fiscal_year DESC, statement_scope, account_nm
    """, (code,)).fetchall()
    for r in rows:
        out_rows.append({
            "stock_code": code,
            "fiscal_year": r["fiscal_year"],
            "scope": r["statement_scope"],
            "account_id": r["account_id"],
            "account_nm": r["account_nm"],
            "amount": r["amount"],
            "source": r["source"],
        })

# 3) CSV 저장
out_csv = OUT_DIR / "연결별도_55개_상세_AI진단용.csv"
with open(out_csv, "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
    w.writeheader()
    w.writerows(out_rows)

# 4) AI에 던질 요약 표 만들기 (피벗)
pivot = {}
for r in out_rows:
    key = (r["stock_code"], r["fiscal_year"])
    pivot.setdefault(key, {"stock_code": r["stock_code"], "fiscal_year": r["fiscal_year"]})
    label = f'{r["scope"] or "?"}_{r["account_nm"]}'
    pivot[key][label] = r["amount"]

# 5) 마크다운 요약 (AI에 바로 붙여넣을 형태)
out_md = OUT_DIR / "연결별도_55개_요약_AI진단용.md"
with open(out_md, "w", encoding="utf-8") as f:
    f.write("# 연결<별도 이상 55개 종목 — AI 진단 요청용 데이터\n\n")
    f.write(f"- 이상 종목 수: **{len(codes)}개**\n")
    f.write(f"- 이상 행: {len(abnormal_rows)}건 (종목당 1~3개 연도)\n")
    f.write(f"- 추출 일시: 2026-05-29 (금)\n\n")
    f.write("## 문제 정의\n")
    f.write("회계상 **연결재무제표 자산총계 ≥ 별도재무제표 자산총계** 가 일반적이나, 아래 종목들은 반대 (연결 < 별도) 로 적재됨.\n\n")
    f.write("## 의심 원인 후보\n")
    f.write("1. 파싱 시 CFS(연결)/OFS(별도) 라벨 뒤바뀜\n")
    f.write("2. 같은 컨텍스트에서 연결/별도 행이 중복 매핑\n")
    f.write("3. 실제 회계 현상 (종속회사 손실로 연결자산 감소 등) - 정상 케이스\n\n")
    f.write("## 상위 10종목 상세 (전체는 CSV 참조)\n\n")
    f.write("| 종목 | 연도 | 연결자산 | 별도자산 | 연결/별도 | 비고 |\n")
    f.write("|---|:-:|---:|---:|---:|---|\n")
    shown = 0
    for r in abnormal_rows:
        if shown >= 10:
            break
        ratio = float(r.get("연결/별도비율", 0)) if r.get("연결/별도비율") else 0
        f.write(f"| {r['stock_code']} | {r['fiscal_year']} | "
                f"{int(float(r['연결자산'])):,} | {int(float(r['별도자산'])):,} | "
                f"{ratio:.2f} | {'⚠️ 큰 차이' if ratio < 0.85 else '경미'} |\n")
        shown += 1

conn.close()
print(f"[OK] CSV  : {out_csv}")
print(f"[OK] 요약 : {out_md}")
