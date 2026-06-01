"""
FILMN9 - 2단계: 네이버 증권 컨센서스 스크래퍼 (v3 - cTB511 직접 파싱)
=========================================================================
스크린샷 실측 기반. finance.naver.com/item/coinfo.naver?code={code}
메인 페이지의 table#cTB511(gHead01.all-width)에
매출액/영업이익/당기순이익/EPS/BPS/PER/PBR/ROE/EV EBITDA 3년 추정치 포함.

Ajax 불필요. 정적 HTML 파싱.

컬럼 순서 (0-based, th 제외):
  0: 매출액(억원)  1: YoY(%)  2: 영업이익(억원)  3: 당기순이익(억원)
  4: EPS(원)       5: BPS(원) 6: PER(배)          7: PBR(배)
  8: ROE(%)        9: EV/EBITDA(배)  10: 주재무제표

(E) 행 식별: th scope='row' class 'line center colorE' 또는 텍스트에 '(E)' 포함

추가 수집 (상단 gHead03 테이블):
  - 컨센서스 목표가 평균, 기관수 (gHead all-width)
  - 증권사별 목표가 (gHead01 all-width — 별도 테이블)

실행:
  python part_valuation/collect_naver_consensus.py
"""

import requests, json, time, re, statistics as _stat
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup
import urllib3

urllib3.disable_warnings()

# ── 설정 ───────────────────────────────────────────────────────────
HK_META_PATH = Path("C:/Users/Admin/FILMN9/data/hankyung/reports_metadata.json")
OUT_DIR      = Path("C:/Users/Admin/FILMN9/data/naver_consensus/by_stock_code")
DELAY_SEC    = 0.35
TIMEOUT      = 15

NAVER_URL = "https://finance.naver.com/item/coinfo.naver?code={code}"

HEADERS = {
    'User-Agent':      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept-Language': 'ko-KR,ko;q=0.9',
    'Accept':          'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}

# ── 컬럼 인덱스 (th 제외한 td 기준) ───────────────────────────────
COL = {
    'revenue'   : 0,   # 매출액(억원)
    'yoy'       : 1,   # YoY(%)
    'op_income' : 2,   # 영업이익(억원)
    'net_income': 3,   # 당기순이익(억원)
    'eps'       : 4,   # EPS(원)
    'bps'       : 5,   # BPS(원)
    'per'       : 6,   # PER(배)
    'pbr'       : 7,   # PBR(배)
    'roe'       : 8,   # ROE(%)
    'ev_ebitda' : 9,   # EV/EBITDA(배)
}

# ── 유틸 ───────────────────────────────────────────────────────────
def to_int(s):
    if s is None: return None
    s = re.sub(r'[^\d.-]', '', str(s))
    try: return int(float(s))
    except: return None

def to_float(s):
    if s is None: return None
    s = re.sub(r'[^\d.-]', '', str(s))
    try: return float(s)
    except: return None

def cell_val(tds, idx):
    """td 리스트에서 idx번째 값 반환. 범위 초과 시 None."""
    return tds[idx].get_text(strip=True).replace(',', '') if idx < len(tds) else None


# ── 핵심 파서 ──────────────────────────────────────────────────────
def parse_naver_page(html: str, code: str, stock_name: str) -> dict:
    soup = BeautifulSoup(html, 'html.parser')

    # ── 1. cTB511 테이블 (주가&컨센서스 연간 탭) ──────────────────
    # id=cTB511 또는 class='gHead01 all-width' 중 매출액 헤더 있는 것
    target_tbl = soup.find('table', id='cTB511')
    if not target_tbl:
        # fallback: gHead01 all-width 테이블 중 '매출액' 포함하는 것
        for tbl in soup.find_all('table', class_='gHead01'):
            if '매출액' in tbl.get_text():
                target_tbl = tbl
                break

    forecast_rows = []   # [(year_str, is_estimate, {col: value})]

    if target_tbl:
        tbody = target_tbl.find('tbody')
        rows  = (tbody or target_tbl).find_all('tr')

        for row in rows:
            # 행 헤더(th): 연도 + (A)/(E) 구분
            th = row.find('th')
            if not th:
                continue
            th_text = th.get_text(strip=True)   # 예: "2026.12(E)"
            yr_m = re.search(r'(20\d{2})', th_text)
            if not yr_m:
                continue

            year     = int(yr_m.group(1))
            is_est   = '(E)' in th_text or 'colorE' in ' '.join(th.get('class', []))

            tds = row.find_all('td')
            vals = {k: cell_val(tds, i) for k, i in COL.items()}

            forecast_rows.append({
                'year'      : year,
                'label'     : th_text,
                'is_estimate': is_est,
                'revenue'   : to_float(vals['revenue']),
                'op_income' : to_float(vals['op_income']),
                'net_income': to_float(vals['net_income']),
                'eps'       : to_int(vals['eps']),
                'bps'       : to_int(vals['bps']),
                'per'       : to_float(vals['per']),
                'pbr'       : to_float(vals['pbr']),
                'roe'       : to_float(vals['roe']),
                'ev_ebitda' : to_float(vals['ev_ebitda']),
            })

    # 추정치만 분리
    est_rows = [r for r in forecast_rows if r['is_estimate']]
    all_rows = forecast_rows  # 실적(A) + 추정(E) 전체

    years_all = [r['year']  for r in all_rows]
    is_est_all= [r['is_estimate'] for r in all_rows]

    def col_list(key): return [r.get(key) for r in all_rows]

    # ── 2. 컨센서스 요약 (gHead all-width — 목표가 평균, 기관수) ──
    target_price_avg = None
    analyst_count    = None
    consensus_eps    = None
    consensus_per    = None

    for tbl in soup.find_all('table', class_='gHead'):
        if 'all-width' not in tbl.get('class', []):
            continue
        rows_c = tbl.find_all('tr')
        if len(rows_c) < 2:
            continue
        hdrs = [c.get_text(strip=True) for c in rows_c[0].find_all(['th','td'])]
        vals = [c.get_text(strip=True).replace(',','') for c in rows_c[1].find_all(['th','td'])]
        idx  = {h: i for i, h in enumerate(hdrs)}
        if '목표주가(원)' in idx: target_price_avg = to_int(vals[idx['목표주가(원)']])
        if '추정기관수'   in idx: analyst_count    = to_int(vals[idx['추정기관수']])
        if 'EPS(원)'      in idx: consensus_eps    = to_int(vals[idx['EPS(원)']])
        if 'PER(배)'      in idx: consensus_per    = to_float(vals[idx['PER(배)']])
        break

    # ── 3. 증권사별 목표가 (gHead01 all-width — '제공처' 컬럼 있는 것) ──
    broker_targets = []
    for tbl in soup.find_all('table', class_='gHead01'):
        if 'all-width' not in tbl.get('class', []):
            continue
        rows_b = tbl.find_all('tr')
        if not rows_b:
            continue
        hdrs = [c.get_text(strip=True) for c in rows_b[0].find_all(['th','td'])]
        if '제공처' not in hdrs:
            continue
        for row in rows_b[1:]:
            cells = [c.get_text(strip=True).replace(',','') for c in row.find_all(['th','td'])]
            if len(cells) < 3:
                continue
            entry = dict(zip(hdrs, cells))
            tp = to_int(entry.get('목표가',''))
            if tp:
                broker_targets.append({
                    'broker'      : entry.get('제공처',''),
                    'date'        : entry.get('최종일자',''),
                    'target_price': tp,
                    'opinion'     : entry.get('투자의견',''),
                })
        break

    # 증권사 목표가 통계
    tps = [b['target_price'] for b in broker_targets if b['target_price']]
    target_stats = {}
    if tps:
        target_stats = {
            'avg'   : round(_stat.mean(tps)),
            'median': round(_stat.median(tps)),
            'min'   : min(tps),
            'max'   : max(tps),
            'stddev': round(_stat.stdev(tps)) if len(tps) >= 2 else None,
        }
        if not target_price_avg:
            target_price_avg = target_stats['avg']

    return {
        'stock_code'     : code,
        'stock_name'     : stock_name,
        'collected_at'   : datetime.now().strftime('%Y-%m-%d %H:%M'),
        # 전체 연도 (실적 A + 추정 E)
        'fiscal_years'   : years_all,
        'is_estimate'    : is_est_all,
        # 재무지표 시계열
        'revenue'        : col_list('revenue'),
        'op_income'      : col_list('op_income'),
        'net_income'     : col_list('net_income'),
        'eps'            : col_list('eps'),
        'bps'            : col_list('bps'),
        'per'            : col_list('per'),
        'pbr'            : col_list('pbr'),
        'roe'            : col_list('roe'),
        'ev_ebitda'      : col_list('ev_ebitda'),
        # 추정치만 별도 (편의용)
        'estimate_years' : [r['year'] for r in est_rows],
        'estimate_data'  : est_rows,
        # 컨센서스
        'analyst_count'  : analyst_count,
        'target_price'   : target_price_avg,
        'target_stats'   : target_stats,
        'broker_targets' : broker_targets,
        'consensus_eps'  : consensus_eps,
        'consensus_per'  : consensus_per,
    }


# ── 메인 ───────────────────────────────────────────────────────────
def main():
    print(f"{'='*60}")
    print(f"  FILMN9 네이버 컨센서스 스크래퍼 v3")
    print(f"  소스: finance.naver.com 주가&컨센서스 테이블 (cTB511)")
    print(f"  수집: 매출/영업이익/당기순이익/EPS/BPS/PER/PBR/ROE/EV")
    print(f"{'='*60}")

    if not HK_META_PATH.exists():
        print("❌ 한경 메타 없음. collect_hankyung.py 먼저 실행하세요.")
        return

    meta = json.loads(HK_META_PATH.read_text(encoding='utf-8'))
    target_codes = sorted(set(
        (r['stock_code'], r['stock_name']) for r in meta['reports']
    ), key=lambda x: x[0])

    print(f"  대상: {len(target_codes)}개 종목")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    # 쿠키 획득
    session.get('https://finance.naver.com', headers=HEADERS, verify=False, timeout=10)

    success, fail = 0, 0

    for i, (code, stock_name) in enumerate(target_codes, 1):
        out_path = OUT_DIR / f'{code}.json'

        # 이미 파싱 성공한 파일 skip
        if out_path.exists():
            existing = json.loads(out_path.read_text(encoding='utf-8'))
            if (existing.get('status') != 'fetch_failed'
                    and existing.get('fiscal_years')
                    and existing.get('revenue')
                    and any(v is not None for v in existing.get('revenue', []))):
                success += 1
                continue

        try:
            r = session.get(
                NAVER_URL.format(code=code),
                headers=HEADERS, timeout=TIMEOUT, verify=False
            )
            if r.status_code != 200 or len(r.text) < 1000:
                raise ValueError(f'HTTP {r.status_code}')
            r.encoding = 'euc-kr'
            record = parse_naver_page(r.text, code, stock_name)
            out_path.write_text(
                json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8'
            )
            success += 1

        except Exception as e:
            empty = {
                'stock_code': code, 'stock_name': stock_name,
                'collected_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
                'status': 'fetch_failed', 'error': str(e),
                'fiscal_years': [], 'is_estimate': [],
                'revenue': [], 'op_income': [], 'net_income': [],
                'eps': [], 'bps': [], 'per': [], 'pbr': [],
                'roe': [], 'ev_ebitda': [],
                'analyst_count': None, 'target_price': None,
                'broker_targets': [],
            }
            out_path.write_text(
                json.dumps(empty, ensure_ascii=False, indent=2), encoding='utf-8'
            )
            fail += 1

        time.sleep(DELAY_SEC)

        if i % 50 == 0:
            print(f"  진행: {i}/{len(target_codes)} (성공 {success}, 실패 {fail})")

    print(f"\n  완료: 성공 {success} / 실패 {fail}")

    # ── 품질 체크 ──
    rev_ok, per_ok, tp_ok = 0, 0, 0
    for p in OUT_DIR.glob('*.json'):
        d = json.loads(p.read_text(encoding='utf-8'))
        if d.get('revenue') and any(v is not None for v in d.get('revenue',[])):
            rev_ok += 1
        if d.get('per') and any(v is not None for v in d.get('per',[])):
            per_ok += 1
        if d.get('target_price'):
            tp_ok += 1

    total = success + fail
    print(f"\n  [파싱 품질]")
    print(f"    매출액 파싱:  {rev_ok}/{total} ({rev_ok*100//max(total,1)}%)")
    print(f"    PER 파싱:     {per_ok}/{total} ({per_ok*100//max(total,1)}%)")
    print(f"    목표가 파싱:  {tp_ok}/{total} ({tp_ok*100//max(total,1)}%)")

    # 샘플 출력 (매출 파싱 성공한 것 중 첫 번째)
    for sp in sorted(OUT_DIR.glob('*.json')):
        d = json.loads(sp.read_text(encoding='utf-8'))
        rev = d.get('revenue', [])
        if rev and any(v is not None for v in rev):
            yrs  = d.get('fiscal_years', [])
            est  = d.get('is_estimate',  [])
            print(f"\n  [샘플 - {d['stock_code']} {d['stock_name']}]")
            for j, (y, e, rv, op, ni, p, pb, roe) in enumerate(zip(
                yrs, est,
                d.get('revenue',    []),
                d.get('op_income',  []),
                d.get('net_income', []),
                d.get('per',        []),
                d.get('pbr',        []),
                d.get('roe',        []),
            )):
                tag = '(E)' if e else '(A)'
                print(f"    {y}{tag}  매출 {rv}  영업이익 {op}  순이익 {ni}  "
                      f"PER {p}  PBR {pb}  ROE {roe}")
            print(f"    목표가: {d.get('target_price')}  기관수: {d.get('analyst_count')}")
            break

    print(f"\n{'='*60}")
    print(f"  다음: build_valuation_input.py 실행")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
