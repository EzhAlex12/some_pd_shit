/*
 * ============================================================================
 *  WIFI RSSI HUMAN RADAR (Method 1: Jukić et al. 2025) · ESP32-S3 Firmware
 * ============================================================================
 *  (No-LED / No-Buzzer Generic Dev Module build)
 * ============================================================================
 */

#include <WiFi.h>
#include <WiFiUdp.h>
#include <ESPmDNS.h>
#include "esp_wifi.h"
#include <math.h>

// ====================== CONFIGURATION ======================
#define NODE_ID        0                 // <<< CHANGE THIS ON EACH BOARD: 0,1,2,3

const char* WIFI_SSID  = "YOUR_WIFI_SSID";   // <<< your Wi-Fi SSID (2.4GHz)
const char* WIFI_PASS  = "YOUR_WIFI_PASS";   // <<< your password

const uint16_t WS_PORT = 81;             // WebSocket port
#define MDNS_BASE       "sgpcsi"         // mDNS: sgpcsi-<ID>.local

// --- Method 1 Parameters (Jukić et al., Section 3.1.1) ---
const float F_FACTOR        = 2.2f;      // Decision threshold factor f = 2.2
const int   RSSI_WINDOW_LEN = 128;       // Ring buffer of last 128 RSSI samples
const uint32_t REPORT_MS    = 50;        // Report interval (20 Hz)
const uint32_t STIM_MS      = 20;        // Channel stimulus ping (50 Hz traffic)
// ===========================================================

#include <WebSocketsServer.h>
WebSocketsServer webSocket(WS_PORT);

WiFiUDP udpStim;

// --- RSSI Promiscuous Buffer & State ---
volatile int8_t  g_rssi_buf[RSSI_WINDOW_LEN];
volatile int     g_buf_head = 0;
volatile int     g_buf_count = 0;
volatile int8_t  g_last_rssi = -60;

volatile float   g_energy = 0.0f;        // sigma (standard deviation) in dB
volatile bool    g_presence = false;     // Local Method 1 decision
float            g_baseline_sigma = 0.43f;
bool             g_baseline_calibrated = false;

uint32_t lastReport = 0;
uint32_t lastStim   = 0;

void IRAM_ATTR wifiSnifferCallback(void* buf, wifi_promiscuous_pkt_type_t type) {
  if (!buf) return;
  wifi_promiscuous_pkt_t* pkt = (wifi_promiscuous_pkt_t*)buf;
  int8_t r = pkt->rx_ctrl.rssi;

  if (r < 0 && r > -110) {
    g_last_rssi = r;
    g_rssi_buf[g_buf_head] = r;
    g_buf_head = (g_buf_head + 1) % RSSI_WINDOW_LEN;
    if (g_buf_count < RSSI_WINDOW_LEN) {
      g_buf_count++;
    }
  }
}

float computeRssiStdDev() {
  int count = g_buf_count;
  if (count < 15) return 0.0f;

  int8_t copy_buf[RSSI_WINDOW_LEN];
  for (int i = 0; i < count; i++) {
    copy_buf[i] = g_rssi_buf[i];
  }

  float sum = 0.0f;
  for (int i = 0; i < count; i++) {
    sum += (float)copy_buf[i];
  }
  float mean = sum / (float)count;

  float var_sum = 0.0f;
  for (int i = 0; i < count; i++) {
    float diff = (float)copy_buf[i] - mean;
    var_sum += diff * diff;
  }
  return sqrtf(var_sum / (float)count);
}

void enableSniffer() {
  wifi_promiscuous_filter_t filter = {
    .filter_mask = WIFI_PROMIS_FILTER_MASK_MGMT | WIFI_PROMIS_FILTER_MASK_DATA
  };
  esp_wifi_set_promiscuous_filter(&filter);
  esp_wifi_set_promiscuous_rx_cb(&wifiSnifferCallback);
  esp_wifi_set_promiscuous(true);
  Serial.println("[SNIFFER] Wi-Fi Promiscuous RSSI monitor enabled");
}

void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.printf("[WiFi] connecting to %s", WIFI_SSID);
  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED) {
    if (millis() - start > 12000) break;
    delay(50);
    if ((millis() - start) % 400 < 50) Serial.print(".");
  }
  Serial.println();
  Serial.printf("[WiFi] OK  IP=%s  GW=%s  RSSI=%d\n",
                WiFi.localIP().toString().c_str(),
                WiFi.gatewayIP().toString().c_str(),
                WiFi.RSSI());
  Serial.printf("[NODE] id=%d  ws://%s:%d\n",
                NODE_ID, WiFi.localIP().toString().c_str(), WS_PORT);
}

void stimulateChannel() {
  uint8_t b = 0x55;
  udpStim.beginPacket(WiFi.gatewayIP(), 9);
  udpStim.write(&b, 1);
  udpStim.endPacket();
}

void broadcastOwn() {
  char json[128];
  snprintf(json, sizeof(json),
           "{\"id\":%d,\"e\":%.3f,\"rssi\":%d,\"on\":1,\"std\":%.3f,\"p\":%d}",
           NODE_ID, g_energy, (int)g_last_rssi, g_energy, g_presence ? 1 : 0);
  webSocket.broadcastTXT(json);
}

void onWsEvent(uint8_t num, WStype_t type, uint8_t* payload, size_t length) {
  if (type == WStype_CONNECTED)         Serial.printf("[WS] client connected #%u\n", num);
  else if (type == WStype_DISCONNECTED) Serial.printf("[WS] client disconnected #%u\n", num);
}

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\n=== SGP METHOD 1 (RSSI STDDEV) HUMAN DETECTOR ===");

  connectWiFi();
  enableSniffer();

  udpStim.begin(0);

  webSocket.begin();
  webSocket.onEvent(onWsEvent);

  String hn = String(MDNS_BASE) + "-" + String(NODE_ID);
  if (MDNS.begin(hn.c_str())) {
    MDNS.addService("sgpcsi", "tcp", WS_PORT);
    Serial.printf("[mDNS] advertised as %s.local\n", hn.c_str());
  }
  Serial.printf("[WS] ready at ws://%s.local:%d\n", hn.c_str(), WS_PORT);
}

void loop() {
  uint32_t now = millis();

  webSocket.loop();

  if (now - lastStim >= STIM_MS) {
    lastStim = now;
    stimulateChannel();
  }

  if (now - lastReport >= REPORT_MS) {
    lastReport = now;

    float cur_sigma = computeRssiStdDev();
    g_energy = cur_sigma;

    if (!g_baseline_calibrated && g_buf_count >= 50) {
      g_baseline_sigma = cur_sigma;
      g_baseline_calibrated = true;
      Serial.printf("[CALIB] Noise baseline <sigma> = %.3f dB\n", g_baseline_sigma);
    } else if (g_baseline_calibrated) {
      if (cur_sigma < g_baseline_sigma) {
        g_baseline_sigma += 0.05f * (cur_sigma - g_baseline_sigma);
      } else {
        g_baseline_sigma += 0.0005f * (cur_sigma - g_baseline_sigma);
      }
    }

    g_presence = (cur_sigma > F_FACTOR * g_baseline_sigma);
    broadcastOwn();
  }

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[WiFi] lost, reconnecting...");
    connectWiFi();
    enableSniffer();
  }
}
