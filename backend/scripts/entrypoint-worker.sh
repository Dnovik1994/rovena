#!/usr/bin/env bash
set -euo pipefail

log() {
  echo "[entrypoint-worker] $*"
}

if [[ "${COMMIT_SHA:-unknown}" == "unknown" ]] && command -v git >/dev/null 2>&1; then
  COMMIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
  export COMMIT_SHA
fi

if [[ "${WAIT_FOR_DEPS:-1}" == "1" ]]; then
  /app/scripts/wait-for-deps.sh
fi

if [[ "${RUN_MIGRATIONS:-1}" == "1" ]]; then
  /app/scripts/run-migrations.sh
else
  log "Skipping migrations (RUN_MIGRATIONS=${RUN_MIGRATIONS:-0})."
fi

if [[ "${WAIT_FOR_DB_TABLES:-1}" == "1" ]]; then
  /app/scripts/wait-for-db.sh
fi

if [[ "${WAIT_FOR_REDIS:-1}" == "1" ]]; then
  /app/scripts/wait-for-redis.sh
fi

if [[ $# -eq 0 ]]; then
  set -- celery -A "${CELERY_APP:-app.workers:celery_app}" worker \
    --loglevel=info \
    --hostname "celery@%h" \
    --pool "${CELERY_POOL:-solo}" \
    --concurrency "${CELERY_CONCURRENCY:-1}"
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
