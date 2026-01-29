#!/usr/bin/env bash
set -euo pipefail

log() {
  echo "[wait-for-deps] $*"
}

check_port() {
  local host="$1"
  local port="$2"
  python - "$host" "$port" <<'PY'
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])

try:
    with socket.create_connection((host, port), timeout=2):
        sys.exit(0)
except OSError:
    sys.exit(1)
PY
}

wait_for() {
  local name="$1"
  local host="$2"
  local port="$3"
  local max_retries="${WAIT_MAX_RETRIES:-30}"
  local backoff_base="${WAIT_BACKOFF_BASE:-2}"
  local backoff_max="${WAIT_BACKOFF_MAX:-20}"
  local attempt=1
  local delay="${WAIT_INITIAL_DELAY:-1}"

  log "Waiting for ${name} at ${host}:${port}."
  until check_port "$host" "$port"; do
    if [[ "$attempt" -ge "$max_retries" ]]; then
      log "Timeout waiting for ${name} after ${attempt} attempts."
      return 1
    fi
    log "${name} not ready (attempt ${attempt}/${max_retries}), retrying in ${delay}s."
    sleep "$delay"
    delay=$((delay * backoff_base))
    if [[ "$delay" -gt "$backoff_max" ]]; then
      delay="$backoff_max"
    fi
    attempt=$((attempt + 1))
  done
  log "${name} is available."
}

if [[ "${WAIT_FOR_DB:-1}" == "1" ]]; then
  wait_for "database" "${DB_HOST:-db}" "${DB_PORT:-3306}"
fi

if [[ "${WAIT_FOR_REDIS:-1}" == "1" ]]; then
  wait_for "redis" "${REDIS_HOST:-redis}" "${REDIS_PORT:-6379}"
fi
