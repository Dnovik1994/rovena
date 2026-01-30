#!/usr/bin/env bash
set -euo pipefail

mkdir -p certbot/www

docker compose -f docker-compose.prod.yml run --rm \
  certbot renew \
  --webroot -w /var/www/certbot

# reload nginx if running
if docker compose -f docker-compose.prod.yml ps -q nginx >/dev/null 2>&1; then
  docker compose -f docker-compose.prod.yml exec -T nginx nginx -s reload
fi
