@echo off
REM ════════════════════════════════════════════════════════════════════════
REM  FILMN9 연간 파이프라인 — Windows 작업 스케줄러 실행용
REM  매년 4월 1일 자동 실행 (또는 수동 더블클릭)
REM
REM  스케줄러 등록: docs/scheduler_setup.md 참조
REM
REM  본인 환경에 맞게 수정할 곳:
REM    - CONDA_ENV    : Conda 환경명 (기본 hf-nlp)
REM    - CONDA_PATH   : conda 설치 경로
REM ════════════════════════════════════════════════════════════════════════

REM ── 콘솔 UTF-8 ──
chcp 65001 > nul

REM ── 스크립트 경로 (자동 감지) ──
set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

REM ── Conda 환경 (필요 시 수정) ──
set CONDA_ENV=hf-nlp
set CONDA_PATH=%USERPROFILE%\miniconda3

REM ── Conda 환경 활성화 ──
if exist "%CONDA_PATH%\Scripts\activate.bat" (
    call "%CONDA_PATH%\Scripts\activate.bat" %CONDA_ENV%
) else if exist "%USERPROFILE%\anaconda3\Scripts\activate.bat" (
    call "%USERPROFILE%\anaconda3\Scripts\activate.bat" %CONDA_ENV%
) else (
    echo [WARN] Conda 환경 찾지 못함. 현재 PATH 의 python 사용
)

REM ── 실행 ──
python run_annual_pipeline.py --continue-on-error

REM ── 종료 ──
echo.
echo 파이프라인 완료. 로그: %SCRIPT_DIR%logs\
pause
