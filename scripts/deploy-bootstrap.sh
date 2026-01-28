#!/usr/bin/env bash
set -euo pipefail

docker compose -f docker-compose.prod.yml down -v
docker volume rm rovena_postgres-data || true
docker compose -f docker-compose.prod.yml up -d --build
