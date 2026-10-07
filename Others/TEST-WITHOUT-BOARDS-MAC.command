#!/bin/bash
# ============================================================
#  SGP CSI · Tracker (SIMULATOR, no hardware) — double-click to start
# ============================================================
# This file lives in Others/ ; the code lives in backend/ and frontend/
cd "$(dirname "$0")/.." || exit 1
clear
echo "==================================================="
echo "   SGP CSI  ·  TRACKER (SIMULATOR, no hardware)"
echo "==================================================="
echo ""

# creates the environment and installs libraries the first time
if [ ! -d "backend/.venv" ]; then
  echo "[setup] First time: preparing environment (1-2 min)..."
  python3 -m venv backend/.venv || { echo "[!] python3 not found"; exit 1; }
fi
source backend/.venv/bin/activate
python -m pip install -q --upgrade pip
python -m pip install -q websockets numpy

echo ""
echo "Starting... (the web will open by itself in the browser)"
echo "When it opens, click the  ⚡ PYTHON POWER  button"
echo "(to stop: press Ctrl + C, or close this window)"
echo "---------------------------------------------------"
# opens the web a couple of seconds later, while the tracker starts
( sleep 2 && open "frontend/index.html" ) &
python backend/tracker.py --sim

# keeps the window open if the program ends/errors out
echo ""
echo "--- the simulator has stopped ---"
read -n 1 -s -r -p "Press any key to close..."
