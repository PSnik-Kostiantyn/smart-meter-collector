// Прошивка вузла обліку на ESP32 з модулем PZEM-004T v3.0.
//
// Пристрій раз на PUBLISH_INTERVAL_MS читає напругу, струм, потужність,
// накопичену енергію, частоту й коефіцієнт потужності, додає час за NTP
// і публікує JSON у топік meters/<district>/<meter_id>/readings з QoS 0.
// Поки немає зв'язку з брокером, показники складаються в кільцевий буфер
// і надсилаються по порядку після відновлення з'єднання.
//
// Підключення PZEM-004T до ESP32
//   PZEM TX -> GPIO16 (RX2), PZEM RX -> GPIO17 (TX2), живлення 5 В.
//
// Бібліотеки
//   PZEM004Tv30 1.2 (Jakub Mandula), PubSubClient 2.8 (Nick O'Leary), ArduinoJson 7.

#include <WiFi.h>
#include <PubSubClient.h>
#include <PZEM004Tv30.h>
#include <ArduinoJson.h>
#include <time.h>

#include "config.h"

static const int PZEM_RX_PIN = 16;
static const int PZEM_TX_PIN = 17;
static const size_t BUFFER_CAPACITY = 96;  // 24 години при інтервалі 15 хв

PZEM004Tv30 pzem(Serial2, PZEM_RX_PIN, PZEM_TX_PIN);
WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);

char topic[96];
String ring[BUFFER_CAPACITY];
size_t ringHead = 0;
size_t ringCount = 0;
unsigned long lastSample = 0;

void connectWifi() {
  if (WiFi.status() == WL_CONNECTED) return;
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 15000) {
    delay(250);
  }
}

bool connectMqtt() {
  if (mqtt.connected()) return true;
  if (WiFi.status() != WL_CONNECTED) return false;
  String clientId = String("meter-") + METER_ID;
  return mqtt.connect(clientId.c_str(), MQTT_USER, MQTT_PASSWORD);
}

bool timeIsSet() {
  return time(nullptr) > 1700000000;  // NTP вже відповів
}

void isoNow(char *out, size_t len) {
  time_t now = time(nullptr);
  struct tm utc;
  gmtime_r(&now, &utc);
  strftime(out, len, "%Y-%m-%dT%H:%M:%SZ", &utc);
}

// Повертає false, якщо PZEM не відповів. Тоді показник не надсилається.
bool readMeter(String &json) {
  float voltage = pzem.voltage();
  float current = pzem.current();
  float power = pzem.power();
  float energy = pzem.energy();
  float frequency = pzem.frequency();
  float pf = pzem.pf();
  if (isnan(voltage) || isnan(current) || isnan(power) || isnan(energy) ||
      isnan(frequency) || isnan(pf)) {
    return false;
  }
  char ts[25];
  isoNow(ts, sizeof(ts));

  JsonDocument doc;
  doc["meter_id"] = METER_ID;
  doc["ts"] = ts;
  doc["energy_kwh"] = serialized(String(energy, 3));
  doc["power_w"] = serialized(String(power, 1));
  doc["voltage_v"] = serialized(String(voltage, 1));
  doc["current_a"] = serialized(String(current, 3));
  doc["power_factor"] = serialized(String(pf, 2));
  doc["frequency_hz"] = serialized(String(frequency, 1));
  json.clear();
  serializeJson(doc, json);
  return true;
}

void pushRing(const String &msg) {
  size_t idx = (ringHead + ringCount) % BUFFER_CAPACITY;
  ring[idx] = msg;
  if (ringCount < BUFFER_CAPACITY) {
    ringCount++;
  } else {
    ringHead = (ringHead + 1) % BUFFER_CAPACITY;  // найстаріший показник втрачається
  }
}

void flushRing() {
  while (ringCount > 0 && mqtt.connected()) {
    if (!mqtt.publish(topic, ring[ringHead].c_str())) return;
    ring[ringHead] = String();
    ringHead = (ringHead + 1) % BUFFER_CAPACITY;
    ringCount--;
    mqtt.loop();
  }
}

void setup() {
  Serial.begin(115200);
  snprintf(topic, sizeof(topic), "meters/%s/%s/readings", DISTRICT, METER_ID);
  connectWifi();
  configTime(0, 0, "pool.ntp.org", "time.google.com");
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setBufferSize(512);
  mqtt.setKeepAlive(60);
}

void loop() {
  connectWifi();
  connectMqtt();
  mqtt.loop();

  unsigned long nowMs = millis();
  if (timeIsSet() && (lastSample == 0 || nowMs - lastSample >= PUBLISH_INTERVAL_MS)) {
    lastSample = nowMs;
    String json;
    if (readMeter(json)) {
      pushRing(json);
      Serial.println(json);
    } else {
      Serial.println("PZEM read failed");
    }
  }
  flushRing();
  delay(50);
}
