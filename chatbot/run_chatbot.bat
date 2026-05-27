@echo off
REM ─────────────────────────────────────────────────────────────
REM  사업보고서 RAG 챗봇 실행 (Windows)
REM  사전 준비:
REM    1) 파이썬 환경 활성화 (예: conda activate dart-rag)
REM    2) .env 에 OPENAI_API_KEY 설정 (.env.example 참고)
REM    3) embedding\chroma_db\ (임베딩 DB) 배치 — 별도 공유받은 파일
REM  실행 후 브라우저에서 http://127.0.0.1:8000 접속
REM ─────────────────────────────────────────────────────────────
setlocal
set HOST=127.0.0.1
set PORT=8000
cd /d "%~dp0"
echo [run_chatbot] http://%HOST%:%PORT%  (종료: Ctrl+C)
python -m uvicorn embedding.chatbot.api:app --host %HOST% --port %PORT%
endlocal
