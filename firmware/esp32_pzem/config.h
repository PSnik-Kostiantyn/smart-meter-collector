// Налаштування конкретного вузла обліку. Перед прошивкою змініть значення.
#pragma once

#define WIFI_SSID "your-wifi"
#define WIFI_PASSWORD "your-password"

#define MQTT_HOST "192.168.1.10"
#define MQTT_PORT 1883
#define MQTT_USER nullptr
#define MQTT_PASSWORD nullptr

// Має збігатися із записом у config/meters.json на сервері
#define METER_ID "M-000001"
#define DISTRICT "holosiivskyi"

// 15 хвилин, як у побутових інтелектуальних лічильниках
#define PUBLISH_INTERVAL_MS (15UL * 60UL * 1000UL)
