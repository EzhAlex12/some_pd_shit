#!/usr/bin/env python3
# ============================================================================
#  SINGLE BOARD CSI LIVE VIEWER · ESP32-S3
# ============================================================================
#  Скрипт для работы с ОДНОЙ платой ESP32-S3.
#  - Автоматически находит USB-порт платы
#  - Читает 64 поднесущие CSI
#  - Выводит живой водопад (спектрограмму) и график амплитуд
#  - Фильтрует шум и детектирует реальное движение человека
#
#  Запуск:
#    python3 backend/single_csi.py                # автопоиск порта или симуляция
#    python3 backend/single_csi.py --save log.csv  # с записью данных в файл
#    python3 backend/single_csi.py --threshold 2.8 # калибровка порога движения
# ============================================================================

import sys
import os
import time
import json
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
frame_times = deque(maxlen=30)
last_rssi = -60
start_time = time.time()
save_file = None
smoothed_variance = 0.0
VAR_WINDOW = 12          # кадров для дисперсии
source_label = "ИНИЦИАЛИЗАЦИЯ"   # что сейчас является источником данных (показывается в HUD)
source_error = None              # текст ошибки источника (порт отвалился и т.п.)

# Буфер истории НЕ заполняется фейковым фоном: иначе первые кадры с реальной
# платы (другой уровень амплитуд) дают огромную дисперсию и ложное «движение».


def push_frame(amps, rssi_val):
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

        # Вычисляем дисперсию поднесущих за последние 12 кадров (~0.48 сек при 25 Гц)
        # Окно из 12 кадров отсекает одиночные случайные всплески радиопомех.
        # Пока окно не набралось, движение не оцениваем (0), а не выдумываем значение.
        if len(csi_history) >= VAR_WINDOW:
            recent = np.array(list(csi_history)[-VAR_WINDOW:])
            var_raw = float(np.mean(np.var(recent, axis=0)))
            # Экспоненциальное сглаживание (EMA) для устранения ложных срабатываний
            smoothed_variance = 0.75 * smoothed_variance + 0.25 * var_raw
        energy_history.append(smoothed_variance)

        if save_file:
            row = [f"{rel_time:.3f}", str(rssi_val)] + [f"{x:.1f}" for x in arr]
            save_file.write(",".join(row) + "\n")
            save_file.flush()


# USB VID типичных мостов/чипов на платах ESP32: Espressif (нативный USB-CDC S2/S3/C3),
# Silicon Labs CP210x, WCH CH340/CH9102, FTDI.
ESP_USB_VIDS = {0x303A, 0x10C4, 0x1A86, 0x0403}


def auto_detect_serial():
    """Ищет порт ESP32 на macOS / Windows / Linux. Возвращает имя порта или None."""
    try:
        from serial.tools import list_ports
    except ImportError:
        print("[!] pyserial не установлен (pip install pyserial) — автопоиск порта невозможен")
        return None
    ports = list(list_ports.comports())
    for p in ports:
        if p.vid in ESP_USB_VIDS:
            return p.device
    # запасной вариант — по имени устройства
    for p in ports:
        if any(k in p.device for k in ("usbmodem", "usbserial", "wchusbserial", "SLAB", "ttyACM", "ttyUSB")):
            return p.device
    return None


def parse_line(line):
    """Разбирает строку платы. Возвращает (amps, rssi) или None."""
    if line.startswith("CSI,") or line.startswith("CSI:"):
        parts = line[4:].split(",")
        rssi = int(parts[0])
        amps = [float(x) for x in parts[1:]]
        return amps, rssi
    if line.startswith("{") and "csi" in line:
        d = json.loads(line)
        return d["csi"], d.get("rssi", -55)
    return None


def serial_reader(port, baud=115200):
    global source_error
    import serial
    print(f"[*] Открываем порт {port} на скорости {baud}...")
    try:
        ser = serial.Serial(port, baud, timeout=1)
    except Exception as e:
        print(f"[!] Ошибка открытия порта {port}: {e}")
        source_error = f"порт {port} не открылся"
        return

    bad_lines = 0
    while True:
        try:
            raw = ser.readline()
        except serial.SerialException as e:
            # плату выдернули / порт пропал — выходим, а не крутим пустой цикл на 100% CPU
            print(f"[!] Порт {port} потерян: {e}")
            source_error = f"порт {port} потерян"
            return
        line = raw.decode("utf-8", errors="ignore").strip()
        if not line:
            continue
        try:
            parsed = parse_line(line)
        except (ValueError, KeyError, IndexError) as e:
            bad_lines += 1
            if bad_lines <= 5:
                print(f"[!] Не удалось разобрать строку ({e}): {line[:80]}")
            continue
        if parsed:
            push_frame(*parsed)


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
            # Человек идет рядом с платой (активное движение, вариация ~3.5 - 5.0)
            multipath = 6.0 * np.sin(t * 8.0 + np.linspace(0, 4 * np.pi, NUM_SUBCARRIERS))
            noise = np.random.normal(0, 0.7, NUM_SUBCARRIERS)
            frame = base + multipath + noise
            rssi = -52 + int(np.random.normal(0, 2))
        elif 14.0 <= cycle <= 20.0:
            # Человек сидит и дышит / легкие движения рук (вариация ~1.2)
            breath = 1.3 * np.sin(t * 2 * np.pi * 0.33)
            noise = np.random.normal(0, 0.2, NUM_SUBCARRIERS)
            frame = base + breath + noise
            rssi = -50
        else:
            # Пустая комната / покой (вариация ~0.2)
            noise = np.random.normal(0, 0.15, NUM_SUBCARRIERS)
            frame = base + noise
            rssi = -49
        push_frame(frame, rssi)


def main():
    global save_file
    parser = argparse.ArgumentParser(description="Single ESP32 CSI Monitor")
    parser.add_argument("--port", type=str, help="USB Serial порт (например /dev/cu.usbmodem1101)")
    parser.add_argument("--baud", type=int, default=115200, help="Скорость порта Serial (по умолчанию 115200)")
    parser.add_argument("--save", type=str, help="Имя CSV-файла для записи потока")
    parser.add_argument("--threshold", type=float, default=2.5,
                        help="Порог вариации для активного движения (по умолчанию 2.5)")
    parser.add_argument("--sim", action="store_true", help="Принудительно запустить симуляцию")
    args = parser.parse_args()

    if args.save:
        save_file = open(args.save, "w", encoding="utf-8")
        headers = ["time", "rssi"] + [f"sub_{i}" for i in range(NUM_SUBCARRIERS)]
        save_file.write(",".join(headers) + "\n")
        print(f"[*] Данные будут записываться в: {args.save}")

    global source_label
    port = None if args.sim else (args.port or auto_detect_serial())
    is_sim = port is None
    if is_sim:
        source_label = "СИМУЛЯЦИЯ (--sim)" if args.sim else "СИМУЛЯЦИЯ — ПЛАТА НЕ НАЙДЕНА"
        threading.Thread(target=sim_reader, daemon=True).start()
    else:
        source_label = f"ПЛАТА {port}"
        threading.Thread(target=serial_reader, args=(port, args.baud), daemon=True).start()

    # GUI настройки темной темы
    plt.style.use("dark_background")
    fig = plt.figure(figsize=(11, 7.2), facecolor="#090d14")
    fig.canvas.manager.set_window_title(
        "1x ESP32 CSI Live Monitor" + ("  —  !!! СИМУЛЯЦИЯ, НЕ РЕАЛЬНЫЕ ДАННЫЕ !!!" if is_sim else f"  —  {port}"))

    # Сетка: top=0.81 оставляет 19% высоты под HUD (заголовок + статусная строка).
    # width_ratios=[0.97, 0.03] даёт отдельную ось для колорбара cax, благодаря чему
    # ax1 и ax2 идеально совпадают по ширине и их границы никогда не смещаются.
    gs = fig.add_gridspec(
        2, 2,
        height_ratios=[1.2, 1.0],
        width_ratios=[0.97, 0.03],
        left=0.08, right=0.92,
        top=0.81, bottom=0.09,
        hspace=0.38, wspace=0.025
    )

    # 1. Водопад (Тепловая карта во времени)
    ax1 = fig.add_subplot(gs[0, 0], facecolor="#06090e")
    cax = fig.add_subplot(gs[0, 1])
    ax1.set_title("1. CSI ВОДОПАД (ТЕПЛОВАЯ КАРТА ПОДНЕСУЩИХ ВО ВРЕМЕНИ)",
                  color="#00e5ff", fontsize=10, fontweight="bold", loc="left", pad=8)
    ax1.set_ylabel("Время (кадры)", color="#94a3b8", fontsize=9)
    ax1.tick_params(colors="#64748b", labelsize=8)
    ax1.set_xticklabels([])

    im = ax1.imshow(np.zeros((HISTORY_LEN, NUM_SUBCARRIERS)), aspect="auto", cmap="turbo")
    cb = plt.colorbar(im, cax=cax)
    cb.ax.tick_params(colors="#64748b", labelsize=7)
    cb.set_label("Ампл.", color="#94a3b8", fontsize=8)

    # 2. Мгновенная амплитуда
    ax2 = fig.add_subplot(gs[1, 0], facecolor="#06090e")
    ax2.set_title("2. МГНОВЕННАЯ АМПЛИТУДА ПОДНЕСУЩИХ |H(f)|",
                  color="#00ff66", fontsize=10, fontweight="bold", loc="left", pad=8)
    ax2.set_ylabel("Амплитуда", color="#94a3b8", fontsize=9)
    ax2.set_xlabel("Номер поднесущей OFDM (1..64)", color="#94a3b8", fontsize=9)
    ax2.set_xlim(0, NUM_SUBCARRIERS - 1)
    ax2.set_ylim(0, 42)
    ax2.grid(True, linestyle="--", alpha=0.25, color="#334155")
    ax2.tick_params(colors="#64748b", labelsize=8)
    line, = ax2.plot(range(NUM_SUBCARRIERS), np.zeros(NUM_SUBCARRIERS), color="#00ff66", lw=2)

    # Единая верхняя панель (HUD): размещена строго выше графиков (y >= 0.89)
    # Источник данных — прямо в заголовке, чтобы симуляцию нельзя было принять за реальную плату
    title_txt = fig.text(0.5, 0.955, f"ESP32-S3  •  CSI РАДАР  •  ИСТОЧНИК: {source_label}",
                         fontsize=12, fontweight="bold", ha="center", va="center",
                         color="#e879f9" if is_sim else "#38bdf8")
    status_txt = fig.text(0.5, 0.895, "[ ИНИЦИАЛИЗАЦИЯ... ]   |   RSSI: -- dBm   |   ВАРИАЦИЯ: --   |   ЧАСТОТА: -- Гц",
                          fontsize=10.5, fontweight="bold", ha="center", va="center", color="#94a3b8")

    def update(_):
        with data_lock:
            stale = not frame_times or (time.time() - frame_times[-1]) > 2.0
            if stale:
                why = source_error or "нет кадров от платы (проверьте прошивку / Wi-Fi / порт)"
                status_txt.set_text(f"[ НЕТ ДАННЫХ ]   |   {why}")
                status_txt.set_color("#94a3b8")
                if not csi_history:
                    return
            if not csi_history:
                return

            rows = np.array(list(csi_history))
            # недостающие строки водопада — NaN (пусто), а не выдуманный фон
            arr = np.full((HISTORY_LEN, NUM_SUBCARRIERS), np.nan)
            arr[-len(rows):] = rows
            im.set_data(arr)
            vmin = np.percentile(rows, 3)
            vmax = np.percentile(rows, 97)
            if vmax - vmin < 2.0:
                vmax = vmin + 4.0
            im.set_clim(vmin=vmin, vmax=vmax)
            if stale:
                return

            # Обновление мгновенного спектра
            line.set_ydata(rows[-1])

            # Расчет реальной частоты пакетов
            fps = 0.0
            if len(frame_times) >= 6:
                dt = frame_times[-1] - frame_times[0]
                if dt > 0.05:
                    fps = (len(frame_times) - 1) / dt

            # Обновление статуса детекции движения
            if len(csi_history) < VAR_WINDOW:
                status_txt.set_text(f"[ НАКОПЛЕНИЕ КАДРОВ {len(csi_history)}/{VAR_WINDOW} ]   |   RSSI: {last_rssi:3d} dBm")
                status_txt.set_color("#94a3b8")
            elif energy_history:
                cur_var = energy_history[-1]
                motion_threshold = args.threshold
                if cur_var >= motion_threshold:
                    status_txt.set_text(
                        f"[ ВНИМАНИЕ: АКТИВНОЕ ДВИЖЕНИЕ ]   |   RSSI: {last_rssi:3d} dBm   |   ВАРИАЦИЯ: {cur_var:.2f} (порог {motion_threshold:.1f})   |   ЧАСТОТА: {fps:.0f} Гц"
                    )
                    status_txt.set_color("#ef4444")
                elif cur_var >= 0.75:
                    status_txt.set_text(
                        f"[ МИКРО-ДВИЖЕНИЕ / ПОКОЙ ]   |   RSSI: {last_rssi:3d} dBm   |   ВАРИАЦИЯ: {cur_var:.2f} (порог {motion_threshold:.1f})   |   ЧАСТОТА: {fps:.0f} Гц"
                    )
                    status_txt.set_color("#f59e0b")
                else:
                    status_txt.set_text(
                        f"[ ЗОНА СВОБОДНА / ПОКОЙ ]   |   RSSI: {last_rssi:3d} dBm   |   ВАРИАЦИЯ: {cur_var:.2f} (порог {motion_threshold:.1f})   |   ЧАСТОТА: {fps:.0f} Гц"
                    )
                    status_txt.set_color("#10b981")

    anim = FuncAnimation(fig, update, interval=40, blit=False)
    plt.show()

    if save_file:
        save_file.close()


if __name__ == "__main__":
    main()
