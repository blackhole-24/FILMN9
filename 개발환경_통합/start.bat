@echo off
title FILMN9 Demo Launcher

echo.
echo ================================================================
echo   FILMN9 PoC  -  Demo Launcher
echo   FastAPI :8000  +  Next.js :3000
echo ================================================================
echo.

set ROOT=%~dp0
set PYTHON=C:\Users\Admin\miniconda3\envs\FILMN9_env\python.exe
set NPM=C:\Program Files\nodejs\npm.cmd

if not exist "%PYTHON%" (
    echo [ERROR] Python not found: %PYTHON%
    pause
    exit /b 1
)

echo [1/2] Starting FastAPI server (port 8000)...
start "FILMN9-API :8000" cmd /k "cd /d "%ROOT%" && "%PYTHON%" -m uvicorn backend.main:app --reload --port 8000"

timeout /t 3 /nobreak > nul

if exist "%ROOT%frontend\node_modules" (
    echo [2/2] Starting Next.js (port 3000)...
    start "FILMN9-UI :3000" cmd /k "cd /d "%ROOT%frontend" && "%NPM%" run dev"
    timeout /t 8 /nobreak > nul
    echo.
    echo Opening browser...
    start "" "http://localhost:3000"
) else (
    echo [2/2] Next.js not installed - opening HTML version...
    timeout /t 4 /nobreak > nul
    start "" "http://localhost:8000/app/index.html"
)

echo.
echo ================================================================
echo   Server started!
echo   Frontend : http://localhost:3000
echo   API Docs : http://localhost:8000/docs
echo ================================================================
echo.
pause
