@echo off
REM ============================================================
REM  SGP CSI . Tracker (REAL MODE) - double-click to start
REM ============================================================
cd /d "%~dp0"
title SGP CSI Tracker
echo ===================================================
echo    SGP CSI  -  TRACKER (real mode, 4 nodes)
echo ===================================================
echo.

if not exist ".venv" (
  echo [setup] First time: preparing environment ^(1-2 min^)...
  python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt

echo.
echo Starting... opens index.html and click  PYTHON POWER
echo (to stop: Ctrl + C, or close this window)
echo ---------------------------------------------------
start "" "..\visualizer\index.html"
python tracker.py

echo.
echo --- the tracker has stopped ---
pause
