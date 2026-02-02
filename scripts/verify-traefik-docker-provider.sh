#!/usr/bin/env bash
set -euo pipefail

compose_args=(--env-file .env -f docker-compose.prod.yml)

traefik_config=$(docker compose "${compose_args[@]}" config | sed -n '/^  traefik:/,/^  [A-Za-z0-9_-]\+:/p')
echo "$traefik_config" | grep -nE 'image:|command:|providers.docker.endpoint' || true
if ! echo "$traefik_config" | grep -q "--providers.docker.endpoint=unix:///var/run/docker.sock"; then
  echo "Traefik compose config is missing --providers.docker.endpoint=unix:///var/run/docker.sock."
  exit 1
fi

traefik_status=$(docker compose "${compose_args[@]}" ps traefik --format '{{.Status}}')
if [ -z "$traefik_status" ]; then
  echo "Traefik container is not running."
  docker compose "${compose_args[@]}" ps traefik
  exit 1
fi
if ! echo "$traefik_status" | grep -q '^Up'; then
  echo "Traefik container is not in Up status."
  echo "Status: $traefik_status"
  docker compose "${compose_args[@]}" ps traefik
  exit 1
fi

logs=$(docker compose "${compose_args[@]}" logs --tail=200 traefik)
if echo "$logs" | grep -Fq "client version 1.24 is too old"; then
  echo "Traefik Docker provider compatibility error detected in logs."
  echo "$logs"
  exit 1
fi

echo "Traefik Docker provider smoke check passed."
