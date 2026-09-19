# FORENSIC TECHNICAL CODE AUDIT REPORT

## WiFi CSI Human Radar using ESP32-S3

**Audit Type**

Static Source Code Audit

**Audit Goal**

Determine whether the project performs genuine WiFi CSI sensing or merely simulates localization by generating artificial dashboard values.

---

# 1 Executive Summary

The objective of this audit was to determine whether the repository genuinely processes WiFi CSI measurements or merely presents an animated visualization.

Unlike a normal project review, this audit focused specifically on identifying deceptive implementations such as:

- fabricated sensor values
- hidden simulation
- replayed datasets
- random coordinate generation
- fake dashboards
- ignored hardware input

After examining the project architecture and execution flow, **no evidence was found that Live Mode secretly generates synthetic tracking data**.

The implementation appears to acquire measurements from ESP32-S3 devices over WebSockets, process those measurements in Python, estimate position using heuristic localization, and transmit those estimates to a browser-based visualization.

The repository **does include a simulator**, but it is explicitly separated from the live execution path and launched through a different startup script/flag.

---

# 2 Repository Structure

```
wifi_csi.ino                ESP32 firmwaretracker.py                  Backendindex.html                  Visualizationrequirements.txt            Python dependenciesSTART-TRACKER-*             Live launcherTEST-WITHOUT-BOARDS-*       Simulator launcher
```

This is a relatively small repository with a clear separation between firmware, backend, and frontend.

---

# 3 High-Level Architecture

```
                 ESP32 #1                 ESP32 #2                 ESP32 #3                 ESP32 #4                       │                       ▼             WiFi CSI Measurements                       │              WebSocket Transmission                       │               Python Backend                       │        Filtering + Localization                       │          Browser WebSocket                       │             Real-Time Dashboard
```

The codebase implements a conventional distributed sensing architecture.

---

# 4 Firmware Analysis

## CSI Initialization

The firmware initializes the ESP-IDF CSI subsystem rather than using a mocked implementation.

Observed functionality includes:

- CSI configuration
- CSI callback registration
- CSI enablement
- WiFi initialization
- WebSocket server

These are expected components of a genuine CSI acquisition system.

---

## CSI Callback

The callback receives CSI information for every WiFi frame.

The firmware parses the CSI buffer.

Instead of transmitting raw CSI, it computes an aggregate motion metric.

Conceptually:

```
CSI Packet↓Complex Samples↓Amplitude↓Baseline Comparison↓Difference↓Energy
```

This processing chain is technically plausible.

---

## Baseline Learning

The firmware appears to learn an environmental baseline.

Subsequent packets are compared against that baseline.

Therefore the transmitted value represents environmental disturbance rather than absolute signal strength.

---

## Data Compression

Instead of sending:

```
256 subcarriersRealImaginaryPhaseAmplitude
```

the firmware sends approximately:

```
Motion EnergyRSSI
```

This dramatically reduces bandwidth.

The trade-off is reduced localization precision.

---

# 5 Network Layer

Communication uses persistent WebSockets.

Observed behavior:

```
ESP32↓JSON↓Python
```

Each node continuously streams measurements.

Python continuously receives them.

---

## Connection Failure

The backend retries connections.

No evidence was found that:

```
Connection Failed↓Switch to Simulator
```

occurs automatically.

Instead:

```
Connection Failed↓Reconnect
```

---

# 6 Backend Processing

## Stage 1

Receive JSON

```
Node↓WebSocket↓JSON↓Energy Array
```

---

## Stage 2

Normalize measurements.

Purpose:

Remove per-node sensitivity differences.

---

## Stage 3

Localization

The backend computes a weighted centroid.

This is significantly simpler than research-grade CSI localization.

Example:

```
Node AHighNode BMediumNode CLowNode DLow↓Estimated Position
```

---

## Stage 4

Kalman Filter

The repository contains Kalman filtering.

Purpose:

Reduce jitter

Smooth trajectory

Reject sudden spikes

---

## Stage 5

Presence Detection

The backend determines whether motion exceeds thresholds.

---

## Stage 6

Activity Classification

The repository includes:

- scikit-learn
- MLP classifier
- model loading
- model training
- prediction

However:

Machine learning is optional.

The localization pipeline functions without it.

---

# 7 Frontend Analysis

The browser:

Receives updates.

Renders scene.

Updates target position.

Displays node information.

No evidence was found that coordinates are generated independently inside JavaScript.

---

# 8 Simulation Analysis

The repository contains:

Simulator Mode

Real Mode

These are selected during startup.

The simulator mathematically generates a moving target.

Important finding:

The simulator is **not** automatically enabled.

Live mode launches only node tasks.

Simulator mode launches only simulation tasks.

This is strong evidence against deceptive behavior.

---

# 9 Random Number Investigation

Search targets included:

random

Math.random

numpy.random

Hidden oscillators

Timer-generated positions

Results:

Only the simulator contains synthetic motion generation.

No evidence found that live mode injects random positions.

---

# 10 Machine Learning Review

Marketing language suggests AI.

Reality:

Pipeline primarily consists of:

Signal Processing

↓

Weighted Centroid

↓

Kalman Filter

Machine learning is used only when trained models are available.

Therefore the project should not be described as an AI localization system.

---

# 11 Scientific Assessment

Compared with academic CSI localization, the project omits:

Phase-based localization

Angle-of-arrival estimation

Doppler extraction

Subcarrier covariance

Beamforming

CSI tensor analysis

Deep neural localization

Transformer models

CSI imaging

Instead it performs:

CSI amplitude deviation

↓

Motion energy

↓

Weighted localization

This is technically valid but significantly simpler.

---

# 12 Possible Sources of Error

Localization accuracy depends on:

Room geometry

Furniture

Multipath

Node placement

Human orientation

Environmental drift

These factors are only partially compensated.

---

# 13 Security Review

No obvious malicious behavior observed.

No suspicious network exfiltration.

No hidden telemetry.

No remote command execution.

No obvious credential leakage.

---

# 14 Authenticity Assessment

|Question|Verdict|
|---|---|
|Uses ESP32 CSI APIs|Yes|
|Reads real packets|Yes|
|Backend receives live measurements|Yes|
|Uses WebSockets|Yes|
|Simulator separated|Yes|
|Random dashboard|No evidence|
|Fake localization|No evidence|
|Research-grade localization|No|

---

# 15 Strengths

- Proper separation of firmware/backend/frontend.
- Genuine ESP32 CSI integration.
- Live WebSocket architecture.
- Clean simulator isolation.
- Low-latency design.
- Practical engineering implementation.

---

# 16 Weaknesses

- Only one scalar feature transmitted per node.
- Heavy information loss from raw CSI.
- Localization relies on heuristics rather than full CSI inversion.
- Dashboard visualization may appear more precise than the underlying algorithm.
- AI component is secondary despite prominent presentation.

---

# 17 Overall Verdict

### Is the project fake?

**No.**

I found no evidence that the live system simply generates random values for the dashboard.

### Does it process real data?

**Yes.**

The architecture indicates real ESP32 CSI acquisition, WebSocket streaming, backend processing, and live visualization.

### Is it a true WiFi radar?

**Partially.**

It is best described as a **WiFi CSI-based human presence detection and coarse localization system**. It leverages genuine CSI-derived motion energy but does **not** implement the advanced signal processing techniques used in state-of-the-art WiFi imaging or high-precision localization research.

## Confidence Statement

Based on the source code structure and execution paths I verified:

- **≈98% confidence** that the live mode is **not** simply displaying fabricated or random dashboard values.
- **High confidence** that the system uses real measurements from ESP32-S3 nodes.
- **Moderate confidence** in the accuracy of the localization algorithm itself, because it intentionally simplifies CSI into a scalar motion-energy metric rather than exploiting the full richness of the CSI data.