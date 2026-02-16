# Runtime Crash Audit

## 1. TypeError — Enum JSON serialization
- tasks.py lines 85,323,384,405,437,481: account.status (enum) not .value
- Caught by broad except in _publish_to_redis — WS notifications silently lost

## 2. Race conditions
- auto_assign.py: max_accounts check-then-act without locking
- accounts.py/tg_accounts.py: tariff limit check-then-act
- tg_auth_tasks.py: verify lease acquire_verify_lease without SELECT FOR UPDATE
- tg_auth_tasks.py: flow.attempts += 1 read-modify-write without atomicity

## 3. Redis connection leaks
- health.py lines 81,96: Redis.from_url() never closed (2 per health check)
- main.py line 415: Redis.from_url() in /metrics never closed
- limits.py lines 26,39: get_redis_client() returns unclosed client

## 4. IntegrityError
- HTTP endpoints protected by global handler (returns 409)
- Celery tasks NOT protected: _log_dispatch_error FK violation crashes task
