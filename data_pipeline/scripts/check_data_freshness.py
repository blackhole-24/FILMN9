"""주가·재무 데이터 최신성 + 출처 확인"""
import sqlite3
db = r"C:\Users\Admin\FILMN9\data\filmn9.db"
conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row

print("=" * 70)
print("[ 1 ] OHLCV (주가 일봉) — 최신 날짜")
print("=" * 70)
for code in ['090430', '009150', '035420']:
    rows = conn.execute("""
        SELECT date, close, volume FROM ohlcv
        WHERE stock_code = ? ORDER BY date DESC LIMIT 5
    """, (code,)).fetchall()
    name = {'090430':'아모레퍼시픽','009150':'삼성전기','035420':'NAVER'}[code]
    print(f"\n  {code} {name}:")
    for r in rows:
        print(f"    {r['date']}  종가 {r['close']:>10,}  거래량 {r['volume']:>12,}")

print("\n" + "=" * 70)
print("[ 2 ] financials 테이블 (요약) — 회계연도")
print("=" * 70)
for code in ['090430', '009150', '035420']:
    rows = conn.execute("""
        SELECT fiscal_year, revenue, op_income, source, generated_at
        FROM financials WHERE stock_code = ? ORDER BY fiscal_year DESC
    """, (code,)).fetchall()
    name = {'090430':'아모레퍼시픽','009150':'삼성전기','035420':'NAVER'}[code]
    print(f"\n  {code} {name}:")
    for r in rows:
        rev = (r['revenue'] or 0) / 1e6
        op = (r['op_income'] or 0) / 1e6
        print(f"    FY{r['fiscal_year']}  매출 {rev:>10,.0f}백만  영업이익 {op:>8,.0f}백만  출처: {r['source']}")

print("\n" + "=" * 70)
print("[ 3 ] financial_detail (BS/IS 상세) — 회계연도 분포")
print("=" * 70)
for code in ['090430', '009150', '035420']:
    rows = conn.execute("""
        SELECT DISTINCT fiscal_year, statement_type, COUNT(*) as cnt, source
        FROM financial_detail WHERE stock_code = ?
        GROUP BY fiscal_year, statement_type ORDER BY fiscal_year DESC, statement_type
    """, (code,)).fetchall()
    name = {'090430':'아모레퍼시픽','009150':'삼성전기','035420':'NAVER'}[code]
    print(f"\n  {code} {name}:")
    for r in rows:
        print(f"    FY{r['fiscal_year']}  {r['statement_type']:3}  계정수 {r['cnt']:>3}  출처: {r['source']}")

print("\n" + "=" * 70)
print("[ 4 ] DART 사업보고서 (disclosures) — 보유한 보고서 목록")
print("=" * 70)
for code in ['090430', '009150', '035420']:
    rows = conn.execute("""
        SELECT rcept_dt, report_nm FROM disclosures
        WHERE stock_code = ? AND report_nm LIKE '%사업보고서%'
        ORDER BY rcept_dt DESC LIMIT 5
    """, (code,)).fetchall()
    name = {'090430':'아모레퍼시픽','009150':'삼성전기','035420':'NAVER'}[code]
    print(f"\n  {code} {name}:")
    if not rows:
        print("    (사업보고서 항목 없음)")
    for r in rows:
        print(f"    {r['rcept_dt']}  {r['report_nm']}")

conn.close()
