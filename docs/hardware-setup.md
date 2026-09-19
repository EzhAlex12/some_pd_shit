# Hardware Setup

## Components Used

### ESP32 Nodes

- 3 × ESP32-S3 Development Boards
    
- ESP32-S3-WROOM-N16R8
    

### Host System

- Kali Linux
    
- Python 3
    

### Network

- 2.4 GHz WiFi Router
    

---

## Node Configuration

Each ESP32 node was assigned a unique node identifier.

### Node 0

```cpp
#define NODE_ID 0
```

### Node 1

```cpp
#define NODE_ID 1
```

### Node 2

```cpp
#define NODE_ID 2
```

Each node was flashed separately using Arduino IDE.

---

## WiFi Configuration

All nodes were configured to connect to the same WiFi network.

```cpp
const char* WIFI_SSID = "YOUR_WIFI";
const char* WIFI_PASS = "YOUR_PASSWORD";
```

---

## Physical Placement

The ESP32-S3 nodes were positioned around the monitored area to provide spatial diversity for CSI measurements.

Example layout:

```text
Node 1 -------- Node 2

       User

Node 0
```

---

## Power Requirements

Nodes may be powered through:

- USB charger
    
- Power bank
    
- USB hub
    
- Computer USB ports
    

After flashing, nodes operate independently and do not require a USB connection to the host machine.

---

## Validation

Successful operation was confirmed through:

- WiFi connectivity
    
- CSI initialization
    
- WebSocket communication
    
- Real-time dashboard updates