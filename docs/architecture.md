# System Architecture

## Overview

The WiFi CSI Human Radar system uses multiple ESP32-S3 sensing nodes to collect WiFi Channel State Information (CSI) and transmit motion-related measurements to a Python processing backend.

The backend aggregates CSI measurements, estimates user position and activity, and streams the processed data to a real-time visualization dashboard.

---

## Architecture Diagram

```text
+-------------+
| ESP32-S3 #0 |
+-------------+
       |
+-------------+
| ESP32-S3 #1 |
+-------------+
       |
       | WiFi CSI Data
       v
+--------------------+
| Python Tracker     |
| tracker.py         |
+--------------------+
       |
       | WebSocket
       v
+--------------------+
| Dashboard          |
| index.html         |
+--------------------+

+-------------+
| ESP32-S3 #2 |
+-------------+
```

---

## Components

### ESP32-S3 Nodes

Responsibilities:

- Connect to local WiFi network
    
- Collect WiFi CSI measurements
    
- Compute motion-related signal metrics
    
- Stream data through WebSockets
    

### Python Tracker

Responsibilities:

- Receive CSI data from all nodes
    
- Aggregate sensor measurements
    
- Estimate user position
    
- Estimate user activity/posture
    
- Serve processed data to the dashboard
    

### Dashboard

Responsibilities:

- Display node locations
    
- Visualize estimated user position
    
- Display activity metrics
    
- Render real-time room view
    

---

## Data Flow

1. ESP32-S3 nodes collect CSI data.
    
2. CSI measurements are transmitted via WebSockets.
    
3. Python tracker processes incoming data.
    
4. Position and activity estimates are generated.
    
5. Dashboard visualizes results in real time.
    

---

## Network Requirements

- All ESP32-S3 nodes must be connected to the same WiFi network.
    
- Host machine must be connected to the same network.
    
- Port 81 is used by ESP32 WebSocket servers.
    
- Port 8765 is used by the Python tracker.