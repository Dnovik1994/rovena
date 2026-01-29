#!/usr/bin/env bash
set -euo pipefail

if [[ "${COMMIT_SHA:-unknown}" == "unknown" ]] && command -v git >/dev/null 2>&1; then
  COMMIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
  export COMMIT_SHA
fi

max_retries=5
attempts=0
until alembic upgrade head; do
  attempts=$((attempts + 1))
  if [[ $attempts -ge $max_retries ]]; then
    echo "Alembic upgrade failed after retries" >&2
    exit 1
  fi
  echo "alembic upgrade failed, retrying in 2s..." >&2
  sleep 2
done

if [[ $# -eq 0 ]]; then
  set -- uvicorn app.main:app --host 0.0.0.0 --port 8020
fi

exec "$@"
