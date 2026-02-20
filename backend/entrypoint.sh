#!/usr/bin/env bash
set -euo pipefail

role="${APP_ROLE:-backend}"

case "$role" in
  backend)
    exec /app/scripts/entrypoint-backend.sh "$@"
    ;;
  worker)
    exec /app/scripts/entrypoint-worker.sh "$@"
    ;;
  beat)
    # Beat skips migrations — just exec the command from docker-compose
    exec "$@"
    ;;
  *)
    echo "[entrypoint] Unknown APP_ROLE: $role" >&2
    exit 1
    ;;
esac
