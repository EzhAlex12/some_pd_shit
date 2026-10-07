/*
 * ============================================================================
 *  WIFI RSSI HUMAN RADAR (Method 1: Jukić et al. 2025) · ESP32-S3 Firmware
 * ============================================================================
 *  Implements Method 1 from "Detection of presence and number of persons by a
 *  Wi-Fi signal: a practical RSSI-based approach" (arXiv:2308.06773).
 *
 *  Instead of fragile and complex CSI, this firmware uses a Wi-Fi Promiscuous
 *  Sniffer to measure the Received Signal Strength Indicator (RSSI) of frames,
 *  and calculates the rolling Standard Deviation (sigma) in real-time.
 *
 *  Detection rule (Section 3.1.1):
 *    Presence is detected when sigma > f * <sigma_noise>, where f = 2.2.
 *
 *  ARCHITECTURE:
 *    - All nodes connect to the same Wi-Fi router (on a fixed channel).
 *    - Promiscuous sniffer captures all packets/beacons on the channel.
 *    - Node computes rolling std dev of RSSI and exposes WebSocket on port 81.
 *    - Advertises via mDNS as sgpcsi-<ID>.local.
 *    - Compatible with tracker.py and index.html (3D visualizer).
 * ============================================================================
 */

#include <WiFi.h>
#include <WiFiUdp.h>
#include <ESPmDNS.h>
#include "esp_wifi.h"
#include <math.h>

// ====================== CONFIGURATION ======================
#define NODE_ID        0                 // <<< CHANGE THIS ON EACH BOARD: 0,1,2,3
                                         //     (0=MASTER, 1, 2, 3)

#include "secrets.h"   // WIFI_SSID / WIFI_PASS — copy secrets.example.h -> secrets.h (git-ignored)

const uint16_t WS_PORT = 81;             // WebSocket port
#define MDNS_BASE       "sgpcsi"         // mDNS: sgpcsi-<ID>.local

// --- Status RGB LED (WS2812B on GPIO5 for SGP Card Mini) ---
#include <Adafruit_NeoPixel.h>
#define PIN_RGB_LED      5               // GPIO5 on SGP Card Mini (set -1 if none)
#define RGB_COUNT        1
const uint8_t LED_BRIGHTNESS = 80;
Adafruit_NeoPixel rgbLED(RGB_COUNT, PIN_RGB_LED, NEO_GRB + NEO_KHZ800);

// --- Buzzer (GPIO1 on SGP Card Mini) ---
#define PIN_BUZZER       1
const bool BEEP_ENABLED  = true;         // Set false to mute

// --- Method 1 Parameters (Jukić et al., Section 3.1.1) ---
const float F_FACTOR        = 2.2f;      // Decision threshold factor f = 2.2
const int   RSSI_WINDOW_LEN = 128;       // Ring buffer of last 128 RSSI samples (~5-10 s)
const uint32_t REPORT_MS    = 50;        // Report interval (20 Hz)
const uint32_t STIM_MS      = 20;        // Channel stimulus ping (50 Hz traffic)
// ===========================================================

#include <WebSocketsServer.h>
WebSocketsServer webSocket(WS_PORT);

WiFiUDP udpStim;

// --- RSSI Promiscuous Buffer & State ---
// Written by the Wi-Fi task (sniffer callback), read by loop(): guarded by g_mux.
volatile int8_t  g_rssi_buf[RSSI_WINDOW_LEN];
volatile int     g_buf_head = 0;
volatile int     g_buf_count = 0;
volatile int8_t  g_last_rssi = -60;
portMUX_TYPE     g_mux = portMUX_INITIALIZER_UNLOCKED;

// Only frames TRANSMITTED BY OUR ACCESS POINT are used (802.11 addr2 == BSSID).
// Without this filter the window mixes RSSI from every phone/AP/node on the channel,
// and sigma measures "who is talking" instead of the AP->node link disturbance.
volatile uint8_t g_bssid[6] = {0};
volatile bool    g_bssid_ok = false;
volatile uint32_t g_rx_total = 0;        // accepted AP frames (diagnostics, see [RATE] log)

volatile float   g_energy = 0.0f;        // sigma (standard deviation) in dB
volatile bool    g_presence = false;     // Local Method 1 decision
float            g_baseline_sigma = 0.43f; // Default ~0.43 dB as measured in empty room
bool             g_baseline_calibrated = false;

uint32_t lastReport = 0;
uint32_t lastStim   = 0;

// --- RGB LED state ---
enum LedMode { LED_CONNECTING, LED_CONNECTED, LED_FAIL };
volatile LedMode ledMode = LED_CONNECTING;
LedMode  prevLedMode = (LedMode)255;
uint32_t lastBlink = 0, lastFailBeep = 0;
bool     ledOn = false;

// --- Buzzer Helpers ---
void playTone(int freq, int dur) {
  if (!BEEP_ENABLED) return;
  ledcAttach(PIN_BUZZER, freq, 8);
  ledcWrite(PIN_BUZZER, 128);
  delay(dur);
  ledcWrite(PIN_BUZZER, 0);
  ledcDetach(PIN_BUZZER);
}
void beepConnected()  { playTone(1200,60); delay(20); playTone(1800,60); delay(20); playTone(2400,90); }
void beepConnecting() { playTone(700,60); }
void beepFail()       { playTone(500,120); delay(40); playTone(300,180); }

void rgbShowSafe() {
  if (WiFi.status() == WL_CONNECTED) WiFi.setSleep(WIFI_PS_MAX_MODEM);
  rgbLED.show();
  delayMicroseconds(350);
  if (WiFi.status() == WL_CONNECTED) WiFi.setSleep(WIFI_PS_NONE);
  yield();
}

void setLED(uint8_t r, uint8_t g, uint8_t b) {
  rgbLED.setPixelColor(0, rgbLED.Color(r, g, b));
  rgbShowSafe();
}

void updateLED() {
  uint16_t interval;
  switch (ledMode) {
    case LED_CONNECTED:  interval = g_presence ? 150 : 600; break;
    case LED_CONNECTING: interval = 400; break;
    case LED_FAIL:       interval = 130; break;
    default:             interval = 400; break;
  }
  if (millis() - lastBlink < interval) return;
  lastBlink = millis();
  ledOn = !ledOn;

  if (!ledOn) { setLED(0, 0, 0); return; }
  switch (ledMode) {
    case LED_CONNECTED:
      if (g_presence) setLED(255, 180, 0); // Orange/Yellow when human presence detected
      else            setLED(0, 255, 0);   // Green when empty / calm
      break;
    case LED_CONNECTING: setLED(0, 60, 255);  break;
    case LED_FAIL:       setLED(255, 0, 0);   break;
  }
}

void updateBuzzer() {
  if (ledMode != prevLedMode) {
    if      (ledMode == LED_CONNECTED)  beepConnected();
    else if (ledMode == LED_CONNECTING) beepConnecting();
    else if (ledMode == LED_FAIL)     { beepFail(); lastFailBeep = millis(); }
    prevLedMode = ledMode;
  }
  if (ledMode == LED_FAIL && millis() - lastFailBeep > 3000) {
    beepFail(); lastFailBeep = millis();
  }
}

// ---------------------------------------------------------------------------
//  Promiscuous RX callback: captures incoming frames & extracts RSSI
// ---------------------------------------------------------------------------
void IRAM_ATTR wifiSnifferCallback(void* buf, wifi_promiscuous_pkt_type_t type) {
  if (!buf || !g_bssid_ok) return;
  wifi_promiscuous_pkt_t* pkt = (wifi_promiscuous_pkt_t*)buf;
  if (pkt->rx_ctrl.sig_len < 16) return;            // too short to carry addr2

  // 802.11 MAC header: FC(2) Dur(2) addr1(6) addr2(6) ... -> transmitter = payload[10..15]
  const uint8_t* ta = pkt->payload + 10;
  for (int k = 0; k < 6; k++) {
    if (ta[k] != g_bssid[k]) return;                // not from our AP
  }

  int8_t r = pkt->rx_ctrl.rssi;
  if (r < 0 && r > -110) {
    portENTER_CRITICAL(&g_mux);
    g_last_rssi = r;
    g_rssi_buf[g_buf_head] = r;
    g_buf_head = (g_buf_head + 1) % RSSI_WINDOW_LEN;
    if (g_buf_count < RSSI_WINDOW_LEN) {
      g_buf_count++;
    }
    g_rx_total++;
    portEXIT_CRITICAL(&g_mux);
  }
}

// ---------------------------------------------------------------------------
//  Calculate Standard Deviation (sigma) of RSSI over the sliding window
// ---------------------------------------------------------------------------
float computeRssiStdDev() {
  int8_t copy_buf[RSSI_WINDOW_LEN];
  int count;
  // consistent snapshot: the callback may run on the other core at the same time
  portENTER_CRITICAL(&g_mux);
  count = g_buf_count;
  for (int i = 0; i < count; i++) {
    copy_buf[i] = g_rssi_buf[i];
  }
  portEXIT_CRITICAL(&g_mux);
  if (count < 15) return 0.0f;

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

// ---------------------------------------------------------------------------
//  Enable Wi-Fi Promiscuous Sniffer on the active channel
// ---------------------------------------------------------------------------
void enableSniffer() {
  wifi_promiscuous_filter_t filter = {
    .filter_mask = WIFI_PROMIS_FILTER_MASK_MGMT | WIFI_PROMIS_FILTER_MASK_DATA
  };
  esp_wifi_set_promiscuous_filter(&filter);
  esp_wifi_set_promiscuous_rx_cb(&wifiSnifferCallback);
  esp_wifi_set_promiscuous(true);
  Serial.println("[SNIFFER] Wi-Fi Promiscuous RSSI monitor enabled");
}

// ---------------------------------------------------------------------------
void connectWiFi() {
  g_bssid_ok = false;                    // sniffer ignores everything until we know our AP
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.printf("[WiFi] connecting to %s", WIFI_SSID);
  ledMode = LED_CONNECTING;
  uint32_t start = millis();
  uint32_t attemptStart = start;
  while (WiFi.status() != WL_CONNECTED) {
    updateLED();
    updateBuzzer();                      // so the FAIL beep is actually heard while stuck here
    if (millis() - start > 12000) ledMode = LED_FAIL;
    // Retry from scratch every 15 s (wrong password / AP rebooted / out of range):
    // previously the board waited forever after a single WiFi.begin().
    if (millis() - attemptStart > 15000) {
      Serial.printf("\n[WiFi] still not connected (status=%d), retrying", (int)WiFi.status());
      WiFi.disconnect();
      delay(100);
      WiFi.begin(WIFI_SSID, WIFI_PASS);
      attemptStart = millis();
    }
    delay(50);
    if ((millis() - start) % 400 < 50) Serial.print(".");
  }
  ledMode = LED_CONNECTED;

  // remember our AP and start a fresh RSSI window (old samples may be from before the drop)
  uint8_t* b = WiFi.BSSID();
  portENTER_CRITICAL(&g_mux);
  for (int k = 0; k < 6; k++) g_bssid[k] = b ? b[k] : 0;
  g_buf_head = 0;
  g_buf_count = 0;
  portEXIT_CRITICAL(&g_mux);
  g_bssid_ok = (b != nullptr);

  Serial.println();
  Serial.printf("[WiFi] OK  IP=%s  GW=%s  RSSI=%d  BSSID=%s  CH=%d\n",
                WiFi.localIP().toString().c_str(),
                WiFi.gatewayIP().toString().c_str(),
                WiFi.RSSI(), WiFi.BSSIDstr().c_str(), WiFi.channel());
  Serial.printf("[NODE] id=%d  ws://%s:%d\n",
                NODE_ID, WiFi.localIP().toString().c_str(), WS_PORT);
}

// ---------------------------------------------------------------------------
//  Stimulate channel traffic to generate RSSI samples constantly
// ---------------------------------------------------------------------------
void stimulateChannel() {
  uint8_t b = 0x55;
  udpStim.beginPacket(WiFi.gatewayIP(), 9);
  udpStim.write(&b, 1);
  udpStim.endPacket();
}

// ---------------------------------------------------------------------------
//  Broadcast JSON telemetry to WebSocket clients (tracker.py & index.html)
// ---------------------------------------------------------------------------
void broadcastOwn() {
  char json[128];
  // 'e' sends sigma (standard deviation in dB) to remain compatible with tracker.py
  snprintf(json, sizeof(json),
           "{\"id\":%d,\"e\":%.3f,\"rssi\":%d,\"on\":1,\"std\":%.3f,\"p\":%d}",
           NODE_ID, g_energy, (int)g_last_rssi, g_energy, g_presence ? 1 : 0);
  webSocket.broadcastTXT(json);
}

void onWsEvent(uint8_t num, WStype_t type, uint8_t* payload, size_t length) {
  if (type == WStype_CONNECTED)         Serial.printf("[WS] client connected #%u\n", num);
  else if (type == WStype_DISCONNECTED) Serial.printf("[WS] client disconnected #%u\n", num);
}

// ---------------------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\n=== SGP METHOD 1 (RSSI STDDEV) HUMAN DETECTOR ===");

  rgbLED.begin();
  rgbLED.setBrightness(LED_BRIGHTNESS);
  setLED(0, 60, 255);
  playTone(600,60); delay(20); playTone(900,80);

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

// ---------------------------------------------------------------------------
void loop() {
  uint32_t now = millis();

  if (WiFi.status() == WL_CONNECTED) ledMode = LED_CONNECTED;
  else if (ledMode != LED_FAIL)      ledMode = LED_CONNECTING;
  updateLED();
  updateBuzzer();

  webSocket.loop();

  // Traffic stimulus
  if (now - lastStim >= STIM_MS) {
    lastStim = now;
    stimulateChannel();
  }

  // Periodic computation & WebSocket broadcast
  if (now - lastReport >= REPORT_MS) {
    lastReport = now;

    float cur_sigma = computeRssiStdDev();
    g_energy = cur_sigma;

    // Adaptive noise baseline tracking:
    // Floor slowly drops towards quiet room noise; rises very slowly to avoid drift
    if (!g_baseline_calibrated && g_buf_count >= 50) {
      g_baseline_sigma = cur_sigma;
      g_baseline_calibrated = true;
      Serial.printf("[CALIB] Initial noise baseline <sigma> = %.3f dB\n", g_baseline_sigma);
    } else if (g_baseline_calibrated) {
      if (cur_sigma < g_baseline_sigma) {
        g_baseline_sigma += 0.05f * (cur_sigma - g_baseline_sigma);
      } else {
        g_baseline_sigma += 0.0005f * (cur_sigma - g_baseline_sigma);
      }
    }

    // Method 1 Decision Rule (sigma > f * <sigma_noise>)
    g_presence = (cur_sigma > F_FACTOR * g_baseline_sigma);

    broadcastOwn();
  }

  // Diagnostics: how many AP frames/s actually reach the RSSI window.
  // 128 samples at ~10 frames/s (beacons only) = ~13 s window -> slow reaction.
  static uint32_t lastRateLog = 0, lastRx = 0;
  if (now - lastRateLog >= 5000) {
    uint32_t rx = g_rx_total;
    Serial.printf("[RATE] %.1f AP frames/s -> RSSI window ~%.1f s  sigma=%.3f  base=%.3f  p=%d\n",
                  (rx - lastRx) * 1000.0f / (now - lastRateLog),
                  (rx - lastRx) ? RSSI_WINDOW_LEN * (now - lastRateLog) / 1000.0f / (rx - lastRx) : 0.0f,
                  g_energy, g_baseline_sigma, g_presence ? 1 : 0);
    lastRateLog = now;
    lastRx = rx;
  }

  // Auto-reconnect if Wi-Fi drops
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[WiFi] lost, reconnecting...");
    connectWiFi();
    enableSniffer();
  }
}
