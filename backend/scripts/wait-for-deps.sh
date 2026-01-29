#!/usr/bin/env bash
set -euo pipefail

log() {
  echo "[wait-for-deps] $*"
}

if [[ "${WAIT_FOR_DB:-1}" == "1" ]]; then
  log "Waiting for database readiness checks."
  /app/scripts/wait-for-db.sh
fi

if [[ "${WAIT_FOR_REDIS:-1}" == "1" ]]; then
  log "Waiting for Redis readiness checks."
  /app/scripts/wait-for-redis.sh
fi
