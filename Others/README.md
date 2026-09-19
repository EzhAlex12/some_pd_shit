# SGP CSI · 3D Human Radar (WiFi CSI)

Detect and **triangulate a person** in a room using the way the human body
disturbs WiFi signals (**CSI — Channel State Information**), with **4 SGP Card
Mini boards** (ESP32-S3) in the corners and a **3D web app** that shows the
movement in real time.

> ## ⚠️ Requires 4 SGP Card Mini
> Triangulation needs **all 4 boards**, one in each corner. With fewer boards the
> position is ambiguous. This is mandatory for the system to work properly.

> 👉 **New here? Follow [INSTRUCTIONS.md](INSTRUCTIONS.md) step by step.**

---

## How it works

1. A moving person changes the WiFi *multipath* (reflections) in the room.
2. Each ESP32-S3 is connected to your router and pings constantly to generate
   traffic, capturing the **CSI** of the received packets.
3. It compares the current CSI against a **baseline of the empty room**. The
   deviation = that node's **movement energy**.
4. **Each node is independent**: it exposes its own WebSocket and streams its
   signal. The app connects to all **4 at once** and does the **triangulation**
   (energy-weighted centroid): the most-disturbed node "pulls" the position.
5. The web draws the room in **3D** with an articulated skeleton, its trail, and
   each node's status, in real time.

```
   N3 (0,Y) ───────────── N2 (X,Y)
      │      · person ·      │   each node:  ws://sgpcsi-<id>.local:81
      │        ◍  →           │        ─────────────►  3D web
      │                       │        (the app opens 4 WebSockets)
   N0 (0,0) ───────────────  N1 (X,0)
```

---

## Contents

```
wifi csi/
├── INSTRUCTIONS.md                  ← step-by-step setup guide
├── firmware/wifi_csi/wifi_csi.ino   ← same sketch for the 4 ESP32-S3 boards
├── visualizer/index.html            ← 3D web app (open in a browser)
└── python/                          ← optional "PYTHON POWER" backend
    ├── tracker.py                   ← Kalman + trilateration + posture + AI
    ├── requirements.txt
    ├── START-TRACKER-MAC.command        / .bat (real mode, double-click)
    └── TEST-WITHOUT-BOARDS-MAC.command  / .bat (simulator, double-click)
```

---

## Two modes

- **Direct (default):** zero install. The web talks to the 4 boards over
  WebSocket and does the triangulation in the browser.
- **⚡ Python Power (optional):** run `python/tracker.py`. It adds a **2D Kalman
  filter**, weighted trilateration, posture estimation, and an optional
  **neural network** (MLP) that classifies activities you record. Press the
  orange button in the web to switch to it.

---

## Reality check

ESP32 CSI gives an **approximate** position (zone + movement), not centimeters,
and posture is an **estimate**. With the 4 boards well placed and the room
calibrated it tracks a person and distinguishes standing vs crouching reliably.
All thresholds are tunable from the web. For fine gestures you'd need to stream
the full CSI (subcarriers) from the firmware — a possible next step.

---

*Standalone project. It does not modify your `hama-id-reader` card reader.*
