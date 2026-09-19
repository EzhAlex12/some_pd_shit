# SGP CSI · Setup Instructions

Step-by-step guide to get the **WiFi CSI human radar** running: detect and
triangulate a person in a room and see them move in real time in 3D.

> ## ⚠️ REQUIRED: 4 × SGP Card Mini
> This system **needs the 4 SGP Card Mini boards** (each has an internal
> ESP32-S3). The 4 boards sit in the 4 corners of the room and each one measures
> the WiFi disturbance from its own corner. **Triangulation only works with all
> 4** — with fewer boards the position is ambiguous and unreliable. Do not skip
> this: 4 boards, one in each corner, is mandatory for it to be effective.

---

## What you need

- **4 × SGP Card Mini** (ESP32-S3 inside), powered (USB or battery).
- A **2.4 GHz WiFi** network (the ESP32 does **not** use 5 GHz).
- A computer (macOS or Windows) on the **same WiFi** network.
- **Arduino IDE** to flash the boards (one-time).
- (Optional) **Python 3** for the advanced "Python Power" mode (Kalman + AI).

---

## STEP 1 — Flash the 4 boards (one time)

1. Install **Arduino IDE 2.x**.
2. Add the ESP32 boards: *Preferences → Additional Boards Manager URLs* →
   `https://espressif.github.io/arduino-esp32/package_esp32_index.json`
   then install **esp32** from *Boards Manager*.
3. Install two libraries (*Library Manager*):
   - **WebSockets** by *Markus Sattler*
   - **Adafruit NeoPixel**
4. Open `firmware/wifi_csi/wifi_csi.ino`. At the top set your WiFi:
   ```cpp
   const char* WIFI_SSID = "YOUR_WIFI";       // 2.4 GHz
   const char* WIFI_PASS = "YOUR_PASSWORD";
   ```
5. Select board **ESP32S3 Dev Module**.
6. Flash each board changing **only** `NODE_ID` each time:

   | Board | Set this line       | Then click |
   |-------|---------------------|------------|
   | 1     | `#define NODE_ID 0` | Upload     |
   | 2     | `#define NODE_ID 1` | Upload     |
   | 3     | `#define NODE_ID 2` | Upload     |
   | 4     | `#define NODE_ID 3` | Upload     |

That's it — there is **no master**. All 4 boards are identical and independent.

### How to know a board works
- On power-up: 🔵 **blue blinking** while connecting → 🟢 **green blinking** +
  a beep when connected to WiFi. 🔴 **red** = it cannot join WiFi (check
  SSID/password and that it's 2.4 GHz).
- Open the **Serial Monitor** (115200) to see:
  `[WS] ready at ws://sgpcsi-0.local:81` (with its own number).

---

## STEP 2 — Place the boards

Put one board in **each of the 4 corners** of the room, roughly at chest height,
with nothing metallic blocking them. Remember which corner is N0, N1, N2, N3.

```
   N3 ───────────── N2
    │   (room)      │
    │      ◍        │
    │   person      │
   N0 ───────────── N1
```

---

## STEP 3 — Open the web app

1. Open `visualizer/index.html` in your browser (double-click).
2. It **auto-connects** to the 4 boards (`sgpcsi-0..3.local`). Top-right you'll
   see **`LIVE 4/4`** when all four are up.
   - If your network can't resolve `.local` names, type the **4 board IPs**
     (comma-separated) in the connection box. You can read each IP in that
     board's Serial Monitor.
3. Set your room size (**Room width X / length Y**, in meters).
4. Switch to the **Top** or **Drone** camera view and **drag each node** onto its
   real corner (or type its X/Y/Z in meters). Accurate placement = accurate
   tracking.
5. With the room **empty**, click **Recalibrate empty room** to learn the
   baseline. From then on, any movement shows up as presence.

### Tuning (sliders)
- **Sharpness** – higher pulls the estimate harder toward the dominant node.
- **Position smoothing** – higher = smoother/slower, less jitter.
- **Presence threshold (0–1)** – minimum activity to count as "someone here".
- **Posture sensitivity** – how easily it calls "crouching".

Now walk around — the 3D skeleton should follow you, and show **standing /
crouching**.

---

## STEP 4 (optional) — "Python Power": Kalman + AI

The web works on its own. For more reliable position and **activity detection**,
run the Python engine.

1. Start it (double-click):
   - macOS: `python/START-TRACKER-MAC.command`
   - Windows: `python/START-TRACKER-WINDOWS.bat`
   The first run installs everything; a Terminal opens and the web opens by
   itself.
2. In the web, click the orange **⚡ PYTHON POWER** button.
   - Success → green toast **"Python connected ✓"**, and the Terminal prints a
     big **`>>> WEB CONNECTED — PYTHON POWER ACTIVE`** banner.
   - If it isn't running, the web shows a panel telling you which file to open.
3. Click the button again to return to direct mode.

> Just want to test without the boards? Use
> `python/TEST-WITHOUT-BOARDS-MAC.command` (or the `-WINDOWS.bat`): it simulates
> a moving person so you can verify the whole chain.

### Teach it activities (neural network)
The AI must be trained **in your room** (every room echoes WiFi differently).
In a Terminal:
```bash
cd "wifi csi/python"
source .venv/bin/activate            # Windows: .venv\Scripts\activate
python tracker.py --record standing --seconds 30
python tracker.py --record crouching --seconds 30
python tracker.py --record walking  --seconds 30
python tracker.py --record empty    --seconds 20
python tracker.py --train            # trains the neural network
python tracker.py                    # run again; the web now shows the activity
```
While in Python Power mode you'll see **`AI: <ACTIVITY> (xx%)`** top-right.

---

## Troubleshooting

| Problem                              | Fix                                                                 |
|--------------------------------------|----------------------------------------------------------------------|
| Board LED stays red                  | Wrong WiFi / not 2.4 GHz. Re-check SSID and password.                |
| Web shows `LIVE 3/4`                 | One board is off or not flashed. Power it / flash its `NODE_ID`.     |
| Web won't connect                    | Same network; open as `file://` (not `https://`); or type the 4 IPs.|
| No presence detected                 | Lower the threshold; recalibrate with the room empty.               |
| Presence with empty room             | Raise the threshold; recalibrate; reduce fans/curtains.             |
| Position too jumpy                   | Raise position smoothing.                                            |
| "Python not detected" panel          | Open `START-TRACKER-MAC.command` first, then press the button.      |

---

## Reality check
ESP32 CSI gives an **approximate** position (zone + movement), not centimeters,
and posture is an **estimate**. With all **4 boards** well placed and the room
calibrated it tracks a person around the room and tells standing vs crouching
quite reliably. For finer gestures you'd stream the full CSI (next-level upgrade).
