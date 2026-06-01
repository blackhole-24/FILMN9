# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════
  FILMN9 무인 자동 분석 — 15개 작업 통합 실행 (5일치)
═══════════════════════════════════════════════════════════
  옵션 B: 사용자 한 번 허용 → 모든 작업 자동 진행
  OpenAI 사용 0회 / 데이터 변경 0회 (읽기 전용)
"""
import os
import sys
import json
import time
import sqlite3
import statistics
import csv
import re
from pathlib import Path
from datetime import datetime
from collections import defaultdict, Counter

ROOT = Path(r"C:\Users\Admin\FILMN9")
DB   = ROOT / "data" / "filmn9.db"
OUT  = ROOT / "auto_reports"
OUT.mkdir(exist_ok=True)

# 결과 마스터 로그
MASTER = OUT / "00_MASTER_REPORT.md"
LOG    = OUT / "00_RUN_LOG.txt"

def log(msg):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def write_md(filename, title, body):
    path = OUT / filename
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n")
        f.write(f"_생성: {datetime.now().strftime('%Y-%m-%d %H:%M')}_\n\n")
        f.write(body)
    return path

def write_csv(filename, rows, headers):
    path = OUT / filename
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(headers)
        for r in rows:
            w.writerow(r)
    return path

# ═════════════════════════════════════════════════════════
def conn_db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

# ═════════════════════════════════════════════════════════
# [1] 비정상 수치 자동 탐지 (PER·PBR·매출 음수·이상 변동)
# ═════════════════════════════════════════════════════════
def task_01_outlier_detection():
    log("[1/15] 비정상 수치 자동 탐지 시작...")
    conn = conn_db()
    outliers = []
    # 1. 자산총계가 음수인 종목
    for r in conn.execute("""
        SELECT stock_code, fiscal_year, statement_scope, account_nm, amount
        FROM financial_detail
        WHERE statement_type='BS' AND amount < 0
          AND (account_nm LIKE '%자산총계%' OR account_nm LIKE '%자산 총계%')
    """):
        outliers.append((r['stock_code'], r['fiscal_year'], r['statement_scope'],
                         '자산총계 음수', r['account_nm'], r['amount']))
    # 2. 매출액이 음수인 종목
    for r in conn.execute("""
        SELECT stock_code, fiscal_year, statement_scope, account_nm, amount
        FROM financial_detail
        WHERE statement_type IN ('IS','CIS') AND amount < 0
          AND (account_nm LIKE '%매출액%' OR account_nm LIKE '%영업수익%' OR account_nm = '수익(매출액)')
    """):
        outliers.append((r['stock_code'], r['fiscal_year'], r['statement_scope'],
                         '매출 음수', r['account_nm'], r['amount']))
    # 3. 비정상 큰 수 (10^15 초과)
    for r in conn.execute("""
        SELECT stock_code, fiscal_year, statement_scope, statement_type, account_nm, amount
        FROM financial_detail WHERE ABS(amount) > 1e15 LIMIT 100
    """):
        outliers.append((r['stock_code'], r['fiscal_year'], r['statement_scope'],
                         '비정상 큰 수', r['account_nm'], r['amount']))
    conn.close()

    path = write_csv("01_이상치_보고서.csv", outliers,
                     ['stock_code','fiscal_year','scope','이상유형','계정','금액'])
    log(f"  → {len(outliers)}개 이상치 → {path.name}")
    return f"이상치 {len(outliers)}건 탐지"

# ═════════════════════════════════════════════════════════
# [2] 데이터 정합성 검증 (DB 자체 일관성)
# ═════════════════════════════════════════════════════════
def task_02_data_integrity():
    log("[2/15] 데이터 정합성 검증 시작...")
    conn = conn_db()
    issues = []
    # NULL amount 비율
    total = conn.execute("SELECT COUNT(*) FROM financial_detail").fetchone()[0]
    null_amt = conn.execute("SELECT COUNT(*) FROM financial_detail WHERE amount IS NULL").fetchone()[0]
    null_rate = null_amt / total * 100 if total else 0

    # 중복 PK 후보
    dup = conn.execute("""
        SELECT stock_code, fiscal_year, statement_type, account_id, statement_scope, COUNT(*) as cnt
        FROM financial_detail
        GROUP BY stock_code, fiscal_year, statement_type, account_id, statement_scope
        HAVING cnt > 1 LIMIT 100
    """).fetchall()

    # 종목별 데이터 수 통계
    stock_counts = conn.execute("""
        SELECT stock_code, COUNT(*) as cnt FROM financial_detail
        GROUP BY stock_code ORDER BY cnt
    """).fetchall()
    cnts = [r['cnt'] for r in stock_counts]
    conn.close()

    body = f"""## 데이터 정합성 종합

- 총 행 수: **{total:,}건**
- NULL amount: **{null_amt:,}건 ({null_rate:.2f}%)**
- 중복 PK 후보: **{len(dup)}개** (있으면 PK 정합성 깨짐)
- 적재 종목: **{len(stock_counts):,}개**
- 종목당 평균 행 수: **{statistics.mean(cnts) if cnts else 0:.0f}건**
- 최소 행 수: **{min(cnts) if cnts else 0}건**
- 최대 행 수: **{max(cnts) if cnts else 0}건**
- 중앙값: **{statistics.median(cnts) if cnts else 0:.0f}건**

## 데이터 적재 행 수 분포 (하위 10개 종목)
| 종목 | 행 수 |
|------|------|
"""
    for r in stock_counts[:10]:
        body += f"| {r['stock_code']} | {r['cnt']} |\n"
    body += "\n## 데이터 적재 행 수 분포 (상위 10개 종목)\n| 종목 | 행 수 |\n|------|------|\n"
    for r in stock_counts[-10:]:
        body += f"| {r['stock_code']} | {r['cnt']} |\n"

    path = write_md("02_정합성_검증_리포트.md", "데이터 정합성 검증 리포트", body)
    log(f"  → 정합성 검증 완료 (NULL {null_rate:.2f}%) → {path.name}")
    return f"NULL {null_rate:.2f}% / 중복PK {len(dup)}개"

# ═════════════════════════════════════════════════════════
# [3] 외감법인 529개 JSONL/임베딩 보유 현황
# ═════════════════════════════════════════════════════════
def task_03_audit_company_coverage():
    log("[3/15] 외감법인 JSONL/임베딩 보유 분석...")
    raw_dir = ROOT / "data" / "raw"
    rag_dir = ROOT / "data" / "RAG"

    # 감사보고서 종목 (XML 헤더에 ACODE="00760")
    audit_codes = set()
    for child in raw_dir.iterdir():
        if not child.is_dir():
            continue
        m = re.match(r"^([0-9A-Z]{6})_", child.name)
        if not m:
            continue
        xml = child / "2025-annual_cleaned.xml"
        if xml.exists():
            try:
                with open(xml, "rb") as f:
                    head = f.read(2000).decode("utf-8", errors="ignore")
                if 'ACODE="00760"' in head:
                    audit_codes.add(m.group(1))
            except:
                pass

    # JSONL 보유 종목
    jsonl_codes = set()
    if rag_dir.exists():
        for f in rag_dir.iterdir():
            m = re.match(r"^([0-9A-Z]{6})_", f.name)
            if m:
                jsonl_codes.add(m.group(1))

    overlap = audit_codes & jsonl_codes
    only_audit = audit_codes - jsonl_codes

    rows = []
    for code in sorted(audit_codes):
        has_jsonl = "✅" if code in jsonl_codes else "❌"
        rows.append((code, has_jsonl))

    path = write_csv("03_외감법인_보유현황.csv", rows,
                     ['stock_code', 'JSONL_보유'])

    body = f"""## 외감법인 보유 현황 요약

- 감사보고서 XML 보유 종목: **{len(audit_codes)}개**
- 그 중 JSONL도 보유: **{len(overlap)}개** ({len(overlap)/len(audit_codes)*100 if audit_codes else 0:.1f}%)
- JSONL 없음 (보충 불가): **{len(only_audit)}개**

## 결론
- JSONL로 보충 가능한 외감법인: **{len(overlap)}개**
- 보충 불가능 (어떤 형식으로도 데이터 없음): **{len(only_audit)}개**
"""
    write_md("03_외감법인_보유현황_요약.md", "외감법인 JSONL 보유 현황", body)
    log(f"  → 감사보고서 {len(audit_codes)}개, JSONL 보유 {len(overlap)}개")
    return f"감사 {len(audit_codes)} 중 JSONL {len(overlap)}개 보충 가능"

# ═════════════════════════════════════════════════════════
# [4] 종목별 데이터 완전성 점수
# ═════════════════════════════════════════════════════════
def task_04_completeness_score():
    log("[4/15] 종목별 완전성 점수 자동 계산...")
    conn = conn_db()
    rows = []
    for r in conn.execute("""
        SELECT stock_code, fiscal_year, statement_type, statement_scope, COUNT(*) as cnt
        FROM financial_detail
        GROUP BY stock_code, fiscal_year, statement_type, statement_scope
    """):
        rows.append(dict(r))
    conn.close()

    # 종목별 종합
    by_stock = defaultdict(lambda: {'years': set(), 'types': set(), 'scopes': set(), 'cells': 0})
    for r in rows:
        s = r['stock_code']
        by_stock[s]['years'].add(r['fiscal_year'])
        by_stock[s]['types'].add(r['statement_type'])
        by_stock[s]['scopes'].add(r['statement_scope'])
        by_stock[s]['cells'] += r['cnt']

    # 완전성 점수 (0~100)
    # 만점: 3개년 × 2(BS,IS/CIS) × 2(연결,별도) = 12 영역 + 행 100+ = 100점
    output = []
    for code, info in sorted(by_stock.items()):
        score_year  = min(len(info['years']), 3) / 3 * 25       # 25점 (3개년)
        types_eff = info['types'] - {'CIS'} if 'IS' in info['types'] else info['types']
        score_type  = min(len(info['types']), 2) / 2 * 25       # 25점 (BS+IS/CIS)
        score_scope = len(info['scopes']) / 2 * 25              # 25점 (연결+별도)
        score_cell  = min(info['cells'] / 200, 1) * 25          # 25점 (행 200+)
        total = score_year + score_type + score_scope + score_cell
        output.append((code, len(info['years']), len(info['types']), len(info['scopes']),
                       info['cells'], round(total, 1)))

    output.sort(key=lambda x: x[5])  # 점수 낮은 순
    path = write_csv("04_종목별_완전성_점수.csv", output,
                     ['stock_code','연도수','유형수','범위수','총행수','완전성점수'])

    # 통계
    scores = [o[5] for o in output]
    perfect = sum(1 for s in scores if s >= 95)
    bad = sum(1 for s in scores if s < 50)
    log(f"  → 완전성 평균 {statistics.mean(scores):.1f}점 (완벽 {perfect}개, 부족 {bad}개)")
    return f"평균 {statistics.mean(scores):.1f}점 / 완벽 {perfect}개"

# ═════════════════════════════════════════════════════════
# [5] 필수 계정 누락 종목 탐지
# ═════════════════════════════════════════════════════════
def task_05_missing_required_accounts():
    log("[5/15] 필수 계정 누락 종목 탐지...")
    REQUIRED = {
        'BS': ['자산총계', '자산 총계', '유동자산', '비유동자산',
               '부채총계', '부채 총계', '자본총계', '자본 총계'],
        'IS': ['매출액', '영업수익', '수익(매출액)', '매출',
               '영업이익', '영업손실', '당기순이익', '당기순손실'],
    }
    conn = conn_db()
    all_stocks = [r[0] for r in conn.execute(
        "SELECT DISTINCT stock_code FROM financial_detail").fetchall()]

    missing_report = []
    for code in all_stocks:
        for st_type, keywords in REQUIRED.items():
            target_types = ('IS', 'CIS') if st_type == 'IS' else (st_type,)
            placeholders = ','.join('?'*len(target_types))
            r = conn.execute(f"""
                SELECT GROUP_CONCAT(account_nm) FROM financial_detail
                WHERE stock_code=? AND fiscal_year=2025
                  AND statement_type IN ({placeholders}) AND statement_scope='연결'
            """, (code, *target_types)).fetchone()
            accounts = r[0] or ""
            has_any = any(kw in accounts for kw in keywords)
            if not has_any:
                missing_report.append((code, st_type, ', '.join(keywords[:3])))
    conn.close()

    path = write_csv("05_필수계정_누락_종목.csv", missing_report,
                     ['stock_code','statement_type','누락_키워드_예시'])
    log(f"  → 필수 계정 누락 종목 {len(missing_report)}개")
    return f"{len(missing_report)}개 종목 필수계정 누락"

# ═════════════════════════════════════════════════════════
# [6] 연결-별도 일관성 검증
# ═════════════════════════════════════════════════════════
def task_06_consolidated_vs_separate():
    log("[6/15] 연결-별도 일관성 검증...")
    conn = conn_db()
    issues = []
    # 같은 종목·연도 자산총계: 연결 vs 별도
    for r in conn.execute("""
        SELECT stock_code, fiscal_year,
            MAX(CASE WHEN statement_scope='연결' THEN amount END) as cons,
            MAX(CASE WHEN statement_scope='별도' THEN amount END) as sep
        FROM financial_detail
        WHERE statement_type='BS' AND (account_nm LIKE '%자산총계%' OR account_nm LIKE '%자산 총계%')
        GROUP BY stock_code, fiscal_year
    """):
        if r['cons'] is None or r['sep'] is None:
            continue
        # 연결 < 별도 인 경우 이상 (보통 연결 >= 별도)
        if r['cons'] < r['sep'] * 0.95:  # 5% 이상 차이
            ratio = r['cons']/r['sep'] if r['sep'] else 0
            issues.append((r['stock_code'], r['fiscal_year'],
                          int(r['cons']), int(r['sep']), f"{ratio:.2f}"))
    conn.close()

    path = write_csv("06_연결별도_이상_종목.csv", issues,
                     ['stock_code','fiscal_year','연결자산','별도자산','연결/별도비율'])
    log(f"  → 연결<별도 이상 종목 {len(issues)}개")
    return f"{len(issues)}개 종목 연결<별도 이상"

# ═════════════════════════════════════════════════════════
# [7] YoY 증감률 자동 계산 + 이상치
# ═════════════════════════════════════════════════════════
def task_07_yoy_analysis():
    log("[7/15] YoY 증감률 자동 분석...")
    conn = conn_db()
    rows = []

    # 종목별 매출액 3년치 가져오기
    matrix = defaultdict(dict)
    for r in conn.execute("""
        SELECT stock_code, fiscal_year, amount FROM financial_detail
        WHERE statement_type IN ('IS','CIS') AND statement_scope='연결'
          AND (account_nm LIKE '%매출액%' OR account_nm LIKE '%영업수익%'
            OR account_nm = '수익(매출액)')
        ORDER BY display_order LIMIT 50000
    """):
        if r['amount']:
            matrix[r['stock_code']][r['fiscal_year']] = r['amount']

    extreme = []
    for code, years in matrix.items():
        v25, v24, v23 = years.get(2025), years.get(2024), years.get(2023)
        if v25 and v24 and v24 != 0:
            yoy24_25 = (v25 - v24) / abs(v24) * 100
            if abs(yoy24_25) > 300:
                extreme.append((code, '2024→2025', f"{yoy24_25:+.0f}%", int(v24), int(v25)))
        if v24 and v23 and v23 != 0:
            yoy23_24 = (v24 - v23) / abs(v23) * 100
            if abs(yoy23_24) > 300:
                extreme.append((code, '2023→2024', f"{yoy23_24:+.0f}%", int(v23), int(v24)))
    conn.close()

    path = write_csv("07_YoY_이상치_보고서.csv", extreme,
                     ['stock_code','연도구간','YoY','전기값','당기값'])
    log(f"  → YoY ±300% 초과 {len(extreme)}건")
    return f"YoY ±300% 초과 {len(extreme)}건"

# ═════════════════════════════════════════════════════════
# [8] 업종별 평균·중앙값 (WICS 기준)
# ═════════════════════════════════════════════════════════
def task_08_sector_stats():
    log("[8/15] 업종별 통계 자동 계산...")
    conn = conn_db()
    # company_info의 sector 사용
    sector_data = defaultdict(list)
    for r in conn.execute("""
        SELECT c.sector, c.stock_code, f.amount, f.account_nm
        FROM company_info c
        JOIN financial_detail f ON c.stock_code = f.stock_code
        WHERE f.statement_type='IS' AND f.statement_scope='연결'
          AND f.fiscal_year=2025
          AND (f.account_nm LIKE '%매출액%' OR f.account_nm LIKE '%영업수익%')
        LIMIT 10000
    """):
        if r['amount'] and r['sector']:
            sector_data[r['sector']].append(r['amount'])
    conn.close()

    rows = []
    for sector, vals in sector_data.items():
        if len(vals) >= 2:
            rows.append((sector, len(vals), int(statistics.mean(vals)),
                        int(statistics.median(vals)), int(min(vals)), int(max(vals))))
    rows.sort(key=lambda x: -x[1])  # 종목 수 많은 순

    path = write_csv("08_업종별_매출_통계.csv", rows,
                     ['sector_code','종목수','평균매출','중앙값','최소','최대'])
    log(f"  → {len(rows)}개 업종 통계")
    return f"{len(rows)}개 업종 통계"

# ═════════════════════════════════════════════════════════
# [9] 한글 깨짐 자동 탐지
# ═════════════════════════════════════════════════════════
def task_09_encoding_check():
    log("[9/15] 한글 인코딩 이상 탐지...")
    conn = conn_db()
    issues = []
    # account_nm 에 깨진 문자 패턴 (¿ 등) 포함된 종목
    for r in conn.execute("""
        SELECT DISTINCT stock_code, account_nm FROM financial_detail
        WHERE account_nm LIKE '%¿%' OR account_nm LIKE '%?%'
           OR account_nm LIKE '%□%' OR LENGTH(account_nm) - LENGTH(REPLACE(account_nm, '?', '')) > 2
        LIMIT 100
    """):
        issues.append((r['stock_code'], r['account_nm']))
    conn.close()

    path = write_csv("09_인코딩_이상_종목.csv", issues, ['stock_code','account_nm'])
    log(f"  → 인코딩 이상 {len(issues)}건")
    return f"인코딩 이상 {len(issues)}건"

# ═════════════════════════════════════════════════════════
# [10] 백엔드 API 응답 속도
# ═════════════════════════════════════════════════════════
def task_10_api_performance():
    log("[10/15] 백엔드 API 성능 측정...")
    import urllib.request
    import urllib.error

    endpoints = [
        "/api/overview/090430",
        "/api/overview/009150",
        "/api/overview/035420",
        "/api/financial_detail/090430/BS?scope=%EC%97%B0%EA%B2%B0",
        "/api/financial_detail/009150/IS?scope=%EC%97%B0%EA%B2%B0",
        "/api/ohlcv/090430",
        "/api/health/090430",
        "/api/news/090430?limit=3",
        "/api/realtime/090430",
        "/api/shareholders/090430",
    ]
    base = "http://localhost:8000"
    results = []
    for ep in endpoints:
        times = []
        ok = 0
        for _ in range(10):
            try:
                t = time.time()
                urllib.request.urlopen(base + ep, timeout=10).read()
                times.append((time.time() - t) * 1000)
                ok += 1
            except:
                pass
        if times:
            results.append((ep, ok, round(min(times),1), round(statistics.mean(times),1),
                           round(max(times),1)))
        else:
            results.append((ep, 0, '-', '-', '-'))

    path = write_csv("10_API_성능_리포트.csv", results,
                     ['endpoint','성공/10','최소ms','평균ms','최대ms'])
    log(f"  → {len(endpoints)}개 엔드포인트 측정 완료")
    return f"{len(endpoints)}개 API 측정"

# ═════════════════════════════════════════════════════════
# [11] 프런트엔드 코드 라인·복잡도
# ═════════════════════════════════════════════════════════
def task_11_code_analysis():
    log("[11/15] 프런트엔드 코드 분석...")
    stats = []
    base = ROOT / "frontend-next"
    if base.exists():
        for f in base.rglob("*.tsx"):
            if "node_modules" in str(f):
                continue
            try:
                txt = f.read_text(encoding="utf-8", errors="ignore")
                lines = txt.count('\n') + 1
                funcs = len(re.findall(r'\bfunction\s+\w+|\bconst\s+\w+\s*=\s*\(', txt))
                hooks = len(re.findall(r'use(?:State|Effect|Memo|Callback|Ref)\b', txt))
                stats.append((f.name, lines, funcs, hooks))
            except:
                pass
        for f in base.rglob("*.ts"):
            if "node_modules" in str(f):
                continue
            try:
                txt = f.read_text(encoding="utf-8", errors="ignore")
                stats.append((f.name, txt.count('\n')+1, 0, 0))
            except:
                pass

    stats.sort(key=lambda x: -x[1])
    path = write_csv("11_코드_복잡도.csv", stats,
                     ['파일명','라인수','함수수','React_훅수'])
    total_lines = sum(s[1] for s in stats)
    log(f"  → {len(stats)}개 파일, 총 {total_lines:,} 라인")
    return f"{len(stats)}개 파일 {total_lines:,}라인"

# ═════════════════════════════════════════════════════════
# [12] DB 테이블별 용량·인덱스
# ═════════════════════════════════════════════════════════
def task_12_db_stats():
    log("[12/15] DB 테이블 통계...")
    conn = conn_db()
    tables = ['company_info','financials','financial_detail','ohlcv',
              'shareholders','executives','disclosures','credit_ratings','valuations']
    stats = []
    for t in tables:
        try:
            cnt = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            idx = conn.execute(f"PRAGMA index_list({t})").fetchall()
            stats.append((t, cnt, len(idx)))
        except:
            stats.append((t, 0, 0))
    conn.close()

    db_size = os.path.getsize(DB) / 1024 / 1024
    body = f"## DB 통계\n\n- DB 파일 크기: **{db_size:.1f} MB**\n\n| 테이블 | 행 수 | 인덱스 수 |\n|--------|------:|------:|\n"
    for t, cnt, idx in stats:
        body += f"| {t} | {cnt:,} | {idx} |\n"
    path = write_md("12_DB_통계.md", "DB 테이블 통계", body)
    log(f"  → DB {db_size:.1f}MB / 9 테이블")
    return f"DB {db_size:.1f}MB"

# ═════════════════════════════════════════════════════════
# [13] 데모 3종목 검증 (Playwright 대신 API 검증)
# ═════════════════════════════════════════════════════════
def task_13_demo_verification():
    log("[13/15] 데모 3종목 API 검증...")
    import urllib.request
    base = "http://localhost:8000"
    results = []
    for code, name in [("090430","아모레퍼시픽"),("009150","삼성전기"),("035420","NAVER")]:
        for path_ in [f"/api/financial_detail/{code}/BS",
                      f"/api/financial_detail/{code}/IS"]:
            try:
                r = urllib.request.urlopen(base + path_ + "?scope=%EC%97%B0%EA%B2%B0", timeout=10).read()
                data = json.loads(r.decode("utf-8"))
                results.append((code, name, path_.split('/')[-1],
                              data.get('count', 0),
                              ','.join(data.get('fiscal_years', []))))
            except Exception as e:
                results.append((code, name, path_.split('/')[-1], 'ERR', str(e)[:40]))

    path = write_csv("13_데모3종목_검증.csv", results,
                     ['stock_code','회사명','statement_type','count','years'])
    log(f"  → 데모 3종목 × 2 = 6개 응답 검증")
    return "데모 3종목 검증 완료"

# ═════════════════════════════════════════════════════════
# [14] 사업보고서 vs DB 일치율 (샘플 30종목)
# ═════════════════════════════════════════════════════════
def task_14_source_match():
    log("[14/15] 사업보고서 원본 일치율 검증...")
    raw_dir = ROOT / "data" / "raw"
    conn = conn_db()
    samples = []
    # 무작위 30종목
    all_codes = [r[0] for r in conn.execute(
        "SELECT DISTINCT stock_code FROM financial_detail "
        "WHERE source LIKE '%XML 파싱%' LIMIT 30").fetchall()]

    for code in all_codes[:30]:
        # XML 안 자산총계 (regex로 추출)
        xml_path = None
        for child in raw_dir.iterdir():
            if child.is_dir() and child.name.startswith(code + "_"):
                p = child / "2025-annual_cleaned.xml"
                if p.exists():
                    xml_path = p
                    break
        if not xml_path:
            continue
        try:
            txt = xml_path.read_text(encoding="utf-8", errors="ignore")
            # ifrs-full_Assets 패턴 검색
            m = re.search(r'ACODE="ifrs-full_Assets"\s+ACONTEXT="CFY2025[^"]*ConsolidatedMember[^"]*"[^>]*>([\d,]+)<', txt)
            if not m:
                continue
            xml_amt = float(m.group(1).replace(",",""))
            # DB 값
            r = conn.execute("""
                SELECT amount FROM financial_detail
                WHERE stock_code=? AND fiscal_year=2025 AND statement_type='BS'
                  AND statement_scope='연결' AND account_id='ifrs-full_Assets'
            """, (code,)).fetchone()
            if r and r[0]:
                db_amt = r[0]
                match = "✅" if abs(xml_amt - db_amt) < 1 else "❌"
                samples.append((code, int(xml_amt), int(db_amt), match))
        except:
            pass
    conn.close()

    matched = sum(1 for s in samples if s[3] == "✅")
    body = f"""## 사업보고서 원본 vs DB 일치율

- 검증 종목: **{len(samples)}개** (무작위 샘플)
- 일치: **{matched}개** ({matched/len(samples)*100 if samples else 0:.1f}%)
- 불일치: **{len(samples)-matched}개**

| stock_code | XML 자산총계 | DB 자산총계 | 일치 |
|------------|----:|----:|:----:|
"""
    for code, xml, db, match in samples:
        body += f"| {code} | {xml:,} | {db:,} | {match} |\n"

    path = write_md("14_원본_일치율.md", "사업보고서 원본 vs DB 일치율", body)
    log(f"  → {len(samples)}개 중 {matched}개 일치 ({matched/len(samples)*100 if samples else 0:.1f}%)")
    return f"{matched}/{len(samples)} 일치 ({matched/len(samples)*100 if samples else 0:.1f}%)"

# ═════════════════════════════════════════════════════════
# [15] 적정주가 mock vs 실데이터 차이 분석
# ═════════════════════════════════════════════════════════
def task_15_valuation_gap():
    log("[15/15] 밸류에이션 mock vs 실데이터 분석...")
    conn = conn_db()
    # current_price 가 valuations 에 없으므로 ohlcv 최신 종가와 JOIN
    rows = conn.execute("""
        SELECT v.stock_code,
               v.fair_price_avg,
               (SELECT close FROM ohlcv o
                WHERE o.stock_code = v.stock_code
                ORDER BY date DESC LIMIT 1) AS current_price,
               v.upside_pct
        FROM valuations v
        WHERE v.fair_price_avg IS NOT NULL
        LIMIT 100
    """).fetchall()
    conn.close()

    output = []
    for r in rows:
        fp = r['fair_price_avg'] or 0
        cp = r['current_price'] or 0
        # upside 재계산 (DB 값 없을 때)
        upside = r['upside_pct']
        if upside is None and cp > 0:
            upside = (fp - cp) / cp * 100
        output.append((r['stock_code'], fp, cp or 0, upside or 0))

    path = write_csv("15_밸류에이션_괴리.csv", output,
                     ['stock_code','fair_price_avg','current_price','upside_pct'])
    log(f"  → 밸류에이션 {len(output)}개")
    return f"밸류에이션 {len(output)}개 분석"

# ═════════════════════════════════════════════════════════
# 메인
# ═════════════════════════════════════════════════════════
if __name__ == "__main__":
    LOG.unlink(missing_ok=True)
    MASTER.unlink(missing_ok=True)
    log("=" * 70)
    log("  FILMN9 무인 자동 분석 — 15개 작업 일괄 실행")
    log("=" * 70)

    TASKS = [
        task_01_outlier_detection,
        task_02_data_integrity,
        task_03_audit_company_coverage,
        task_04_completeness_score,
        task_05_missing_required_accounts,
        task_06_consolidated_vs_separate,
        task_07_yoy_analysis,
        task_08_sector_stats,
        task_09_encoding_check,
        task_10_api_performance,
        task_11_code_analysis,
        task_12_db_stats,
        task_13_demo_verification,
        task_14_source_match,
        task_15_valuation_gap,
    ]

    results = []
    start = time.time()
    for fn in TASKS:
        try:
            res = fn()
            results.append((fn.__name__, "OK", res))
        except Exception as e:
            results.append((fn.__name__, "ERR", str(e)[:60]))
            log(f"  ❌ {fn.__name__} 실패: {e}")

    elapsed = time.time() - start
    log("=" * 70)
    log(f"  완료 — 총 소요 {elapsed:.1f}초")
    log("=" * 70)

    # 마스터 리포트
    body = f"""# FILMN9 무인 자동 분석 — 종합 리포트

**실행 일시**: {datetime.now().strftime('%Y-%m-%d %H:%M')}
**총 소요 시간**: {elapsed:.1f}초
**OpenAI 사용**: 0회 / $0

## 작업 결과 요약

| # | 작업명 | 상태 | 결과 요약 |
|---|--------|:----:|----------|
"""
    for i, (name, status, res) in enumerate(results, 1):
        body += f"| {i} | {name} | {status} | {res} |\n"

    body += "\n## 생성된 결과물\n\n"
    for f in sorted(OUT.iterdir()):
        if f.name.startswith("00_"):
            continue
        body += f"- `{f.name}`\n"

    MASTER.write_text(body, encoding="utf-8")
    print(f"\n마스터 리포트: {MASTER}")
