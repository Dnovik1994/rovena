#!/usr/bin/env bash
set -euo pipefail

python - <<'PY'
import os
import sys
import urllib.request

url = os.getenv("BACKEND_HEALTH_URL", "http://localhost:8020/health")

try:
    with urllib.request.urlopen(url, timeout=2) as response:
        if 200 <= response.status < 300:
            sys.exit(0)
except Exception:
    sys.exit(1)

sys.exit(1)
PY
