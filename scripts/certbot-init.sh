#!/usr/bin/env bash
set -euo pipefail

DOMAIN=${1:-kass.freestorms.top}
EMAIL=${2:-}

if [[ -z "$EMAIL" ]]; then
  echo "Usage: $0 <domain> <email>" >&2
  exit 1
fi

mkdir -p certbot/www

docker compose -f docker-compose.prod.yml run --rm \
  certbot certonly \
  --webroot -w /var/www/certbot \
  -d "$DOMAIN" \
  --email "$EMAIL" \
  --agree-tos \
  --non-interactive
