#!/usr/bin/env bash
set -euo pipefail

compose_args=(--env-file .env -f docker-compose.prod.yml)

if ! docker compose "${compose_args[@]}" ps traefik | awk 'NR>1 {print $0}' | rg -q '\bUp\b'; then
  echo "Traefik container is not running."
  docker compose "${compose_args[@]}" ps traefik
  exit 1
fi

logs=$(docker compose "${compose_args[@]}" logs --tail=200 traefik)
if echo "$logs" | rg -q "client version 1\.24 is too old|Minimum supported API version is 1\.44"; then
  echo "Traefik Docker provider compatibility error detected in logs."
  echo "$logs"
  exit 1
fi

echo "Traefik Docker provider smoke check passed."
