#!/usr/bin/env bash
set -euo pipefail

# Only remove legacy postgres volume; mysql-data is the active production
# volume and must NEVER be removed here (see F02 in DEPLOYMENT_MIGRATIONS_AUDIT).
docker volume rm rovena_postgres-data || true
