#!/usr/bin/env bash
set -euo pipefail

export PIP_INDEX_URL=${PIP_INDEX_URL:-https://pypi.org/simple}
export NPM_REGISTRY=${NPM_REGISTRY:-https://registry.npmjs.org/}
export COMMIT_SHA=${COMMIT_SHA:-$(git rev-parse --short HEAD 2>/dev/null || echo unknown)}

docker compose up --build --force-recreate
