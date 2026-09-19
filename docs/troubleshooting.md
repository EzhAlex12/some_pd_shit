# Troubleshooting

## Tracker Cannot Connect to Nodes

### Symptoms

```text
[node 0] no connection
[node 1] no connection
[node 2] no connection
```

### Cause

mDNS hostnames may not resolve correctly on Linux systems.

### Solution

Replace:

```python
sgpcsi-0.local
sgpcsi-1.local
sgpcsi-2.local
```

with the actual IP addresses of the ESP32 nodes.

---

## Finding Node IP Addresses

Use:

```bash
nmap -sn 192.168.1.0/24
```

Look for devices identified as:

```text
Espressif
```

Verify WebSocket availability:

```bash
nmap -p 81 <IP_ADDRESS>
```

Expected:

```text
81/tcp open
```

---

## ESP32 Upload Failure

### Symptoms

Arduino upload does not start.

### Solution

1. Hold BOOT button.
    
2. Press RESET.
    
3. Release RESET.
    
4. Release BOOT.
    
5. Upload firmware again.
    

---

## Dashboard Not Updating

### Check

Python tracker must be running:

```bash
python tracker.py
```

Expected:

```text
[node 0] connected
[node 1] connected
[node 2] connected
```

---

## WiFi Connection Failure

### Symptoms

Serial monitor repeatedly shows:

```text
connecting...
```

### Solution

Verify:

- SSID is correct
    
- Password is correct
    
- Router supports 2.4 GHz WiFi
    

---

## CSI Not Working

### Check

Serial monitor should display:

```text
[CSI] enabled
```

If not present, verify firmware configuration and ESP32 Arduino core installation.