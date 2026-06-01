# 트러블슈팅 가이드

> 자동화 파이프라인 실행 중 자주 만나는 에러 + 해결책

---

## 🔑 환경변수 / API 키 관련

### `[FAIL] OPENAI_API_KEY 미설정`
**원인**: `.env` 파일에 키가 없거나 잘못 들어감

**해결**:
1. `automation/.env` 파일 존재 확인
2. 형식 확인:
   ```env
   OPENAI_API_KEY=sk-proj-...
   ```
   - 따옴표 없이
   - = 양옆 공백 없이

### `[FAIL] DART_API_KEY 미설정`
**원인**: DART API 키 누락

**해결**:
1. OpenDART (https://opendart.fss.or.kr) 가입 + 키 발급
2. `.env`에 추가:
   ```env
   DART_API_KEY=...
   ```

### `[FAIL] MONGO_URI 미설정`
**해결**: `.env`에 추가
```env
MONGO_URI=mongodb+srv://<user>:<password>@<cluster>.mongodb.net/
```

---

## 🌐 네트워크 / 연결 관련

### MongoDB `SSL handshake failed: TLSV1_ALERT_INTERNAL_ERROR`
**원인**: Atlas 클러스터의 IP 화이트리스트에서 현재 IP가 거부됨

**해결**:
1. https://cloud.mongodb.com 접속
2. 좌측 메뉴 **Network Access**
3. **IP Access List** 확인 — `0.0.0.0/0` Active 상태?
4. 아니면 **+ ADD IP ADDRESS** → **ADD CURRENT IP** 추가

### DART API `400 Bad Request` 또는 `013: 조회된 데이터 없음`
**원인**: 검색 기간 / 회사코드 문제

**해결**:
1. `code/config.py`의 `TARGET_FISCAL_YEAR` 확인 (현재 연도 - 1)
2. 사업보고서 공시 후 (3월 말~4월 초) 실행하는지 확인

### `ModuleNotFoundError: No module named 'finance_datareader'`
**해결**: 패키지명 주의 (소문자 + 하이픈)
```bash
pip install finance-datareader
```

---

## 🖥️ Windows 환경 관련

### 한글 깨짐 (`?�일이 ?�습?�다`)
**원인**: cp949 인코딩

**해결**:
```bash
chcp 65001
```
실행 후 다시 시도. 또는 PowerShell 사용.

### `'#'은(는) 내부 또는 외부 명령...`
**원인**: 주석을 명령어로 실행하려 함

**해결**: 주석(`# ...`) 제외하고 명령어만 입력
```bash
# 잘못된 입력 (주석 포함)
# 1. 종목 갱신
python -m code.update_companies

# 올바른 입력
python -m code.update_companies
```

### `mklink` 권한 거부
**원인**: 일반 권한으로는 symlink 불가

**해결**: cmd를 **관리자 권한으로 실행** 후 재시도

---

## 🤖 LLM 호출 관련

### `[ERROR] JSON 파싱 실패`
**원인**: LLM 응답이 JSON 형식이 아님

**해결**: 거의 자동 재시도로 해결됨. 빈번하면:
1. `code/helpers/llm_client.py` 의 모델 확인
2. 프롬프트(`automation/prompts/`) 수정

### `RateLimitError` 또는 `429 Too Many Requests`
**원인**: OpenAI API rate limit 초과

**해결**:
1. 잠시 대기 (보통 1분)
2. `tier_RATE_LIMIT_SLEEP` 늘리기 (`code/config.py`)
3. 또는 처리 종목 수 줄이기 (`--limit 50`)

### 비용이 예상보다 큼
**확인**: 매 단계 끝나면 누적 비용 출력됨
```
누적 100개  /  input 500,000 + output 30,000 tokens  /  $0.18
```

비정상적으로 크면:
1. `--limit` 옵션으로 테스트 후 본 실행
2. `--dry-run` 으로 시뮬레이션 먼저

---

## 📂 파일 / 경로 관련

### `[FAIL] 회사 리스트 파일 없음`
**해결**: 종목 갱신 먼저
```bash
python -m code.update_companies
```

### `[FAIL] 브리핑 파일 없음`
**해결**: 브리핑 생성 먼저
```bash
python -m code.generate_briefs --pass 1
```

### `처리 대상 0개`
**원인 1**: 이미 처리됨 (기본 skip 동작)

**해결**:
```bash
python -m code.generate_briefs --pass 1 --no-skip
```

**원인 2**: JSONL 파일 없음
```bash
python -m code.collect_dart
```

---

## ⏱️ 실행 시간 / 진행 관련

### 자동 실행이 4월 1일 02:00에 안 됨
**확인 항목**:
1. PC가 켜져있어야 함 (전원 / 절전 X)
2. 작업 스케줄러 설정 — "예약된 시간에 작업을 시작할 수 없는 경우 빨리 시작" 체크
3. 작업 스케줄러 GUI에서 마지막 실행 결과 확인

### 파이프라인 도중 멈춤
**해결**:
1. `logs/run_YYYYMMDD_HHMMSS.log` 확인 → 마지막 단계 파악
2. `--only-steps N`으로 중단된 단계부터 재개
   ```bash
   python run_annual_pipeline.py --only-steps 5,6,7,8
   ```

### 너무 오래 걸림
**예상 시간**:
- update_companies: 1-3분
- collect_dart (2,500개): 30-60분
- generate_briefs 1pass: 1-2시간
- evaluate 1pass: 30분-1시간
- generate_briefs 2pass: 20-40분
- evaluate 2pass: 10-20분
- merge_best: 즉시
- load_mongo: 1-2분
- **합계**: 3-5시간

너무 오래 걸리면 인터넷 / API 응답 속도 확인.

---

## 🔄 데이터 일관성

### MongoDB에 중복 적재 우려
**해결**: load_mongo는 `upsert` 방식. 같은 `stock_code`면 덮어쓰기, 다르면 추가. 중복 안 됨.

### 작년 데이터를 덮어쓰는지?
**현재 동작**:
- JSONL/평가: 같은 종목코드면 덮어쓰기 (매년 새 사업보고서로)
- MongoDB 브리핑: 덮어쓰기 (최신만 보관)

이력 보관이 필요하면 [roadmap.md](roadmap.md) 의 Phase 2 (S3) 참조.

---

## 🧪 안전 체크리스트 (실행 전)

본 실행 전에 다음 확인:

- [ ] `python -m code.config` → `[OK] 모든 필수 항목 정상`
- [ ] `python run_annual_pipeline.py --dry-run` → 모든 단계 dry_run 표시
- [ ] `python -m code.collect_dart --limit 1` → 1개 JSONL 다운로드 OK
- [ ] `python -m code.generate_briefs --pass 1 --limit 1` → 1개 브리핑 생성 OK
- [ ] `python -m code.evaluate --pass 1 --limit 1` → 평가 결과 출력
- [ ] `python -m code.load_mongo --dry-run` → 시뮬레이션 OK

위 6개 다 통과하면 본 실행 가능.

---

## 📞 도움 요청

위 가이드로 해결 안 되면:
1. 에러 메시지 전체 캡처
2. `logs/run_*.log` 마지막 부분
3. 실행한 명령어 + 환경 (`python --version`, OS)

세트로 모아서 문의.
