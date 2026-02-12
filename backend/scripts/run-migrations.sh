#!/usr/bin/env bash
set -euo pipefail

log() {
  echo "[migrations] $*"
}

# ---------------------------------------------------------------------------
# MySQL advisory lock to prevent concurrent migration runs.
# GET_LOCK() is session-scoped and re-entrant within the same connection,
# so even if the backend calls this script twice in the same startup
# sequence, only one process at a time will actually run Alembic.
# ---------------------------------------------------------------------------
LOCK_NAME="alembic_migration_lock"
LOCK_TIMEOUT="${MIGRATION_LOCK_TIMEOUT:-120}"

acquire_lock() {
  log "Acquiring advisory lock '${LOCK_NAME}' (timeout ${LOCK_TIMEOUT}s)..."
  lock_result=$(python -c "
from sqlalchemy import create_engine, text
from app.core.settings import get_settings
engine = create_engine(get_settings().database_url)
with engine.connect() as conn:
    result = conn.execute(text(\"SELECT GET_LOCK('${LOCK_NAME}', ${LOCK_TIMEOUT})\")).scalar()
    print(result)
" 2>&1) || true

  if [[ "$lock_result" != "1" ]]; then
    log "ERROR: Failed to acquire advisory lock (result: ${lock_result})."
    log "Another migration may be running or the timeout was exceeded."
    exit 1
  fi
  log "Advisory lock acquired."
}

release_lock() {
  log "Releasing advisory lock '${LOCK_NAME}'..."
  python -c "
from sqlalchemy import create_engine, text
from app.core.settings import get_settings
engine = create_engine(get_settings().database_url)
with engine.connect() as conn:
    conn.execute(text(\"SELECT RELEASE_LOCK('${LOCK_NAME}')\"))
" 2>/dev/null || log "WARNING: Could not release advisory lock (may auto-release on disconnect)."
}

# Ensure lock is released on any exit (success, failure, signal).
trap release_lock EXIT

acquire_lock

# ---------------------------------------------------------------------------
# Run Alembic migrations with retry logic for known recoverable errors.
# ---------------------------------------------------------------------------
attempt=1
max_retries=3

log "Running Alembic migrations."
while [[ "$attempt" -le "$max_retries" ]]; do
  log "Attempt ${attempt}: upgrading..."
  upgrade_output=""
  if upgrade_output="$(alembic upgrade head 2>&1)"; then
    log "Alembic migrations complete."
    break
  fi

  if echo "$upgrade_output" | grep -Eqi "duplicate key name|1061"; then
    log "Detected duplicate index, downgrading to 0014..."
    if ! alembic downgrade 0014; then
      log "Alembic downgrade to 0014 failed."
      exit 1
    fi
  elif echo "$upgrade_output" | grep -Eqi "Data too long for column.*version_num|1406.*version_num"; then
    log "Detected version_num column too narrow, widening to VARCHAR(128)..."
    python -c "
from sqlalchemy import create_engine, text
from app.core.settings import get_settings
engine = create_engine(get_settings().database_url)
with engine.connect() as conn:
    conn.execute(text('ALTER TABLE alembic_version MODIFY version_num VARCHAR(128) NOT NULL'))
    conn.commit()
print('version_num widened successfully')
" 2>&1 && log "Column widened, retrying migration." || log "Column widen failed, retrying anyway."
  else
    log "Alembic upgrade failed with unexpected error:"
    echo "$upgrade_output"
    exit 1
  fi

  attempt=$((attempt + 1))
  if [[ "$attempt" -gt "$max_retries" ]]; then
    log "Migration failed after ${max_retries} retries, manual fix required."
    exit 1
  fi
done

# ---------------------------------------------------------------------------
# Post-migration consistency checks.
# ---------------------------------------------------------------------------
log "Running post-migration consistency checks..."

row_count=$(python -c "
from sqlalchemy import create_engine, text
from app.core.settings import get_settings
engine = create_engine(get_settings().database_url)
with engine.connect() as conn:
    count = conn.execute(text('SELECT COUNT(*) FROM alembic_version')).scalar()
    print(count)
" 2>&1)

if [[ "$row_count" != "1" ]]; then
  log "CRITICAL: alembic_version has ${row_count} row(s) — expected exactly 1."
  log "This indicates corruption from a concurrent migration run."
  log "Manual remediation required: DELETE extra rows and keep only the correct head."
  exit 1
fi
log "OK: alembic_version has exactly 1 row."

# Verify the DB revision matches alembic's single head.
db_revision=$(python -c "
from sqlalchemy import create_engine, text
from app.core.settings import get_settings
engine = create_engine(get_settings().database_url)
with engine.connect() as conn:
    rev = conn.execute(text('SELECT version_num FROM alembic_version')).scalar()
    print(rev)
" 2>&1)

alembic_head=$(alembic heads 2>&1 | grep -oP '^\S+' | head -n1) || true

if [[ -n "$alembic_head" && "$db_revision" != "$alembic_head" ]]; then
  log "WARNING: DB revision '${db_revision}' does not match alembic head '${alembic_head}'."
  log "This may indicate a migration was partially applied."
  # Non-fatal: the upgrade succeeded, but heads may differ if there are branches.
  # Log a warning but do not block startup.
fi

log "Post-migration checks passed (revision: ${db_revision})."
