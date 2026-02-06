#!/usr/bin/env bash
set -euo pipefail

redis_url="${REDIS_URL:-}"
hostname="${HOSTNAME:-}"
timeout="${CELERY_HEALTHCHECK_TIMEOUT:-5}"
max_age="${CELERY_HEARTBEAT_MAX_AGE:-20}"

if [[ -z "$redis_url" ]]; then
  echo "REDIS_URL is not set"
  exit 1
fi

HEARTBEAT_KEY="celery:worker:heartbeat:${hostname}" \
CELERY_HEARTBEAT_TIMEOUT="$timeout" \
CELERY_HEARTBEAT_MAX_AGE="$max_age" \
python - <<'PY'
import os
import sys
import time

import redis

redis_url = os.environ["REDIS_URL"]
key = os.environ["HEARTBEAT_KEY"]
timeout = float(os.environ.get("CELERY_HEARTBEAT_TIMEOUT", "5"))
max_age = float(os.environ.get("CELERY_HEARTBEAT_MAX_AGE", "20"))

client = redis.Redis.from_url(
    redis_url,
    socket_timeout=timeout,
    socket_connect_timeout=timeout,
)
value = client.get(key)
if not value:
    sys.exit(1)
try:
    ts = float(value)
except (TypeError, ValueError):
    sys.exit(1)
if time.time() - ts > max_age:
    sys.exit(1)
PY
