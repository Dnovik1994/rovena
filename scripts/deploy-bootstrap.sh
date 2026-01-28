#!/usr/bin/env bash
set -euo pipefail

COMMIT_SHA="$(git rev-parse --short HEAD)"
export COMMIT_SHA

docker compose -f docker-compose.prod.yml down -v
docker volume rm rovena_postgres-data || true
docker compose -f docker-compose.prod.yml up -d --build
