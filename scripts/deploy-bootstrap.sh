#!/usr/bin/env bash
set -euo pipefail

COMMIT_SHA="$(git rev-parse --short HEAD)"
export COMMIT_SHA

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"${SCRIPT_DIR}/pre-deploy-clean.sh"

docker compose -f docker-compose.prod.yml down -v
docker compose -f docker-compose.prod.yml up -d --build
