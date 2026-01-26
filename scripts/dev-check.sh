#!/usr/bin/env bash
set -euo pipefail

echo "== Service status =="
docker compose ps

echo "== Backend logs (tail) =="
docker logs backend | tail -n 50 || true

echo "== Worker logs (tail) =="
docker logs worker | tail -n 50 || true

echo "== 3proxy logs (tail) =="
docker logs 3proxy | tail -n 50 || true

echo "== Frontend health =="
curl -fsS http://localhost:5173 || true

echo "== Backend health =="
curl -fsS http://localhost:8000/health || true

echo "== 3proxy config =="
docker exec 3proxy cat /etc/3proxy/3proxy.cfg || true
