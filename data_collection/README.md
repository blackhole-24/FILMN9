# DART 공시 → 임베딩용 JSONL 수집 파이프라인

DART OpenAPI 에서 한국 상장사 정기공시 (사업보고서·반기·분기) 를 받아,
**임베딩 모델에 바로 투입 가능한 JSONL 청크 파일** 까지 만드는 파이프라인.

> 본 파이프라인은 **DART → 임베딩 직전 JSON 변환 단계** 만 담당합니다.
> 임베딩 / 벡터DB / 분석 / WACC 계산 등 후속 단계는 별도 모듈.

```
[DART OpenAPI] ──► [원본 XML] ──► [정제 XML] ──► [표·문장 청킹] ──► [JSONL]
                                                                      ↑
                                                               임베딩 직전 산출물
```

---

## 📋 목차

1. [환경 셋업](#1-환경-셋업)
2. [DART API 키 발급 + 등록](#2-dart-api-키-발급--등록)
3. [⭐ 변경 포인트 — 회사 / 보고서 / 연도](#3-⭐-변경-포인트--회사--보고서--연도)
4. [실행](#4-실행)
5. [파이프라인 구조 (코드 중심)](#5-파이프라인-구조-코드-중심)
6. [JSONL 산출물 스키마](#6-jsonl-산출물-스키마)
7. [트러블슈팅](#7-트러블슈팅)

---

## 1. 환경 셋업

### 1-1. 가상환경 (Anaconda Prompt)

```bat
conda create -n dart-rag python=3.11 -y
conda activate dart-rag
cd C:\Users\Admin\Desktop\DART\data_collection
pip install -r requirements.txt
python -m ipykernel install --user --name dart-rag --display-name "Python (dart-rag)"
```

### 1-2. 검증

```bat
python -c "import lxml, requests, tqdm, pandas, nbformat; print('OK')"
```

---

## 2. DART API 키 발급 + 등록

### 2-1. 키 발급

1. https://opendart.fss.or.kr → 회원가입
2. `오픈API 인증키 신청 / 관리` → 신청
3. 발급된 키 복사 (40자)

일일 한도: **20,000건** (사업보고서 1 + 분기 1 = 2건/회사 → 50개사 ≈ 100건).

### 2-2. `.env` 작성

```bat
copy .env.example .env
notepad .env
```

```ini
DART_API_KEY=발급받은_키
```

> ⚠ `.env` **깃 커밋 금지** — `.gitignore` 에 등록.
> ⚠ 키를 슬랙·이메일 평문 공유 금지. 1Password 등 사용.

---

## 3. ⭐ 변경 포인트 — 회사 / 보고서 / 연도

팀원이 손대는 파일은 **2 개뿐**:

### 3-1. `companies.py` — 회사 추가/변경

```python
COMPANIES = [
    ("G1", "064350", "현대로템"),
    ("G1", "047810", "한국항공우주"),
    # ⭐ 여기에 한 줄씩 추가하면 끝
    # ("G3", "005930", "삼성전자"),
]
```

규칙:
- 한 줄 = `(그룹라벨, 종목코드 6자리, 한글 회사명)`
- 그룹라벨 자유 (`"G1"`, `"방산"`, `"Auto"` 등)
- 회사명은 DART 공시상 정확한 표기 (특수문자 주의)
- 종목코드 0 패딩 유지 (`"064350"` ✓, `"64350"` ✗)

검증:
```bat
python companies.py
```

### 3-2. `config.py` — 보고서 종류 / 연도

```python
# ① 회계연도 (한 줄로 모드 전환)
TARGET_FISCAL_YEAR = "2024"
#   "2024" → 2024 사업보고서 + 2025 분기보고서 (테스트)
#   "2025" → 2025 사업보고서 + 2026 분기보고서 (운영)

# ② 어떤 보고서 수집할지
REPORT_TYPES = [
    "annual",   # 사업보고서
    "Q1",       # 1분기보고서
    # "H1",     # ← 반기보고서 활성화하려면 주석 풀기
    # "Q3",     # ← 3분기보고서
]
```

| 변경 사항 | 파일 | 변수 |
|---|---|---|
| 회사 1개 추가/삭제 | `companies.py` | `COMPANIES` 한 줄 |
| 회사 그룹 분류 | `companies.py` | 첫 번째 컬럼 |
| 사업보고서·분기·반기 토글 | `config.py` | `REPORT_TYPES` |
| 회계연도 변경 | `config.py` | `TARGET_FISCAL_YEAR` |
| 출력 폴더 | `config.py` | `RAG_DIR` / `RAW_DIR` |

→ 다른 파일 (`pipeline.py`, `dart_downloader.py` 등) 은 자동 인식.

---

## 4. 실행

### 4-1. CLI

```bat
conda activate dart-rag
cd C:\Users\Admin\Desktop\DART\data_collection

:: 전체 회사
python pipeline.py

:: 특정 그룹만
python pipeline.py --group G1

:: 첫 5개사만 (테스트)
python pipeline.py --limit 5

:: 이미 만들어진 JSONL 도 덮어쓰기
python pipeline.py --no-skip
```

⚠ **재실행 안전**: 이미 있는 JSONL 자동 스킵 → 중간에 멈춰도 이어서 진행 가능.

### 4-2. 노트북 (단계별 디버깅)

VS Code → `pipeline.ipynb` → 셀 1부터 Shift+Enter

### 4-3. 산출물

```
C:\Users\Admin\Desktop\DART\
├── RAG\                                                        ← config.py 의 RAG_DIR
│   ├── 064350_현대로템_2024_annual_chunks.jsonl                ⭐ 임베딩용
│   ├── 064350_현대로템_2025_Q1_chunks.jsonl
│   └── ...
└── raw\                                                        ← RAW_DIR
    └── 064350_현대로템\
        ├── 2024-annual_raw.xml                                 (DART 원본)
        ├── 2024-annual_cleaned.xml                             (정제본)
        ├── 2025-Q1_raw.xml
        └── 2025-Q1_cleaned.xml
```

진행 로그:
```
data_collection/outputs/
├── progress_YYYYMMDD_HHMMSS.csv      (회사별 처리 결과)
└── failed.json                        (실패 케이스)
```

---

## 5. 파이프라인 구조 (코드 중심)

```
[ pipeline.py: main() ]   ← 진입점
        │
        │  config.TARGET_FISCAL_YEAR / REPORT_TYPES 로드
        │  companies.COMPANIES 로드
        ▼
┌───────────────────────────────────────────────────────────────────────┐
│ Step 1. corp_code 매핑                                                 │
│   dart_downloader.get_corp_map()                                      │
│     · DART corpCode.xml ZIP 다운로드 (1회만)                            │
│     · 종목코드 ↔ corp_code 캐시 → raw/_corp_map.json                   │
└───────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────────────────┐
│ Step 2. 회사별 보고서 조회                                              │
│   dart_downloader.fetch_reports(corp_code)                            │
│     · DART list.json (BGN_DE / END_DE)                                │
│     · pblntf_ty=A (정기공시) 필터                                        │
│     · REPORT_TYPES 의 각 종류별 rcept_no 매칭                           │
│       (annual="2024.12", Q1="2025.03", H1="2025.06", Q3="2025.09")    │
└───────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────────────────┐
│ Step 3. 원본 XML 다운로드                                               │
│   dart_downloader.download_document(rcept_no)                         │
│     · document.xml ZIP → 본문 XML                                      │
│     · 저장: raw/{stock_code}_{name}/{report_kind}_raw.xml             │
└───────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────────────────┐
│ Step 4. XML 정제 (★ 핵심)                                              │
│   xml_cleaner.clean_xml(text)                                         │
│     · 진짜 XML 태그 외 모든 < 를 &lt; 로 escape                          │
│     · 잘못된 & 를 &amp; 로 보정                                         │
│   xml_cleaner.parse_with_fallback(cleaned)                            │
│     · strict 파서 → 실패 시 lxml recover 모드 자동 폴백                 │
└───────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────────────────┐
│ Step 5. 표·문장 인식 청킹 (★ 핵심)                                      │
│   chunker.build_chunks(root, meta)                                    │
│     · TH/TD/TE 셀 → 마크다운 표                                          │
│     · 표 직전 짧은 P → 캡션으로 결합                                     │
│     · "(단위: 백만원)" 행은 prefix 로 항상 동행                           │
│     · 분할 시 매 조각에 캡션·단위·헤더 재삽입                             │
│     · 단일 셀에 본문이 들어간 "레이아웃 표" → 텍스트로 변환                │
│     · 한국어 문장 경계(다/요/음/.) splitter (안전망)                     │
└───────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────────────────┐
│ Step 6. JSONL 저장                                                     │
│   pipeline.process_one_report() 마지막 블록                            │
│     · 청크 1개 = 임베딩 1건 = JSONL 1줄                                  │
│     · 파일명: {stock_code}_{name}_{year}_{type}_chunks.jsonl            │
│     · 재실행 안전: 이미 존재하면 자동 스킵                                │
└───────────────────────────────────────────────────────────────────────┘
        │
        ▼
   [ RAG/*_chunks.jsonl ]   ← 임베딩 직전 산출물
```

### 모듈 요약

| 파일 | 역할 |
|---|---|
| `companies.py` | ⭐ **회사 리스트** (팀원 수정 포인트) |
| `config.py` | ⭐ **연도·보고서·경로·옵션** (팀원 수정 포인트) |
| `dart_downloader.py` | DART API 호출 (corp_code, list, document) + .env 로드 |
| `xml_cleaner.py` | XML 정제 v3 + parse_with_fallback |
| `chunker.py` | 표·문장 인식 청킹 |
| `pipeline.py` | CLI 진입점 |
| `pipeline.ipynb` | 노트북 진입점 (단계별 디버깅) |

---

## 6. JSONL 산출물 스키마

청크 1개 = JSONL 한 줄 = 임베딩 1건:

```json
{
  "id": "064350-2024-annual-00050",
  "group": "G1",
  "stock_code": "064350",
  "corp_code": "00164900",
  "corp_name": "현대로템",
  "report_nm": "사업보고서 (2024.12)",
  "report_kind": "2024-annual",
  "report_type": "annual",
  "rcept_no": "20250310001234",
  "rcept_dt": "20250310",
  "fiscal_period": "2024-annual",
  "source_url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250310001234",
  "parse_mode": "strict",
  "kind": "table",
  "section_path": ["III. 재무에 관한 사항", "2. 연결재무제표"],
  "section_path_str": "III. 재무에 관한 사항 > 2. 연결재무제표",
  "char_len": 1240,
  "text": "[표] 연결재무상태표\n(단위: 백만원)\n| 구분 | 제27기 | 제26기 | ..."
}
```

임베딩 시 권장 입력:
```python
input_text = f"[{rec['corp_name']}·{rec['report_kind']}]\n[{rec['section_path_str']}]\n\n{rec['text']}"
```

---

## 7. 트러블슈팅

| 현상 | 원인 | 해결 |
|---|---|---|
| `DART_API_KEY 미설정` | `.env` 파일 위치/형식 | `data_collection/.env` 확인 후 VS Code 재시작 |
| `010: 등록되지 않은 키` | 키 오타 / 미발급 | DART 사이트 재발급 |
| `013: 조회된 데이터 없음` | 평가일 범위 외 / 미공시 | `TARGET_FISCAL_YEAR` 확인 또는 회사 일정 점검 |
| `020: 요청 제한 초과` | 일일 한도 (20,000건) | 다음날 재시도 |
| 매핑 실패 (corpCode.xml) | 종목코드 오타 / 비상장 | `companies.py` 종목코드 재확인 |
| 한글 깨짐 (Windows CMD) | 코드페이지 | `chcp 65001` 또는 PowerShell 사용 |
| JSONL 청크 0건 | 정제·파싱 실패 | `outputs/failed.json` 확인 + raw XML 직접 점검 |

---

## 📞 문의

- 코드 이슈: `git issue`
- 회사 추가/변경: `companies.py` PR
- 보고서 종류 변경: `config.py` PR
