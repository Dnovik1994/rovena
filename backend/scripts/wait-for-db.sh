#!/usr/bin/env bash
set -euo pipefail

log() {
  echo "[wait-for-db] $*"
}

check_tables=0
if [[ "${1:-}" == "--check-tables" ]]; then
  check_tables=1
fi

max_retries="${DB_WAIT_MAX_RETRIES:-${WAIT_MAX_RETRIES:-30}}"
backoff_base="${DB_WAIT_BACKOFF_BASE:-${WAIT_BACKOFF_BASE:-2}}"
backoff_max="${DB_WAIT_BACKOFF_MAX:-${WAIT_BACKOFF_MAX:-20}}"
attempt=1
delay="${DB_WAIT_INITIAL_DELAY:-${WAIT_INITIAL_DELAY:-1}}"

required_tables="${REQUIRED_DB_TABLES:-alembic_version}"

log "Checking database readiness${check_tables:+ with table validation}."

until python - "$check_tables" "$required_tables" <<'PY'
import os
import sys
from urllib.parse import urlparse

import pymysql

check_tables = bool(int(sys.argv[1]))
required_tables = [t.strip() for t in sys.argv[2].split(",") if t.strip()]

def get_db_config():
    db_url = os.getenv("DATABASE_URL") or os.getenv("database_url")
    if db_url:
        parsed = urlparse(db_url)
        scheme = parsed.scheme.split("+")[0]
        if scheme not in {"mysql", "mariadb"}:
            raise ValueError(f"Unsupported database scheme: {parsed.scheme}")
        return {
            "host": parsed.hostname or "db",
            "port": parsed.port or 3306,
            "user": parsed.username or "rovena",
            "password": parsed.password or "rovena",
            "database": (parsed.path or "/rovena").lstrip("/") or "rovena",
        }
    return {
        "host": os.getenv("DB_HOST", "db"),
        "port": int(os.getenv("DB_PORT", "3306")),
        "user": os.getenv("DB_USER", "rovena"),
        "password": os.getenv("DB_PASSWORD", "rovena"),
        "database": os.getenv("DB_NAME", "rovena"),
    }

config = get_db_config()

try:
    connection = pymysql.connect(
        host=config["host"],
        port=config["port"],
        user=config["user"],
        password=config["password"],
        database=config["database"],
        connect_timeout=3,
        read_timeout=3,
        write_timeout=3,
        charset="utf8mb4",
        autocommit=True,
    )
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema='mysql' AND table_name='user'"
        )
        system_tables_ready = cursor.fetchone()[0] > 0
        if not system_tables_ready:
            sys.exit(1)
        if check_tables and required_tables:
            for table in required_tables:
                cursor.execute(
                    "SELECT COUNT(*) FROM information_schema.tables "
                    "WHERE table_schema=%s AND table_name=%s",
                    (config["database"], table),
                )
                if cursor.fetchone()[0] == 0:
                    sys.exit(1)
except Exception as exc:
    print(f"Database readiness check failed: {exc}", file=sys.stderr)
    sys.exit(1)
else:
    sys.exit(0)
finally:
    try:
        connection.close()
    except Exception:
        pass
PY
  do
    if [[ "$attempt" -ge "$max_retries" ]]; then
      log "Database not ready after ${attempt} attempts."
      exit 1
    fi
    log "Database not ready (attempt ${attempt}/${max_retries}), retrying in ${delay}s."
    sleep "$delay"
    delay=$((delay * backoff_base))
    if [[ "$delay" -gt "$backoff_max" ]]; then
      delay="$backoff_max"
    fi
    attempt=$((attempt + 1))
  done

log "Database is ready."
