#!/usr/bin/env bash
set -euo pipefail

log() {
  echo "[wait-for-redis] $*"
}

max_retries="${REDIS_WAIT_MAX_RETRIES:-${WAIT_MAX_RETRIES:-30}}"
backoff_base="${REDIS_WAIT_BACKOFF_BASE:-${WAIT_BACKOFF_BASE:-2}}"
backoff_max="${REDIS_WAIT_BACKOFF_MAX:-${WAIT_BACKOFF_MAX:-20}}"
attempt=1
delay="${REDIS_WAIT_INITIAL_DELAY:-${WAIT_INITIAL_DELAY:-1}}"

log "Checking Redis readiness."

until python - <<'PY'
import os
import sys
import time
import redis

redis_url = os.getenv("REDIS_URL") or os.getenv("redis_url")
if not redis_url:
    host = os.getenv("REDIS_HOST", "redis")
    port = int(os.getenv("REDIS_PORT", "6379"))
    db = int(os.getenv("REDIS_DB", "0"))
    redis_url = f"redis://{host}:{port}/{db}"

client = redis.Redis.from_url(
    redis_url,
    socket_connect_timeout=3,
    socket_timeout=3,
    decode_responses=True,
)

key = f"healthcheck:{os.getpid()}"
value = f"{time.time()}"

try:
    client.ping()
    client.set(key, value, ex=5)
    result = client.get(key)
    if result != value:
        raise RuntimeError("Redis read/write mismatch")
except Exception as exc:
    print(f"Redis readiness check failed: {exc}", file=sys.stderr)
    sys.exit(1)

sys.exit(0)
PY
  do
    if [[ "$attempt" -ge "$max_retries" ]]; then
      log "Redis not ready after ${attempt} attempts."
      exit 1
    fi
    log "Redis not ready (attempt ${attempt}/${max_retries}), retrying in ${delay}s."
    sleep "$delay"
    delay=$((delay * backoff_base))
    if [[ "$delay" -gt "$backoff_max" ]]; then
      delay="$backoff_max"
    fi
    attempt=$((attempt + 1))
  done

log "Redis is ready."
