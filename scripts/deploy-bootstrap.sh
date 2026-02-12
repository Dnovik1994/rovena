#!/usr/bin/env bash
# Usage:
#   ./deploy-bootstrap.sh                          # safe deploy (no volume wipe)
#   ./deploy-bootstrap.sh --wipe-volumes           # wipe volumes (with confirmation prompt)
#   ./deploy-bootstrap.sh --wipe-volumes --force   # wipe volumes (skip confirmation)
set -euo pipefail

COMMIT_SHA="$(git rev-parse --short HEAD)"
export COMMIT_SHA

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"${SCRIPT_DIR}/pre-deploy-clean.sh"

WIPE_VOLUMES=false
FORCE=false

for arg in "$@"; do
  if [ "$arg" = "--wipe-volumes" ]; then
    WIPE_VOLUMES=true
  fi
  if [ "$arg" = "--force" ]; then
    FORCE=true
  fi
done

if [ "$WIPE_VOLUMES" = true ]; then
  if [ "$FORCE" != true ]; then
    read -p "This will DELETE ALL DOCKER VOLUMES. Type 'WIPE' to continue: " confirm
    if [ "$confirm" != "WIPE" ]; then
      echo "Aborted."
      exit 1
    fi
  fi
  echo "WARNING: Wiping Docker volumes..."
  docker compose -f docker-compose.prod.yml down -v
else
  docker compose -f docker-compose.prod.yml down
fi

docker compose -f docker-compose.prod.yml up -d --build
