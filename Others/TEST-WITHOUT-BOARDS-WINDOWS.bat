@echo off
REM ============================================================
REM  SGP CSI . Tracker (SIMULATOR, no hardware)
REM ============================================================
REM  This file lives in Others\ ; the code lives in backend\ and frontend\
cd /d "%~dp0.."
title SGP CSI Tracker (SIM)
echo ===================================================
echo    SGP CSI  -  TRACKER (SIMULATOR, no hardware)
echo ===================================================
echo.

if not exist "backend\.venv" (
  echo [setup] First time: preparing environment ^(1-2 min^)...
  python -m venv backend\.venv
  if errorlevel 1 ( echo [!] Python not found. Install Python 3.9+ and retry. & pause & exit /b 1 )
)
call backend\.venv\Scripts\activate.bat
python -m pip install -q --upgrade pip
python -m pip install -q websockets numpy

echo.
echo Simulating a person. The web app opens; click  PYTHON POWER
echo (to stop: Ctrl + C, or close this window)
echo ---------------------------------------------------
start "" "frontend\index.html"
python backend\tracker.py --sim

echo.
echo --- the simulator has stopped ---
pause
