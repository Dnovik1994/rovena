#!/usr/bin/env bash
set -euo pipefail

export PIP_INDEX_URL=${PIP_INDEX_URL:-https://pypi.org/simple}
export NPM_REGISTRY=${NPM_REGISTRY:-https://registry.npmjs.org/}

docker compose up --build --force-recreate
