#!/usr/bin/env bash
# Ступінчасте навантаження. Для кожної сумарної швидкості R два емулятори
# по R/2 повідомлень за секунду працюють DURATION секунд.
# SCALE задає кількість копій колектора, які ділять потік через $share.
# У CSV записується
#   received_at_stop  скільки колектори отримали на момент зупинки емуляторів
#   lag_msgs          скільки повідомлень на той момент ще чекало в черзі
#   drain_s           за скільки секунд колектори дочитали чергу
set -euo pipefail
cd "$(dirname "$0")/.."
DURATION=${DURATION:-40}
SCALE=${SCALE:-1}
OUT=results/step_test_x${SCALE}.csv
echo "replicas,rate_target,sent,rate_sent,received_at_stop,rate_collected,lag_msgs,drain_s" > "$OUT"

received() {
  docker compose logs collector 2>/dev/null | grep 'msg/s' \
    | sed -E 's/^(collector-[0-9]+).*received=([0-9]+).*/\1 \2/' \
    | awk '{last[$1]=$2} END{s=0; for (k in last) s+=last[k]; print s}'
}

for R in "$@"; do
  SCALE=$SCALE STATS_INTERVAL_S=1 ./tools/reset_stack.sh > /dev/null 2>&1
  sleep 3
  HALF=$((R / 2))
  pids=()
  for i in 0 1; do
    .venv/bin/python tools/fake_meters.py --offset $((i * 500)) --limit 500 --rate "$HALF" \
      --duration "$DURATION" --report "results/step_x${SCALE}_${R}_$i.json" > /dev/null &
    pids+=($!)
  done
  for p in "${pids[@]}"; do wait "$p"; done
  T_STOP=$(date +%s.%N)
  sleep 1.1
  AT_STOP=$(received)
  SENT=$(python3 -c "import json;print(sum(json.load(open(f'results/step_x${SCALE}_${R}_{i}.json'))['sent'] for i in (0,1)))")
  for k in $(seq 1 600); do
    [ "$(received)" -ge "$SENT" ] && break
    sleep 0.5
  done
  DRAIN=$(echo "$(date +%s.%N) - $T_STOP" | bc | xargs printf "%.0f")
  docker compose logs collector > "results/step_x${SCALE}_${R}_collector.log"
  echo "$SCALE,$R,$SENT,$((SENT / DURATION)),$AT_STOP,$((AT_STOP / DURATION)),$((SENT - AT_STOP)),$DRAIN" | tee -a "$OUT"
done
