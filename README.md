# Wi-Fi CSI Human Radar & Sensing (ESP32-S3)

Система бесконтактного обнаружения человека, визуализации поднесущих Wi-Fi CSI (Channel State Information) и 3D-трекинга перемещений по возмущению радиоволн на базе чипов **ESP32-S3**.

Поддерживает работу на **macOS**, **Windows** и **Linux**.

---

## 🚀 Быстрый старт: выберите ваш сценарий

### 1. Работа с ОДНОЙ платой (Сырые поднесущие CSI, Водопад, Детекция дыхания и движения)
Используется 1 плата ESP32-S3, подключенная по USB Type-C:
* 📖 **[Пошаговая инструкция для всех платформ (macOS / Windows / Linux)](INSTRUCTIONS_SINGLE_CSI.md)**
* **Прошивка:** `firmware/single_node_csi/single_node_csi.ino` (или `firmware/raw_csi_streamer/raw_csi_streamer.ino`)
* **Визуализатор (GUI):**
  ```bash
  python3 backend/single_csi.py
  ```
* **Запись данных в CSV:**
  ```bash
  python3 backend/data_parser.py --serial /dev/cu.usbmodem... --out dataset.csv
  ```

---

### 2. Полный 3D Радар (3 или 4 платы по углам комнаты, триангуляция человека)
Используются 3–4 независимые ноды ESP32-S3, размещённые по периметру:
* 📖 **[Инструкция по настройке 3D радара (macOS / Windows / Linux)](Others/INSTRUCTIONS.md)**
* **Прошивка:** `firmware/wifi_csi/wifi_csi.ino` (прошивается на каждую ноду с уникальным `NODE_ID`: 0, 1, 2, 3)
* **3D Веб-интерфейс:**
  ```bash
  python3 -m http.server 8000
  ```
  *(Открыть `http://localhost:8000/frontend/index.html`)*
* **Python Power (2D Kalman + AI):**
  ```bash
  python3 backend/tracker.py
  ```

---

## 📦 Структура репозитория

```text
some_pd_shit/
├── INSTRUCTIONS_SINGLE_CSI.md    # Руководство по 1 плате (macOS / Windows / Linux)
├── firmware/
│   ├── single_node_csi/          # Прошивка для 1 платы (USB Serial stream)
│   ├── raw_csi_streamer/         # Прошивка 1 платы (только USB Serial)
│   └── wifi_csi/                 # Прошивка для многонодного 3D радара
├── backend/
│   ├── single_csi.py             # Live-монитор поднесущих (водопад + амплитуды)
│   ├── csi_monitor.py            # Монитор с графиком дисперсии возмущения
│   ├── data_parser.py            # Парсер и экспортер в CSV (Serial / WebSocket)
│   ├── tracker.py                # Сервер триангуляции и Kalman-фильтрации (порт 8765)
│   └── requirements.txt          # Python-зависимости (matplotlib, pyserial, websockets и др.)
├── frontend/
│   └── index.html                # 3D интерактивный дашборд Three.js
└── Others/
    ├── INSTRUCTIONS.md           # Руководство по 4 платам (3D Radar)
    └── START-TRACKER-MAC.command # Лаунчер для Mac
```

---

## 🔑 Wi-Fi пароль для прошивок

Пароли больше не хранятся в `.ino`. В папке каждого скетча лежит `secrets.example.h` —
скопируйте его в `secrets.h` рядом и впишите SSID/пароль 2.4 ГГц сети. `secrets.h` в `.gitignore`.

---

## 🛠️ Установка зависимостей

* **macOS / Linux:**
  ```bash
  pip3 install -r backend/requirements.txt
  ```
* **Windows:**
  ```cmd
  pip install -r backend\requirements.txt
  ```
