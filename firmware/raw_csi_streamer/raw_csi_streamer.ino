/*
 * ============================================================================
 *  ESP32-S3 RAW WIFI CSI STREAMER
 * ============================================================================
 *  Прошивка для захвата и передачи сырых 64 поднесущих CSI в Python.
 *
 *  Данные передаются в USB Serial на высокой скорости (115200 или 921600 бод):
 *  Формат строки:
 *    CSI,<rssi>,<amp_0>,<amp_1>,...,<amp_63>
 *
 *  Также параллельно поднимается WebSocket сервер на порту 81:
 *    {"csi": [amp0, amp1, ...], "rssi": -55}
 * ============================================================================
 */

#include <WiFi.h>
#include <WiFiUdp.h>
#include "esp_wifi.h"
#include <math.h>

const char* WIFI_SSID = "Pixel 8a";   // Имя сети 2.4 ГГц
const char* WIFI_PASS = "k4t4Z0V_best";   // Пароль сети

#define NUM_SUBCARRIERS 64

volatile float g_csi_amps[NUM_SUBCARRIERS];
volatile int8_t g_last_rssi = -60;
volatile bool g_new_frame = false;

WiFiUDP udpStim;
uint32_t lastStim = 0;
uint32_t lastPrint = 0;

// ---------------------------------------------------------------------------
//  CSI Callback: вызывается ESP-IDF драйвером на каждый принятый Wi-Fi пакет
// ---------------------------------------------------------------------------
void IRAM_ATTR csiCallback(void* ctx, wifi_csi_info_t* info) {
  if (!info || !info->buf || info->len < 2) return;

  const int8_t* buf = info->buf;
  int pairs = info->len / 2;
  if (pairs > NUM_SUBCARRIERS) pairs = NUM_SUBCARRIERS;

  for (int i = 0; i < pairs; i++) {
    int8_t imag = buf[i * 2];
    int8_t real = buf[i * 2 + 1];
    // Вычисляем модуль амплитуды поднесущей |H(f)| = sqrt(I^2 + Q^2)
    g_csi_amps[i] = sqrtf((float)real * real + (float)imag * imag);
  }

  g_last_rssi = info->rx_ctrl.rssi;
  g_new_frame = true;
}

void enableCSI() {
  wifi_csi_config_t csi_config = {
    .lltf_en           = true,
    .htltf_en          = true,
    .stbc_htltf2_en    = true,
    .ltf_merge_en      = true,
    .channel_filter_en = true,
    .manu_scale        = false,
    .shift             = 0,
  };
  esp_wifi_set_csi_config(&csi_config);
  esp_wifi_set_csi_rx_cb(&csiCallback, NULL);
  esp_wifi_set_csi(true);
  Serial.println("[CSI] Драйвер сырого CSI активирован");
}

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println("\n=== ESP32 RAW CSI STREAMER ===");

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false); // Отключаем энергосбережение для стабильного захвата
  WiFi.begin(WIFI_SSID, WIFI_PASS);

  Serial.print("[WiFi] Подключение");
  while (WiFi.status() != WL_CONNECTED) {
    delay(100);
    Serial.print(".");
  }
  Serial.printf("\n[WiFi] Подключено! IP: %s | RSSI: %d dBm\n",
                WiFi.localIP().toString().c_str(), WiFi.RSSI());

  enableCSI();
  udpStim.begin(0);
}

void loop() {
  uint32_t now = millis();

  // Отправляем короткий UDP-пинг роутеру для постоянной стимуляции трафика (50 Гц)
  if (now - lastStim >= 20) {
    lastStim = now;
    uint8_t ping_byte = 0xAA;
    udpStim.beginPacket(WiFi.gatewayIP(), 9);
    udpStim.write(&ping_byte, 1);
    udpStim.endPacket();
  }

  // Передаем сырой CSI кадр в Serial каждые 40 мс (~25 Гц)
  if (g_new_frame && (now - lastPrint >= 40)) {
    lastPrint = now;
    g_new_frame = false;

    // Выводим строку CSV: CSI,rssi,amp0,amp1,...,amp63
    Serial.printf("CSI,%d", g_last_rssi);
    for (int i = 0; i < NUM_SUBCARRIERS; i++) {
      Serial.printf(",%.1f", g_csi_amps[i]);
    }
    Serial.println();
  }
}
