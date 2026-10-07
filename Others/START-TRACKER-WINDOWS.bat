@echo off
REM ============================================================
REM  SGP CSI . Tracker (REAL MODE) - double-click to start
REM  Usage: START-TRACKER-WINDOWS.bat [--hosts ip1,ip2,ip3]
REM ============================================================
REM  This file lives in Others\ ; the code lives in backend\ and frontend\
cd /d "%~dp0.."
title SGP CSI Tracker
echo ===================================================
echo    SGP CSI  -  TRACKER (real mode)
echo ===================================================
echo.

if not exist "backend\.venv" (
  echo [setup] First time: preparing environment ^(1-2 min^)...
  python -m venv backend\.venv
  if errorlevel 1 ( echo [!] Python not found. Install Python 3.9+ and retry. & pause & exit /b 1 )
)
call backend\.venv\Scripts\activate.bat
python -m pip install -q --upgrade pip
python -m pip install -q -r backend\requirements.txt

echo.
echo Starting... the web app opens; click  PYTHON POWER
echo (to stop: Ctrl + C, or close this window)
echo ---------------------------------------------------
start "" "frontend\index.html"
python backend\tracker.py %*

echo.
echo --- the tracker has stopped ---
pause
