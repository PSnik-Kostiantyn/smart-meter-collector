#!/usr/bin/env bash
# Навантажувальний тест. Аргументи
#   $1 кількість паралельних емуляторів (за замовчуванням 4)
#   $2 повідомлень на один емулятор (за замовчуванням 100000)
#   $3 мітка запуску для файлів у results/
#   $4 QoS публікації (за замовчуванням 1)
set -euo pipefail
cd "$(dirname "$0")/.."
P=${1:-4}; N=${2:-100000}; TAG=${3:-load}; QOS=${4:-1}
METERS=$(python3 -c "import json;print(len(json.load(open('config/meters.json'))))")
PER=$((METERS / P))
mkdir -p results
(while sleep 1; do
  docker stats --no-stream --format '{{.Name}} {{.CPUPerc}} {{.MemUsage}}' \
    | grep -E 'collector|influxdb|mosquitto' | tr '\n' ' '; echo
 done) > "results/${TAG}_dockerstats.log" &
DS=$!
T0=$(date +%s.%N)
pids=()
for i in $(seq 0 $((P - 1))); do
  .venv/bin/python tools/fake_meters.py --offset $((i * PER)) --limit $PER --total "$N" \
    --rate 0 --qos "$QOS" --report "results/${TAG}_sent_$i.json" > /dev/null &
  pids+=($!)
done
for p in "${pids[@]}"; do wait "$p"; done
T1=$(date +%s.%N)
TOTAL=$((P * N))
for k in $(seq 1 600); do
  GOT=$(docker compose logs collector --no-log-prefix | grep 'msg/s' | tail -1 | sed -E 's/.*received=([0-9]+).*/\1/')
  [ "${GOT:-0}" -ge "$TOTAL" ] && break
  sleep 1
done
T2=$(date +%s.%N)
sleep 2
kill $DS
echo "publishers: $P x $N messages, publish time $(echo "$T1 - $T0" | bc) s, all received after $(echo "$T2 - $T0" | bc) s"
docker compose logs collector --no-log-prefix | grep 'msg/s' > "results/${TAG}_collector.log"
