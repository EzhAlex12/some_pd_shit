/*
 * ============================================================================
 *  WIFI-CSI HUMAN RADAR  ·  ESP32-S3 firmware
 * ============================================================================
 *  Detects and triangulates people using WiFi perturbation (CSI).
 *
 *  Flash the SAME sketch onto all 4 devices. You only need to change the
 *  value of NODE_ID (0,1,2,3) and, if you want, the WiFi credentials.
 *
 *  ARCHITECTURE: the 4 nodes are IDENTICAL and INDEPENDENT. Each one connects
 *  to WiFi on its own, captures its own CSI and exposes its own WebSocket
 *  server (port 81). The 3D app connects to all 4 separately and combines the
 *  signals -> the reading from each board is direct and real, without going
 *  through any intermediate node. Each node advertises itself over mDNS as
 *  sgpcsi-<ID>.local
 *
 *  PHYSICAL PLACEMENT: put the 4 nodes in the 4 corners of the room. The
 *  actual positions (in meters) are configured in the web app (visualizer).
 *
 * ----------------------------------------------------------------------------
 *  REQUIREMENTS (Arduino IDE)
 *    - Board: "ESP32S3 Dev Module" (espressif/arduino-esp32 board manager).
 *      Tested with arduino-esp32 v2.0.17 and v3.0.x.
 *    - Library: "WebSockets" by Markus Sattler (arduinoWebSockets), on all.
 *      Library Manager -> search for "WebSockets" by Markus Sattler.
 *    - Library: "Adafruit NeoPixel" (status RGB LED).
 * ----------------------------------------------------------------------------
 *  WARNING: the ESP32 CSI gives APPROXIMATE position (zone/movement), not cm.
 *           Calibrate the thresholds from the web app until you like the
 *           response.
 * ============================================================================
 */

#include <WiFi.h>
#include <WiFiUdp.h>
#include <ESPmDNS.h>
#include "esp_wifi.h"
#include <math.h>

// ====================== CONFIGURATION ======================
#define NODE_ID        0                 // <<< CHANGE THIS ON EACH BOARD: 0,1,2,3
                                          //     (all 4 are identical and independent)

const char* WIFI_SSID  = "ES";          // <<< your WiFi network (2.4GHz)
const char* WIFI_PASS  = "31415926";   // <<< your password

const uint16_t WS_PORT  = 81;            // each node exposes its own WebSocket
#define MDNS_BASE       "sgpcsi"         // each node advertises as sgpcsi-<ID>.local
                                          // (the app connects to all 4 separately)

// --- Status RGB LED (DISABLED: not wired on this board) ---
// #include <Adafruit_NeoPixel.h>
// #define PIN_RGB_LED      5
// #define RGB_COUNT        1
// const uint8_t LED_BRIGHTNESS = 80;
// Adafruit_NeoPixel rgbLED(RGB_COUNT, PIN_RGB_LED, NEO_GRB + NEO_KHZ800);

// --- Buzzer (DISABLED: not wired on this board) ---
// #define PIN_BUZZER       1
const bool BEEP_ENABLED  = false;        // forced off since buzzer is disabled

// --- detection parameters (tunable) ---
const float BASELINE_ALPHA = 0.02f;      // speed at which the "empty
                                          // environment" is relearned (higher =
                                          // forgets the movement sooner)
const float ENERGY_ALPHA   = 0.30f;      // smoothing of the output energy
const int   MAX_SUBCARRIERS = 256;       // cap of subcarriers to process
const uint32_t REPORT_MS    = 50;        // how often a report is sent (20 Hz)
const uint32_t STIM_MS      = 8;         // how often the channel is "stimulated"
// ===========================================================

#include <WebSocketsServer.h>
WebSocketsServer webSocket(WS_PORT);

WiFiUDP udpStim;      // channel stimulus ping

// --- CSI state shared with the callback (runs in the WiFi task) ---
volatile float g_energy = 0.0f;          // smoothed movement energy
volatile int   g_rssi   = 0;
static   float baseline[MAX_SUBCARRIERS];
static   bool  baselineReady = false;

uint32_t lastReport = 0;
uint32_t lastStim   = 0;

// --- RGB LED state ---
enum LedMode { LED_CONNECTING, LED_CONNECTED, LED_FAIL };
volatile LedMode ledMode = LED_CONNECTING;
LedMode  prevLedMode = (LedMode)255;     // forces the first beep
uint32_t lastBlink = 0, lastFailBeep = 0;
bool     ledOn = false;

// --- Buzzer and LED (DISABLED: no hardware wired). Stubbed as no-ops so the
// rest of the sketch (which calls these) still compiles and runs unchanged. ---
void playTone(int freq, int dur) { /* buzzer disabled */ }
void beepConnected()  { /* buzzer disabled */ }
void beepConnecting() { /* buzzer disabled */ }
void beepFail()       { /* buzzer disabled */ }

void rgbShowSafe() { /* LED disabled */ }

void setLED(uint8_t r, uint8_t g, uint8_t b) { /* LED disabled */ }

void updateLED() { /* LED disabled */ }

// beeps when the state changes; on failure it repeats the alert every 3 s
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
//  CSI callback: called for every packet received. It must be FAST.
// ---------------------------------------------------------------------------
void IRAM_ATTR csiCallback(void* ctx, wifi_csi_info_t* info) {
  if (!info || !info->buf || info->len < 2) return;

  const int8_t* buf = info->buf;
  int pairs = info->len / 2;
  if (pairs > MAX_SUBCARRIERS) pairs = MAX_SUBCARRIERS;

  float dev = 0.0f;
  int   cnt = 0;

  for (int i = 0; i < pairs; i++) {
    int8_t imag = buf[i * 2];
    int8_t real = buf[i * 2 + 1];
    float amp = sqrtf((float)real * real + (float)imag * imag);

    if (!baselineReady) {
      baseline[i] = amp;
    } else {
      float d = amp - baseline[i];
      if (d < 0) d = -d;
      dev += d;
      // the baseline slowly relearns the static environment
      baseline[i] += BASELINE_ALPHA * (amp - baseline[i]);
      cnt++;
    }
  }

  if (!baselineReady) { baselineReady = true; return; }
  if (cnt == 0) return;

  float inst = dev / (float)cnt;                 // mean deviation per subcarrier
  g_energy = (1.0f - ENERGY_ALPHA) * g_energy + ENERGY_ALPHA * inst;
  g_rssi   = info->rx_ctrl.rssi;
}

// ---------------------------------------------------------------------------
void enableCSI() {
  // NOTE: wifi_csi_config_t struct valid in arduino-esp32 2.0.x / 3.0.x.
  // If your core is very new and it does not compile, check the README (CSI section).
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
  Serial.println("[CSI] enabled");
}

// ---------------------------------------------------------------------------
void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);                  // no power-save -> more stable CSI
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.printf("[WiFi] connecting to %s", WIFI_SSID);
  ledMode = LED_CONNECTING;                 // blue while connecting
  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED) {
    updateLED();
    if (millis() - start > 12000) ledMode = LED_FAIL;   // red if it does not latch on
    delay(50);
    if ((millis() - start) % 400 < 50) Serial.print(".");
  }
  ledMode = LED_CONNECTED;                  // green once connected
  Serial.println();
  Serial.printf("[WiFi] OK  IP=%s  GW=%s  RSSI=%d\n",
                WiFi.localIP().toString().c_str(),
                WiFi.gatewayIP().toString().c_str(),
                WiFi.RSSI());
  Serial.printf("[NODE] id=%d  ws://%s:%d\n",
                NODE_ID, WiFi.localIP().toString().c_str(), WS_PORT);
}

// ---------------------------------------------------------------------------
//  Channel stimulus: we send a UDP packet to the router very frequently to
//  force traffic (and its ACKs) -> more packets received -> more CSI samples.
// ---------------------------------------------------------------------------
void stimulateChannel() {
  uint8_t b = 0x55;
  udpStim.beginPacket(WiFi.gatewayIP(), 9);   // discard port
  udpStim.write(&b, 1);
  udpStim.endPacket();
}

// ---------------------------------------------------------------------------
//  Each node emits ITS OWN signal over WebSocket to the app.
// ---------------------------------------------------------------------------
void broadcastOwn() {
  char json[96];
  snprintf(json, sizeof(json),
           "{\"id\":%d,\"e\":%.3f,\"rssi\":%d,\"on\":1}",
           NODE_ID, g_energy, g_rssi);
  webSocket.broadcastTXT(json);
}

void onWsEvent(uint8_t num, WStype_t type, uint8_t* payload, size_t length) {
  if (type == WStype_CONNECTED)         Serial.printf("[WS] app connected #%u\n", num);
  else if (type == WStype_DISCONNECTED) Serial.printf("[WS] app disconnected #%u\n", num);
}

// ---------------------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\n=== SGP CSI HUMAN RADAR ===");

  // LED/buzzer init skipped (hardware disabled)
  connectWiFi();
  enableCSI();

  udpStim.begin(0);

  webSocket.begin();
  webSocket.onEvent(onWsEvent);

  // each node advertises over mDNS as  sgpcsi-<ID>.local
  String hn = String(MDNS_BASE) + "-" + String(NODE_ID);
  if (MDNS.begin(hn.c_str())) {
    MDNS.addService("sgpcsi", "tcp", WS_PORT);
    Serial.printf("[mDNS] advertised as %s.local\n", hn.c_str());
  }
  Serial.printf("[WS] ready at ws://%s.local:%d  (the app connects on its own)\n",
                hn.c_str(), WS_PORT);
}

// ---------------------------------------------------------------------------
void loop() {
  uint32_t now = millis();

  // status LED: green=connected / blue=connecting / red=failure
  if (WiFi.status() == WL_CONNECTED) ledMode = LED_CONNECTED;
  else if (ledMode != LED_FAIL)      ledMode = LED_CONNECTING;
  updateLED();
  updateBuzzer();

  webSocket.loop();

  if (now - lastStim >= STIM_MS) {
    lastStim = now;
    stimulateChannel();
  }

  if (now - lastReport >= REPORT_MS) {
    lastReport = now;
    broadcastOwn();
  }

  // simple reconnection
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[WiFi] lost, reconnecting...");
    connectWiFi();
  }
}
