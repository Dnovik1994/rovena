#!/usr/bin/env bash
set -euo pipefail

log() {
  echo "[migrations] $*"
}

# ── Bootstrap: widen alembic_version.version_num ──────────────────────
# Default Alembic creates version_num as VARCHAR(32) which is too short
# for revision IDs like '0018_add_telegram_accounts_auth_flows' (41 chars).
# We widen it BEFORE running Alembic so that long revision IDs can be stamped.
log "Ensuring alembic_version.version_num is wide enough."
python - <<'PY'
import sys
from sqlalchemy import inspect as sa_inspect, text
from app.core.database import engine

try:
    with engine.connect() as conn:
        inspector = sa_inspect(conn)
        if "alembic_version" not in inspector.get_table_names():
            # Table will be created by Alembic on first run.
            sys.exit(0)
        cols = {c["name"]: c for c in inspector.get_columns("alembic_version")}
        ver_col = cols.get("version_num")
        if ver_col is None:
            sys.exit(0)
        col_length = getattr(ver_col.get("type"), "length", None)
        if col_length is not None and col_length < 128:
            conn.execute(text(
                "ALTER TABLE alembic_version MODIFY version_num VARCHAR(128) NOT NULL"
            ))
            conn.commit()
            print("[migrations] Widened alembic_version.version_num to VARCHAR(128)")
        else:
            print("[migrations] alembic_version.version_num already wide enough")
except Exception as exc:
    # Non-fatal: if the table doesn't exist yet Alembic will create it.
    print(f"[migrations] Bootstrap note: {exc}", file=sys.stderr)
PY

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
  elif echo "$upgrade_output" | grep -Eqi "Data too long for column.*version_num|1406"; then
    log "Detected version_num overflow, retrying with widened column..."
    python -c "
from sqlalchemy import text
from app.core.database import engine
with engine.connect() as c:
    c.execute(text(\"ALTER TABLE alembic_version MODIFY version_num VARCHAR(128) NOT NULL\"))
    c.commit()
" 2>/dev/null || true
  else
    log "Alembic upgrade failed with unexpected error:"
    echo "$upgrade_output"
    exit 1
  fi

  attempt=$((attempt + 1))
done

log "Migration failed after retries, manual fix required"
exit 1
