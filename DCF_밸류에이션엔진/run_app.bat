@echo off
REM ─────────────────────────────────────────────────────────────
REM  KPMG AX PoC — 기업가치 평가 시스템 실행 런처 (Windows)
REM
REM  [사전 요건]
REM    1. 이 파일과 같은 폴더에 .env 파일이 있어야 합니다.
REM       (.env 필수 키: OPENAI_API_KEY, DART_API_KEY, ECOS_API_KEY)
REM    2. data/filmn9_embeddings_chromadb/ 폴더 (임베딩 DB) 존재해야 합니다.
REM
REM  [사용법]
REM    이 파일을 더블클릭하거나 터미널에서 실행:
REM      run_app.bat            ← 기본 (포트 8012, localhost)
REM      run_app.bat 8013       ← 포트 지정
REM      run_app.bat 8012 0.0.0.0  ← 다른 PC 접속 허용 (LAN 공유)
REM
REM  [접속]
REM    브라우저에서 http://localhost:8012/ 열기
REM    (다른 PC 접속 시 http://<이 PC의 IP>:8012/)
REM ─────────────────────────────────────────────────────────────
setlocal

set PY=C:\Users\Admin\miniconda3\envs\dart-rag\python.exe
set PORT=8012
set HOST=127.0.0.1

REM ── 인수로 포트·호스트 지정 가능 ──────────────────────────────
if not "%1"=="" set PORT=%1
if not "%2"=="" set HOST=%2

REM ── 프로젝트 루트로 이동 ───────────────────────────────────────
cd /d "%~dp0"

REM ── Python·.env 존재 여부 사전 점검 ──────────────────────────
if not exist "%PY%" (
  echo [오류] Python 실행 파일을 찾을 수 없습니다:
  echo        %PY%
  echo        miniconda3 dart-rag 환경이 설치되어 있는지 확인하세요.
  pause
  exit /b 1
)

if not exist ".env" (
  echo [경고] .env 파일이 없습니다. API 키 없이 실행 시 일부 기능이 제한됩니다.
  echo        .env.example 을 복사해 .env 로 만들고 API 키를 입력하세요.
  echo.
)

echo.
echo ┌─────────────────────────────────────────────────────────┐
echo │  KPMG AX PoC - 기업가치 평가 시스템                    │
echo │  서버 주소: http://%HOST%:%PORT%/                       │
echo │  종료: Ctrl+C                                           │
echo └─────────────────────────────────────────────────────────┘
echo.

"%PY%" -m uvicorn valuation_engine.api:app --host %HOST% --port %PORT%

endlocal
