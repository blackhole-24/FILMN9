# FINSIGHT AWS 배포 로드맵 — 초보자 가이드 (2026-06-14)

> 목표: 로컬 FINSIGHT를 AWS에 올린다.
> 구조(하이브리드): **RDS**(관계형 16테이블) + **EC2-GPU**(ChromaDB) + **Atlas**(MongoDB 유지) + **S3**(파일).
> ⚠️ 프론트 UI(밸류탭·챗봇·메인)는 나중에 바뀌어도 됨 — 인프라 먼저 깔고, 프론트는 마지막에 다시 빌드해서 얹으면 됨(재배포 자유).

체크는 `[ ]` → 끝나면 `[x]`. 리전은 전부 **서울(ap-northeast-2)**.

---

## 🧰 사전 준비 (내 PC에 설치)
- [ ] **AWS CLI** 설치 — https://aws.amazon.com/cli/ (설치 후 `aws configure`로 키 입력)
- [ ] **PostgreSQL 클라이언트(psql·pg_dump)** 설치 — https://www.postgresql.org/download/windows/
      (설치 시 "Command Line Tools" 체크. 버전은 RDS와 같은 17 권장)
- [ ] `pip install boto3` (S3 업로드 스크립트용) — FINSIGHT_env에 설치
- [ ] AWS 콘솔 로그인 (또는 가입) — 결제수단 등록 필요(프리티어 일부 가능)

---

## Phase 0 · 기반 (0.5일)
- [ ] **IAM 사용자** 생성(관리자 권한) → 액세스 키 발급 → `aws configure`에 입력
- [ ] **VPC**: 기본 VPC 사용해도 됨(처음엔 단순하게)
- [ ] **보안그룹** 2개:
      · `finsight-app-sg`: 인바운드 80/443(웹), 22(SSH 내 IP만)
      · `finsight-db-sg`: 인바운드 5432(app-sg에서만)

## Phase 1 · RDS (관계형 DB) (0.5~1일)
- [ ] **RDS → PostgreSQL** 생성 (엔진 17, 서울, db.t3.medium, 스토리지 50GB gp3,
      퍼블릭 액세스 일단 "예"로 시작 후 나중에 제한, 보안그룹 `finsight-db-sg`)
- [ ] 현재 Supabase에서 **데이터 덤프** (PC에서, 약 2.7GB):
  ```
  pg_dump "현재_DATABASE_URL(.env값)" -Fc -f finsight.dump
  ```
- [ ] RDS로 **복원**:
  ```
  pg_restore -h <RDS엔드포인트> -U postgres -d postgres --no-owner finsight.dump
  ```
  (ohlcv 1천만행이라 시간 걸림. 끊기면 `--jobs 4` 병렬 옵션 추가)
- [ ] 검증: `psql -h <RDS> -U postgres -c "SELECT count(*) FROM ohlcv;"` → 10,678,102 확인
- [ ] **백엔드 .env 교체**: `DB_HOST`/`DB_PORT`/`DB_NAME`/`DB_USER`/`DB_PASS`/`DATABASE_URL`을
      RDS 값으로. (`DB_BACKEND=postgres` 유지) → 코드 수정 0, .env만 바꾸면 됨

> 💡 빠른 길: RDS 안 쓰고 **Supabase 그대로 유지**도 가능. 그러면 Phase 1 전체 생략 →
> 배포 1~2일 단축. "전부 AWS 안에" 정책이 아니면 이 길이 더 빠름.

## Phase 2 · S3 (정적 파일) (0.5일)
- [ ] **S3 버킷** 생성: `finsight-static-<임의>` (서울)
- [ ] 업로드(이 폴더의 `s3_upload_static.py` 사용):
  ```
  set FINSIGHT_S3_BUCKET=finsight-static-xxxx
  python s3_upload_static.py
  ```
  → outputs/sankey(2,691) + data/valuation_results(13,344) 업로드
- [ ] 백엔드의 파일 서빙 경로를 S3(또는 CloudFront) URL로 전환
      (지금은 `/sankey/{code}`가 로컬 파일 → S3에서 읽도록 또는 EC2 디스크에 복사)

## Phase 3 · EC2-GPU + ChromaDB (1~1.5일, 가장 무거움) ⚠️
- [ ] **EC2 GPU 인스턴스**(g4dn.xlarge 등, 서울, Ubuntu, 보안그룹 app-sg) 생성
- [ ] **EBS 볼륨** 60GB+ 부착(ChromaDB 40GB용)
- [ ] 로컬 ChromaDB(`chatbot/embedding/chroma_db`, ~40GB)를 EC2로 전송
      (`scp` 또는 압축 후 S3 경유 다운로드 — 40GB라 시간 걸림)
- [ ] GPU 드라이버·CUDA·임베딩/리랭커 모델 세팅, 챗봇 서버(:8800) 기동 테스트

## Phase 4 · EC2 앱 배포 (0.5~1일)
- [ ] **EC2(앱)**: 백엔드 FastAPI(uvicorn) + nginx 리버스프록시
- [ ] 프론트: `npm run build` → EC2에서 서빙 (또는 S3+CloudFront 정적 호스팅)
- [ ] **MongoDB Atlas**: Network Access에 EC2 공인 IP 화이트리스트 추가(코드 변경 0)
- [ ] 환경변수: 아래 13개를 EC2 `.env` 또는 **Secrets Manager**에 등록

## Phase 5 · 도메인·HTTPS·검증 (0.5일)
- [ ] **Route53** 도메인 + **ACM** 인증서(HTTPS) → ALB 또는 nginx에 연결
- [ ] **전수 헬스체크**(healthcheck_full.py 류)·회귀검증(NO-MOCK)
- [ ] 데모 URL 공유

---

## 🔐 환경변수 목록 (Secrets Manager/.env에 넣을 것 — 값은 절대 코드/Git에 X)
DART_API_KEY · ECOS_API_KEY · OPENAI_API_KEY ·
DB_HOST · DB_PORT · DB_NAME · DB_USER · DB_PASS · DATABASE_URL · DB_BACKEND ·
MONGO_URI · MONGO_DB · MONGO_COLLECTION · Naver_Client_Id · Naver_Client_Secret

## ⏱ 총 예상: 3~5일 (Supabase 유지 시 2~3일)
## 💰 월 비용 개략: RDS(t3.medium ~$60) + EC2-GPU(g4dn ~$380 상시/스팟 절감) + S3(~$1) + Atlas(기존)
   → GPU가 가장 큼. 데모 기간만 켜고 끄면 절감. (정확 산정은 AWS 요금계산기)

---
## 다음에 클로드가 도와줄 수 있는 것
- pg_dump/restore 실제 실행 보조 · S3 업로드 스크립트 실행 · 백엔드 .env 전환 ·
  EC2 nginx 설정 파일 작성 · 헬스체크 스크립트. (AWS 콘솔 클릭은 본인이, 스크립트·검증은 클로드가)
