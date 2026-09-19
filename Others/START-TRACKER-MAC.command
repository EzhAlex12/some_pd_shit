#!/bin/bash
# ============================================================
#  SGP CSI · Tracker (REAL MODE)  — double-click to start
#  Connects to your 4 nodes and serves the web (PYTHON POWER button).
# ============================================================
cd "$(dirname "$0")"
clear
echo "==================================================="
echo "   SGP CSI  ·  TRACKER (real mode, 4 nodes)"
echo "==================================================="
echo ""

# creates the environment and installs libraries the first time
if [ ! -d ".venv" ]; then
  echo "[setup] First time: preparing environment (1-2 min)..."
  python3 -m venv .venv
fi
source .venv/bin/activate
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt

echo ""
echo "Starting... (the web will open by itself in the browser)"
echo "When it opens, click the  ⚡ PYTHON POWER  button"
echo "(to stop: press Ctrl + C, or close this window)"
echo "---------------------------------------------------"
# opens the web a couple of seconds later, while the tracker starts
( sleep 2 && open "../visualizer/index.html" ) &
python tracker.py

# keeps the window open if the program ends/errors out
echo ""
echo "--- the tracker has stopped ---"
read -n 1 -s -r -p "Press any key to close..."
