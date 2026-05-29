# DART 정기보고서 자동 업데이트 시스템

KOSPI·KOSDAQ 전종목의 정기보고서를 **DART 공시 일정에 맞춰 자동 교체·임베딩**하는 파이프라인.

---

## 1. 정책 — 보고서 교체 규칙

| 새 보고서 공시 | 삭제 대상 | 추가 |
|---|---|---|
| 사업보고서 (Y년 12월 결산) | 이전 사업보고서(Y-1) + Y회계연도 마지막 분기(Q3) | Y 사업보고서 |
| 1분기 (Y+1 03월) | (없음 — 같은 회계연도 첫 분기) | Y+1 Q1 |
| 반기 (Y+1 06월) | Y+1 Q1 | Y+1 H1 |
| 3분기 (Y+1 09월) | Y+1 H1 | Y+1 Q3 |

**종목별 보유 패턴**: 항상 `[최신 annual]` + (있으면) `[최신 분기/반기 — annual보다 newer fiscal year일 때만]`.

예시 사이클:
```
현재: 2025-annual + 2026-q1
→ 2026 H1 공시: 2026-q1 삭제 + 2026-h1 추가 → [2025-annual, 2026-h1]
→ 2026 Q3 공시: 2026-h1 삭제 + 2026-q3 추가 → [2025-annual, 2026-q3]
→ 2026 사업보고서 공시: 2025-annual + 2026-q3 삭제 + 2026-annual → [2026-annual]
→ 2027 Q1 공시: 2027-q1 추가 → [2026-annual, 2027-q1]
(매년 반복)
```

---

## 2. 스케줄 — 연 8회 (KST 03:00)

| 월·일 | 노리는 보고서 | 법정 마감 |
|---|---|---|
| **4/1, 4/15** | 사업보고서 | 3/31 (+ 2주 정정 버퍼) |
| **6/1, 6/15** | 1분기보고서 | 5/15 |
| **9/1, 9/15** | 반기보고서 | 8/15 |
| **12/1, 12/15** | 3분기보고서 | 11/15 |

각 보고서마다 2회 도는 이유: **늦은 신고·[기재정정]·[첨부정정]까지 캐치**.

---

## 3. 로컬 실행 (Windows)

### 3.1 한 번 등록 (관리자 PowerShell)
```powershell
PowerShell -ExecutionPolicy Bypass -File C:\Users\Admin\Desktop\VAR\embedding\register_auto_update.ps1
```
→ 작업 스케줄러에 `\DART_AutoUpdate\*` 8개 작업 자동 등록.

### 3.2 수동 실행 (테스트·강제 실행)
```cmd
REM 변경 미리보기 (DB·파일 손대지 않음)
C:\Users\Admin\miniconda3\envs\dart-rag\python.exe C:\Users\Admin\Desktop\VAR\embedding\auto_update.py --dry

REM 첫 10종목만 (실제 적용)
C:\Users\Admin\miniconda3\envs\dart-rag\python.exe C:\Users\Admin\Desktop\VAR\embedding\auto_update.py --limit 10

REM 전체 종목 (실제 적용 — 챗봇 떠 있으면 종료해야 ChromaDB 충돌 없음)
C:\Users\Admin\Desktop\VAR\embedding\auto_update.bat
```

### 3.3 로그·확인
- 실행 로그: `embedding\auto_update.log`
- 등록된 작업 확인: `Get-ScheduledTask -TaskPath '\DART_AutoUpdate\'`
- 작업 제거: `Get-ScheduledTask -TaskPath '\DART_AutoUpdate\' | Unregister-ScheduledTask -Confirm:$false`

### 3.4 자동 챗봇 종료
`auto_update.bat`은 시작 시 **`embedding.chatbot.api`를 실행 중인 python 프로세스만 식별해 종료**합니다(전 python 종료 X). ChromaDB 락 해제를 위해 5초 대기 후 업데이트 시작. 업데이트 종료 후 챗봇은 자동 재시작되지 **않으니**, 필요하면 별도 작업 스케줄러로 재시작 등록.

---

## 4. 안전 장치

| 항목 | 처리 |
|---|---|
| ChromaDB 삭제 | 종목당 1~2개 report_kind = ~500~5,000 청크 단위(작은 트랜잭션). 이전 1.7M 대량삭제 크래시와 무관 |
| jsonl 삭제 | 즉시 (정책: 자동삭제). 백업 X — 필요하면 git/별도 백업 |
| DART rate limit | 전역 스로틀 분당 600회 (한도 1,000회의 60%) |
| 백업 era 호환 | annual 삭제는 `where={ticker, year}` (report_kind 없는 청크도 포함) |
| 재실행 안전 | 중간 실패해도 jsonl/DB가 일관되게 남아 다음 실행 시 차분이 재계산 |

---

## 5. AWS 클라우드 이전 (Phase 2)

### 5.1 아키텍처
```
┌─────────────────────────────────────────────────────────┐
│ EventBridge (cron: 8회/년, KST 03:00)                   │
└──────────────────────┬──────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────┐
│ Lambda: StartInstances + SSM RunCommand                  │
│   → EC2 g5.xlarge 기동 + 컨테이너 실행 + EC2 종료        │
└──────────────────────┬──────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────┐
│ EC2 g5.xlarge (Seoul ap-northeast-2)                     │
│   · Docker: dart-rag image (auto_update + dependencies)  │
│   · EBS gp3 60GB attached at /chromadb (영구)            │
│   · 실행 후 자동 종료(shutdown -h now)                   │
└──────────────────────┬──────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────┐
│ S3: jsonl 백업 + corpcode.xml 캐시                       │
└─────────────────────────────────────────────────────────┘
```

### 5.2 예상 비용 (연간)

| 항목 | 사양·계산 | 비용 |
|---|---|---|
| EC2 g5.xlarge (1×A10G GPU) On-Demand Seoul | $1.006/hr × 평균 1.5hr × 8회 = 12시간/년 | **$12** |
| EBS gp3 60GB (ChromaDB 영구) | $0.08/GB-월 × 60 × 12 | **$58** |
| S3 (jsonl 백업 ~5GB) | $0.023/GB-월 × 5 × 12 | **$1.4** |
| Lambda + EventBridge (스케줄러) | 거의 무료 | **$0.1** |
| 데이터 전송 (DART download ~3GB/년 out) | $0.09/GB | **$0.3** |
| **합계** | | **~$72/년 (약 10만원)** |

**더 저렴한 옵션**: g4dn.xlarge Spot ($0.158/hr) → compute $4/년 → 총 **~$64/년**.

**비용 최적화 팁**:
- EBS를 줄이려면 ChromaDB를 **S3에 압축 백업**, 실행 시 EBS로 복원/재업로드 → 평소 $0, 실행 시만 비용 (복잡도 ↑)
- 더 작은 GPU (T4) 사용 — 약간 느림이지만 비용 절반

### 5.3 마이그레이션 단계 (간단 가이드)
1. `Dockerfile` 작성 — 베이스 `nvidia/cuda:12.x` + Python + 패키지 + auto_update.py
2. ECR에 이미지 push
3. EC2 g5.xlarge 인스턴스 생성 (Docker pre-installed AMI), EBS 60GB attach to /chromadb
4. 초기 데이터 마이그레이션: 로컬 chroma_db (19GB) → S3 → EC2 EBS
5. Lambda 함수 작성: `boto3.start_instances` + `ssm.send_command(docker run ...)` + 인스턴스가 스스로 `shutdown -h now`
6. EventBridge 규칙 8개: cron(`0 18 1,15 3,5,8,11 ? *` 등 UTC 환산)
7. 모니터링: CloudWatch Logs + SNS 알림(실패 시)

(Phase 2 본격 진행 시 Dockerfile + Lambda 함수 + Terraform 모듈을 별도 모듈로 제공)

---

## 6. 트러블슈팅

| 증상 | 원인·조치 |
|---|---|
| `ModuleNotFoundError: embedding.dc_chunker` | VAR 루트가 sys.path에 없음 → bat 파일이 cd 했는지 확인 |
| `Expected IDs to be unique` 에러 | 같은 종목의 jsonl 두 개 존재 → `embedding/_duplicate_jsonl_backup/` 확인 |
| `File is not a zip file` | 해당 rcept_no가 [첨부정정] 본문 없음 → 다음 실행 시 자동 재시도 |
| ChromaDB 락 충돌 | 챗봇 서버나 다른 노트북이 떠 있음 → 종료 필요 |
| DART connection 끊김 | 한도(분당 1000) 근접 또는 DART 점검 → 자동 retry, 다음 스케줄에 이어 |

---

## 7. 파일 구조
```
embedding/
├─ auto_update.py            # 메인 로직
├─ auto_update.bat           # Windows 진입점 (챗봇 종료 + 실행)
├─ register_auto_update.ps1  # 작업 스케줄러 8회 등록
├─ AUTO_UPDATE_README.md     # 이 문서
├─ auto_update.log           # 실행 로그 (자동 생성)
├─ dc_chunker.py / dc_xml_cleaner.py  # (기존) 마크다운 청킹
├─ embedder.py / vector_store.py      # (기존) 임베딩 · DB
└─ chroma_db/                # (기존) 영구 벡터 DB
```
