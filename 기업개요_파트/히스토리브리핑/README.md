# FILMN9 자동화 파이프라인

> KOSPI/KOSDAQ 전 종목 사업보고서 → LLM 브리핑 생성 → MongoDB 적재까지 일괄 자동화

**연 1회 실행** (매년 4월 1일 새벽 02:00 자동) — 받는 사람은 이 폴더만 있으면 됨.

---

## 📋 목차

- [빠른 시작](#-빠른-시작)
- [파이프라인 흐름](#-파이프라인-흐름)
- [폴더 구조](#-폴더-구조)
- [환경 설정](#-환경-설정)
- [사용법](#-사용법)
- [트러블슈팅](#-트러블슈팅)
- [비용 예상](#-비용-예상)
- [관련 문서](#-관련-문서)

---

## 🚀 빠른 시작

```bash
# 1) 의존성 설치
pip install -r automation/requirements.txt

# 2) 환경변수 설정
copy automation\.env.example automation\.env
# .env 파일 열어서 API 키 채우기

# 3) 시뮬레이션 (안전, 비용 0)
cd automation
python run_annual_pipeline.py --dry-run

# 4) 실제 실행 (전체)
python run_annual_pipeline.py
```

자동 실행 등록은 → [docs/scheduler_setup.md](docs/scheduler_setup.md)

---

## 🔄 파이프라인 흐름

```
                              매년 4월 1일 02:00
                                     ↓
        ┌────────────────────────────────────────────────────┐
        │ STEP 1  종목 목록 갱신 (KRX + 네이버 WICS)         │
        │         python -m code.update_companies            │
        ├────────────────────────────────────────────────────┤
        │ STEP 2  DART 사업보고서 수집 → JSONL              │
        │         python -m code.collect_dart                │
        ├────────────────────────────────────────────────────┤
        │ STEP 3  브리핑 생성 1pass (gpt-5-mini)            │
        │         python -m code.generate_briefs --pass 1    │
        ├────────────────────────────────────────────────────┤
        │ STEP 4  품질 평가 1pass (4-Phase)                 │
        │         python -m code.evaluate --pass 1           │
        ├────────────────────────────────────────────────────┤
        │ STEP 5  저점수 재생성 2pass (gpt-5.4-mini)        │
        │         python -m code.generate_briefs --pass 2    │
        ├────────────────────────────────────────────────────┤
        │ STEP 6  품질 평가 2pass                            │
        │         python -m code.evaluate --pass 2           │
        ├────────────────────────────────────────────────────┤
        │ STEP 7  best-of-two 통합 → data/briefs/           │
        │         python -m code.merge_best                  │
        ├────────────────────────────────────────────────────┤
        │ STEP 8  MongoDB Atlas 적재                         │
        │         python -m code.load_mongo                  │
        └────────────────────────────────────────────────────┘
                                     ↓
                          서비스가 자동 반영 (API → 화면)
```

소요 시간: 약 3-5시간 (PC 켜둔 채로 자동 진행).

---

## 📂 폴더 구조

```
automation/
├── README.md                       # 본 문서
├── requirements.txt                # 의존성
├── .env / .env.example             # 환경변수 (시크릿, gitignore)
├── .gitignore
├── run_annual_pipeline.py          # 메인 오케스트레이터
├── run_pipeline.bat                # Windows 배치 (스케줄러용)
│
├── code/                           # 모든 로직
│   ├── config.py                   # 통합 설정 + 환경변수 로드
│   ├── storage.py                  # 저장 추상화 (local + 향후 S3)
│   ├── update_companies.py         # ① 종목 갱신
│   ├── collect_dart.py             # ② DART 수집
│   ├── generate_briefs.py          # ③⑤ 브리핑 생성
│   ├── evaluate.py                 # ④⑥ 품질 평가
│   ├── merge_best.py               # ⑦ best-of-two
│   ├── load_mongo.py               # ⑧ MongoDB 적재
│   ├── wics_seed.json              # 초기 WICS 매핑 (84 KB)
│   └── helpers/
│       ├── extraction.py           # 사업보고서 텍스트 추출
│       ├── llm_client.py           # OpenAI 호출 + 비용 추적
│       ├── chunker.py              # JSONL 청킹
│       ├── dart_downloader.py      # DART API
│       └── xml_cleaner.py          # XML 정제
│
├── prompts/                        # LLM 프롬프트
│   ├── system_prompt.txt
│   └── user_prompt_template.txt
│
├── docs/                           # 문서
│   ├── scheduler_setup.md          # Windows 스케줄러 등록
│   ├── troubleshooting.md          # 자주 만나는 에러
│   └── roadmap.md                  # 향후 계획 (S3, 운영 이전 등)
│
├── data/                           # 데이터 (gitignore, 자동 생성)
│   ├── companies.json              # KRX 종목 + WICS
│   ├── wics_cache.json             # WICS 캐시
│   ├── rag/                        # JSONL 청크
│   ├── raw/                        # 원본 XML
│   ├── briefs_1pass/               # 1pass 브리핑
│   ├── briefs_2pass/               # 2pass 브리핑 (저점수)
│   ├── eval_1pass/                 # 1pass 평가
│   ├── eval_2pass/                 # 2pass 평가
│   └── briefs/                     # 최종 best-of-two
│
└── logs/                           # 실행 로그 (gitignore)
```

---

## ⚙️ 환경 설정

### 1. 의존성 설치

```bash
pip install -r requirements.txt
```

핵심 라이브러리:
- `finance-datareader` (KRX 종목)
- `requests`, `beautifulsoup4` (네이버 WICS)
- `openai` (LLM)
- `pymongo`, `certifi` (MongoDB)
- `lxml` (XML 파싱)

### 2. `.env` 파일

```bash
copy .env.example .env
```

`.env`를 열어서 다음 키들 채우기:

```env
# API 키
OPENAI_API_KEY=sk-...
DART_API_KEY=...
MONGO_URI=mongodb+srv://...

# 저장 모드 (기본 local)
STORAGE_MODE=local

# LLM 모델
LLM_MODEL_1PASS=gpt-5-mini
LLM_MODEL_2PASS=gpt-5.4-mini

# 저점수 기준 (이 점수 미만 → 2pass 재생성)
LOW_SCORE_THRESHOLD=70

# 처리 후 자동 정리 (JSONL/XML 삭제, 브리핑은 보존)
AUTO_CLEANUP=false
```

### 3. 설정 검증

```bash
python -m code.config
```

`[OK] 모든 필수 항목 정상` 나오면 OK.

---

## 🎯 사용법

### A. 전체 자동 실행

```bash
cd automation
python run_annual_pipeline.py                  # 전체, strict 모드
python run_annual_pipeline.py --continue-on-error   # 일부 실패해도 계속
python run_annual_pipeline.py --dry-run        # 시뮬레이션 (비용 0)
```

옵션:
- `--skip-steps 1,2` — 특정 단계 건너뛰기
- `--only-steps 3` — 특정 단계만
- `--continue-on-error` — 에러 시 다음 단계 진행
- `--dry-run` — 실제 실행 X

### B. 단계별 수동 실행

```bash
# 1) 종목 갱신
python -m code.update_companies
python -m code.update_companies --refresh-wics   # 전체 WICS 재크롤링

# 2) DART 수집
python -m code.collect_dart
python -m code.collect_dart --limit 5            # 처음 5개만 (테스트)
python -m code.collect_dart --no-skip            # 기존 JSONL 덮어쓰기

# 3) 브리핑 생성 1pass
python -m code.generate_briefs --pass 1
python -m code.generate_briefs --pass 1 --limit 5

# 4) 평가 1pass
python -m code.evaluate --pass 1

# 5) 재생성 2pass (저점수만)
python -m code.generate_briefs --pass 2

# 6) 평가 2pass
python -m code.evaluate --pass 2

# 7) best-of-two
python -m code.merge_best

# 8) MongoDB 적재
python -m code.load_mongo --dry-run              # 시뮬레이션
python -m code.load_mongo                        # 실제 적재
python -m code.load_mongo --find 005930          # 특정 종목 조회
python -m code.load_mongo --list                 # 전체 목록
```

### C. 자동 실행 등록 (Windows 작업 스케줄러)

[docs/scheduler_setup.md](docs/scheduler_setup.md) 참조 — GUI 방식 + PowerShell 방식 모두 안내.

---

## 🐛 트러블슈팅

자주 만나는 에러는 [docs/troubleshooting.md](docs/troubleshooting.md) 참조.

대표적 이슈:
| 증상 | 원인 | 해결 |
|------|------|------|
| `MONGO_URI` SSL handshake fail | Atlas IP whitelist | Atlas 콘솔에서 0.0.0.0/0 허용 |
| `OPENAI_API_KEY` 미설정 | .env 누락 | `.env.example` 복사 후 채움 |
| `'#'은(는) 내부 명령 아님` | 주석을 그대로 실행 | 주석(# ...) 제외하고 명령만 입력 |
| Windows 인코딩 깨짐 | cp949 | `chcp 65001` 실행 후 재시도 |

---

## 💰 비용 예상

연간 1회 실행 기준:

| 항목 | 비용 |
|------|------|
| KRX 종목 조회 (finance-datareader) | $0 |
| DART API (사업보고서) | $0 |
| 네이버 WICS 크롤링 | $0 |
| 1pass 브리핑 (gpt-5-mini, ~2,500 종목) | ~$12 |
| 2pass 재생성 (gpt-5.4-mini, ~700 종목) | ~$7 |
| 4-Phase 평가 (1pass + 2pass) | ~$5-10 |
| MongoDB Atlas (M0 무료티어) | $0 |
| **합계** | **~$25-30/년** |

테스트 (3종목): ~$0.05

---

## 📚 관련 문서

- [scheduler_setup.md](docs/scheduler_setup.md) — Windows 작업 스케줄러 등록 가이드
- [troubleshooting.md](docs/troubleshooting.md) — 자주 만나는 에러 + 해결
- [roadmap.md](docs/roadmap.md) — 향후 계획 (S3 통합, 운영 이전 등)

---

## 🤝 운영 책임 분담

| 작업 | 담당 |
|------|------|
| 자동화 코드 (이 폴더) | 본인 |
| MongoDB Atlas 운영 | 팀원 (재무정보 파트) |
| FastAPI 백엔드 | 팀원 |
| 화면 표시 | 팀원 |

자동화는 본인 PC에서 매년 1회 실행 → MongoDB 업로드 → 서비스 자동 반영.
