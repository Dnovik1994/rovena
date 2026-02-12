#!/usr/bin/env bash
set -euo pipefail

log() {
  echo "[migrations] $*"
}

# ---------------------------------------------------------------------------
# Run Alembic migrations under a MySQL advisory lock.
#
# All locking, migration, and post-migration consistency logic lives in
# migrate_with_lock.py so the advisory lock is held in a single MySQL
# session for the entire duration (GET_LOCK is session-scoped).
# ---------------------------------------------------------------------------
log "Starting migration runner."
exec python /app/scripts/migrate_with_lock.py
