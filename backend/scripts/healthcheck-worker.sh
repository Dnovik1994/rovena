#!/usr/bin/env bash
set -euo pipefail

celery_app="${CELERY_APP:-app.workers}"
hostname="${HOSTNAME:-}"
timeout="${CELERY_HEALTHCHECK_TIMEOUT:-5}"

celery -A "$celery_app" inspect ping -d "celery@${hostname}" --timeout "$timeout" >/dev/null 2>&1
