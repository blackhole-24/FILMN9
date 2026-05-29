@echo off
REM ──────────────────────────────────────────────────────────────────
REM run_chatbot.bat — 챗봇 서버 1-클릭 실행 (Windows)
REM   사전 조건:
REM     1) .env 작성 완료 (OPENAI_API_KEY · DART_API_KEY)
REM     2) pip install -r requirements.txt 완료
REM     3) embedding\chroma_db\ 배치 완료
REM ──────────────────────────────────────────────────────────────────
setlocal
set "PYTHONIOENCODING=utf-8"
cd /d %~dp0

echo [run_chatbot] 챗봇 서버 시작 — http://localhost:8000
echo [run_chatbot] 종료: Ctrl + C
echo.

python -m uvicorn embedding.chatbot.api:app --host 0.0.0.0 --port 8000

endlocal
