#!/usr/bin/env bash
set -euo pipefail

docker compose down -v --remove-orphans
docker system prune -f
