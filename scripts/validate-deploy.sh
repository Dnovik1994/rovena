#!/usr/bin/env bash
# Post-deploy validation for rovena production stack.
#
# Checks:
#   1. Container health  — backend, db, redis are healthy / running
#   2. HTTP endpoints     — GET /health and /api/v1/health return 200
#   3. Migration rows     — alembic_version has exactly 1 row
#   4. Migration version  — DB version_num matches `alembic heads`
#   5. Worker safety      — worker container has RUN_MIGRATIONS=0
#
# Output: [OK] / [FAIL] per check.  Exit 0 on success, 1 on any failure.
#
# Usage:
#   ./scripts/validate-deploy.sh              # uses DOMAIN from env or default
#   DOMAIN=example.com ./scripts/validate-deploy.sh
set -uo pipefail

COMPOSE="docker compose -f docker-compose.prod.yml"
DOMAIN="${DOMAIN:-kass.freestorms.top}"
FAILURES=0

pass() { printf "  [OK]   %s\n" "$1"; }
fail() { printf "  [FAIL] %s\n" "$1"; FAILURES=$((FAILURES + 1)); }

# ── 1. Container health ──────────────────────────────────────────────
echo "=== Container health ==="
for svc in backend db redis; do
  health=$($COMPOSE ps --format '{{.Health}}' "$svc" 2>/dev/null || true)
  state=$($COMPOSE ps --format '{{.State}}' "$svc" 2>/dev/null || true)
  if [ "$health" = "healthy" ]; then
    pass "$svc is healthy"
  elif [ "$state" = "running" ]; then
    pass "$svc is running (health: ${health:-n/a})"
  else
    fail "$svc not running (state: ${state:-unknown}, health: ${health:-unknown})"
  fi
done

# ── 2. HTTP health endpoints ─────────────────────────────────────────
echo ""
echo "=== HTTP health endpoints ==="
for path in /health /api/v1/health; do
  http_code=$(curl -sk -o /dev/null -w '%{http_code}' \
    "https://localhost${path}" -H "Host: ${DOMAIN}" 2>/dev/null || echo "000")
  if [ "$http_code" = "200" ]; then
    pass "GET ${path} => ${http_code}"
  else
    fail "GET ${path} => ${http_code} (expected 200)"
  fi
done

# ── 3. alembic_version row count ─────────────────────────────────────
echo ""
echo "=== Alembic migration state ==="
row_count=$($COMPOSE exec -T backend python -c \
  "from sqlalchemy import create_engine, text; from app.core.settings import get_settings; \
   e = create_engine(get_settings().database_url); \
   print(e.connect().execute(text('SELECT COUNT(*) FROM alembic_version')).scalar())" \
  2>/dev/null | tr -d '[:space:]') || row_count="error"

if [ "$row_count" = "1" ]; then
  pass "alembic_version row count = 1"
else
  fail "alembic_version row count = ${row_count} (expected 1)"
fi

# ── 4. Alembic HEAD matches DB version ───────────────────────────────
db_version=$($COMPOSE exec -T backend python -c \
  "from sqlalchemy import create_engine, text; from app.core.settings import get_settings; \
   e = create_engine(get_settings().database_url); \
   print(e.connect().execute(text('SELECT version_num FROM alembic_version')).scalar())" \
  2>/dev/null | tr -d '[:space:]') || db_version="error"

alembic_head=$($COMPOSE exec -T backend alembic heads 2>/dev/null \
  | grep -oE '^[0-9a-f]+' | head -1) || alembic_head="error"

if [ -n "$db_version" ] && [ "$db_version" != "error" ] && \
   [ -n "$alembic_head" ] && [ "$alembic_head" != "error" ] && \
   [ "$db_version" = "$alembic_head" ]; then
  pass "DB version matches alembic HEAD (${db_version})"
else
  fail "DB version (${db_version}) != alembic HEAD (${alembic_head})"
fi

# ── 5. Worker has RUN_MIGRATIONS=0 ───────────────────────────────────
echo ""
echo "=== Worker configuration ==="
run_mig=$($COMPOSE exec -T worker printenv RUN_MIGRATIONS 2>/dev/null | tr -d '[:space:]') \
  || run_mig="error"

if [ "$run_mig" = "0" ]; then
  pass "worker RUN_MIGRATIONS=0"
else
  fail "worker RUN_MIGRATIONS=${run_mig} (expected 0)"
fi

# ── Summary ──────────────────────────────────────────────────────────
echo ""
if [ "$FAILURES" -eq 0 ]; then
  echo "=== All checks passed ==="
else
  echo "=== ${FAILURES} check(s) FAILED ==="
  exit 1
fi
