#!/usr/bin/env bash
# Перезапускає стек з чистими томами. Потрібно перед кожним вимірюванням.
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose down -v --remove-orphans
docker compose up -d --build --wait --scale collector="${SCALE:-1}"
