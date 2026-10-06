#!/usr/bin/env python3
# ============================================================================
#  SINGLE BOARD CSI LIVE VIEWER · ESP32-S3
# ============================================================================
#  Скрипт для работы с ОДНОЙ платой ESP32.
#  - Автоматически находит USB-порт платы
#  - Читает 64 поднесущие CSI
#  - Выводит живой водопад (спектрограмму) и график амплитуд
#
#  Запуск:
#    python3 backend/single_csi.py                # автопоиск порта или симуляция
#    python3 backend/single_csi.py --save log.csv  # с записью данных в файл
# ============================================================================

import sys
import os
import glob
import time
import argparse
import threading
from collections import deque
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

NUM_SUBCARRIERS = 64
HISTORY_LEN     = 100

data_lock = threading.Lock()
csi_history = deque(maxlen=HISTORY_LEN)
current_csi = np.zeros(NUM_SUBCARRIERS)
energy_history = deque(maxlen=200)
time_history = deque(maxlen=200)
last_rssi = -60
start_time = time.time()
save_file = None

# Заполнение буфера начальным фоном
for _ in range(HISTORY_LEN):
    csi_history.append(np.ones(NUM_SUBCARRIERS) * 18.0 + np.random.normal(0, 0.1, NUM_SUBCARRIERS))


def push_frame(amps, rssi_val):
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

        # Вариация последних 6 кадров (порог движения)
        if len(csi_history) >= 5:
            recent = np.array(list(csi_history)[-6:])
            var_val = float(np.mean(np.var(recent, axis=0)))
        else:
            var_val = 0.05
        energy_history.append(var_val)

        if save_file:
            row = [f"{now:.3f}", str(rssi_val)] + [f"{x:.1f}" for x in arr]
            save_file.write(",".join(row) + "\n")


def auto_detect_serial():
    ports = glob.glob("/dev/cu.usb*") + glob.glob("/dev/cu.wch*") + glob.glob("/dev/cu.SLAB*")
    return ports[0] if ports else None


def serial_reader(port, baud=115200):
    import serial
    print(f"[*] Открываем порт {port} на скорости {baud}...")
    ser = serial.Serial(port, baud, timeout=1)
    while True:
        try:
            line = ser.readline().decode("utf-8", errors="ignore").strip()
            if line.startswith("CSI,"):
                parts = line.split(",")[1:]
                rssi = int(parts[0])
                amps = [float(x) for x in parts[1:]]
                push_frame(amps, rssi)
        except Exception:
            pass


def sim_reader():
    print("[*] Плата по USB пока не обнаружена -> запущен демонстрационный режим.")
    print("    (Подключите ESP32 по кабелю Type-C и перезапустите для реальных данных)")
    t = 0.0
    while True:
        time.sleep(0.04)
        t += 0.04
        cycle = t % 25.0
        base = 20.0 + 6.0 * np.sin(np.linspace(0, 3 * np.pi, NUM_SUBCARRIERS))

        if 6.0 < cycle < 14.0:
            # Человек идет рядом с платой
            multipath = 6.0 * np.sin(t * 8.0 + np.linspace(0, 4 * np.pi, NUM_SUBCARRIERS))
            noise = np.random.normal(0, 0.7, NUM_SUBCARRIERS)
            frame = base + multipath + noise
            rssi = -52 + int(np.random.normal(0, 2))
        elif 14.0 <= cycle <= 20.0:
            # Человек сидит и дышит
            breath = 1.2 * np.sin(t * 2 * np.pi * 0.33)
            noise = np.random.normal(0, 0.15, NUM_SUBCARRIERS)
            frame = base + breath + noise
            rssi = -50
        else:
            # Пустая комната
            noise = np.random.normal(0, 0.15, NUM_SUBCARRIERS)
            frame = base + noise
            rssi = -49
        push_frame(frame, rssi)


def main():
    global save_file
    parser = argparse.ArgumentParser(description="Single ESP32 CSI Monitor")
    parser.add_argument("--port", type=str, help="USB Serial порт (например /dev/cu.usbmodem1101)")
    parser.add_argument("--save", type=str, help="Имя CSV-файла для записи потока")
    parser.add_argument("--sim", action="store_true", help="Принудительно запустить симуляцию")
    args = parser.parse_args()

    if args.save:
        save_file = open(args.save, "w", encoding="utf-8")
        headers = ["time", "rssi"] + [f"sub_{i}" for i in range(NUM_SUBCARRIERS)]
        save_file.write(",".join(headers) + "\n")
        print(f"[*] Данные будут записываться в: {args.save}")

    port = args.port or auto_detect_serial()
    if args.sim or not port:
        threading.Thread(target=sim_reader, daemon=True).start()
    else:
        threading.Thread(target=serial_reader, args=(port,), daemon=True).start()

    # GUI
    plt.style.use("dark_background")
    fig = plt.figure(figsize=(11, 7))
    fig.canvas.manager.set_window_title("1x ESP32 CSI Live Monitor")
    gs = fig.add_gridspec(2, 1, height_ratios=[1.3, 1.0])

    ax1 = fig.add_subplot(gs[0])
    ax1.set_title("CSI ВОДОПАД (ТЕПЛОВАЯ КАРТА ПОДНЕСУЩИХ ВО ВРЕМЕНИ)", color="#00e5ff", fontsize=10, fontweight="bold")
    ax1.set_ylabel("Время (кадры)")
    ax1.set_xlabel("Номер поднесущей (1..64)")
    im = ax1.imshow(np.zeros((HISTORY_LEN, NUM_SUBCARRIERS)), aspect="auto", cmap="plasma")
    plt.colorbar(im, ax=ax1, pad=0.01)

    ax2 = fig.add_subplot(gs[1])
    ax2.set_title("МГНОВЕННАЯ АМПЛИТУДА ПОДНЕСУЩИХ |H(f)|", color="#00ff66", fontsize=10, fontweight="bold")
    ax2.set_ylabel("Амплитуда")
    ax2.set_xlabel("Поднесущая")
    ax2.set_ylim(5, 38)
    ax2.grid(True, linestyle="--", alpha=0.3)
    line, = ax2.plot(range(NUM_SUBCARRIERS), np.zeros(NUM_SUBCARRIERS), color="#00ff66", lw=2)

    status_txt = fig.text(0.02, 0.96, "СТАТУС: ИНИЦИАЛИЗАЦИЯ...", fontsize=11, fontweight="bold", color="#fff")

    plt.tight_layout()

    def update(_):
        with data_lock:
            if not csi_history: return
            arr = np.array(list(csi_history))
            im.set_data(arr)
            im.set_clim(vmin=np.percentile(arr, 3), vmax=np.percentile(arr, 97))
            line.set_ydata(arr[-1])

            if energy_history:
                cur_var = energy_history[-1]
                if cur_var > 1.0:
                    status_txt.set_text(f"🔴 ЧЕЛОВЕК ДВИЖЕТСЯ (CSI вариация: {cur_var:.2f} | RSSI: {last_rssi} dBm)")
                    status_txt.set_color("#ff3333")
                elif cur_var > 0.35:
                    status_txt.set_text(f"🟡 МИКРО-ДВИЖЕНИЕ / ДЫХАНИЕ (CSI вариация: {cur_var:.2f} | RSSI: {last_rssi} dBm)")
                    status_txt.set_color("#ffcc00")
                else:
                    status_txt.set_text(f"🟢 ПУСТАЯ ЗОНА (CSI вариация: {cur_var:.2f} | RSSI: {last_rssi} dBm)")
                    status_txt.set_color("#00ff66")

    anim = FuncAnimation(fig, update, interval=40, blit=False)
    plt.show()

    if save_file:
        save_file.close()


if __name__ == "__main__":
    main()
