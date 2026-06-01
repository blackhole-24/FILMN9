"""
네이버 증권 실제 구조 진단 v3
- 메인 페이지 iframe 여부 확인
- 실제 컨센서스 데이터 소스 URL 특정
"""
import requests
from bs4 import BeautifulSoup
from pathlib import Path
import urllib3, re, json
urllib3.disable_warnings()

CODE = "000080"
OUT  = Path("C:/Users/Admin/FILMN9/data/_debug")
OUT.mkdir(parents=True, exist_ok=True)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept-Language': 'ko-KR,ko;q=0.9',
    'Referer': 'https://finance.naver.com',
}

session = requests.Session()
session.get('https://finance.naver.com', headers=HEADERS, verify=False, timeout=10)

print("="*60)
print(f"  네이버 구조 진단 - {CODE}")
print("="*60)

# ── 1. 메인 페이지 ──
url_main = f"https://finance.naver.com/item/coinfo.naver?code={CODE}"
r = session.get(url_main, headers=HEADERS, verify=False, timeout=15)
print(f"\n[메인] status={r.status_code}, size={len(r.content)}B")

# 인코딩 두 가지 시도
html_euc = r.content.decode('euc-kr', errors='ignore')
soup = BeautifulSoup(html_euc, 'html.parser')

# 테이블 목록
tables = soup.find_all('table')
print(f"  테이블 수: {len(tables)}")
for i, t in enumerate(tables[:5]):
    print(f"  [{i}] id={t.get('id','')!r} class={t.get('class',[])} rows={len(t.find_all('tr'))}")

# iframe 목록
iframes = soup.find_all('iframe')
print(f"\n  iframe 수: {len(iframes)}")
for f in iframes:
    src = f.get('src', '')
    print(f"    src: {src}")

# 키워드 체크
for kw in ['매출액', 'cTB511', 'colorE', '2026', 'coinfo', 'finsum']:
    print(f"  '{kw}' 출현: {html_euc.count(kw)}회")

(OUT / "naver_main.html").write_text(html_euc, encoding='utf-8')

# ── 2. finsum_more (wisereport iframe) ──
url_finsum = f"https://finance.naver.com/item/coinfo.naver?code={CODE}&target=finsum_more"
r2 = session.get(url_finsum, headers=HEADERS, verify=False, timeout=15)
print(f"\n[finsum_more] status={r2.status_code}, size={len(r2.content)}B")
html2 = r2.content.decode('euc-kr', errors='ignore')
soup2 = BeautifulSoup(html2, 'html.parser')
tables2 = soup2.find_all('table')
print(f"  테이블 수: {len(tables2)}")
for i, t in enumerate(tables2[:5]):
    print(f"  [{i}] id={t.get('id','')!r} class={t.get('class',[])} rows={len(t.find_all('tr'))}")
for kw in ['매출액', 'cTB511', 'colorE', '2026']:
    print(f"  '{kw}' 출현: {html2.count(kw)}회")
(OUT / "naver_finsum.html").write_text(html2, encoding='utf-8')

# ── 3. wisereport 직접 ──
url_wise = f"https://navercomp.wisereport.co.kr/v2/company/c1010001.aspx?cmp_cd={CODE}"
r3 = session.get(url_wise, headers={**HEADERS, 'Referer': 'https://finance.naver.com'}, verify=False, timeout=15)
print(f"\n[wisereport] status={r3.status_code}, size={len(r3.content)}B")
html3 = r3.content.decode('utf-8', errors='ignore')
soup3 = BeautifulSoup(html3, 'html.parser')
tables3 = soup3.find_all('table')
print(f"  테이블 수: {len(tables3)}")
for i, t in enumerate(tables3):
    cls = t.get('class', [])
    rows = t.find_all('tr')
    if len(rows) > 3:  # 의미있는 테이블만
        # 첫 번째 행 텍스트
        first_row = rows[0].get_text(' ', strip=True)[:60]
        print(f"  [{i}] id={t.get('id','')!r} class={cls} rows={len(rows)} | {first_row}")
for kw in ['매출액', 'cTB511', 'colorE', '2026', 'TB511']:
    print(f"  '{kw}' 출현: {html3.count(kw)}회")
(OUT / "wisereport_000080.html").write_text(html3, encoding='utf-8')

# ── 4. wisereport에서 실제 테이블 구조 ──
# cTB511 또는 매출액 포함 테이블 상세 분석
target = soup3.find('table', id='cTB511')
if not target:
    for t in soup3.find_all('table'):
        if '매출액' in t.get_text():
            target = t
            break

if target:
    print(f"\n★ 매출액 테이블 발견! id={target.get('id')!r} class={target.get('class')}")
    rows = target.find_all('tr')
    print(f"  행 수: {len(rows)}")
    for row in rows[:8]:
        th = row.find('th')
        tds= row.find_all('td')
        th_txt = th.get_text(strip=True) if th else '-'
        td_txts= [td.get_text(strip=True)[:10] for td in tds[:6]]
        print(f"  th={th_txt!r:20s} | tds={td_txts}")
else:
    print("\n★ 매출액 테이블 없음")
    # 모든 텍스트에서 매출액 주변 컨텍스트 출력
    idx = html3.find('매출액')
    if idx > 0:
        print(f"  매출액 주변 HTML: ...{html3[idx-100:idx+200]}...")

print(f"\n저장 완료: {OUT}")
print("="*60)
