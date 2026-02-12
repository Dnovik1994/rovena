#!/usr/bin/env bash
# Usage:
#   ./deploy-bootstrap.sh                          # safe deploy (no volume wipe)
#   ./deploy-bootstrap.sh --wipe-volumes           # wipe volumes (with confirmation prompt)
#   ./deploy-bootstrap.sh --wipe-volumes --force   # wipe volumes (skip confirmation)
set -euo pipefail

# WARNING: The rovena_mysql-data Docker volume holds all production MySQL data.
# It must NEVER be removed without an explicit wipe confirmation (--wipe-volumes).
# Unconditional volume deletion will cause total production data loss.

COMMIT_SHA="$(git rev-parse --short HEAD)"
export COMMIT_SHA

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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

# Clean up legacy volumes (safe — does not touch mysql-data)
"${SCRIPT_DIR}/pre-deploy-clean.sh"

if [ "$WIPE_VOLUMES" = true ]; then
  if [ "$FORCE" != true ]; then
    read -p "This will DELETE ALL DOCKER VOLUMES. Type 'WIPE' to continue: " confirm
    if [ "$confirm" != "WIPE" ]; then
      echo "Aborted."
      exit 1
    fi
  fi
  echo "WARNING: Wiping Docker volumes..."
  docker compose -f docker-compose.prod.yml down --remove-orphans -v
else
  docker compose -f docker-compose.prod.yml down --remove-orphans
fi

docker compose -f docker-compose.prod.yml up -d --build --remove-orphans
