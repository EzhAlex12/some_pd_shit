# Инструкция: Wi-Fi CSI на одной плате ESP32-S3 (macOS / Windows / Linux)

Полное руководство по настройке, прошивке одной платы **ESP32-S3** и запуску Python-анализатора сырых поднесущих CSI (Channel State Information) для отслеживания движения человека.

---

## 1. Поддерживаемые платформы и порты

| Платформа | Определение порта платы | Команда запуска Python |
|---|---|---|
| **macOS** | `/dev/cu.usbmodem*` или `/dev/cu.usbserial*` | `python3` |
| **Windows** | `COM3`, `COM4` и т.д. (см. Диспетчер устройств) | `python` |
| **Linux (Ubuntu/Debian/Kali)** | `/dev/ttyACM0` или `/dev/ttyUSB0` | `python3` |

### Требования к оборудованию:
* **1 × плата ESP32-S3** с кабелем Type-C (с поддержкой передачи данных).
* Сеть Wi-Fi **2.4 ГГц** (домашний роутер либо раздача с телефона) — *опционально*, так как в прошивке предусмотрен автономный режим SoftAP.

---

## 2. Установка зависимостей Python

### macOS / Linux:
```bash
# Перейдите в корень проекта
cd some_pd_shit

# Установка зависимостей
pip3 install -r backend/requirements.txt
```

> **Для пользователей Linux:**  
> Чтобы получить доступ к USB-порту без sudo, добавьте пользователя в группу `dialout`:
> ```bash
> sudo usermod -aG dialout $USER
> newgrp dialout
> ```

### Windows:
```cmd
cd some_pd_shit
pip install -r backend\requirements.txt
```

---

## 3. Настройка и прошивка ESP32-S3 в Arduino IDE (Все ОС)

1. Установите **Arduino IDE 2.x** ([arduino.cc/en/software](https://www.arduino.cc/en/software)).
2. Добавьте поддержку плат ESP32:  
   *Файл → Настройки (Preferences) → Дополнительные ссылки для Менеджера плат*:  
   `https://espressif.github.io/arduino-esp32/package_esp32_index.json`
3. В *Инструменты → Плата → Менеджер плат* найдите и установите **esp32** от Espressif Systems.
4. Откройте скетч:
   * `firmware/raw_csi_streamer/raw_csi_streamer.ino` (рекомендуется)
   * либо `firmware/single_node_csi/single_node_csi.ino`
5. В начале скетча укажите имя и пароль вашей Wi-Fi сети (строго **2.4 ГГц**):
   ```cpp
   const char* WIFI_SSID = "YOUR_WIFI_SSID";
   const char* WIFI_PASS = "YOUR_WIFI_PASS";
   ```
   > **Примечание:** Если Wi-Fi недоступен, через 5 секунд плата автоматически перейдёт в автономный режим SoftAP (`ESP32_CSI_RADAR`) и продолжит захват CSI без зависания.
6. В меню **Инструменты (Tools)** выставьте:
   * **Плата (Board):** `ESP32S3 Dev Module`
   * **USB CDC On Boot:** `Enabled` ⚠️ *(Обязательно для передачи данных через Type-C)*
   * **Upload Speed:** `921600` (или `115200`)
   * **Порт (Port):** выберите вашу подключенную плату
7. Нажмите кнопку **Загрузить (Upload)**.
8. ⚠️ **ВАЖНО:** После прошивки **закройте Serial Monitor в Arduino IDE**, иначе порт будет заблокирован для Python.

---

## 4. Запуск визуализации и анализатора

### Вариант 1: Pro-визуализатор реального времени (Водопад + Спектр + График энергии)
Автоматически определяет порт на macOS/Linux/Windows и выводит полный спектральный дашборд:

* **macOS / Linux:**
  ```bash
  python3 backend/single_csi.py
  ```
  *Принудительный порт (если подключено несколько устройств):*
  ```bash
  python3 backend/single_csi.py --port /dev/cu.usbmodem1101   # macOS
  python3 backend/single_csi.py --port /dev/ttyACM0          # Linux
  ```

* **Windows:**
  ```cmd
  python backend\single_csi.py
  ```
  *Принудительный порт:*
  ```cmd
  python backend\single_csi.py --port COM3
  ```

* **С одновременной записью в CSV:**
  ```bash
  python3 backend/single_csi.py --save walk_data.csv       # macOS/Linux
  python backend\single_csi.py --save walk_data.csv        # Windows
  ```

* **Режим симуляции (проверить работу без платы):**
  ```bash
  python3 backend/single_csi.py --sim                      # macOS/Linux
  python backend\single_csi.py --sim                       # Windows
  ```

---

### Вариант 2: Расширенный монитор c графиком вариации (csi_monitor.py)
* **macOS / Linux:**
  ```bash
  python3 backend/csi_monitor.py --serial /dev/cu.usbmodem1101
  ```
* **Windows:**
  ```cmd
  python backend\csi_monitor.py --serial COM3
  ```

---

### Вариант 3: Консольный сбор данных в CSV (без интерфейса)
* **macOS / Linux:**
  ```bash
  python3 backend/data_parser.py --serial /dev/cu.usbmodem1101 --out dataset.csv
  ```
* **Windows:**
  ```cmd
  python backend\data_parser.py --serial COM3 --out dataset.csv
  ```

---

## 5. Что отображается на дашборде

1. **HUD-панель сверху:** текущий уровень сигнала (RSSI dBm), частота входящих пакетов (RATE Hz), числовой индекс возмущения (VAR) и статус-бейдж (`[ СПОКОЙНАЯ ЗОНА ]` / `[ ДВИЖЕНИЕ ОБНАРУЖЕНО ]`).
2. **CSI Waterfall:** тепловая карта 64 поднесущих OFDM во времени. При движении человека появляются характерные интерференционные волны.
3. **Мгновенный профиль |H(f)|:** спектральный отклик поднесущих и средний фоновый базис.
4. **Вариация сигнала во времени:** скользящий 15-секундный график дисперсии с порогом детекции человека.

---

## 6. Решение типовых проблем

| Ошибка / Симптом | Причина | Решение |
|---|---|---|
| `[Errno 16] Resource busy` (macOS) / `Access is denied` (Windows) | Порт открыт в Arduino IDE | Закройте **Serial Monitor** в Arduino IDE. |
| `Permission denied: '/dev/ttyACM0'` (Linux) | Нет прав пользователя на чтение tty | Выполните: `sudo usermod -aG dialout $USER && newgrp dialout`. |
| В Serial идут точки `.....` | Плата не может найти Wi-Fi сеть | Убедитесь, что сеть 2.4 ГГц (на iPhone включите «Максимальная совместимость»). Новая прошивка через 5 сек автоматически переходит в SoftAP. |
| Окно открылось, но график плоский | Плата не шлёт пакеты | В Arduino IDE убедитесь, что включен `USB CDC On Boot: Enabled`, и перезагрузите плату кнопкой RST. |
