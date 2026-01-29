#!/usr/bin/env bash
set -euo pipefail

log() {
  echo "[migrations] $*"
}

max_retries="${MIGRATION_MAX_RETRIES:-10}"
backoff_base="${MIGRATION_BACKOFF_BASE:-2}"
backoff_max="${MIGRATION_BACKOFF_MAX:-30}"
attempt=1
delay="${MIGRATION_INITIAL_DELAY:-1}"

log "Running Alembic migrations."
until alembic upgrade head; do
  if [[ "$attempt" -ge "$max_retries" ]]; then
    log "Alembic upgrade failed after ${attempt} attempts."
    exit 1
  fi
  log "Alembic upgrade failed (attempt ${attempt}/${max_retries}), retrying in ${delay}s."
  sleep "$delay"
  delay=$((delay * backoff_base))
  if [[ "$delay" -gt "$backoff_max" ]]; then
    delay="$backoff_max"
  fi
  attempt=$((attempt + 1))
done

log "Alembic migrations complete."
