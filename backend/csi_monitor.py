#!/usr/bin/env python3
# ============================================================================
#  REAL-TIME ESP32 WIFI CSI VISUALIZER & MONITOR
# ============================================================================
#  Скрипт для живой визуализации сырых поднесущих Wi-Fi CSI (OFDM 64 subcarriers).
#
#  Запуск:
#    1. Симуляция (посмотреть как меняется график прямо сейчас):
#       python3 backend/csi_monitor.py --sim
#
#    2. По проводу через USB Serial (рекомендуемый самый быстрый способ):
#       python3 backend/csi_monitor.py --serial /dev/cu.usbmodem1101
#
#    3. По воздуху через WebSocket:
#       python3 backend/csi_monitor.py --ws ws://192.168.1.15:81
# ============================================================================

import sys
import time
import json
import argparse
import threading
from collections import deque
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

NUM_SUBCARRIERS = 64        # 64 поднесущие для 20 MHz WiFi
HISTORY_LEN     = 100       # Длина водопада (строк во времени)

data_lock = threading.Lock()
csi_history = deque(maxlen=HISTORY_LEN)
current_csi = np.zeros(NUM_SUBCARRIERS)
energy_history = deque(maxlen=200)
time_history = deque(maxlen=200)
last_rssi = -60
start_time = time.time()

# Заполняем начальную историю тишиной
for _ in range(HISTORY_LEN):
    csi_history.append(np.ones(NUM_SUBCARRIERS) * 15.0 + np.random.normal(0, 0.1, NUM_SUBCARRIERS))


def push_csi_frame(amps, rssi_val=-55):
    """Добавляет новый кадр поднесущих в буфер отрисовки."""
    global current_csi, last_rssi
    arr = np.array(amps, dtype=float)
    if len(arr) != NUM_SUBCARRIERS:
        arr = np.interp(np.linspace(0, 1, NUM_SUBCARRIERS),
                        np.linspace(0, 1, len(arr)), arr)

    now = time.time() - start_time
    with data_lock:
        csi_history.append(arr)
        current_csi = arr
        last_rssi = rssi_val
        time_history.append(now)

        # Считаем дисперсию последних кадров (энергия возмущения)
        if len(csi_history) >= 5:
            recent = np.array(list(csi_history)[-8:])
            var_val = float(np.mean(np.var(recent, axis=0)))
        else:
            var_val = 0.05
        energy_history.append(var_val)


# ---------------------------------------------------------------------------
#  ИСТОЧНИКИ ДАННЫХ
# ---------------------------------------------------------------------------
def run_simulation():
    """Синтезирует честный физический отклик CSI при появлении человека."""
    print("[SIM] Запущена симуляция. Человек циклически входит/выходит...")
    t = 0.0
    while True:
        time.sleep(0.04)  # ~25 кадров в секунду
        t += 0.04
        cycle = t % 30.0

        # Статичный профиль комнаты (многолучевое затухание)
        static_profile = 20.0 + 7.0 * np.sin(np.linspace(0, 3 * np.pi, NUM_SUBCARRIERS))

        if 6.0 < cycle < 16.0:
            # ЧЕЛОВЕК ИДЕТ: мощные интерференционные колебания по поднесущим
            multipath = 6.0 * np.sin(t * 7.0 + np.linspace(0, 5 * np.pi, NUM_SUBCARRIERS))
            noise = np.random.normal(0, 0.8, NUM_SUBCARRIERS)
            frame = static_profile + multipath + noise
            rssi = -52 + int(np.random.normal(0, 3))
        elif 16.0 <= cycle <= 24.0:
            # ЧЕЛОВЕК СИДИТ И ДЫШИТ: узкая гармоника (~0.33 Гц)
            breath = 1.3 * np.sin(t * 2 * np.pi * 0.33 + np.linspace(0, np.pi, NUM_SUBCARRIERS))
            noise = np.random.normal(0, 0.2, NUM_SUBCARRIERS)
            frame = static_profile + breath + noise
            rssi = -50
        else:
            # ПУСТАЯ КОМНАТА: стационарный шум
            noise = np.random.normal(0, 0.15, NUM_SUBCARRIERS)
            frame = static_profile + noise
            rssi = -49

        push_csi_frame(frame, rssi)


def run_serial(port, baud=115200):
    """Читает CSI поток через USB Serial порт."""
    import serial
    print(f"[SERIAL] Открытие {port} на скорости {baud}...")
    ser = serial.Serial(port, baud, timeout=1)
    while True:
        try:
            line = ser.readline().decode("utf-8", errors="ignore").strip()
            if not line:
                continue

            # Формат 1: CSV строка вида "CSI,rssi,amp0,amp1,...,amp63"
            if line.startswith("CSI,") or line.startswith("CSI:"):
                parts = line.split(",")[1:]
                rssi = int(parts[0])
                amps = [float(x) for x in parts[1:]]
                push_csi_frame(amps, rssi)

            # Формат 2: JSON строка вида {"csi":[...],"rssi":-50}
            elif line.startswith("{") and "csi" in line:
                d = json.loads(line)
                push_csi_frame(d["csi"], d.get("rssi", -55))
        except Exception:
            pass


def run_websocket(url):
    """Читает CSI поток по WebSocket."""
    import websocket
    print(f"[WS] Подключение к {url}...")

    def on_message(ws, msg):
        try:
            d = json.loads(msg)
            if "csi" in d:
                push_csi_frame(d["csi"], d.get("rssi", -55))
        except Exception:
            pass

    def start():
        ws = websocket.WebSocketApp(url, on_message=on_message)
        ws.run_forever()

    threading.Thread(target=start, daemon=True).start()


# ---------------------------------------------------------------------------
#  МАТПЛОТЛИБ ДАШБОРД В РЕАЛЬНОМ ВРЕМЕНИ
# ---------------------------------------------------------------------------
def main_gui():
    plt.style.use("dark_background")
    fig = plt.figure(figsize=(12, 8))
    fig.canvas.manager.set_window_title("ESP32 Wi-Fi CSI Live Inspector")
    gs = fig.add_gridspec(3, 1, height_ratios=[1.3, 1.0, 0.8])

    # 1. Водопад (Heatmap / Спектрограмма)
    ax_waterfall = fig.add_subplot(gs[0])
    ax_waterfall.set_title("1. CSI WATERFALL (СПЕКТРОГРАММА ВО ВРЕМЕНИ)", color="#00e5ff", fontsize=11, fontweight="bold")
    ax_waterfall.set_ylabel("Кадры времени (История)")
    ax_waterfall.set_xlabel("Номер поднесущей (1..64 OFDM)")
    im_waterfall = ax_waterfall.imshow(np.zeros((HISTORY_LEN, NUM_SUBCARRIERS)),
                                       aspect="auto", cmap="plasma", vmin=10, vmax=35)
    cbar = plt.colorbar(im_waterfall, ax=ax_waterfall, pad=0.01)
    cbar.set_label("Амплитуда", color="#ccc")

    # 2. Мгновенный профиль поднесущих
    ax_spectrum = fig.add_subplot(gs[1])
    ax_spectrum.set_title("2. ТЕКУЩИЙ ПРОФИЛЬ ПОДНЕСУЩИХ (МГНОВЕННЫЙ СПЕКТР)", color="#00ff66", fontsize=11, fontweight="bold")
    ax_spectrum.set_ylabel("Амплитуда |H(f)|")
    ax_spectrum.set_xlabel("Поднесущая")
    ax_spectrum.set_ylim(5, 40)
    ax_spectrum.grid(True, linestyle="--", alpha=0.3)
    line_spec, = ax_spectrum.plot(range(NUM_SUBCARRIERS), np.zeros(NUM_SUBCARRIERS),
                                  color="#00ff66", lw=2, marker="o", markersize=3)

    # 3. Энергия возмущения во времени (Детекция движения)
    ax_energy = fig.add_subplot(gs[2])
    ax_energy.set_title("3. ВАРИАЦИЯ СИГНАЛА / ДВИЖЕНИЕ (ДИСПЕРСИЯ ПО ВСЕМ ПОДНЕСУЩИМ)", color="#ff9900", fontsize=11, fontweight="bold")
    ax_energy.set_ylabel("CSI Variance")
    ax_energy.set_xlabel("Время (сек)")
    ax_energy.set_ylim(-0.1, 5.0)
    ax_energy.grid(True, linestyle="--", alpha=0.3)
    line_energy, = ax_energy.plot([], [], color="#ff9900", lw=2.2, label="CSI Perturbation")
    line_thresh = ax_energy.axhline(0.6, color="#ff3333", linestyle="--", label="Порог детекции (Человек в зоне)")
    ax_energy.legend(loc="upper right", fontsize=8)

    status_hud = fig.text(0.02, 0.965, "ИНИЦИАЛИЗАЦИЯ...", fontsize=12, fontweight="bold", color="#fff")

    plt.tight_layout()

    def update(_):
        with data_lock:
            if not csi_history:
                return

            arr = np.array(list(csi_history))
            # Динамическая автоподстройка контраста водопада
            im_waterfall.set_data(arr)
            im_waterfall.set_clim(vmin=np.percentile(arr, 3), vmax=np.percentile(arr, 97))

            # Текущий спектр
            line_spec.set_ydata(arr[-1])

            # Энергия возмущения
            t_data = list(time_history)
            e_data = list(energy_history)
            if len(t_data) > 1:
                line_energy.set_data(t_data, e_data)
                ax_energy.set_xlim(t_data[0], t_data[-1] + 0.1)

                cur_e = e_data[-1]
                if cur_e > 1.2:
                    status_hud.set_text(f"🔴 ЧЕЛОВЕК ДВИЖЕТСЯ! (CSI возмущение = {cur_e:.2f} | RSSI = {last_rssi} dBm)")
                    status_hud.set_color("#ff3333")
                elif cur_e > 0.4:
                    status_hud.set_text(f"🟡 МИКРО-ДВИЖЕНИЕ / ДЫХАНИЕ (CSI возмущение = {cur_e:.2f} | RSSI = {last_rssi} dBm)")
                    status_hud.set_color("#ffcc00")
                else:
                    status_hud.set_text(f"🟢 ПУСТАЯ КОМНАТА / ШУМ (CSI возмущение = {cur_e:.2f} | RSSI = {last_rssi} dBm)")
                    status_hud.set_color("#00ff66")

    anim = FuncAnimation(fig, update, interval=40, blit=False)
    plt.show()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Live Wi-Fi CSI Monitor")
    parser.add_argument("--sim", action="store_true", help="Режим симуляции (без платы)")
    parser.add_argument("--serial", type=str, help="Порт Serial (например: /dev/cu.usbmodem1101)")
    parser.add_argument("--baud", type=int, default=115200, help="Скорость Serial")
    parser.add_argument("--ws", type=str, help="URL сокета (например: ws://192.168.1.15:81)")
    args = parser.parse_args()

    if args.serial:
        threading.Thread(target=run_serial, args=(args.serial, args.baud), daemon=True).start()
    elif args.ws:
        run_websocket(args.ws)
    else:
        threading.Thread(target=run_simulation, daemon=True).start()

    main_gui()
