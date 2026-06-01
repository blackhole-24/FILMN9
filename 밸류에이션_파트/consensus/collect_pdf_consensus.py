"""
FILMN9 - 2단계 대안: 한경 PDF → OPENAI API 추정치 추출
========================================================
한경 reports_metadata.json에서 종목별 최신 PDF 1개 다운로드
→ pdfplumber 텍스트 추출
→ gpt-4o-mini 으로 재무 추정치 정형화
→ data/naver_consensus/by_stock_code/{code}.json 저장 (동일 스키마)

비용: haiku 기준 종목당 약 1-2원, 634개 = 약 1,000원
시간: 약 20-30분 (PDF 다운 + API 호출)

실행:
  pip install pdfplumber anthropic requests
  python 밸류에이션_파트/collect_pdf_consensus.py

주의:
  ANTHROPIC_API_KEY 환경변수 필요
  (없으면 스크립트 상단 API_KEY 직접 입력)
"""

import os, json, time, re, requests, urllib3
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import openai

urllib3.disable_warnings()

# ── 설정 ───────────────────────────────────────────────────────────
API_KEY = os.environ.get("OPENAI_API_KEY", "")  # .env 의 OPENAI_API_KEY 사용 (코드 하드코딩 금지)
HK_META_PATH = Path("C:/Users/Admin/FILMN9/data/hankyung/reports_metadata.json")
OUT_DIR      = Path("C:/Users/Admin/FILMN9/data/naver_consensus/by_stock_code")
PDF_CACHE    = Path("C:/Users/Admin/FILMN9/data/_pdf_cache")  # PDF 임시 저장
DELAY_SEC    = 0.5   # API 호출 간 딜레이
MAX_WORKERS  = 1     # 순차 처리 (rate limit 안전)

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

# ── gpt 프롬프트 ─────────────────────────────────────────────────
SYSTEM = """당신은 증권 애널리스트 리포트에서 재무 추정치를 추출하는 전문가입니다.
주어진 리포트 텍스트에서 미래 추정치(E) 데이터만 정확히 추출하여 JSON으로 반환하세요.
반드시 JSON만 반환하고 다른 텍스트는 절대 포함하지 마세요."""

def make_prompt(text: str, stock_name: str) -> str:
    return f"""다음은 '{stock_name}' 종목 애널리스트 리포트입니다.

아래 형식의 JSON을 반환하세요. 값이 없으면 null로 표기하세요.
단위: 매출액/영업이익/당기순이익은 억원, EPS/BPS는 원, PER/PBR/ROE는 배/%

{{
  "fiscal_years": [2025, 2026, 2027],
  "is_estimate": [true, true, true],
  "revenue": [null, null, null],
  "op_income": [null, null, null],
  "net_income": [null, null, null],
  "eps": [null, null, null],
  "bps": [null, null, null],
  "per": [null, null, null],
  "pbr": [null, null, null],
  "roe": [null, null, null],
  "target_price": null,
  "wacc": null,
  "terminal_growth_rate": null
}}

주의사항:
- 실적(A)은 제외, 추정치(E)만 포함
- 연도가 다르면 fiscal_years 배열 조정
- 매출액 단위가 백억/조원이면 억원으로 환산
- target_price는 적정주가(원)
- wacc는 % 숫자만 (예: 8.5)
- 리포트 텍스트 앞 3000자:

{text[:3000]}"""


# ── PDF 텍스트 추출 ─────────────────────────────────────────────────
def extract_pdf_text(pdf_bytes: bytes) -> str:
    try:
        import pdfplumber, io
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            texts = []
            for page in pdf.pages[:6]:  # 최대 6페이지 (리포트 앞부분에 추정치 테이블 있음)
                t = page.extract_text()
                if t:
                    texts.append(t)
            return "\n".join(texts)
    except Exception as e:
        return ""


# ── gpt API 호출 ─────────────────────────────────────────────────
def extract_with_gpt(client, text, stock_name):
    if not text.strip():
        return None
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=1000,
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user",   "content": make_prompt(text, stock_name)}
            ]
        )
        raw = resp.choices[0].message.content.strip()
        raw = re.sub(r'^```json\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)
        return json.loads(raw)
    except Exception as e:
        return None


# ── 메인 ───────────────────────────────────────────────────────────
def main():
    if not API_KEY:
        # main() 안의 if not API_KEY: 블록
        print("❌ OPENAI_API_KEY가 없습니다.")
        print("   set OPENAI_API_KEY=sk-proj-...")
        print("   또는 스크립트 상단 API_KEY에 직접 입력")
        return

    print(f"{'='*60}")
    print(f"  FILMN9 PDF → Gpt 추정치 추출 파이프라인")
    print(f"{'='*60}")

    meta = json.loads(HK_META_PATH.read_text(encoding='utf-8'))

    # 종목별 최신 리포트 1개씩 선택
    by_stock: dict[str, list] = defaultdict(list)
    for r in meta['reports']:
        if r.get('pdf_url'):
            by_stock[r['stock_code']].append(r)

    # 최신 날짜 기준 정렬
    latest = {}
    for code, reports in by_stock.items():
        latest[code] = sorted(reports, key=lambda x: x['date'], reverse=True)[0]

    print(f"  대상 종목: {len(latest)}개")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PDF_CACHE.mkdir(parents=True, exist_ok=True)

    client = openai.OpenAI(api_key=API_KEY)
    session = requests.Session()

    success, fail, skip = 0, 0, 0
    total_input_tokens  = 0
    total_output_tokens = 0

    for i, (code, report) in enumerate(sorted(latest.items()), 1):
        out_path = OUT_DIR / f"{code}.json"

        # 이미 성공한 파일 skip
        if out_path.exists():
            existing = json.loads(out_path.read_text(encoding='utf-8'))
            if (existing.get('status') != 'fetch_failed'
                    and existing.get('revenue')
                    and any(v is not None for v in existing.get('revenue', []))):
                skip += 1
                continue

        stock_name = report['stock_name']
        pdf_url    = report['pdf_url']

        # ── PDF 다운로드 (캐시 활용) ──
        cache_path = PDF_CACHE / f"{code}_{report.get('report_idx','')}.pdf"
        if cache_path.exists():
            pdf_bytes = cache_path.read_bytes()
        else:
            try:
                resp = session.get(pdf_url, headers=HEADERS, timeout=20, verify=False)
                if resp.status_code != 200 or not resp.content.startswith(b'%PDF'):
                    raise ValueError(f"PDF 다운 실패: {resp.status_code}")
                pdf_bytes = resp.content
                cache_path.write_bytes(pdf_bytes)
            except Exception as e:
                _save_fail(out_path, code, stock_name, str(e))
                fail += 1
                print(f"  ⚠ OpenAI 오류: {e}")  # 이 줄 추가
                continue

        # ── 텍스트 추출 ──
        text = extract_pdf_text(pdf_bytes)
        if not text:
            _save_fail(out_path, code, stock_name, "PDF 텍스트 추출 실패")
            fail += 1
            continue

        # ── gpt 추출 ──
        result = extract_with_gpt(client, text, stock_name)
        if not result:
            _save_fail(out_path, code, stock_name, "gpt 파싱 실패")
            fail += 1
            continue

        # 스키마 표준화
        record = {
            'stock_code'         : code,
            'stock_name'         : stock_name,
            'collected_at'       : datetime.now().strftime('%Y-%m-%d %H:%M'),
            'source'             : 'pdf_gpt',
            'source_report_date' : report['date'],
            'source_broker'      : report.get('broker', ''),
            'fiscal_years'       : result.get('fiscal_years', []),
            'is_estimate'        : result.get('is_estimate', []),
            'revenue'            : result.get('revenue', []),
            'op_income'          : result.get('op_income', []),
            'net_income'         : result.get('net_income', []),
            'eps'                : result.get('eps', []),
            'bps'                : result.get('bps', []),
            'per'                : result.get('per', []),
            'pbr'                : result.get('pbr', []),
            'roe'                : result.get('roe', []),
            'ev_ebitda'          : [],
            'analyst_count'      : 1,  # PDF 1개 기준
            'target_price'       : result.get('target_price'),
            'wacc'               : result.get('wacc'),
            'terminal_growth_rate': result.get('terminal_growth_rate'),
            'target_stats'       : {},
            'broker_targets'     : [],
        }
        out_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        success += 1

        time.sleep(DELAY_SEC)

        if i % 20 == 0:
            print(f"  진행: {i}/{len(latest)} | 성공 {success} 실패 {fail} 스킵 {skip}")

    # ── 품질 체크 ──
    rev_ok, tp_ok, wacc_ok = 0, 0, 0
    for p in OUT_DIR.glob('*.json'):
        d = json.loads(p.read_text(encoding='utf-8'))
        if d.get('revenue') and any(v is not None for v in d.get('revenue', [])): rev_ok += 1
        if d.get('target_price'): tp_ok += 1
        if d.get('wacc'): wacc_ok += 1

    total = success + fail
    print(f"\n  완료: 성공 {success} / 실패 {fail} / 스킵 {skip}")
    print(f"\n  [파싱 품질]")
    print(f"    매출 추정치: {rev_ok}/{total} ({rev_ok*100//max(total,1)}%)")
    print(f"    적정주가:   {tp_ok}/{total} ({tp_ok*100//max(total,1)}%)")
    print(f"    WACC:       {wacc_ok}/{total} ({wacc_ok*100//max(total,1)}%)")

    # 샘플
    for sp in sorted(OUT_DIR.glob('*.json')):
        d = json.loads(sp.read_text(encoding='utf-8'))
        if d.get('revenue') and any(v is not None for v in d.get('revenue', [])):
            print(f"\n  [샘플 - {d['stock_code']} {d['stock_name']}]")
            print(f"    연도:     {d.get('fiscal_years')}")
            print(f"    매출:     {d.get('revenue')}")
            print(f"    영업이익: {d.get('op_income')}")
            print(f"    EPS:      {d.get('eps')}")
            print(f"    적정주가: {d.get('target_price')}")
            print(f"    WACC:     {d.get('wacc')}")
            print(f"    출처:     {d.get('source_broker')} {d.get('source_report_date')}")
            break

    print(f"\n{'='*60}")
    print(f"  다음: build_valuation_input.py 실행")
    print(f"{'='*60}")


def _save_fail(path, code, name, err):
    path.write_text(json.dumps({
        'stock_code': code, 'stock_name': name,
        'collected_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'status': 'fetch_failed', 'error': err,
        'fiscal_years': [], 'is_estimate': [],
        'revenue': [], 'op_income': [], 'net_income': [],
        'eps': [], 'bps': [], 'per': [], 'pbr': [],
        'roe': [], 'ev_ebitda': [],
        'analyst_count': None, 'target_price': None,
        'wacc': None, 'terminal_growth_rate': None,
        'broker_targets': [],
    }, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
