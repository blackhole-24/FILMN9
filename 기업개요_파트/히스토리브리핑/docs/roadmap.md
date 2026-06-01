# Roadmap (To-be)

> 자동화 파이프라인의 현재 상태 + 향후 개선 계획

작성일: 2026-05-26

---

## Phase 1 (현재 As-is): 로컬 저장 + 본인 PC

### 구성
- 저장: `automation/data/` 로컬 디스크
- 운영: 본인 PC + Windows 작업 스케줄러
- 실행 주기: 연 1회 (4월 1일 새벽)

### 산출물 위치
- 최종 브리핑: MongoDB Atlas (서비스 직접 사용)
- 중간 데이터(JSONL, 평가): 로컬 디스크
- 로컬 브리핑 백업: `data/briefs/` (~4MB)

---

## Phase 2 (To-be): S3 통합

### 동기
- 데이터 백업 (PC 고장 대비)
- 운영 위치 이전 시 데이터 손실 방지
- 다른 PC에서도 접근 가능

### 작업 내용
- `boto3` 라이브러리 추가
- `code/storage.py` 의 `S3Storage` 클래스 구현
- `.env`에 AWS 키 추가:
  ```
  STORAGE_MODE=s3
  AWS_ACCESS_KEY_ID=...
  AWS_SECRET_ACCESS_KEY=...
  AWS_REGION=ap-northeast-2
  S3_BUCKET=filmn9-data
  ```

### 코드 영향
- 최소 (storage.py 추상화 레이어로 인해)
- `.env` 한 줄 변경 + boto3 설치만

### 예상 비용
- JSONL 20GB × $0.023/GB/월 = **$5-10/년**

---

## Phase 3 (To-be): 운영 위치 이전

### 동기
- 본인 PC 의존성 제거
- 24/7 안정 동작

### 옵션
| 옵션 | 비용 | 안정성 |
|------|------|--------|
| 팀원 백엔드 서버 | $0 | 높음 |
| 클라우드 VM (AWS EC2 등) | $10-50/월 | 최고 |
| GitHub Actions (서버리스) | 무료 (한도 내) | 높음 (단, 실행 시간 제한 6시간) |

### 작업 내용
- self-contained `automation/` 폴더를 이전 환경으로 복사
- 환경변수 (`.env`) 재설정
- 스케줄러 등록 (Linux: cron / Windows: Task Scheduler)
- Phase 2 (S3) 와 함께 진행하면 데이터 마이그레이션 X

### 코드 영향
- 거의 없음 (Python 코드는 OS 무관)
- `.bat` 대신 `.sh` 작성 정도

---

## 미정 (확정 안 됨, 추후 논의)

아래는 추후 결정 사항. 현재 자동화 범위에 포함 X.

- 뉴스/공시 통합 분석 기능
- 종목별 가격 영향 요인 분석 (TOP 3)
- 섹터별 평균 점수 추적
- 임베딩 기반 RAG 챗봇 통합
