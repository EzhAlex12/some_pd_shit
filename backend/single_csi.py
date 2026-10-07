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
    fig = plt.figure(figsize=(12, 7.5), facecolor="#090d14")
    fig.canvas.manager.set_window_title("1x ESP32 CSI Live Monitor")

    # Сетка с явными безопасными отступами: сверху top=0.86 оставляет место для HUD, hspace=0.36 разделяет графики
    gs = fig.add_gridspec(
        2, 1,
        height_ratios=[1.25, 1.0],
        top=0.86, bottom=0.09,
        left=0.08, right=0.93,
        hspace=0.36
    )

    # Верхняя HUD-панель (y=0.93 гарантированно выше графика top=0.86, ничего не наезжает!)
    fig.text(0.08, 0.93, "ESP32-S3 CSI RADAR", fontsize=12, fontweight="bold", color="#38bdf8")
    status_txt = fig.text(0.32, 0.93, "[ ИНИЦИАЛИЗАЦИЯ... ]", fontsize=11, fontweight="bold", color="#38bdf8")
    stats_txt = fig.text(0.93, 0.93, "RSSI: -- dBm  |  VAR: --", fontsize=10, color="#94a3b8", ha="right")

    # 1. Водопад (убираем нижние деления x-axis, чтобы исключить наложение на заголовок нижнего графика)
    ax1 = fig.add_subplot(gs[0], facecolor="#06090e")
    ax1.set_title("1. CSI WATERFALL (ТЕПЛОВАЯ КАРТА ПОДНЕСУЩИХ ВО ВРЕМЕНИ)", color="#00e5ff", fontsize=10, fontweight="bold", pad=8, loc="left")
    ax1.set_ylabel("Время (кадры)", color="#94a3b8", fontsize=9)
    ax1.tick_params(colors="#64748b", labelsize=8)
    ax1.set_xticklabels([])

    im = ax1.imshow(np.zeros((HISTORY_LEN, NUM_SUBCARRIERS)), aspect="auto", cmap="turbo")
    cbar = plt.colorbar(im, ax=ax1, pad=0.015, aspect=20)
    cbar.ax.tick_params(colors="#64748b", labelsize=7)
    cbar.set_label("Амплитуда", color="#94a3b8", fontsize=8)

    # 2. Мгновенный спектр
    ax2 = fig.add_subplot(gs[1], facecolor="#06090e")
    ax2.set_title("2. МГНОВЕННАЯ АМПЛИТУДА ПОДНЕСУЩИХ |H(f)|", color="#00ff66", fontsize=10, fontweight="bold", pad=8, loc="left")
    ax2.set_ylabel("Амплитуда", color="#94a3b8", fontsize=9)
    ax2.set_xlabel("Номер поднесущей OFDM (1..64)", color="#94a3b8", fontsize=9)
    ax2.set_xlim(0, NUM_SUBCARRIERS - 1)
    ax2.set_ylim(0, 40)
    ax2.grid(True, linestyle="--", alpha=0.2, color="#334155")
    ax2.tick_params(colors="#64748b", labelsize=8)
    (line,) = ax2.plot(range(NUM_SUBCARRIERS), np.zeros(NUM_SUBCARRIERS), color="#00ff66", lw=2)

    def update(_):
        with data_lock:
            if not csi_history:
                return
            arr = np.array(list(csi_history))
            im.set_data(arr)
            vmin = np.percentile(arr, 3)
            vmax = np.percentile(arr, 97)
            if vmax - vmin < 0.5:
                vmax = vmin + 2.0
            im.set_clim(vmin=vmin, vmax=vmax)

            line.set_ydata(arr[-1])
            ymax = float(np.max(arr[-1]))
            if ymax > ax2.get_ylim()[1] * 0.88:
                ax2.set_ylim(0, max(40.0, ymax * 1.25))

            if energy_history:
                cur_var = energy_history[-1]
                stats_txt.set_text(f"RSSI: {last_rssi:3d} dBm  |  VAR: {cur_var:.2f}")
                if cur_var > 1.0:
                    status_txt.set_text("[ ДВИЖЕНИЕ ОБНАРУЖЕНО ]")
                    status_txt.set_color("#ef4444")
                elif cur_var > 0.35:
                    status_txt.set_text("[ МИКРО-ДВИЖЕНИЕ / ДЫХАНИЕ ]")
                    status_txt.set_color("#f59e0b")
                else:
                    status_txt.set_text("[ СПОКОЙНАЯ ЗОНА ]")
                    status_txt.set_color("#22c55e")

    anim = FuncAnimation(fig, update, interval=40, blit=False, cache_frame_data=False)
    plt.show()


    if save_file:
        save_file.close()


if __name__ == "__main__":
    main()
