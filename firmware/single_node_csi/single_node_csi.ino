/*
 * ============================================================================
 *  SINGLE BOARD WIFI-CSI RADAR · ESP32-S3
 * ============================================================================
 *  Прошивка для ОДНОЙ платы ESP32.
 *  - Подключается к Wi-Fi роутеру (роутер выступает передатчиком-источником).
 *  - Драйвер Wi-Fi на каждый принятый пакет снимает CSI (64 поднесущие).
 *  - Отправляет кадры прямо в USB Serial в формате CSV:
 *      CSI,<rssi>,<amp0>,<amp1>,...,<amp63>
 * ============================================================================
 */

#include <WiFi.h>
#include <WiFiUdp.h>
#include "esp_wifi.h"
#include <math.h>

// ====== НАСТРОЙКИ WI-FI ======
const char* WIFI_SSID = "Andrey";   // Имя вашей Wi-Fi сети 2.4 ГГц
const char* WIFI_PASS = "10172609pron";   // Пароль сети

#define NUM_SUBCARRIERS 64
volatile float   g_csi_amps[NUM_SUBCARRIERS];
volatile int8_t  g_last_rssi = -60;
volatile bool    g_new_frame = false;

WiFiUDP udpStim;
uint32_t lastStim  = 0;
uint32_t lastPrint = 0;

// ---------------------------------------------------------------------------
//  CSI Callback: аппаратный захват матрицы поднесущих
// ---------------------------------------------------------------------------
void IRAM_ATTR csiCallback(void* ctx, wifi_csi_info_t* info) {
  if (!info || !info->buf || info->len < 2) return;

  const int8_t* buf = info->buf;
  int pairs = info->len / 2;
  if (pairs > NUM_SUBCARRIERS) pairs = NUM_SUBCARRIERS;

  for (int i = 0; i < pairs; i++) {
    int8_t imag = buf[i * 2];
    int8_t real = buf[i * 2 + 1];
    // Амплитуда поднесущей |H(f)| = sqrt(I^2 + Q^2)
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
  Serial.println("[CSI] Аппаратный захват CSI включен");
}

void setup() {
  Serial.begin(115200);
  delay(600);
  Serial.println("\n=== SINGLE ESP32 CSI STREAMER ===");

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false); // Запрещаем сон Wi-Fi модема для чистоты сигнала
  WiFi.begin(WIFI_SSID, WIFI_PASS);

  Serial.print("[WiFi] Подключение к роутеру");
  while (WiFi.status() != WL_CONNECTED) {
    delay(100);
    Serial.print(".");
  }
  Serial.printf("\n[WiFi] Готово! IP: %s, RSSI: %d dBm\n",
                WiFi.localIP().toString().c_str(), WiFi.RSSI());

  enableCSI();
  udpStim.begin(0);
}

void loop() {
  uint32_t now = millis();

  // Отправка легкого UDP-пика роутеру каждые 20 мс (стимулирует входящие ACK-пакеты с CSI)
  if (now - lastStim >= 20) {
    lastStim = now;
    uint8_t ping_val = 0xAA;
    udpStim.beginPacket(WiFi.gatewayIP(), 9);
    udpStim.write(&ping_val, 1);
    udpStim.endPacket();
  }

  // Передача вектора поднесущих в Serial каждые 40 мс (~25 Гц)
  if (g_new_frame && (now - lastPrint >= 40)) {
    lastPrint = now;
    g_new_frame = false;

    // Формат CSV: CSI,rssi,amp0,amp1,...,amp63
    Serial.printf("CSI,%d", (int)g_last_rssi);
    for (int i = 0; i < NUM_SUBCARRIERS; i++) {
      Serial.printf(",%.1f", g_csi_amps[i]);
    }
    Serial.println();
  }

  // Автопереподключение при потере сети
  if (WiFi.status() != WL_CONNECTED) {
    WiFi.disconnect();
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    delay(500);
  }
}
