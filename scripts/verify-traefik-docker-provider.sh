#!/usr/bin/env bash
set -euo pipefail

EXPECTED_ENDPOINT="${TRAEFIK_EXPECTED_ENDPOINT:-tcp://docker-socket-proxy:2375}"
compose_args=(--env-file .env -f docker-compose.prod.yml)

# 1. Verify compose config declares the expected docker provider endpoint
traefik_config=$(docker compose "${compose_args[@]}" config | sed -n '/^  traefik:/,/^  [A-Za-z0-9_-]\+:/p')
echo "$traefik_config" | grep -nE 'image:|command:|providers.docker.endpoint' || true
if ! echo "$traefik_config" | grep -q -- "--providers.docker.endpoint=${EXPECTED_ENDPOINT}"; then
  echo "Traefik compose config is missing --providers.docker.endpoint=${EXPECTED_ENDPOINT}."
  exit 1
fi

# 2. Verify docker-socket-proxy is declared in compose
proxy_config=$(docker compose "${compose_args[@]}" config | sed -n '/^  docker-socket-proxy:/,/^  [A-Za-z0-9_-]\+:/p')
if [ -z "$proxy_config" ]; then
  echo "docker-socket-proxy service is not defined in compose config."
  exit 1
fi

# 3. Verify traefik container is running
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

# 4. Verify the running traefik process uses the expected endpoint
runtime_cmd=$(docker compose "${compose_args[@]}" exec -T traefik cat /proc/1/cmdline 2>/dev/null | tr '\0' ' ') || true
if [ -n "$runtime_cmd" ]; then
  if ! echo "$runtime_cmd" | grep -q -- "--providers.docker.endpoint=${EXPECTED_ENDPOINT}"; then
    echo "Running Traefik process does not use expected endpoint ${EXPECTED_ENDPOINT}."
    echo "Actual cmdline: $runtime_cmd"
    exit 1
  fi
else
  echo "Warning: could not read Traefik process cmdline; skipping runtime endpoint check."
fi

# 5. Verify docker-socket-proxy is running
proxy_status=$(docker compose "${compose_args[@]}" ps docker-socket-proxy --format '{{.Status}}')
if [ -z "$proxy_status" ] || ! echo "$proxy_status" | grep -q '^Up'; then
  echo "docker-socket-proxy container is not running."
  docker compose "${compose_args[@]}" ps docker-socket-proxy
  exit 1
fi

# 6. Check traefik logs for known Docker API errors
logs=$(docker compose "${compose_args[@]}" logs --tail=200 traefik)
if echo "$logs" | grep -Fq "client version 1.24 is too old"; then
  echo "Traefik Docker provider compatibility error detected in logs."
  echo "$logs"
  exit 1
fi

echo "Traefik Docker provider smoke check passed."
