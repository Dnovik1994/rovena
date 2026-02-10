#!/usr/bin/env bash
# Diagnostic script for verifying Telegram auth flow readiness.
# Run inside the backend or worker container:
#   docker compose exec backend  bash /app/scripts/check-auth-flow.sh
#   docker compose exec worker   bash /app/scripts/check-auth-flow.sh
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

pass() { echo -e "${GREEN}[OK]${NC} $1"; }
fail() { echo -e "${RED}[FAIL]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }

echo "=== Telegram Auth Flow Diagnostics ==="
echo ""

# 1) Python + package versions
echo "--- Package versions ---"
python3 -c "import pyrogram; print(f'pyrogram={pyrogram.__version__}')" 2>/dev/null || fail "pyrogram not installed"
python3 -c "import celery; print(f'celery={celery.__version__}')" 2>/dev/null || fail "celery not installed"
python3 -c "import redis; print(f'redis={redis.__version__}')" 2>/dev/null || fail "redis not installed"
python3 -c "import fastapi; print(f'fastapi={fastapi.__version__}')" 2>/dev/null || fail "fastapi not installed"
echo ""

# 2) Redis connectivity
echo "--- Redis connectivity ---"
python3 -c "
import os, redis
url = os.environ.get('REDIS_URL', os.environ.get('CELERY_BROKER_URL', 'redis://redis:6379/0'))
r = redis.from_url(url, socket_connect_timeout=5, socket_timeout=5)
r.ping()
print(f'Connected to Redis at {url}')
" && pass "Redis reachable" || fail "Redis UNREACHABLE"
echo ""

# 3) Celery task registration
echo "--- Celery task registration ---"
python3 -c "
from app.workers import celery_app
celery_app.loader.import_default_modules()

required = [
    'app.workers.tg_auth_tasks.send_code_task',
    'app.workers.tg_auth_tasks.confirm_code_task',
    'app.workers.tg_auth_tasks.confirm_password_task',
]
registered = list(celery_app.tasks.keys())
for task_name in required:
    if task_name in registered:
        print(f'  [OK] {task_name}')
    else:
        print(f'  [FAIL] {task_name} NOT FOUND')
        print(f'         Registered tasks: {[t for t in registered if \"tg_auth\" in t]}')
" 2>&1

echo ""

# 4) Broker transport options
echo "--- Broker transport options ---"
python3 -c "
from app.workers import celery_app
opts = celery_app.conf.get('broker_transport_options', {})
print(f'  socket_connect_timeout = {opts.get(\"socket_connect_timeout\", \"NOT SET\")}')
print(f'  socket_timeout         = {opts.get(\"socket_timeout\", \"NOT SET\")}')
print(f'  visibility_timeout     = {opts.get(\"visibility_timeout\", \"NOT SET\")}')
include = celery_app.conf.get('include', [])
print(f'  include                = {include}')
"
echo ""

# 5) Pyrogram kwargs safety
echo "--- Pyrogram Client.__init__ param filter ---"
python3 -c "
from app.clients.telegram_client import _CLIENT_INIT_PARAMS, build_pyrogram_client_kwargs
print(f'  Accepted params ({len(_CLIENT_INIT_PARAMS)}): {sorted(_CLIENT_INIT_PARAMS)[:10]}...')
test_cfg = {'device_model': 'X', 'system_lang_code': 'en', 'bad_param': 'oops'}
result = build_pyrogram_client_kwargs(test_cfg)
if 'bad_param' not in result:
    print('  [OK] Unknown params filtered out')
else:
    print('  [FAIL] Unknown params NOT filtered')
if 'system_lang_code' not in result or 'system_lang_code' in _CLIENT_INIT_PARAMS:
    print('  [OK] system_lang_code handled correctly')
else:
    print('  [FAIL] system_lang_code would cause TypeError')
"
echo ""

# 6) Backend process check
echo "--- Backend process ---"
if pgrep -f 'uvicorn' > /dev/null 2>&1; then
    pass "uvicorn is running"
    ps aux | grep '[u]vicorn' | head -3
elif pgrep -f 'celery' > /dev/null 2>&1; then
    pass "celery worker is running"
    ps aux | grep '[c]elery' | head -3
else
    warn "Neither uvicorn nor celery found (may be running in another container)"
fi
echo ""

echo "=== Done ==="
