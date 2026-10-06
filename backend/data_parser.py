#!/usr/bin/env python3
# ============================================================================
#  DATA PARSER & COLLECTOR · ESP32 CSI / RSSI
# ============================================================================
#  Скрипт для извлечения данных с ESP32 и сохранения в CSV файл.
#
#  Поддерживает три режима:
#    1. ПО ВОЗДУХУ (WebSocket):
#       python3 backend/data_parser.py --ws ws://192.168.1.10:81
#
#    2. ПО ПРОВОДУ (USB Serial):
#       python3 backend/data_parser.py --serial /dev/cu.usbmodem1101
#
#    3. СИМУЛЯЦИЯ (проверка без плат):
#       python3 backend/data_parser.py --sim
#
#  Зависимости:
#    pip install -r backend/requirements.txt
# ============================================================================

import sys
import time
import json
import csv
import asyncio
import argparse
from datetime import datetime

OUTPUT_CSV = "collected_data.csv"
FIELDNAMES = ["timestamp", "node_id", "energy_sigma", "rssi", "presence", "raw_json"]


def open_csv(out_file):
    """Открывает CSV файл и создаёт заголовок, если файл новый."""
    f = open(out_file, "a", newline="", encoding="utf-8")
    writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
    if f.tell() == 0:
        writer.writeheader()
    return f, writer


def log_to_csv(writer, file_obj, row_dict):
    writer.writerow(row_dict)
    file_obj.flush()


def format_status(pres):
    return "[ДВИЖЕНИЕ]" if pres else "[ТИШИНА]"


# ---------------------------------------------------------------------------
#  РЕЖИМ 1: WebSocket (asyncio)
# ---------------------------------------------------------------------------
async def run_websocket(url, out_file):
    try:
        import websockets
    except ImportError:
        print("[!] Библиотека websockets не найдена: pip install websockets")
        return

    print(f"[*] Подключение к WebSocket: {url}")
    print(f"[*] Данные будут записываться в: {out_file}")

    f, writer = open_csv(out_file)
    try:
        async for ws in websockets.connect(url, ping_interval=20, ping_timeout=10):
            try:
                print(f"[+] Подключено к {url}")
                async for msg in ws:
                    try:
                        now_str = datetime.now().isoformat()
                        d = json.loads(msg)
                        node_id = d.get("id", 0)
                        energy = d.get("e", d.get("std", 0.0))
                        rssi_val = d.get("rssi", -100)
                        pres = d.get("p", 0)

                        print(
                            f"[{now_str}] Нода #{node_id} | "
                            f"RSSI: {rssi_val:4d} dBm | "
                            f"sigma: {energy:.3f} | {format_status(pres)}"
                        )

                        log_to_csv(writer, f, {
                            "timestamp": now_str,
                            "node_id": node_id,
                            "energy_sigma": energy,
                            "rssi": rssi_val,
                            "presence": pres,
                            "raw_json": msg,
                        })
                    except json.JSONDecodeError:
                        pass
            except Exception as e:
                print(f"[!] Соединение прервано ({e}), переподключение через 2 с...")
                await asyncio.sleep(2)
    except asyncio.CancelledError:
        pass
    finally:
        f.close()
        print("[*] CSV файл закрыт.")


# ---------------------------------------------------------------------------
#  РЕЖИМ 2: USB Serial
# ---------------------------------------------------------------------------
async def run_serial(port, baud, out_file):
    try:
        import serial
    except ImportError:
        print("[!] Библиотека pyserial не найдена: pip install pyserial")
        return

    print(f"[*] Открытие порта {port} @ {baud}...")
    print(f"[*] Данные будут записываться в: {out_file}")

    try:
        ser = serial.Serial(port, baud, timeout=1)
    except Exception as e:
        print(f"[!] Не удалось открыть порт {port}: {e}")
        import serial.tools.list_ports
        print("    Доступные порты:")
        for p in serial.tools.list_ports.comports():
            print(f"      {p.device} ({p.description})")
        return

    f, writer = open_csv(out_file)
    try:
        while True:
            try:
                line = ser.readline().decode("utf-8", errors="ignore").strip()
                if not line:
                    await asyncio.sleep(0.01)
                    continue

                now_str = datetime.now().isoformat()
                row = None

                # Парсинг JSON
                if line.startswith("{"):
                    try:
                        d = json.loads(line)
                        node_id = d.get("id", 0)
                        energy = d.get("e", d.get("std", 0.0))
                        rssi_val = d.get("rssi", -100)
                        pres = d.get("p", 0)
                        row = {
                            "timestamp": now_str,
                            "node_id": node_id,
                            "energy_sigma": energy,
                            "rssi": rssi_val,
                            "presence": pres,
                            "raw_json": line,
                        }
                        print(
                            f"[{now_str}] Нода #{node_id} | "
                            f"RSSI: {rssi_val:4d} dBm | "
                            f"sigma: {energy:.3f} | {format_status(pres)}"
                        )
                    except json.JSONDecodeError:
                        pass

                # Парсинг формата CSV CSI (CSI,rssi,amp0,...)
                elif line.startswith("CSI,") or line.startswith("CSI:"):
                    parts = line.split(",")[1:]
                    if len(parts) >= 2:
                        try:
                            rssi_val = int(parts[0])
                            row = {
                                "timestamp": now_str,
                                "node_id": 0,
                                "energy_sigma": "",
                                "rssi": rssi_val,
                                "presence": "",
                                "raw_json": line,
                            }
                            print(f"[{now_str}] CSI кадр | RSSI: {rssi_val:4d} dBm | {len(parts)-1} поднесущих")
                        except ValueError:
                            pass

                if row is None:
                    row = {
                        "timestamp": now_str,
                        "node_id": "",
                        "energy_sigma": "",
                        "rssi": "",
                        "presence": "",
                        "raw_json": line,
                    }

                log_to_csv(writer, f, row)

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[!] Ошибка serial: {e}")
                await asyncio.sleep(0.5)
    finally:
        ser.close()
        f.close()
        print("[*] Порт и CSV файл закрыты.")


# ---------------------------------------------------------------------------
#  РЕЖИМ 3: Симуляция
# ---------------------------------------------------------------------------
async def run_sim(out_file):
    print(f"[*] Режим симуляции (пишем тестовые данные в {out_file})...")

    f, writer = open_csv(out_file)
    try:
        for step in range(50):
            now_str = datetime.now().isoformat()
            is_moving = 15 < step < 35
            sigma = 2.45 if is_moving else 0.41
            rssi_val = -54 if is_moving else -50
            pres = 1 if is_moving else 0

            print(
                f"[{now_str}] Нода #0 | "
                f"RSSI: {rssi_val:4d} dBm | "
                f"sigma: {sigma:.3f} | {format_status(pres)}"
            )

            log_to_csv(writer, f, {
                "timestamp": now_str,
                "node_id": 0,
                "energy_sigma": sigma,
                "rssi": rssi_val,
                "presence": pres,
                "raw_json": json.dumps({"id": 0, "e": sigma, "rssi": rssi_val, "p": pres}),
            })
            await asyncio.sleep(0.1)
    finally:
        f.close()

    print(f"[*] Тест завершён! {out_file} записан.")


# ---------------------------------------------------------------------------
async def main():
    parser = argparse.ArgumentParser(description="ESP32 Data Extractor & CSV Logger")
    parser.add_argument("--ws", type=str, help="URL сокета (например: ws://192.168.1.10:81)")
    parser.add_argument("--serial", type=str, help="USB COM-порт (например: /dev/cu.usbmodem1101)")
    parser.add_argument("--baud", type=int, default=115200, help="Скорость serial (по умолчанию 115200)")
    parser.add_argument("--out", type=str, default=OUTPUT_CSV, help="Имя выходного CSV-файла")
    parser.add_argument("--sim", action="store_true", help="Запустить тест симуляции")
    args = parser.parse_args()

    if args.ws:
        await run_websocket(args.ws, args.out)
    elif args.serial:
        await run_serial(args.serial, args.baud, args.out)
    elif args.sim:
        await run_sim(args.out)
    else:
        parser.print_help()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[*] Запись остановлена.")
