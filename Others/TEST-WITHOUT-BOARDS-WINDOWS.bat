@echo off
REM ============================================================
REM  SGP CSI . Tracker (SIMULATOR, no hardware)
REM ============================================================
cd /d "%~dp0"
title SGP CSI Tracker (SIM)
echo ===================================================
echo    SGP CSI  -  TRACKER (SIMULATOR, no hardware)
echo ===================================================
echo.

if not exist ".venv" (
  echo [setup] First time: preparing environment ^(1-2 min^)...
  python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install -q --upgrade pip
python -m pip install -q websockets numpy

echo.
echo Simulating a person. Opens index.html and click  PYTHON POWER
echo (to stop: Ctrl + C, or close this window)
echo ---------------------------------------------------
start "" "..\visualizer\index.html"
python tracker.py --sim

echo.
echo --- the simulator has stopped ---
pause
