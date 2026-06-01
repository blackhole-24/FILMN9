@echo off
REM ──────────────────────────────────────────────────────────────────
REM auto_update.bat — Windows 작업 스케줄러 진입점
REM 1) 챗봇 서버(uvicorn embedding.chatbot.api:app) 자동 종료
REM 2) auto_update.py 실행 (DART 새 보고서 감지 → 이전 교체 → 임베딩)
REM 로그: embedding\auto_update.log (Python 스크립트 내부 기록)
REM ──────────────────────────────────────────────────────────────────
setlocal
set "PY=C:\Users\Admin\miniconda3\envs\dart-rag\python.exe"
set "VAR=C:\Users\Admin\Desktop\VAR"
set "SCRIPT=%VAR%\embedding\auto_update.py"
set "PYTHONIOENCODING=utf-8"

cd /d "%VAR%"

echo [auto_update.bat] %DATE% %TIME% — 챗봇 서버 식별·종료 시도
REM 챗봇 프로세스만 정확히 식별(CommandLine에 'chatbot.api' 포함된 python.exe)해 종료
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*chatbot.api*' -or $_.CommandLine -like '*embedding.chatbot*' } | ForEach-Object { Write-Host ('  종료: PID ' + $_.ProcessId); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

REM 락 해제 안정화 대기 (ChromaDB 핸들 release)
timeout /t 5 /nobreak >nul

echo [auto_update.bat] %DATE% %TIME% — auto_update.py 시작
"%PY%" "%SCRIPT%"
set "RC=%ERRORLEVEL%"
echo [auto_update.bat] %DATE% %TIME% — auto_update.py 종료 (exit=%RC%)

endlocal & exit /b %RC%
