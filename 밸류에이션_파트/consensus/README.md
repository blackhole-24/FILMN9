# FILMN9 데이터 수집 파이프라인

DCF 밸류에이션 입력값 자동 수집 시스템 (A2 방식)

## 실행 순서

```bash
python collect_hankyung.py        # 1단계
python collect_pdf_consensus.py   # 2단계
python build_valuation_input.py   # 3단계
```

## 파일 설명

### 수집
- `collect_hankyung.py` — 한경 컨센서스 메타 스크래핑. 적정가 분포(min/avg/max), 투자의견, 증권사별 리포트 수집. 약 1-2분, 634종목
- `collect_pdf_consensus.py` — 한경 리포트 PDF 다운로드 → pdfplumber 텍스트 추출 → GPT-4o-mini로 매출/영업이익/EPS 3년 추정치 정형화. 약 20-30분, OpenAI API 키 필요
- `build_valuation_input.py` — 한경(적정가) + PDF(추정치) 통합. `valuation_input/{code}.json` 생성. 데이터 품질 green/yellow/red 자동 분류

### 진단 (개발용)
- `debug_naver_structure.py` — wisereport 페이지 구조 확인용
- `debug_naver_v3.py` — 네이버/wisereport HTML 덤프 및 테이블 구조 분석
- `find_wise_ajax.py` — wisereport Ajax API 엔드포인트 탐색용
- `collect_naver_consensus.py` — 네이버 증권 스크래핑 시도 (wisereport 동적 로딩으로 매출 수집 불가, 미사용)

## 산출물

```
data/
├── hankyung/
│   ├── reports_metadata.json       # 전체 리포트 메타 (3,837건)
│   └── by_stock_code/{code}.json   # 종목별 적정가 분포
├── naver_consensus/
│   └── by_stock_code/{code}.json   # PDF 추출 추정치
└── valuation_input/
    └── by_stock_code/{code}.json   # A2 통합 최종 입력값 ← valuation.py에서 사용
```

## 품질 기준

| 등급 | 조건 | 현황 |
|------|------|------|
| 🟢 green | 한경 + PDF 추정치 모두 있음 | 569개 (90%) |
| 🟡 yellow | 한경만 or 추정치 일부 누락 | 65개 (10%) |
| 🔴 red | 데이터 없음 | 0개 |

## 환경

```bash
conda activate filmn9
pip install requests beautifulsoup4 pdfplumber openai
set OPENAI_API_KEY=sk-proj-...
```
```
