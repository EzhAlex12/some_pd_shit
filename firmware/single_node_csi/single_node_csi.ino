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
#include "secrets.h"   // WIFI_SSID / WIFI_PASS — copy secrets.example.h -> secrets.h (git-ignored)

#define NUM_SUBCARRIERS 64
// Пишется из Wi-Fi задачи (CSI callback), читается в loop() — защищено g_mux,
// иначе в Serial может уйти «склейка» из половин двух разных пакетов.
float            g_csi_amps[NUM_SUBCARRIERS];
int8_t           g_last_rssi = -60;
volatile bool    g_new_frame = false;
portMUX_TYPE     g_mux = portMUX_INITIALIZER_UNLOCKED;

// CSI берётся ТОЛЬКО с пакетов нашего роутера (MAC отправителя == BSSID).
// Без фильтра в поток попадают кадры соседних точек, телефонов и т.д.
volatile uint8_t g_bssid[6] = {0};
volatile bool    g_bssid_ok = false;

WiFiUDP udpStim;
uint32_t lastStim  = 0;
uint32_t lastPrint = 0;
uint32_t lastReconnect = 0;

// ---------------------------------------------------------------------------
//  CSI Callback: аппаратный захват матрицы поднесущих
// ---------------------------------------------------------------------------
void IRAM_ATTR csiCallback(void* ctx, wifi_csi_info_t* info) {
  if (!info || !info->buf || info->len < 2 || !g_bssid_ok) return;
  for (int k = 0; k < 6; k++) {
    if (info->mac[k] != g_bssid[k]) return;        // пакет не от нашего роутера
  }

  const int8_t* buf = info->buf;
  int pairs = info->len / 2;
  if (pairs > NUM_SUBCARRIERS) pairs = NUM_SUBCARRIERS;

  float amps[NUM_SUBCARRIERS] = {0};
  for (int i = 0; i < pairs; i++) {
    int8_t imag = buf[i * 2];
    int8_t real = buf[i * 2 + 1];
    // Амплитуда поднесущей |H(f)| = sqrt(I^2 + Q^2)
    amps[i] = sqrtf((float)real * real + (float)imag * imag);
  }

  portENTER_CRITICAL(&g_mux);
  memcpy(g_csi_amps, amps, sizeof(amps));
  g_last_rssi = info->rx_ctrl.rssi;
  g_new_frame = true;
  portEXIT_CRITICAL(&g_mux);
}

void rememberBssid() {
  uint8_t* b = WiFi.BSSID();
  for (int k = 0; k < 6; k++) g_bssid[k] = b ? b[k] : 0;
  g_bssid_ok = (b != nullptr);
  Serial.printf("[WiFi] BSSID роутера: %s, канал %d\n", WiFi.BSSIDstr().c_str(), WiFi.channel());
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
  uint32_t attemptStart = millis();
  while (WiFi.status() != WL_CONNECTED) {
    delay(100);
    Serial.print(".");
    if (millis() - attemptStart > 15000) {          // неверный пароль / роутер далеко — пробуем снова
      Serial.printf("\n[WiFi] нет подключения (status=%d), повтор", (int)WiFi.status());
      WiFi.disconnect();
      delay(100);
      WiFi.begin(WIFI_SSID, WIFI_PASS);
      attemptStart = millis();
    }
  }
  Serial.printf("\n[WiFi] Готово! IP: %s, RSSI: %d dBm\n",
                WiFi.localIP().toString().c_str(), WiFi.RSSI());
  rememberBssid();

  enableCSI();
  udpStim.begin(0);
}

void loop() {
  uint32_t now = millis();

  // Отправка легкого UDP-пика роутеру каждые 20 мс (стимулирует входящие ACK-пакеты с CSI)
  if (now - lastStim >= 20 && WiFi.status() == WL_CONNECTED) {
    lastStim = now;
    uint8_t ping_val = 0xAA;
    udpStim.beginPacket(WiFi.gatewayIP(), 9);
    udpStim.write(&ping_val, 1);
    udpStim.endPacket();
  }

  // Передача вектора поднесущих в Serial каждые 40 мс (~25 Гц)
  if (g_new_frame && (now - lastPrint >= 40)) {
    lastPrint = now;

    // целостный снимок кадра (callback может писать в этот момент на другом ядре)
    float amps[NUM_SUBCARRIERS];
    int8_t rssi;
    portENTER_CRITICAL(&g_mux);
    memcpy(amps, g_csi_amps, sizeof(amps));
    rssi = g_last_rssi;
    g_new_frame = false;
    portEXIT_CRITICAL(&g_mux);

    // Формат CSV: CSI,rssi,amp0,amp1,...,amp63
    Serial.printf("CSI,%d", (int)rssi);
    for (int i = 0; i < NUM_SUBCARRIERS; i++) {
      Serial.printf(",%.1f", amps[i]);
    }
    Serial.println();
  }

  // Автопереподключение при потере сети.
  // Раньше здесь на КАЖДОМ проходе loop() делались disconnect()+begin()+delay(500):
  // ассоциация занимает дольше 500 мс, поэтому каждая попытка обрывалась следующей
  // и плата могла не переподключиться никогда. Теперь — не чаще раза в 10 с.
  static bool wasConnected = true;
  if (WiFi.status() != WL_CONNECTED) {
    if (wasConnected) {
      Serial.println("[WiFi] связь потеряна, переподключаемся...");
      g_bssid_ok = false;
      wasConnected = false;
      lastReconnect = now;
    }
    if (now - lastReconnect >= 10000) {
      lastReconnect = now;
      WiFi.disconnect();
      WiFi.begin(WIFI_SSID, WIFI_PASS);
    }
  } else if (!wasConnected) {
    wasConnected = true;
    Serial.printf("[WiFi] снова в сети, IP: %s\n", WiFi.localIP().toString().c_str());
    rememberBssid();                                  // роутер мог смениться (mesh / роуминг)
  }
}
