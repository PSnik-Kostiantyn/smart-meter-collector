# Smart Meter Collector

Програма збору показників електролічильників для курсової роботи
«Розробка системи моніторингу показників електролічильників», частина 1.2.

Автори Костянтин Сінько і Артем Хворостяний, група ТВ-61мн, КПІ ім. Ігоря Сікорського.

## Що робить програма

Лічильник, тобто ESP32 з модулем PZEM-004T v3.0, публікує JSON у топік MQTT
`meters/<район>/<номер_лічильника>/readings`. Колектор на Python підписаний на ці
топіки. Він перевіряє кожне повідомлення і пачками записує прийняті показники
в InfluxDB. Повідомлення, які не пройшли перевірку, теж потрапляють у базу,
але в окремий measurement разом із причиною відмови. Раз на кілька секунд
колектор пише, скільки повідомлень прийнято і відкинуто.

```
ESP32 + PZEM-004T  ->  Mosquitto (MQTT)  ->  collector (Python)  ->  InfluxDB  ->  Grafana / обробка
```

## Формат повідомлення

```json
{
  "meter_id": "M-000123",
  "ts": "2026-11-23T00:15:00Z",
  "energy_kwh": 1234.567,
  "power_w": 2310.5,
  "voltage_v": 229.8,
  "current_a": 10.812,
  "power_factor": 0.93,
  "frequency_hz": 50.01
}
```

| Поле | Одиниця | Допустимі значення |
|---|---|---|
| meter_id | рядок | має бути в довіднику `config/meters.json` і збігатися з топіком |
| ts | ISO 8601 з часовим поясом або Unix-секунди | не більше 60 с у майбутньому, не старше 7 діб |
| energy_kwh | кВт·год, накопичувальний | 0 і більше, не менший за попередній показник |
| power_w | Вт | 0–69000, не більше U·I·кількість фаз з допуском 10% |
| voltage_v | В | 80–300 |
| current_a | А | 0–100 |
| power_factor | | 0–1 |
| frequency_hz | Гц | 45–65 |

## Структура даних в InfluxDB

Bucket `meters`, організація `iot`.

| Measurement | Теги | Поля |
|---|---|---|
| `readings` | meter_id, district, customer_type | energy_kwh, power_w, voltage_v, current_a, power_factor, frequency_hz |
| `rejected_messages` | reason, meter_id якщо відомий | raw_payload, topic, detail |
| `collector_stats` | instance | received, accepted, rejected, received_rate, accepted_rate, rejected_rate, buffer |

Довідник лічильників зберігається у `config/meters.json`. Колектор перечитує файл
кожні 10 секунд, якщо той змінився.

Причини відмови мають такі коди. `invalid_json`, `schema_error`, `topic_mismatch`,
`unknown_meter`, `district_mismatch`, `out_of_range`, `inconsistent_power`,
`future_timestamp`, `stale_timestamp`, `out_of_order`, `energy_decreased`.

## Запуск

Потрібні Docker і Docker Compose.

```bash
cp .env.example .env                 # за потреби змініть паролі
python3 tools/gen_meters.py --count 1000 --out config/meters.json
docker compose up -d --build
docker compose logs -f collector
```

Після запуску доступні MQTT на порту 1883, InfluxDB на http://localhost:8086
і Grafana на http://localhost:3000. Логін у Grafana admin, пароль з `.env`.
Джерело даних InfluxDB у Grafana вже налаштоване.

Надіслати тестові дані можна емулятором.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
# 1000 лічильників, кожен раз на секунду, 5% зіпсованих повідомлень, 60 секунд
.venv/bin/python tools/fake_meters.py --interval 1 --duration 60 --bad 0.05
```

Кілька копій колектора ділять потік між собою через спільну підписку
`$share/collectors/...`.

```bash
docker compose up -d --scale collector=2
```

## Тести

```bash
.venv/bin/python -m pytest -q
```

Модульні тести покривають усі правила перевірки, формування line protocol,
поділ на пачки і поведінку при недоступній БД.

Інтеграційні й навантажувальні тести запускаються скриптами з `tools/`.

| Скрипт | Що робить |
|---|---|
| `tools/reset_stack.sh` | перезапускає стек з чистою базою |
| `tools/fake_meters.py` | емулює лічильники, вміє псувати частину повідомлень |
| `tools/verify_counts.py` | звіряє кількість записаного в InfluxDB із надісланим |
| `tools/load_test.sh` | кілька емуляторів на максимальній швидкості |
| `tools/step_test.sh` | ступінчасте навантаження із заданою швидкістю |

Результати наших вимірювань лежать у `results/`, а їхній опис є в пояснювальній записці.

## Прошивка ESP32

`firmware/esp32_pzem` містить скетч для ESP32 з PZEM-004T v3.0. Перед прошивкою
заповніть `config.h`. Скетч компілюється для `esp32:esp32:esp32` з бібліотеками
PZEM004Tv30 1.2.1, PubSubClient 2.8 і ArduinoJson 7.4.

```bash
arduino-cli compile --fqbn esp32:esp32:esp32 firmware/esp32_pzem
```

На реальному пристрої прошивку не перевіряли, бо заліза в нас не було.
Перевірено лише компіляцію.

## Структура репозиторію

```
collector/            код колектора і Dockerfile
config/meters.json    довідник лічильників
firmware/esp32_pzem/  прошивка вузла обліку
grafana/              автоматичне налаштування джерела даних
mosquitto/            конфігурація брокера
results/              результати тестів
tests/                модульні тести
tools/                емулятор і скрипти тестування
```

## Ліцензія

MIT
