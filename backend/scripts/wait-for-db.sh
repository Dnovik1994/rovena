#!/usr/bin/env bash
set -euo pipefail

log() {
  echo "[wait-for-db] $*"
}

max_retries=30
backoff_base=2
backoff_max=20
attempt=1
delay=1

db_host="${DB_HOST:-db}"
db_port="${DB_PORT:-3306}"
db_user="${DB_USER:-rovena}"
db_password="${DB_PASSWORD:-rovena}"
required_tables="${REQUIRED_DB_TABLES:-alembic_version}"

log "Checking database readiness."

while [[ "$attempt" -le "$max_retries" ]]; do
  log "Attempt ${attempt}: pinging database."
  ping_ok=0
  if ! python -m app.utils.db_readiness ping; then
    log "Database ping failed."
  else
    log "Database ping ok."
    ping_ok=1
  fi

  if [[ "$ping_ok" -eq 1 ]] && python -m app.utils.db_readiness ensure-db; then
    if [[ "${RUN_MIGRATIONS:-1}" == "1" ]]; then
      if ! /app/scripts/run-migrations.sh; then
        log "Migrations failed; will retry."
      fi
    else
      log "Skipping migrations (RUN_MIGRATIONS=${RUN_MIGRATIONS:-0})."
    fi

    if python -m app.utils.db_readiness check-tables "$required_tables"; then
      log "Database ready after ${attempt} attempts."
      exit 0
    fi
  fi

  if [[ "$attempt" -ge "$max_retries" ]]; then
    log "Database not ready after retries"
    exit 1
  fi

  log "Database not ready (attempt ${attempt}/${max_retries}), retrying in ${delay}s."
  sleep "$delay"
  delay=$((delay * backoff_base))
  if [[ "$delay" -gt "$backoff_max" ]]; then
    delay="$backoff_max"
  fi
  attempt=$((attempt + 1))
done
