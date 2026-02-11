#!/usr/bin/env bash
set -euo pipefail

log() {
  echo "[migrations] $*"
}

attempt=1
max_retries=3

log "Running Alembic migrations."
while [[ "$attempt" -le "$max_retries" ]]; do
  log "Attempt ${attempt}: upgrading..."
  upgrade_output=""
  if upgrade_output="$(alembic upgrade head 2>&1)"; then
    log "Alembic migrations complete."
    exit 0
  fi

  if echo "$upgrade_output" | grep -Eqi "duplicate key name|1061"; then
    log "Detected duplicate index, downgrading to 0014..."
    if ! alembic downgrade 0014; then
      log "Alembic downgrade to 0014 failed."
      exit 1
    fi
  else
    log "Alembic upgrade failed with unexpected error:"
    echo "$upgrade_output"
    exit 1
  fi

  attempt=$((attempt + 1))
done

log "Migration failed after retries, manual fix required"
exit 1
