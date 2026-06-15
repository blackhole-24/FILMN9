@echo off
REM ============================================================
REM  FINSIGHT 로컬 서버 전체 1-클릭 실행 (백엔드+프론트+챗봇)
REM  더블클릭하면 3개 창이 뜹니다. 각 창을 닫으면 그 서버가 꺼집니다.
REM  접속: http://localhost:3000  (관리자 http://localhost:3000/admin)
REM ============================================================

echo [FINSIGHT] 로컬 서버 3개 시작...

REM 1) 백엔드 (FastAPI :8090, SQLite)
start "FINSIGHT Backend :8090" cmd /k "cd /d C:\Users\Admin\FILMN9 && C:\Users\Admin\miniconda3\envs\FILMN9_env\python.exe -m uvicorn backend.main:app --app-dir C:\Users\Admin\FILMN9 --port 8090"

REM 2) 프론트엔드 (Next.js :3000)
start "FINSIGHT Frontend :3000" cmd /k "cd /d C:\Users\Admin\FILMN9\frontend && npm run dev"

REM 3) AI 챗봇 (RAG :8800, GPU·40GB 로딩 1~3분)
start "FINSIGHT Chatbot :8800" cmd /k "cd /d C:\Users\Admin\FILMN9\chatbot && set PYTHONIOENCODING=utf-8 && set CHATBOT_OPENAI_MODEL=gpt-5-mini && set CHATBOT_ANALYZER_MODEL=gpt-5-mini && C:\Users\Admin\miniconda3\envs\FILMN9_chatbot_env\python.exe -m uvicorn embedding.chatbot.api:app --host 0.0.0.0 --port 8800"

echo.
echo [FINSIGHT] 3개 창이 떴습니다. 챗봇(8800)은 40GB 로딩으로 1~3분 후 준비됩니다.
echo           접속: http://localhost:3000
echo.
pause
