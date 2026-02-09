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

if [[ "${WAIT_FOR_DB_TABLES:-1}" == "1" ]]; then
  /app/scripts/wait-for-db.sh
fi

if [[ "${WAIT_FOR_REDIS:-1}" == "1" ]]; then
  /app/scripts/wait-for-redis.sh
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
