#!/usr/bin/env bash
set -euo pipefail

compose_args=(--env-file .env -f docker-compose.prod.yml)

traefik_config=$(docker compose "${compose_args[@]}" config | sed -n '/^  traefik:/,/^  [A-Za-z0-9_-]\+:/p')
echo "$traefik_config" | grep -nE 'image:|environment:|DOCKER_' || true
if ! echo "$traefik_config" | grep -q "DOCKER_HOST=unix:///var/run/docker.sock"; then
  echo "Traefik compose config is missing DOCKER_HOST=unix:///var/run/docker.sock."
  exit 1
fi
if ! echo "$traefik_config" | grep -q "DOCKER_API_VERSION=1.44"; then
  echo "Traefik compose config is missing DOCKER_API_VERSION=1.44."
  exit 1
fi

traefik_running=$(docker compose "${compose_args[@]}" ps --status running traefik | awk 'NR>1 {print $0}')
if [ -z "$traefik_running" ]; then
  echo "Traefik container is not running."
  docker compose "${compose_args[@]}" ps traefik
  exit 1
fi

traefik_env=$(docker compose "${compose_args[@]}" exec -T traefik sh -lc 'env | grep -E "^DOCKER_(HOST|API_VERSION)="') || {
  echo "Failed to read DOCKER_* environment variables from Traefik container."
  exit 1
}
traefik_echo=$(docker compose "${compose_args[@]}" exec -T traefik sh -lc 'echo "$DOCKER_API_VERSION"; echo "$DOCKER_HOST"') || {
  echo "Failed to echo DOCKER_* environment variables from Traefik container."
  exit 1
}
if [ -z "$traefik_echo" ]; then
  echo "DOCKER_API_VERSION/DOCKER_HOST are empty inside the Traefik container."
  exit 1
fi
if ! echo "$traefik_env" | grep -q '^DOCKER_HOST=unix:///var/run/docker.sock'; then
  echo "DOCKER_HOST is not set correctly inside the Traefik container."
  echo "$traefik_env"
  exit 1
fi
if ! echo "$traefik_env" | grep -q '^DOCKER_API_VERSION=1.44'; then
  echo "DOCKER_API_VERSION is not set correctly inside the Traefik container."
  echo "$traefik_env"
  exit 1
fi

logs=$(docker compose "${compose_args[@]}" logs --tail=200 traefik)
if echo "$logs" | grep -Fq "client version 1.24 is too old"; then
  echo "Traefik Docker provider compatibility error detected in logs."
  echo "$logs"
  exit 1
fi

echo "Traefik Docker provider smoke check passed."
