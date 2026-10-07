# SGP CSI · Setup Instructions (Multi-Platform: macOS / Windows / Linux)

Step-by-step guide to get the **WiFi CSI human radar** running: detect and
triangulate a person in a room and see them move in real time in 3D.

> ## ⚠️ REQUIRED FOR 3D RADAR: 3 or 4 ESP32-S3 Boards
> This mode triangulates a person across the room.
> The boards sit in the corners of the room and each one measures
> the WiFi disturbance from its own corner.
> *(If you only have **one board**, see [INSTRUCTIONS_SINGLE_CSI.md](../INSTRUCTIONS_SINGLE_CSI.md) instead!)*

---

## 1. What You Need

* **3 или 4 платы ESP32-S3** (питание по USB или аккумуляторам).
* Сеть Wi-Fi **2.4 GHz** (ESP32 не поддерживает 5 GHz).
* Компьютер (**macOS, Windows или Linux**) в той же локальной сети.
* **Arduino IDE 2.x** для единоразовой прошивки плат.
* **Python 3.9+** для расширенного бэкенда "Python Power" (Kalman 2D + AI).

---

## 2. STEP 1 — Flash the Boards (Arduino IDE on macOS / Windows / Linux)

1. Установите **Arduino IDE 2.x** ([arduino.cc/en/software](https://www.arduino.cc/en/software)).
2. Добавьте платы ESP32: *File → Preferences → Additional Boards Manager URLs*:
   `https://espressif.github.io/arduino-esp32/package_esp32_index.json`
3. Установите библиотеки (*Tools → Manage Libraries*):
   * **WebSockets** by *Markus Sattler*
   * **Adafruit NeoPixel**
4. Откройте `firmware/wifi_csi/wifi_csi.ino`.
5. В начале скетча введите SSID и пароль вашей 2.4 GHz Wi-Fi сети:
   ```cpp
   const char* WIFI_SSID  = "YOUR_WIFI_2.4G";
   const char* WIFI_PASS  = "YOUR_PASSWORD";
   ```
6. Выберите плату: **ESP32S3 Dev Module**.
7. Прошейте каждую плату по очереди, меняя только значение `NODE_ID`:
   * Плата 1: `#define NODE_ID 0` (Master)
   * Плата 2: `#define NODE_ID 1`
   * Плата 3: `#define NODE_ID 2`
   * Плата 4: `#define NODE_ID 3`

### Как понять, что плата подключилась:
* При старте: 🔵 мигает синим (подключение) → 🟢 мигает зелёным (успешно в сети).
* В **Serial Monitor (115200)** отобразится:
  `[WS] ready at ws://sgpcsi-0.local:81` (с соответствующим номером ID и IP-адресом).

---

## 3. STEP 2 — Размещение плат в комнате

Разместите платы по углам комнаты примерно на уровне груди (1.2–1.5 м от пола):

```text
   N3 ───────────── N2
    │   (комната)   │
    │      ◍        │
    │   человек     │
   N0 ───────────── N1
```

---

## 4. STEP 3 — Запуск 3D Веб-интерфейса

Веб-приложение работает прямо в браузере (Chrome, Safari, Firefox, Edge).

### Запуск встроенного веб-сервера (рекомендуется для всех ОС):

* **macOS / Linux:**
  ```bash
  python3 -m http.server 8000
  ```
* **Windows:**
  ```cmd
  python -m http.server 8000
  ```

Откройте в браузере: **`http://localhost:8000/frontend/index.html`**

1. Интерфейс автоматически начнёт подключаться к нодам (`sgpcsi-0..3.local:81`).
2. Вверху справа появится статус: **`LIVE 4/4`** (или количество обнаруженных плат).
   * *Если в вашей сети mDNS (.local) не резолвится:* введите IP-адреса плат через запятую в поле "Nodes", например: `192.168.1.101, 192.168.1.102, 192.168.1.103, 192.168.1.104`.
3. Задайте реальные размеры комнаты (X и Y в метрах) и расставьте ноды по углам на плане.
4. В пустой комнате нажмите **Recalibrate empty environment** (калибровка фонового шума).

---

## 5. STEP 4 — Python Power (Kalman-фильтр + Распознавание поз)

Для устранения рывков координат и включения нейросетевого классификатора активности запустите Python-бэкенд:

### Установка зависимостей:
* **macOS / Linux:**
  ```bash
  pip3 install -r backend/requirements.txt
  ```
* **Windows:**
  ```cmd
  pip install -r backend\requirements.txt
  ```

### Запуск бэкенда:
* **macOS / Linux:**
  ```bash
  python3 backend/tracker.py
  ```
* **Windows:**
  ```cmd
  python backend\tracker.py
  ```

В открытом браузере нажмите оранжевую кнопку **⚡ PYTHON POWER**.  
Координаты человека начнут фильтроваться через 2D Kalman-фильтр на сервере.

---

## 6. Режим симуляции (без физических плат)

Если плат под рукой нет, вы можете протестировать систему в виртуальном режиме:

* **macOS / Linux:**
  ```bash
  python3 backend/tracker.py --sim
  ```
* **Windows:**
  ```cmd
  python backend\tracker.py --sim
  ```
  Или двойным кликом запустите `Others/TEST-WITHOUT-BOARDS-WINDOWS.bat`.

---

## 7. Сводная таблица команд по платформам

| Действие | macOS | Windows | Linux |
|---|---|---|---|
| **Установка библиотек** | `pip3 install -r backend/requirements.txt` | `pip install -r backend\requirements.txt` | `pip3 install -r backend/requirements.txt` |
| **Запуск 1 платы (GUI)** | `python3 backend/single_csi.py` | `python backend\single_csi.py` | `python3 backend/single_csi.py` |
| **Запуск 1 платы (CSV)** | `python3 backend/data_parser.py --serial /dev/cu.usbmodem...` | `python backend\data_parser.py --serial COM3` | `python3 backend/data_parser.py --serial /dev/ttyACM0` |
| **Запуск 3D веб-сервера**| `python3 -m http.server 8000` | `python -m http.server 8000` | `python3 -m http.server 8000` |
| **Запуск 4-нодного трекера** | `python3 backend/tracker.py` | `python backend\tracker.py` | `python3 backend/tracker.py` |
| **Симуляция трекера** | `python3 backend/tracker.py --sim` | `python backend\tracker.py --sim` | `python3 backend/tracker.py --sim` |

