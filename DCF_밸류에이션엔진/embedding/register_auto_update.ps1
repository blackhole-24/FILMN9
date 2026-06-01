# ──────────────────────────────────────────────────────────────────
# register_auto_update.ps1 — Windows 작업 스케줄러에 8회/년 등록
#   4월 1·15일, 6월 1·15일, 9월 1·15일, 12월 1·15일  각 03:00 KST
#
# 실행: PowerShell 관리자 권한으로 실행
#   PowerShell -ExecutionPolicy Bypass -File embedding\register_auto_update.ps1
# 해제(나중에 일정 제거):
#   Get-ScheduledTask -TaskPath "\DART_AutoUpdate\" | Unregister-ScheduledTask -Confirm:$false
# ──────────────────────────────────────────────────────────────────

$BatPath  = "C:\Users\Admin\Desktop\VAR\embedding\auto_update.bat"
$TaskPath = "\DART_AutoUpdate\"
$RunAs    = "$env:USERDOMAIN\$env:USERNAME"   # 현재 사용자 계정으로 실행

if (-not (Test-Path $BatPath)) {
    Write-Error "auto_update.bat 가 없습니다: $BatPath"
    exit 1
}

# 8회 일정: 월 → [일 목록]
$Schedule = @{
    4  = @(1, 15)   # 사업보고서 (마감 3/31)
    6  = @(1, 15)   # 1분기보고서 (마감 5/15)
    9  = @(1, 15)   # 반기보고서  (마감 8/15)
    12 = @(1, 15)   # 3분기보고서 (마감 11/15)
}

$Action = New-ScheduledTaskAction -Execute $BatPath
$Principal = New-ScheduledTaskPrincipal -UserId $RunAs -LogonType S4U -RunLevel Highest
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun `
    -ExecutionTimeLimit (New-TimeSpan -Hours 6) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

$nReg = 0
foreach ($month in $Schedule.Keys) {
    foreach ($day in $Schedule[$month]) {
        $taskName = ("DART_AutoUpdate_{0:00}-{1:00}" -f $month, $day)
        # 매년 그 날짜에 실행 — Once + Daily 조합 대신 Weekly/Monthly 사용
        # PowerShell ScheduledTask 는 "특정 월·일 매년 반복" 직접 트리거 없음 → Monthly trigger 사용
        # New-ScheduledTaskTrigger 의 -Monthly 는 PS5.1에 없으므로 schtasks /create 로 등록
        $startTime = "03:00"
        $modifier  = "$month/$day"   # 매년 해당 월/일

        # 기존 task 있으면 삭제 후 재등록
        try { Unregister-ScheduledTask -TaskPath $TaskPath -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue } catch {}

        # schtasks /create: 매년 그 달 그 날짜 03:00 실행
        $cmd = "schtasks /create /tn `"$TaskPath$taskName`" /tr `"`"$BatPath`"`" /sc monthly /mo 1 /m ${month}월 /d $day /st 03:00 /ru SYSTEM /rl HIGHEST /f"
        # 한국어 월 이름이 안 먹는 경우 영문 매핑
        $monthEn = @{1='JAN';2='FEB';3='MAR';4='APR';5='MAY';6='JUN';7='JUL';8='AUG';9='SEP';10='OCT';11='NOV';12='DEC'}[$month]
        $cmd = "schtasks /create /tn `"$TaskPath$taskName`" /tr `"`"$BatPath`"`" /sc monthly /mo 1 /m $monthEn /d $day /st 03:00 /ru SYSTEM /rl HIGHEST /f"
        Write-Host "→ $taskName  ($monthEn $day 03:00 매년)"
        cmd /c $cmd | Out-Null
        if ($LASTEXITCODE -eq 0) { $nReg++ } else { Write-Warning "  등록 실패: $taskName (LASTEXITCODE=$LASTEXITCODE)" }
    }
}

Write-Host ""
Write-Host "✅ 등록 완료: $nReg / 8 개 작업"
Write-Host ""
Write-Host "확인:  Get-ScheduledTask -TaskPath '$TaskPath'"
Write-Host "해제:  Get-ScheduledTask -TaskPath '$TaskPath' | Unregister-ScheduledTask -Confirm:`$false"
Write-Host "수동 실행 1회: Start-ScheduledTask -TaskPath '$TaskPath' -TaskName 'DART_AutoUpdate_04-01'"
