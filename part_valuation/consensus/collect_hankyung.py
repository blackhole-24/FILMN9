"""
FILMN9 - 1단계: 한경 컨센서스 스크래퍼
========================================
인수인계서 7장 코드 기반. 주요 보완사항:
 1. 종목코드 추출 — 제목 패턴 외 td[0]에서 직접 추출 시도
 2. requests.Session 으로 쿠키 유지 (urllib 단독보다 안정적)
 3. 페이지별 진행률 출력
 4. 오류 발생 시 재시도 1회

실행:
  cd C:/Users/Admin/FILMN9
  conda activate FILMN9_env
  pip install requests beautifulsoup4  (없는 경우)
  python part_valuation/collect_hankyung.py
"""

import requests, re, json, time, statistics
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict, Counter
import urllib3

urllib3.disable_warnings()

# ── 설정 ─────────────────────────────────────────────────────────────
BASE_URL  = "https://consensus.hankyung.com"
OUT_DIR   = Path("C:/Users/Admin/FILMN9/data/hankyung")
DELAY_SEC = 0.15   # 페이지 간 딜레이 (초)
TIMEOUT   = 20

sdate = (datetime.today() - timedelta(days=365)).strftime('%Y-%m-%d')
edate = datetime.today().strftime('%Y-%m-%d')

HEADERS = {
    'User-Agent':      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept':          'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'ko-KR,ko;q=0.9,en;q=0.8',
    'Referer':         BASE_URL,
}

# ── 유틸 ─────────────────────────────────────────────────────────────
def clean(s: str) -> str:
    s = re.sub(r'<[^>]+>', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()

def fetch(session: requests.Session, url: str, retries: int = 1) -> str | None:
    for attempt in range(retries + 1):
        try:
            r = session.get(url, headers=HEADERS, timeout=TIMEOUT, verify=False)
            if r.status_code == 200:
                return r.text
            print(f"  ⚠ HTTP {r.status_code}: {url}")
        except Exception as e:
            print(f"  ⚠ 요청 실패 (시도 {attempt+1}): {e}")
        if attempt < retries:
            time.sleep(1.0)
    return None

# ── 메인 ─────────────────────────────────────────────────────────────
def main():
    print(f"{'='*60}")
    print(f"  FILMN9 한경 컨센서스 스크래퍼")
    print(f"  기간: {sdate} ~ {edate}")
    print(f"{'='*60}")

    session = requests.Session()
    # 메인 페이지 먼저 방문해서 쿠키 확보
    session.get(BASE_URL, headers=HEADERS, verify=False, timeout=TIMEOUT)

    list_url = (
        f"{BASE_URL}/analysis/list?skinType=business"
        f"&sdate={sdate}&edate={edate}&now_page=1"
    )

    # ── 총 페이지 수 확인 ──
    html0 = fetch(session, list_url)
    if not html0:
        print("❌ 첫 페이지 접근 실패. 네트워크/VPN 상태 확인 후 재시도하세요.")
        return

    page_nums = re.findall(r'now_page=(\d+)', html0)
    last_page = max(int(p) for p in page_nums) if page_nums else 1
    print(f"  총 페이지: {last_page}페이지")

    # ── 전체 페이지 순회 ──
    reports = []
    htmls_to_parse = [(1, html0)]  # 첫 페이지는 이미 받음

    for p in range(2, last_page + 1):
        url = (
            f"{BASE_URL}/analysis/list?skinType=business"
            f"&sdate={sdate}&edate={edate}&now_page={p}"
        )
        html = fetch(session, url)
        if html:
            htmls_to_parse.append((p, html))
        time.sleep(DELAY_SEC)
        if p % 20 == 0:
            print(f"  진행: {p}/{last_page} 페이지 완료")

    print(f"  전체 {len(htmls_to_parse)}/{last_page} 페이지 수신 완료")

    # ── 행 파싱 ──
    for page_no, html in htmls_to_parse:
        tbody = re.search(r'<tbody>(.+?)</tbody>', html, re.DOTALL)
        if not tbody:
            continue
        rows = re.findall(r'<tr[^>]*>(.+?)</tr>', tbody.group(1), re.DOTALL)

        for row in rows:
            tds = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
            if len(tds) < 6:
                continue

            date_str = clean(tds[0])
            raw_title = clean(tds[1])
            target    = clean(tds[2])
            opinion   = clean(tds[3])
            analyst   = clean(tds[4])
            broker    = clean(tds[5])

            # 종목코드: 제목 내 (123456) 패턴 우선, 없으면 data-* 또는 href 추출
            code_m = re.search(r'\((\d{6})\)', raw_title)
            if not code_m:
                code_m = re.search(r'code[=_](\d{6})', row)
            if not code_m:
                code_m = re.search(r'"(\d{6})"', row)
            if not code_m:
                continue  # 종목코드 없으면 skip

            stock_code = code_m.group(1)
            stock_name = raw_title.split('(')[0].strip() if '(' in raw_title else raw_title

            # report_idx: PDF 링크에서 추출
            idx_m = re.search(r'report_idx=(\d+)', row)
            report_idx = int(idx_m.group(1)) if idx_m else None

            # 적정가 정제
            tp_str = re.sub(r'[^\d]', '', target)
            target_price = int(tp_str) if tp_str.isdigit() else None

            reports.append({
                "report_idx"  : report_idx,
                "date"        : date_str,
                "stock_code"  : stock_code,
                "stock_name"  : stock_name,
                "title"       : raw_title,
                "target_price": target_price,
                "opinion"     : opinion if opinion else None,
                "analyst"     : analyst if analyst else None,
                "broker"      : broker if broker else None,
                "pdf_url"     : (f"{BASE_URL}/analysis/downpdf?report_idx={report_idx}"
                                 if report_idx else None),
            })

    unique_codes = set(r["stock_code"] for r in reports)
    print(f"\n  파싱 결과: {len(reports)}건 / {len(unique_codes)}개 종목")

    if not reports:
        print("❌ 파싱 결과 없음. HTML 구조가 변경됐을 수 있습니다.")
        print("   브라우저에서 https://consensus.hankyung.com/analysis/list?skinType=business")
        print("   접속 후 F12 > 소스에서 <tbody> 구조를 확인하세요.")
        return

    # ── 저장 ──
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "by_stock_code").mkdir(exist_ok=True)

    meta_path = OUT_DIR / "reports_metadata.json"
    meta_data = {
        "_meta": {
            "source"         : "한경 컨센서스",
            "url"            : BASE_URL,
            "collected_at"   : datetime.now().strftime('%Y-%m-%d %H:%M'),
            "date_range_from": sdate,
            "date_range_to"  : edate,
            "total_reports"  : len(reports),
            "unique_stocks"  : len(unique_codes),
        },
        "reports": reports
    }
    meta_path.write_text(
        json.dumps(meta_data, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    print(f"\n  ✓ 메타데이터 저장: {meta_path}")

    # ── 종목별 집계 ──
    by_stock: dict[str, list] = defaultdict(list)
    for r in reports:
        by_stock[r["stock_code"]].append(r)

    saved_count = 0
    for code, rs in by_stock.items():
        tps  = [r["target_price"] for r in rs if r["target_price"]]
        ops  = [r["opinion"] for r in rs if r["opinion"]]
        stock_data = {
            "stock_code"         : code,
            "stock_name"         : rs[0]["stock_name"],
            "report_count"       : len(rs),
            "broker_count"       : len(set(r["broker"] for r in rs if r["broker"])),
            "latest_report_date" : max(r["date"] for r in rs),
            "target_price": {
                "avg"   : round(statistics.mean(tps))   if tps else None,
                "median": round(statistics.median(tps)) if tps else None,
                "min"   : min(tps) if tps else None,
                "max"   : max(tps) if tps else None,
                "stddev": round(statistics.stdev(tps))  if len(tps) >= 2 else None,
            },
            "opinion_distribution": dict(Counter(ops)),
            "reports": rs
        }
        out_path = OUT_DIR / "by_stock_code" / f"{code}.json"
        out_path.write_text(
            json.dumps(stock_data, ensure_ascii=False, indent=2), encoding='utf-8'
        )
        saved_count += 1

    print(f"  ✓ 종목별 JSON 저장: {saved_count}개 파일")
    print(f"\n{'='*60}")
    print(f"  완료! 다음 단계: collect_naver_consensus.py 실행")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
