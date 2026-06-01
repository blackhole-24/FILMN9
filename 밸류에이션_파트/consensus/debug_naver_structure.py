"""
FILMN9 - 네이버/wisereport 페이지 구조 진단 스크립트
=======================================================
collect_naver_consensus.py 실행 전, 실제 페이지 구조를 확인.
005930 (삼성전자) 1개 종목으로 HTML 덤프 + 테이블 파싱 진단.

실행:
  python 밸류에이션_파트/debug_naver_structure.py
"""

import requests, json, re
from pathlib import Path
from bs4 import BeautifulSoup
import urllib3

urllib3.disable_warnings()

CODE = "005930"
STOCK_NAME = "삼성전자"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Referer':    'https://finance.naver.com',
    'Accept-Language': 'ko-KR,ko;q=0.9',
}

def try_url(session, url, encoding='utf-8'):
    try:
        r = session.get(url, headers=HEADERS, timeout=15, verify=False)
        print(f"  상태: {r.status_code} / 길이: {len(r.text)}")
        if r.status_code == 200:
            r.encoding = encoding
            return r.text
    except Exception as e:
        print(f"  실패: {e}")
    return None

def analyze_tables(html: str):
    soup = BeautifulSoup(html, 'html.parser')
    tables = soup.find_all('table')
    print(f"\n  발견된 테이블 수: {len(tables)}")

    for i, tbl in enumerate(tables):
        cls = tbl.get('class', [])
        rows = tbl.find_all('tr')
        print(f"\n  테이블[{i}] class={cls} / 행수={len(rows)}")
        for j, row in enumerate(rows[:4]):  # 최대 4행만 출력
            cells = row.find_all(['th', 'td'])
            cell_texts = [c.get_text(strip=True)[:20] for c in cells[:8]]
            print(f"    행[{j}]: {cell_texts}")

def main():
    session = requests.Session()
    session.get('https://finance.naver.com', headers=HEADERS, verify=False, timeout=10)

    print(f"{'='*60}")
    print(f"  네이버/wisereport 구조 진단 - {CODE} {STOCK_NAME}")
    print(f"{'='*60}")

    urls = [
        ("wisereport (utf-8)",  f"https://navercomp.wisereport.co.kr/v2/company/c1010001.aspx?cmp_cd={CODE}", 'utf-8'),
        ("wisereport (euc-kr)", f"https://navercomp.wisereport.co.kr/v2/company/c1010001.aspx?cmp_cd={CODE}", 'euc-kr'),
        ("naver finsum_more",   f"https://finance.naver.com/item/coinfo.naver?code={CODE}&target=finsum_more", 'euc-kr'),
    ]

    out_dir = Path("C:/Users/Admin/FILMN9/data/_debug")
    out_dir.mkdir(parents=True, exist_ok=True)

    for name, url, enc in urls:
        print(f"\n[{name}]")
        print(f"  URL: {url}")
        html = try_url(session, url, enc)
        if html:
            # HTML 저장
            fname = name.replace(' ', '_').replace('(', '').replace(')', '') + '.html'
            (out_dir / fname).write_text(html, encoding='utf-8')
            print(f"  HTML 저장: {out_dir / fname}")
            analyze_tables(html)
            break  # 첫 번째 성공 URL에서 분석

    print(f"\n{'='*60}")
    print(f"  저장된 HTML을 브라우저로 열어서 테이블 구조 확인:")
    print(f"  {out_dir}")
    print(f"\n  이후 parse_wise_table() 함수에서 실제 클래스명/구조 반영 필요.")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
