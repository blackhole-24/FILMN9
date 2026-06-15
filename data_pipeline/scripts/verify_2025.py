import sqlite3
conn = sqlite3.connect(r"C:\Users\Admin\FILMN9\data\filmn9.db")
conn.row_factory = sqlite3.Row

print("=" * 70)
print("  FY2025 재무제표 검증")
print("=" * 70)
for code in ['090430', '009150', '035420']:
    rows = conn.execute("""
        SELECT fiscal_year, statement_type, statement_scope, COUNT(*) as cnt
        FROM financial_detail WHERE stock_code = ? AND fiscal_year >= 2023
        GROUP BY fiscal_year, statement_type, statement_scope
        ORDER BY fiscal_year DESC, statement_type, statement_scope
    """, (code,)).fetchall()
    nm = {'090430':'아모레퍼시픽','009150':'삼성전기','035420':'NAVER'}[code]
    print(f"\n[{code}] {nm}")
    for r in rows:
        print(f"  FY{r['fiscal_year']}  {r['statement_type']:3}  {r['statement_scope']:4}  {r['cnt']}개")

    # 샘플 — FY2025 BS 연결 상위 5개
    print(f"\n  [샘플] FY2025 BS 연결 상위 5계정:")
    samples = conn.execute("""
        SELECT account_nm, amount FROM financial_detail
        WHERE stock_code = ? AND fiscal_year = 2025
          AND statement_type = 'BS' AND statement_scope = '연결'
        ORDER BY display_order LIMIT 5
    """, (code,)).fetchall()
    for s in samples:
        amt = s['amount']
        amt_str = f"{amt:,.0f}원" if amt else "None"
        print(f"    - {s['account_nm']}: {amt_str}")

conn.close()
