#!/usr/bin/env bash
set -euo pipefail

DOMAIN=${1:-kass.freestorms.top}
BACKUP_DIR=${2:-/backups}

health_url="https://${DOMAIN}/health"
metrics_url="https://${DOMAIN}/metrics"
ws_url="wss://${DOMAIN}/ws/status"

echo "Checking health: ${health_url}"
curl -fsS "${health_url}" > /dev/null

echo "Checking HTTPS health: https://${DOMAIN}/health"
curl -fsS "https://${DOMAIN}/health" > /dev/null

echo "Checking metrics: ${metrics_url}"
curl -fsS "${metrics_url}" > /dev/null

echo "Checking Prometheus targets: http://localhost:9090/targets"
curl -fsS "http://localhost:9090/targets" > /dev/null

echo "Checking Grafana health: http://localhost:3000/api/health"
curl -fsS "http://localhost:3000/api/health" > /dev/null

echo "Checking WebSocket endpoint: ${ws_url}"
python - <<PY
import sys
from urllib.parse import urlparse
import websocket

url = "${ws_url}"
try:
    ws = websocket.create_connection(url, timeout=5)
    ws.close()
    print("WebSocket connect OK")
except Exception as exc:
    print(f"WebSocket connect failed: {exc}")
    sys.exit(1)
PY

echo "Checking backup directory: ${BACKUP_DIR}"
if [ ! -d "${BACKUP_DIR}" ]; then
  echo "Backup directory not found: ${BACKUP_DIR}"
  exit 1
fi

latest_backup=$(ls -1t "${BACKUP_DIR}" | head -n 1 || true)
if [ -z "${latest_backup}" ]; then
  echo "No backups found in ${BACKUP_DIR}"
  exit 1
fi

echo "Latest backup: ${latest_backup}"

echo "Tailing backend logs (last 200 lines)"
docker compose -f docker-compose.prod.yml logs --tail=200 backend
