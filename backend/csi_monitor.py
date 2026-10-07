#!/usr/bin/env python3
# ============================================================================
#  REAL-TIME ESP32 WIFI CSI VISUALIZER & MONITOR
# ============================================================================
#  Скрипт для живой визуализации сырых поднесущих Wi-Fi CSI (OFDM 64 subcarriers).
#  - Водопад поднесущих во времени
#  - Мгновенный профиль амплитуд
#  - Дисперсия возмущения во времени (детекция движения человека)
#
#  Запуск:
#    1. Симуляция:
#       python3 backend/csi_monitor.py --sim
#
#    2. По проводу через USB Serial:
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
frame_times = deque(maxlen=30)
last_rssi = -60
start_time = time.time()
smoothed_variance = 0.0

# Заполняем начальную историю тишиной
for _ in range(HISTORY_LEN):
    csi_history.append(np.ones(NUM_SUBCARRIERS) * 15.0 + np.random.normal(0, 0.1, NUM_SUBCARRIERS))


def push_csi_frame(amps, rssi_val=-55):
    """Добавляет новый кадр поднесущих в буфер отрисовки."""
    global current_csi, last_rssi, smoothed_variance
    arr = np.array(amps, dtype=float)
    if len(arr) != NUM_SUBCARRIERS:
        arr = np.interp(np.linspace(0, 1, NUM_SUBCARRIERS),
                        np.linspace(0, 1, len(arr)), arr)

    now = time.time()
    rel_time = now - start_time
    with data_lock:
        csi_history.append(arr)
        current_csi = arr
        last_rssi = rssi_val
        time_history.append(rel_time)
        frame_times.append(now)

        # Дисперсия за последние 12 кадров (~0.48 с при 25 Гц)
        if len(csi_history) >= 8:
            recent = np.array(list(csi_history)[-12:])
            var_raw = float(np.mean(np.var(recent, axis=0)))
        else:
            var_raw = 0.05

        # EMA фильтрация
        smoothed_variance = 0.75 * smoothed_variance + 0.25 * var_raw
        energy_history.append(smoothed_variance)


# ---------------------------------------------------------------------------
#  ИСТОЧНИКИ ДАННЫХ
# ---------------------------------------------------------------------------
def run_simulation():
    """Синтезирует физический отклик CSI при появлении человека."""
    print("[SIM] Запущена симуляция. Человек циклически входит/выходит...")
    t = 0.0
    while True:
        time.sleep(0.04)  # ~25 кадров в секунду
        t += 0.04
        cycle = t % 30.0

        # Статичный профиль комнаты
        static_profile = 20.0 + 7.0 * np.sin(np.linspace(0, 3 * np.pi, NUM_SUBCARRIERS))

        if 6.0 < cycle < 16.0:
            # ЧЕЛОВЕК ИДЕТ (активное движение, вариация ~3.5 - 5.0)
            multipath = 6.0 * np.sin(t * 7.0 + np.linspace(0, 5 * np.pi, NUM_SUBCARRIERS))
            noise = np.random.normal(0, 0.8, NUM_SUBCARRIERS)
            frame = static_profile + multipath + noise
            rssi = -52 + int(np.random.normal(0, 3))
        elif 16.0 <= cycle <= 24.0:
            # ЧЕЛОВЕК СИДИТ И ДЫШИТ (микро-движение, вариация ~1.2)
            breath = 1.3 * np.sin(t * 2 * np.pi * 0.33 + np.linspace(0, np.pi, NUM_SUBCARRIERS))
            noise = np.random.normal(0, 0.2, NUM_SUBCARRIERS)
            frame = static_profile + breath + noise
            rssi = -50
        else:
            # ПУСТАЯ КОМНАТА (вариация ~0.2)
            noise = np.random.normal(0, 0.15, NUM_SUBCARRIERS)
            frame = static_profile + noise
            rssi = -49

        push_csi_frame(frame, rssi)


def run_serial(port, baud=115200):
    """Читает CSI поток через USB Serial порт."""
    import serial
    print(f"[SERIAL] Открытие {port} на скорости {baud}...")
    try:
        ser = serial.Serial(port, baud, timeout=1)
    except Exception as e:
        print(f"[!] Ошибка открытия порта {port}: {e}")
        return

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
def main_gui(motion_threshold=2.5):
    plt.style.use("dark_background")
    fig = plt.figure(figsize=(11, 8.5), facecolor="#090d14")
    fig.canvas.manager.set_window_title("ESP32 Wi-Fi CSI Live Inspector")

    # Сетка: top=0.83 оставляет место под HUD (заголовок + статус)
    # width_ratios=[0.97, 0.03] даёт выделенную ось cax для колорбара
    gs = fig.add_gridspec(
        3, 2,
        height_ratios=[1.2, 1.0, 0.85],
        width_ratios=[0.97, 0.03],
        left=0.08, right=0.92,
        top=0.83, bottom=0.07,
        hspace=0.42, wspace=0.025
    )

    # 1. Водопад (Heatmap / Спектрограмма)
    ax_waterfall = fig.add_subplot(gs[0, 0], facecolor="#06090e")
    cax = fig.add_subplot(gs[0, 1])
    ax_waterfall.set_title("1. CSI WATERFALL (СПЕКТРОГРАММА ВО ВРЕМЕНИ)",
                           color="#00e5ff", fontsize=10, fontweight="bold", loc="left", pad=8)
    ax_waterfall.set_ylabel("Кадры времени", color="#94a3b8", fontsize=9)
    ax_waterfall.tick_params(colors="#64748b", labelsize=8)
    ax_waterfall.set_xticklabels([])
    im_waterfall = ax_waterfall.imshow(np.zeros((HISTORY_LEN, NUM_SUBCARRIERS)),
                                       aspect="auto", cmap="turbo")
    cbar = plt.colorbar(im_waterfall, cax=cax)
    cbar.ax.tick_params(colors="#64748b", labelsize=7)
    cbar.set_label("Ампл.", color="#94a3b8", fontsize=8)

    # 2. Мгновенный профиль поднесущих
    ax_spectrum = fig.add_subplot(gs[1, 0], facecolor="#06090e")
    ax_spectrum.set_title("2. ТЕКУЩИЙ ПРОФИЛЬ ПОДНЕСУЩИХ (МГНОВЕННЫЙ СПЕКТР)",
                          color="#00ff66", fontsize=10, fontweight="bold", loc="left", pad=8)
    ax_spectrum.set_ylabel("Амплитуда |H(f)|", color="#94a3b8", fontsize=9)
    ax_spectrum.set_xlabel("Номер поднесущей OFDM (1..64)", color="#94a3b8", fontsize=9)
    ax_spectrum.set_xlim(0, NUM_SUBCARRIERS - 1)
    ax_spectrum.set_ylim(0, 42)
    ax_spectrum.grid(True, linestyle="--", alpha=0.25, color="#334155")
    ax_spectrum.tick_params(colors="#64748b", labelsize=8)
    line_spec, = ax_spectrum.plot(range(NUM_SUBCARRIERS), np.zeros(NUM_SUBCARRIERS),
                                  color="#00ff66", lw=2)

    # 3. Энергия возмущения во времени (Детекция движения)
    ax_energy = fig.add_subplot(gs[2, 0], facecolor="#06090e")
    ax_energy.set_title("3. ВАРИАЦИЯ СИГНАЛА / ДЕТЕКЦИЯ ДВИЖЕНИЯ",
                        color="#ff9900", fontsize=10, fontweight="bold", loc="left", pad=8)
    ax_energy.set_ylabel("Вариация", color="#94a3b8", fontsize=9)
    ax_energy.set_xlabel("Время (сек)", color="#94a3b8", fontsize=9)
    ax_energy.set_ylim(-0.2, 6.0)
    ax_energy.grid(True, linestyle="--", alpha=0.25, color="#334155")
    ax_energy.tick_params(colors="#64748b", labelsize=8)
    line_energy, = ax_energy.plot([], [], color="#ff9900", lw=2, label="CSI возмущение")
    ax_energy.axhline(motion_threshold, color="#ff3333", linestyle="--",
                      label=f"Порог движения ({motion_threshold:.1f})")
    ax_energy.axhline(0.75, color="#f59e0b", linestyle=":",
                      label="Порог микро-движения (0.75)")
    ax_energy.legend(loc="upper right", fontsize=8, facecolor="#111827", edgecolor="#374151")

    # Единая верхняя панель (HUD)
    fig.text(0.5, 0.96, "ESP32-S3  •  CSI РАДАР ПРИСУТСТВИЯ И ДВИЖЕНИЯ",
             fontsize=12, fontweight="bold", ha="center", va="center", color="#38bdf8")
    status_hud = fig.text(0.5, 0.90, "[ ИНИЦИАЛИЗАЦИЯ... ]   |   RSSI: -- dBm   |   ВОЗМУЩЕНИЕ: --   |   ЧАСТОТА: -- Гц",
                          fontsize=10.5, fontweight="bold", ha="center", va="center", color="#94a3b8")

    def update(_):
        with data_lock:
            if not csi_history:
                return

            arr = np.array(list(csi_history))
            im_waterfall.set_data(arr)
            vmin = np.percentile(arr, 3)
            vmax = np.percentile(arr, 97)
            if vmax - vmin < 2.0:
                vmax = vmin + 4.0
            im_waterfall.set_clim(vmin=vmin, vmax=vmax)

            # Текущий спектр
            line_spec.set_ydata(arr[-1])

            # Частота кадров
            fps = 0.0
            if len(frame_times) >= 6:
                dt = frame_times[-1] - frame_times[0]
                if dt > 0.05:
                    fps = (len(frame_times) - 1) / dt

            # Энергия возмущения
            t_data = list(time_history)
            e_data = list(energy_history)
            if len(t_data) > 1:
                line_energy.set_data(t_data, e_data)
                ax_energy.set_xlim(t_data[0], t_data[-1] + 0.1)

                cur_e = e_data[-1]
                if cur_e >= motion_threshold:
                    status_hud.set_text(
                        f"[ ВНИМАНИЕ: АКТИВНОЕ ДВИЖЕНИЕ ]   |   RSSI: {last_rssi:3d} dBm   |   ВОЗМУЩЕНИЕ: {cur_e:.2f} (порог {motion_threshold:.1f})   |   ЧАСТОТА: {fps:.0f} Гц"
                    )
                    status_hud.set_color("#ef4444")
                elif cur_e >= 0.75:
                    status_hud.set_text(
                        f"[ МИКРО-ДВИЖЕНИЕ / ПОКОЙ ]   |   RSSI: {last_rssi:3d} dBm   |   ВОЗМУЩЕНИЕ: {cur_e:.2f} (порог {motion_threshold:.1f})   |   ЧАСТОТА: {fps:.0f} Гц"
                    )
                    status_hud.set_color("#f59e0b")
                else:
                    status_hud.set_text(
                        f"[ ЗОНА СВОБОДНА / ПОКОЙ ]   |   RSSI: {last_rssi:3d} dBm   |   ВОЗМУЩЕНИЕ: {cur_e:.2f} (порог {motion_threshold:.1f})   |   ЧАСТОТА: {fps:.0f} Гц"
                    )
                    status_hud.set_color("#10b981")

    anim = FuncAnimation(fig, update, interval=40, blit=False)
    plt.show()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Live Wi-Fi CSI Monitor")
    parser.add_argument("--sim", action="store_true", help="Режим симуляции (без платы)")
    parser.add_argument("--serial", type=str, help="Порт Serial (например: /dev/cu.usbmodem1101)")
    parser.add_argument("--baud", type=int, default=115200, help="Скорость Serial")
    parser.add_argument("--ws", type=str, help="URL сокета (например: ws://192.168.1.15:81)")
    parser.add_argument("--threshold", type=float, default=2.5, help="Порог движения (по умолчанию 2.5)")
    args = parser.parse_args()

    if args.serial:
        threading.Thread(target=run_serial, args=(args.serial, args.baud), daemon=True).start()
    elif args.ws:
        run_websocket(args.ws)
    else:
        threading.Thread(target=run_simulation, daemon=True).start()

    main_gui(motion_threshold=args.threshold)
