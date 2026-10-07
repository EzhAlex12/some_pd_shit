#!/usr/bin/env python3
# ============================================================================
#  DATA PARSER & COLLECTOR · ESP32 CSI / RSSI
# ============================================================================
#  Скрипт для вытаскивания данных с ESP32 и сохранения в CSV файл.
#
#  Поддерживает два режима:
#    1. ПО ВОЗДУХУ (WebSocket):
#       python3 data_parser.py --ws ws://192.168.1.10:81
#       или по mDNS:
#       python3 data_parser.py --ws ws://sgpcsi-0.local:81
#
#    2. ПО ПРОВОДУ (USB Serial):
#       python3 data_parser.py --serial /dev/cu.usbmodem1101
#
#    3. СИМУЛЯЦИЯ (проверить без плат):
#       python3 data_parser.py --sim
# ============================================================================

import sys
import time
import json
import csv
import argparse
from datetime import datetime

OUTPUT_CSV = "collected_data.csv"


def log_to_csv(writer, file_obj, row_dict):
    writer.writerow(row_dict)
    file_obj.flush()


def run_websocket(url, out_file):
    import websocket  # pip install websocket-client
    print(f"[*] Подключение к WebSocket: {url}")
    print(f"[*] Данные будут записываться в: {out_file}")

    with open(out_file, "a", newline="", encoding="utf-8") as f:
        fieldnames = ["timestamp", "node_id", "energy_sigma", "rssi", "presence", "raw_json"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if f.tell() == 0:
            writer.writeheader()

        def on_message(ws, msg):
            try:
                now_str = datetime.now().isoformat()
                d = json.loads(msg)
                node_id = d.get("id", 0)
                energy  = d.get("e", d.get("std", 0.0))
                rssi_val = d.get("rssi", -100)
                pres    = d.get("p", 0)

                # Вывод в терминал
                status_icon = "🔴 ДВИЖЕНИЕ" if pres else "🟢 ТИШИНА"
                print(f"[{now_str}] Нода #{node_id} | RSSI: {rssi_val:3d} dBm | σ(RSSI): {energy:.3f} | {status_icon}")

                # Запись в CSV
                log_to_csv(writer, f, {
                    "timestamp": now_str,
                    "node_id": node_id,
                    "energy_sigma": energy,
                    "rssi": rssi_val,
                    "presence": pres,
                    "raw_json": msg
                })
            except Exception as e:
                print(f"[!] Ошибка парсинга: {e} | Строка: {msg}")

        def on_error(ws, err):
            print(f"[!] Ошибка сокета: {err}")

        def on_close(ws, close_code, close_msg):
            print("[*] Соединение закрыто.")

        ws = websocket.WebSocketApp(url, on_message=on_message, on_error=on_error, on_close=on_close)
        ws.run_forever()


def run_serial(port, baud, out_file):
    import serial  # pip install pyserial
    print(f"[*] Открытие порта {port} на скорости {baud}...")
    print(f"[*] Данные будут записываться в: {out_file}")

    ser = serial.Serial(port, baud, timeout=1)
    with open(out_file, "a", newline="", encoding="utf-8") as f:
        fieldnames = ["timestamp", "raw_line"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if f.tell() == 0:
            writer.writeheader()

        while True:
            try:
                line = ser.readline().decode("utf-8", errors="ignore").strip()
                if not line:
                    continue
                now_str = datetime.now().isoformat()
                print(f"[{now_str}] {line}")
                log_to_csv(writer, f, {"timestamp": now_str, "raw_line": line})
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"[!] Ошибка чтения serial: {e}")


def run_sim(out_file):
    print(f"[*] Режим симуляции (пишем тестовые данные в {out_file})...")
    with open(out_file, "a", newline="", encoding="utf-8") as f:
        fieldnames = ["timestamp", "node_id", "energy_sigma", "rssi", "presence", "raw_json"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if f.tell() == 0:
            writer.writeheader()

        for step in range(50):
            now_str = datetime.now().isoformat()
            is_moving = 15 < step < 35
            sigma = 2.45 if is_moving else 0.41
            rssi_val = -54 if is_moving else -50
            pres = 1 if is_moving else 0

            status_icon = "🔴 ДВИЖЕНИЕ" if pres else "🟢 ТИШИНА"
            print(f"[{now_str}] Нода #0 | RSSI: {rssi_val:3d} dBm | σ(RSSI): {sigma:.3f} | {status_icon}")

            log_to_csv(writer, f, {
                "timestamp": now_str,
                "node_id": 0,
                "energy_sigma": sigma,
                "rssi": rssi_val,
                "presence": pres,
                "raw_json": f'{{"id":0,"e":{sigma},"rssi":{rssi_val},"p":{pres}}}'
            })
            time.sleep(0.1)
    print("[*] Тест завершен! Файл записан.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ESP32 Data Extractor & CSV Logger")
    parser.add_argument("--ws", type=str, help="URL сокета (например: ws://192.168.1.10:81 или ws://sgpcsi-0.local:81)")
    parser.add_argument("--serial", type=str, help="USB COM-порт (например: /dev/cu.usbserial-0001)")
    parser.add_argument("--baud", type=int, default=115200, help="Скорость serial (по умолчанию 115200)")
    parser.add_argument("--out", type=str, default=OUTPUT_CSV, help="Имя выходного CSV-файла")
    parser.add_argument("--sim", action="store_true", help="Запустить тест симуляции")
    args = parser.parse_args()

    try:
        if args.ws:
            run_websocket(args.ws, args.out)
        elif args.serial:
            run_serial(args.serial, args.baud, args.out)
        elif args.sim:
            run_sim(args.out)
        else:
            print("Укажите источник данных: --ws <url> или --serial <port> или --sim")
            print("Примеры:")
            print("  python3 data_parser.py --ws ws://192.168.1.10:81")
            print("  python3 data_parser.py --serial /dev/cu.usbmodem1101")
            print("  python3 data_parser.py --sim")
    except KeyboardInterrupt:
        print("\n[*] Запись остановлена пользователем.")
