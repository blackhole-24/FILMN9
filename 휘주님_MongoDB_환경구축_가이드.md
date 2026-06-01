# 🍃 휘주님 환경에서 MongoDB Atlas 연결 + 로컬 적재 가이드

> **작성자**: FILMN9 팀
> **작성일**: 2026-05-26
> **대상**: 휘주님 (또는 동일 환경 구축이 필요한 팀원)
> **목적**: 제 컴퓨터에서 작동하는 MongoDB Atlas 연결 + 2,526개 히스토리 적재 환경을 휘주님 PC에서 그대로 재현

---

## 📋 목차

1. [현재 상황 정리](#-1-현재-상황-정리)
2. [전체 폴더 구조 (관련 파일만)](#-2-전체-폴더-구조-관련-파일만)
3. [환경 구축 4단계](#-3-환경-구축-4단계)
4. [TLS 에러 해결 옵션](#-4-tls-에러-해결-옵션)
5. [briefs_final.zip 적재 실행](#-5-briefs_finalzip-적재-실행)
6. [검증 명령어](#-6-검증-명령어)
7. [장애 대응 — 폴백 모드](#-7-장애-대응--폴백-모드)

---

## 🎯 1. 현재 상황 정리

### 휘주님 환경 이슈
- **TCP 27017 도달**: ✅ 가능
- **TLS Handshake**: ❌ `TLSV1_ALERT_INTERNAL_ERROR` (서버측 거부)
- **시도**: WiFi · 핸드폰 핫스팟 모두 동일 증상
- **추정 원인**: Atlas Network Access의 `0.0.0.0/0` 만료 또는 클러스터 일시 정지

### 데이터
- **파일**: `briefs_final.zip` — 2,526개 JSON
- **파일명 패턴**: `{stock_code}_{corp_name}.json` (예: `090430_아모레퍼시픽.json`)
- **스키마**: `stock_code`, `corp_name`, `brief`, `_llm_model`, `_generated_at`, `meta`, `usage`, `warnings`

### 목표
1. 휘주님 PC에서 Atlas 연결 복구
2. 2,526개 JSON을 `filmn9.histories` 컬렉션에 적재
3. 연결 안 되면 로컬 파일 폴백 모드로 운영

---

## 📁 2. 전체 폴더 구조 (관련 파일만)

```
C:\Users\<휘주님>\FILMN9\          ← 동일하게 구축
├── .env                              ⭐ MongoDB URI 등 환경변수
├── requirements.txt                  ⭐ pymongo 등 의존성
├── start.bat                         원클릭 기동
│
├── api/
│   ├── main.py                       FastAPI 엔트리
│   └── routers/
│       └── overview.py               ⭐ MongoDB → 파일 폴백 로직
│
├── data/
│   ├── filmn9.db                     SQLite (별도 적재)
│   └── parsed_history/               ⭐⭐ briefs_final 압축 해제 위치
│       ├── 090430_아모레퍼시픽.json
│       ├── 009150_삼성전기.json
│       └── ... (2,526개)
│
└── db/
    ├── load_history_to_mongo.py      ⭐⭐⭐ Mongo 적재 핵심 스크립트
    └── test_mongo.py                 연결 테스트
```

### 핵심 파일 4개만 기억

| # | 파일 | 역할 |
|:-:|------|------|
| 1 | `.env` | MongoDB URI 보관 |
| 2 | `db/load_history_to_mongo.py` | JSON → Atlas 적재 |
| 3 | `data/parsed_history/` | briefs_final 풀어둘 폴더 |
| 4 | `api/routers/overview.py` | 폴백 로직 (Mongo 실패 시 파일) |

---

## 🛠️ 3. 환경 구축 4단계

### Step 1. Python 의존성 설치

```bash
cd C:\Users\<휘주님>\FILMN9
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

`requirements.txt`에 다음이 포함되어 있어야 합니다:
```
pymongo>=4.6
fastapi
uvicorn
python-dotenv
```

### Step 2. `.env` 파일 생성

루트 폴더에 `.env` 파일을 만들고 아래 내용 입력:

```env
# ─── MongoDB Atlas ───
MONGO_URI=mongodb+srv://<USERNAME>:<PASSWORD>@<CLUSTER>.mongodb.net/?retryWrites=true&w=majority&appName=filmn9
MONGO_DB=filmn9
MONGO_COLLECTION=histories

# ─── DART (옵션) ───
DART_API_KEY=<발급받은_DART_키>

# ─── OpenAI (옵션) ───
OPENAI_API_KEY=<API_키>
```

> ⚠️ `<USERNAME>`, `<PASSWORD>`, `<CLUSTER>` 부분은 Atlas 대시보드에서 복사해서 채워넣으세요.
> 🔒 `.env` 파일은 절대 Git 커밋하지 마세요 (`.gitignore`에 등록됨).

### Step 3. Atlas Network Access 화이트리스트 확인

1. https://cloud.mongodb.com 접속 → 로그인
2. 좌측 메뉴 **Network Access** 클릭
3. **IP Access List** 확인
   - `0.0.0.0/0` (모든 IP 허용)이 **Active** 상태인지 확인
   - `Inactive` 또는 `Expired`면 → **Edit** → **No time limit** 설정
4. 또는 휘주님 현재 공인 IP만 추가:
   - 본인 IP 확인: https://www.whatismyip.com/
   - **+ ADD IP ADDRESS** → **ADD CURRENT IP ADDRESS** 클릭

### Step 4. 연결 테스트

```bash
python db/test_mongo.py
```

**성공 시 출력**:
```
[OK] MongoDB 연결 성공
[OK] filmn9.histories 컬렉션 접근 가능
[OK] 현재 문서 수: N건
```

**실패 시**: 아래 "[TLS 에러 해결 옵션]"으로 이동.

---

## 🔐 4. TLS 에러 해결 옵션

`TLSV1_ALERT_INTERNAL_ERROR` 발생 시 시도 순서:

### 옵션 A: Atlas 클러스터 재개

1. Atlas 대시보드 → **Database** 메뉴
2. 클러스터 상태 확인 — **PAUSED** 이면 **RESUME** 클릭
3. 5분 정도 후 재시도

### 옵션 B: Python 드라이버 업그레이드

```bash
pip install --upgrade pymongo certifi
```

`pymongo` 4.6+ 권장. 구버전은 일부 TLS 1.3 환경에서 실패합니다.

### 옵션 C: 연결 문자열에 TLS 옵션 추가

`.env`의 `MONGO_URI` 끝에 다음 옵션 추가:
```
&tls=true&tlsAllowInvalidCertificates=false&directConnection=false
```

### 옵션 D: 방화벽·백신 일시 해제

회사망 또는 백신(Avast·Norton 등)의 SSL 검사 기능이 TLS handshake를 방해할 수 있습니다.

- Windows Defender → "SSL 검사" 일시 비활성화
- 백신 프로그램 → "암호화된 연결 검사" 끄기

### 옵션 E: SRV 대신 표준 연결 사용

`mongodb+srv://` 대신 `mongodb://` 표준 형식으로 변경:
```env
MONGO_URI=mongodb://<USER>:<PASS>@cluster0-shard-00-00.xxxx.mongodb.net:27017,cluster0-shard-00-01.xxxx.mongodb.net:27017,cluster0-shard-00-02.xxxx.mongodb.net:27017/?ssl=true&replicaSet=atlas-xxxxx-shard-0&authSource=admin&retryWrites=true&w=majority
```

Atlas 대시보드 **Connect** → **Drivers** → **Connection String Only** 에서 복사 가능.

---

## 📦 5. briefs_final.zip 적재 실행

### Step 1. zip 압축 해제

```bash
# 압축 풀 위치
cd C:\Users\<휘주님>\FILMN9\data\parsed_history

# briefs_final.zip을 위 폴더에 옮긴 뒤
# (윈도우 탐색기에서 우클릭 → 압축풀기 OK)
```

해제 후 폴더에 `*.json` 파일 2,526개가 보여야 합니다.

### Step 2. 적재 실행 (DRY-RUN 먼저)

```bash
cd C:\Users\<휘주님>\FILMN9
python db/load_history_to_mongo.py --dry-run
```

**시뮬레이션 출력 예시**:
```
======================================================================
  load_history_to_mongo.py (DRY-RUN)
  파일 수: 2526
  소스   : C:\Users\...\data\parsed_history
  타겟   : MongoDB Atlas filmn9.histories
======================================================================
  [  1/2526] [PREVIEW] 090430  아모레퍼시픽         meta=True brief=True
  [  2/2526] [PREVIEW] 009150  삼성전기            meta=True brief=True
  ...
```

### Step 3. 실제 업로드

```bash
python db/load_history_to_mongo.py
```

성공 시 컬렉션에 2,526개 문서가 upsert 됩니다.

> 💡 **upsert 모드**: 같은 `stock_code`가 이미 있으면 덮어쓰기, 없으면 신규 추가. 중복 걱정 없이 재실행 가능.

---

## ✅ 6. 검증 명령어

### 적재 완료 확인

```bash
# 전체 종목 목록
python db/load_history_to_mongo.py --list

# 특정 종목 조회
python db/load_history_to_mongo.py --find 090430

# 출력 예시:
# [090430] 아모레퍼시픽
# 생성시각  : 2025-12-15 14:23
# LLM 모델  : gpt-5-mini
# meta      : 일반법인 / 화장품
# brief 키  : ['company_overview', 'business_model', 'risks', ...]
```

### Atlas 대시보드에서 확인

1. https://cloud.mongodb.com → **Browse Collections**
2. **filmn9 → histories** 클릭
3. 문서 2,526건 확인

---

## 🆘 7. 장애 대응 — 폴백 모드 (Atlas 끝까지 연결 불가 시)

좋은 소식: **저희 백엔드는 Atlas 실패 시 자동으로 로컬 JSON 파일을 사용합니다.**

### 작동 원리

`api/routers/overview.py`에 다음 로직이 들어있습니다:

```python
def _get_history(stock_code):
    # 1순위: MongoDB
    col = _get_mongo_collection()
    if col is not None:
        result = col.find_one({"stock_code": stock_code})
        if result: return result
    # 2순위: 로컬 파일 폴백
    return _get_history_from_file(stock_code)
```

### 폴백 모드 활성화 방법

`data/parsed_history/` 폴더에 JSON 2,526개가 그대로 있으면 — **이미 폴백 모드 작동 중**입니다.

따라서:
- ✅ Atlas 적재 성공 → MongoDB 사용
- ✅ Atlas 적재 실패 → 로컬 파일 사용 (서비스 동작에 문제 없음!)

### 폴백 모드 검증

```bash
# 백엔드 실행
python -m uvicorn backend.main:app --port 8000 --reload

# 별도 터미널에서 API 호출
curl http://localhost:8000/api/overview/090430

# 응답에 "_source": "file" 이 보이면 폴백 모드, "mongo" 면 Atlas 모드
```

---

## 📞 휘주님 → FILMN9 팀 보고용 체크리스트

휘주님 환경에서 시도 후 결과를 알려주세요:

- [ ] `python db/test_mongo.py` → 성공 / 실패 (에러 메시지)
- [ ] Atlas 콘솔 Network Access 0.0.0.0/0 상태 (Active/Inactive)
- [ ] 클러스터 상태 (Running/Paused)
- [ ] pymongo 버전 (`pip show pymongo`)
- [ ] 옵션 A~E 중 어떤 것을 시도했고 결과는?
- [ ] briefs_final 압축 해제 위치 (`data/parsed_history/`)
- [ ] 폴백 모드로 백엔드 정상 응답 여부

---

## 🎁 부록 — 자주 묻는 질문

**Q1. .env 파일이 안 보입니다.**
A. 윈도우 탐색기에서 "숨김 파일 표시" 활성화. VS Code에서는 그대로 보입니다.

**Q2. MONGO_URI에 비밀번호에 특수문자(@, /, : 등)가 있어요.**
A. URL 인코딩 필요. 예: `@` → `%40`, `/` → `%2F`. https://www.urlencoder.org 사용.

**Q3. 적재 도중 끊겼는데 처음부터 다시 해야 하나요?**
A. 아니요. upsert 모드라 그대로 재실행하면 됩니다 (이미 적재된 건 덮어쓰기).

**Q4. 142개 + 2,526개 중복 안 되나요?**
A. 같은 `stock_code`면 새 데이터로 덮어쓰기. 다른 `stock_code`면 추가. 따라서 최종 약 2,526개로 수렴.

**Q5. SQLite도 동기화해야 하나요?**
A. 아니요. MongoDB는 사업보고서 LLM 브리핑 전용. SQLite는 별도 데이터(주가·재무 등)라 독립적으로 관리됩니다.

---

© FILMN9 · KPMG AI Lab · 2026-05-26
연락 필요시: 프로젝트 팀 슬랙
