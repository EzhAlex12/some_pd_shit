
# Reproduction Guide (Exact Steps Followed)

## Objective

This guide documents the exact step-by-step process used to build and run the WiFi CSI Human Radar system using ESP32-S3 boards and a Kali Linux host machine. It includes all practical steps, checks, and troubleshooting actions performed during development.

---

## Prerequisites

### Hardware Used

- 3 × ESP32-S3 Development Boards (USB programmable)
    
- 3 × USB cables (data cables, not charge-only)
    
- 1 × 2.4 GHz WiFi network (important: ESP32 CSI works on 2.4 GHz)
    
- 1 × Laptop running Kali Linux
    

---

### Software Used

- Arduino IDE 2.x
    
- Python 3 (pre-installed on Kali)
    
- Git
    
- nmap (used for network scanning)
    

---

## Step 1: Install Arduino IDE and ESP32 Support

1. Download Arduino IDE 2.x from:  
    [https://www.arduino.cc/en/software](https://www.arduino.cc/en/software)
    
2. Open Arduino IDE
    
3. Go to:
    
    ```
    File → Preferences
    ```
    
4. In "Additional Board Manager URLs", add:
    
    ```
    https://espressif.github.io/arduino-esp32/package_esp32_index.json
    ```
    
5. Click OK
    
6. Go to:
    
    ```
    Tools → Board → Boards Manager
    ```
    
7. Search:
    
    ```
    ESP32
    ```
    
8. Install:
    
    ```
    ESP32 by Espressif Systems
    ```
    

---

## Step 2: Install Required Arduino Libraries

Go to:

```
Sketch → Include Library → Manage Libraries
```

Install the following:

- WebSockets by Markus Sattler
    
- Adafruit NeoPixel
    

Wait until installation completes.

---

## Step 3: Open and Configure Firmware

1. Open the firmware file:
    
    ```
    firmware/wifi_csi.ino
    ```
    
2. Locate WiFi configuration section
    
3. Replace with your actual WiFi credentials:
    
    ```cpp
    const char* WIFI_SSID = "YOUR_WIFI";
    const char* WIFI_PASS = "YOUR_PASSWORD";
    ```
    

Important:

- Use a 2.4 GHz network
    
- Ensure your laptop is connected to the same network
    

---

## Step 4: Configure Each ESP32 Node (Very Important)

You must flash each ESP32 separately with a unique NODE_ID.

### Board 1

1. Connect ESP32 via USB
    
2. Select correct port:
    
    ```
    Tools → Port → /dev/ttyUSB0 (or similar)
    ```
    
3. Set:
    
    ```cpp
    #define NODE_ID 0
    ```
    
4. Click Upload
    

---

### Board 2

1. Disconnect Board 1, connect Board 2
    
2. Select correct port again
    
3. Change:
    
    ```cpp
    #define NODE_ID 1
    ```
    
4. Upload
    

---

### Board 3

1. Disconnect Board 2, connect Board 3
    
2. Select correct port
    
3. Change:
    
    ```cpp
    #define NODE_ID 2
    ```
    
4. Upload
    

---

## Step 5: Verify Each Node Using Serial Monitor

After uploading each board:

1. Open:
    
    ```
    Tools → Serial Monitor
    ```
    
2. Set baud rate:
    
    ```
    115200
    ```
    
3. Observe output
    

Expected logs:

```
[WiFi] Connecting...
[WiFi] OK
[CSI] enabled
[WS] ready
```

If WiFi fails:

- Check SSID/password
    
- Ensure 2.4 GHz network
    

---

## Step 6: Find ESP32 IP Addresses (Important Step)

mDNS did NOT work reliably, so IP scanning was used.

### Scan Network

Run:

```bash
nmap -sn 192.168.1.0/24
```

Look for new devices (ESP32 boards).

---

### Verify WebSocket Port (Port 81)

For each suspected IP:

```bash
nmap -p 81 <IP>
```

Expected output:

```
81/tcp open
```

Only those IPs are valid ESP32 nodes.

---

## Step 7: Configure Python Tracker

1. Open:
    
    ```
    backend/tracker.py
    ```
    
2. Locate:
    
    ```python
    NODE_HOSTS
    ```
    
3. Replace with actual IPs found:
    

```python
NODE_HOSTS = [
    "192.168.1.101",
    "192.168.1.102",
    "192.168.1.103"
]
```

Make sure order matches NODE_ID (0, 1, 2).

---

## Step 8: Setup Python Environment

In project root:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

---

## Step 9: Start Python Tracker

Run:

```bash
python tracker.py
```

Expected output:

```
[node 0] connected
[node 1] connected
[node 2] connected
```

If connection fails:

- Recheck IPs
    
- Ensure ESP32 boards are powered
    
- Ensure port 81 is open
    

---

## Step 10: Launch Dashboard

From project root:

```bash
python3 -m http.server 8000
```

Open browser:

```
http://localhost:8000/index.html
```

---

## Step 11: Enable Python Backend in Dashboard

Inside dashboard UI:

Click:

```
⚡ PYTHON POWER
```

This connects frontend to Python tracker via WebSocket.

---

## Final Verification

If everything is working correctly, you should see:

- Real-time presence detection
    
- Motion energy updates
    
- Position estimation changing as you move
    
- Node status indicators
    
- Continuous live updates
    

---

## Notes from Actual Setup

- mDNS (esp32.local) did NOT work reliably → used nmap instead
    
- Port 81 is critical → must be open for WebSocket
    
- All devices must be on same WiFi network
    
- Node IDs must match tracker order
    
- Serial monitor is essential for debugging
    

---

## Result

Following these exact steps successfully reproduces the WiFi CSI Human Radar system with:

- 3 ESP32-S3 nodes
    
- Real-time CSI streaming
    
- Python-based signal processing
    
- Live visualization dashboard