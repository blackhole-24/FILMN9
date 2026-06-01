# Windows 작업 스케줄러 등록 가이드

> 매년 **4월 1일 새벽 02:00**에 자동 실행 등록

---

## 사전 준비

`automation/run_pipeline.bat` 파일이 올바른지 확인. 내용 예시:

```batch
@echo off
chcp 65001 > nul
set PROJECT_DIR=C:\Users\Admin\Desktop\DART
cd /d "%PROJECT_DIR%\automation"
call C:\Users\Admin\miniconda3\Scripts\activate.bat hf-nlp
python run_annual_pipeline.py --continue-on-error
pause
```

> ⚠️ 경로(`C:\Users\Admin\...`, `hf-nlp`)는 본인 환경에 맞게 수정 필요.

---

## 방법 1: GUI 등록 (추천)

### Step 1. 작업 스케줄러 열기
- Windows 키 → `작업 스케줄러` 검색 → 실행

### Step 2. 작업 만들기
- 우측 **작업 만들기** 클릭 (단순한 "기본 작업" 말고)

### Step 3. 일반 탭
| 항목 | 값 |
|------|------|
| 이름 | `FILMN9_AnnualUpdate` |
| 설명 | 매년 4월 1일 사업보고서 자동 수집 + MongoDB 적재 |
| 보안 옵션 | "사용자가 로그온할 때만 실행" 또는 "관계없이" |
| 권한 | "가장 높은 수준으로 실행" 체크 |

### Step 4. 트리거 탭
- **새로 만들기** 클릭
- 작업 시작: **일정에 따라**
- 매년 → 4월 1일 → **시작: 02:00:00**
- 활성화 체크

### Step 5. 동작 탭
- **새로 만들기** 클릭
- 작업: **프로그램 시작**
- 프로그램/스크립트:
  ```
  C:\Users\Admin\Desktop\DART\automation\run_pipeline.bat
  ```
- 시작 위치 (선택):
  ```
  C:\Users\Admin\Desktop\DART\automation
  ```

### Step 6. 조건 탭 (권장)
- "AC 전원을 사용 중인 경우에만 작업 시작" 해제
- "전원이 충분한 경우에만 작업 실행" 체크

### Step 7. 설정 탭
- "예약된 시간에 작업을 시작할 수 없는 경우 빨리 작업 실행" 체크
- "작업이 실패할 경우 재시작" 체크 → 1분 후, 3회

### Step 8. 저장
- **확인** → 자격 증명 입력

---

## 방법 2: PowerShell 명령어 (자동)

관리자 권한 PowerShell 실행 후:

```powershell
$action = New-ScheduledTaskAction `
    -Execute "C:\Users\Admin\Desktop\DART\automation\run_pipeline.bat" `
    -WorkingDirectory "C:\Users\Admin\Desktop\DART\automation"

# 매년 4월 1일 02:00
$trigger = New-ScheduledTaskTrigger `
    -Weekly -At "02:00" -DaysOfWeek Monday   # 임시 (아래 수정)

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME -RunLevel Highest

Register-ScheduledTask `
    -TaskName "FILMN9_AnnualUpdate" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "매년 사업보고서 수집 + MongoDB 적재"
```

> ⚠️ PowerShell의 `New-ScheduledTaskTrigger`는 매년 트리거를 직접 지원하지 않음.
> GUI 방식(방법 1) 추천.

---

## 등록 후 확인

### 등록 상태 확인
```powershell
Get-ScheduledTask -TaskName "FILMN9_AnnualUpdate" | Get-ScheduledTaskInfo
```

### 즉시 테스트 실행
```powershell
Start-ScheduledTask -TaskName "FILMN9_AnnualUpdate"
```

또는 작업 스케줄러 GUI → 우클릭 → **실행**

### 로그 확인
실행 후:
```
C:\Users\Admin\Desktop\DART\automation\logs\run_YYYYMMDD_HHMMSS.log
```

---

## 등록 해제

```powershell
Unregister-ScheduledTask -TaskName "FILMN9_AnnualUpdate" -Confirm:$false
```

또는 GUI에서 우클릭 → **삭제**

---

## 주의사항

- ✅ **PC가 켜져있어야 함** — 절전 / 꺼진 상태에서는 실행 안 됨
- ✅ **인터넷 연결 필수** — DART API, MongoDB Atlas, KRX, OpenAI
- ✅ **.env 파일 정상 상태 유지**
- ⚠️ 4월 1일에 PC 꺼져있으면 → 다음 부팅 시 자동 실행 (위 Step 7 체크 시)
- ⚠️ 실행 도중 PC 끄지 말 것 (~3-5시간 소요)
- ⚠️ 자동 실행이 부담되면 → 트리거 비활성화 후 매년 수동 실행

---

## 대안: 수동 실행

매년 4월 1일 직접 실행하고 싶으면 스케줄러 등록 X.

`run_pipeline.bat`를 더블클릭 또는 명령창에서:
```bash
cd C:\Users\Admin\Desktop\DART\automation
python run_annual_pipeline.py
```
