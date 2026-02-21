#!/usr/bin/env bash
set -euo pipefail

log() {
  echo "[entrypoint-backend] $*"
}

if [[ "${COMMIT_SHA:-unknown}" == "unknown" ]] && command -v git >/dev/null 2>&1; then
  COMMIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
  export COMMIT_SHA
fi

if [[ "${WAIT_FOR_DEPS:-1}" == "1" ]]; then
  /app/scripts/wait-for-deps.sh
fi

# Auto-apply database migrations
if [[ "${RUN_MIGRATIONS:-1}" == "1" ]]; then
  log "Running alembic migrations..."

  # Refuse to start if multiple migration heads exist — resolve manually.
  HEAD_COUNT=$(alembic heads 2>/dev/null | wc -l)
  if [[ "$HEAD_COUNT" -gt 1 ]]; then
    log "CRITICAL: Multiple Alembic heads detected ($HEAD_COUNT). Merge them manually before deploying."
    exit 1
  fi

  migration_ok=0
  for attempt in 1 2 3; do
    log "Migration attempt ${attempt}/3..."
    if alembic upgrade head; then
      migration_ok=1
      break
    fi
    if [[ "$attempt" -lt 3 ]]; then
      backoff=$((attempt * 5))
      log "Migration failed, retrying in ${backoff}s..."
      sleep "$backoff"
    fi
  done

  if [[ "$migration_ok" -ne 1 ]]; then
    log "CRITICAL: alembic upgrade failed after 3 attempts. Refusing to start backend."
    exit 1
  fi
fi

if [[ $# -eq 0 ]]; then
  uvicorn_host="${UVICORN_HOST:-${HOST:-0.0.0.0}}"
  uvicorn_port="${UVICORN_PORT:-${PORT:-8000}}"
  log "Starting uvicorn on ${uvicorn_host}:${uvicorn_port}"
  set -- uvicorn app.main:app --host "${uvicorn_host}" --port "${uvicorn_port}"
fi

terminate() {
  log "Shutdown signal received, forwarding to child process."
  if [[ -n "${child_pid:-}" ]]; then
    kill -TERM "$child_pid" 2>/dev/null || true
    wait "$child_pid" || true
  fi
}

trap terminate SIGTERM SIGINT

"$@" &
child_pid=$!
wait "$child_pid"
