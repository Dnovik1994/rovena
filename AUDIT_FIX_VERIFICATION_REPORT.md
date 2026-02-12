# Audit Fix Verification Report — Rovena (Telegram Mini App)

**Date:** 2026-02-12
**Auditor:** Automated static analysis (no runtime environment)
**Scope:** F01–F25 findings verification against current repository state
**Method:** Static file analysis only (Docker/DB unavailable)

---

## Executive Summary

| Status     | Count |
|------------|-------|
| **Fixed**      | 4     |
| **Not Fixed**  | 18    |
| **Partial**    | 3     |
| **Unknown**    | 0     |

### Critical remaining P0/P1 issues

| ID  | Priority | Issue |
|-----|----------|-------|
| F01 | P0       | Alembic chain break: `0019` revision ≠ `0020` down_revision `0019_widen_telegram_id_bigint` |
| F04 | P0       | Frontend nginx security headers still absent (backend API has them via middleware) |
| F05 | P1       | Sync Redis.ping() + sync _bootstrap_admin() in async startup |
| F06 | P1       | Sync DB calls in async stripe_webhook and websocket_status |
| F07 | P1       | Sync DB calls inside async get_cached_user / get_cached_tariff |
| F09 | P1       | 500 response for /api/ paths returns `{"type": ...}` not `{"error": {...}}` |
| F10 | P1       | deploy-bootstrap.sh runs `down -v` unconditionally |
| F11 | P1       | No initData replay deduplication (no nonce/query_id tracking) |
| F12 | P1       | WS broadcast sends sequentially, not via `asyncio.gather()` |

---

## Findings Verification Table

### F01 (P0) — Alembic chain break 0019→0020

| Field | Value |
|-------|-------|
| **Status** | **Not Fixed** |
| **Evidence** | `backend/alembic/versions/0019_widen_telegram_id_bigint.py:15` → `revision = "0019"` |
|              | `backend/alembic/versions/0020_add_verify_lease_fields.py:13` → `down_revision = "0019_widen_telegram_id_bigint"` |
| **Notes / Risk** | Alembic will fail with "Can't locate revision '0019_widen_telegram_id_bigint'" when running `alembic upgrade head`. This blocks all migrations. P0 blocker for any deployment. |
| **Next action** | Change `revision` in 0019 to `"0019_widen_telegram_id_bigint"` to match 0020's `down_revision`. |

### F02 (P0) — get_cached_tariff() missing import of get_json

| Field | Value |
|-------|-------|
| **Status** | **Fixed** |
| **Evidence** | `backend/app/core/database.py:6` → `from app.core.cache import get_json, set_json` — `get_json` is imported. |
|              | `backend/app/core/database.py:83` → `cached = await get_json(cache_key)` — used correctly. |
| **Notes / Risk** | None. Import is present and correct. |
| **Next action** | None. |

### F03 (P0) — Cron service hardcoded DB creds

| Field | Value |
|-------|-------|
| **Status** | **Fixed** |
| **Evidence** | `docker-compose.prod.yml:385-387`: |
|              | `MYSQL_DATABASE: ${MYSQL_DATABASE}` |
|              | `MYSQL_USER: ${MYSQL_USER}` |
|              | `MYSQL_PASSWORD: ${MYSQL_PASSWORD}` |
| **Notes / Risk** | Credentials are now parameterized via environment variables. |
| **Next action** | None. |

### F04 (P0) — Frontend nginx security headers absent

| Field | Value |
|-------|-------|
| **Status** | **Partial** |
| **Evidence — backend (fixed)** | `backend/app/main.py:288-308` — `SecurityHeadersMiddleware` adds `Content-Security-Policy`, `X-Content-Type-Options`, `X-XSS-Protection` to all API responses. |
| **Evidence — frontend (not fixed)** | `frontend/nginx.conf:1-11` — no `add_header` directives at all. No CSP, HSTS, nosniff, X-Frame-Options. |
|              | No Traefik middleware labels for security headers in `docker-compose.prod.yml`. |
| **Notes / Risk** | HTML/JS/CSS served by frontend nginx have zero security headers. CSP bypass, clickjacking, MIME sniffing attacks possible on frontend assets. The root `nginx.conf` has headers but is not used in prod (Traefik setup). Backend SecurityHeadersMiddleware also lacks HSTS and X-Frame-Options. |
| **Next action** | Add security headers to `frontend/nginx.conf` or configure Traefik security-headers middleware via labels. |

### F05 (P1) — Startup event loop blocking

| Field | Value |
|-------|-------|
| **Status** | **Not Fixed** |
| **Evidence** | `backend/app/main.py:139-140` — inside `async def on_startup()`: |
|              | `redis_client = Redis.from_url(settings.redis_url)` (sync) |
|              | `redis_client.ping()` (sync, blocks event loop) |
|              | `backend/app/main.py:144` — `_bootstrap_admin()` is sync, does DB ops (`SessionLocal()`, `db.get()`, `db.commit()`) |
| **Notes / Risk** | Blocks the uvicorn event loop on startup. If Redis/DB is slow, all other startup tasks stall. |
| **Next action** | Use `await asyncio.to_thread(redis_client.ping)` or `redis.asyncio` for ping. Move `_bootstrap_admin()` to `asyncio.to_thread()`. |

### F06 (P1) — Stripe webhook + WS auth block event loop

| Field | Value |
|-------|-------|
| **Status** | **Not Fixed** |
| **Evidence** | `backend/app/main.py:432-473` — `async def stripe_webhook()`: line 467 `with SessionLocal() as db:` + sync `db.get()`, `db.commit()`. |
|              | `backend/app/main.py:515-519` — `async def websocket_status()`: `with SessionLocal() as db:` + sync `db.get(User, user_id)`. |
| **Notes / Risk** | Sync DB calls in async handlers block the uvicorn event loop. Under load, this causes request queuing and timeout for all concurrent requests. |
| **Next action** | Convert to `def` (let FastAPI run in threadpool) or use `asyncio.to_thread()` for DB calls. |

### F07 (P1) — cached user/tariff async functions do sync DB

| Field | Value |
|-------|-------|
| **Status** | **Not Fixed** |
| **Evidence** | `backend/app/core/database.py:56-77` — `async def get_cached_user()`: `db.get(User, user_id)` is sync. |
|              | `backend/app/core/database.py:79-98` — `async def get_cached_tariff()`: `db.get(Tariff, tariff_id)` is sync. |
|              | Redis calls (`get_json`, `set_json`) are properly async (via `redis.asyncio`). |
| **Notes / Risk** | Sync ORM calls inside async functions block the event loop. |
| **Next action** | Wrap sync DB calls in `asyncio.to_thread()` or convert functions to sync `def` and let callers handle threading. |

### F08 (P1) — contacts.telegram_id still INT instead of BIGINT

| Field | Value |
|-------|-------|
| **Status** | **Fixed** |
| **Evidence** | `backend/app/models/contact.py:16` → `telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)` |
|              | Migration `backend/alembic/versions/0021_widen_contacts_telegram_id_bigint.py` exists and widens the column. |
| **Notes / Risk** | Model and migration are aligned. **Caveat:** migration 0021 depends on 0020, which depends on 0019 (broken chain — F01). Until F01 is fixed, 0021 cannot run. |
| **Next action** | Fix F01 first, then this migration will apply. |

### F09 (P1) — 500 schema inconsistency

| Field | Value |
|-------|-------|
| **Status** | **Not Fixed** |
| **Evidence** | `backend/app/main.py:70-74` — for `/api/` paths: `content={"type": "internal_error"}` |
|              | `backend/app/main.py:75-78` — for non-API paths: `content={"error": {"code": "500", "message": "Internal error"}}` |
|              | All other exception handlers (`http_exception_handler`, `starlette_http_exception_handler`, `validation_exception_handler`, `rate_limit_handler`, etc.) return `{"error": {...}}` format. |
| **Notes / Risk** | API clients receive inconsistent 500 schemas. Frontend error handling may break on `{"type": ...}` vs `{"error": {...}}`. |
| **Next action** | Change the `/api/` branch to return `{"error": {"code": "500", "message": "Internal error"}}`. |

### F10 (P1) — deploy-bootstrap.sh `down -v` without safeguards

| Field | Value |
|-------|-------|
| **Status** | **Not Fixed** |
| **Evidence** | `scripts/deploy-bootstrap.sh:10` → `docker compose -f docker-compose.prod.yml down -v` — runs unconditionally with no confirmation, no environment check, no `--first-run` guard. |
| **Notes / Risk** | Running this on production destroys all named volumes (mysql-data, redis-data, backups). Data loss. |
| **Next action** | Add environment guard (e.g., `FIRST_RUN=1` flag), interactive confirmation, or rename script to indicate danger. |

### F11 (P1) — initData replay dedup absent

| Field | Value |
|-------|-------|
| **Status** | **Not Fixed** |
| **Evidence** | `backend/app/services/telegram_auth.py` — validates HMAC + TTL only. No Redis `SET key NX EX` on hash/query_id. |
|              | `backend/app/api/v1/auth.py:59-145` — `auth_via_telegram()` calls `validate_init_data()` but does not track or reject replayed initData. |
| **Notes / Risk** | Within the TTL window (default 300s), the same initData can be replayed unlimited times. Attacker intercepting one valid initData can impersonate the user. |
| **Next action** | After successful validation, `SET "initdata:{hash}" 1 NX EX {ttl}` in Redis. If SET returns False → reject as replay. |

### F12 (P1) — WS broadcast sequential send

| Field | Value |
|-------|-------|
| **Status** | **Not Fixed** |
| **Evidence** | `backend/app/services/websocket_manager.py:50-63` — `broadcast()` iterates sequentially: |
|              | `for connection in list(self._connections.keys()): await connection.send_text(message)` |
|              | Same pattern in `send_to_user()` at lines 38-48. |
| **Notes / Risk** | One slow/stale WebSocket connection blocks broadcast to all others. With many connections, latency scales linearly. |
| **Next action** | Use `asyncio.gather(*[conn.send_text(message) for conn in connections], return_exceptions=True)`. |

### F13 (P2) — Traefik rules hardcoded domain

| Field | Value |
|-------|-------|
| **Status** | **Not Fixed** |
| **Evidence** | `docker-compose.prod.yml:166` → `Host(\`kass.freestorms.top\`)` |
|              | Lines 175, 183, 311 — same hardcoded domain in all Traefik router rules. |
|              | `${DOMAIN}` is used in `WEB_BASE_URL` and `CORS_ORIGINS` (lines 147-148) but NOT in Traefik labels. |
| **Notes / Risk** | Cannot reuse the compose file for other domains without manual editing. |
| **Next action** | Docker Compose labels don't interpolate `${}` inside backtick-quoted strings reliably. Use Traefik file provider or `docker compose config` with shell expansion. One approach: use double-quoted YAML with escaped backticks. |

### F14 (P2) — worker runs as backend (no APP_ROLE worker)

| Field | Value |
|-------|-------|
| **Status** | **Fixed** |
| **Evidence** | `docker-compose.prod.yml:238` → `APP_ROLE: worker` |
|              | `docker-compose.prod.yml:243` → `command: celery -A app.workers:celery_app worker ...` |
|              | `backend/scripts/entrypoint-worker.sh` — dedicated worker entrypoint. |
| **Notes / Risk** | None. Worker is properly configured. |
| **Next action** | None. |

### F15 (P2) — Prometheus target port mismatch

| Field | Value |
|-------|-------|
| **Status** | **Not Fixed** |
| **Evidence** | `prometheus.yml:12` → `targets: ["backend:8020"]` |
|              | `docker-compose.prod.yml:151` → `UVICORN_PORT: ${UVICORN_PORT:-8000}` — backend listens on 8000. |
|              | `docker-compose.prod.yml:162` → `com.prometheus.port: "8000"` — label says 8000. |
| **Notes / Risk** | Prometheus cannot scrape metrics. All backend metrics (accounts, celery queue, auth rejects) are invisible. Alerting rules depending on these metrics are useless. |
| **Next action** | Change `prometheus.yml` target to `backend:8000`. |

### F16 (P2) — validate-deploy.sh /metrics hits SPA

| Field | Value |
|-------|-------|
| **Status** | **Not Fixed** |
| **Evidence** | `scripts/validate-deploy.sh:8` → `metrics_url="https://${DOMAIN}/metrics"` |
|              | Traefik routes: `/api/v1` → backend (priority 20), `/health` → backend (priority 110), `/ws` → backend (priority 110), `*` → frontend (priority 10). |
|              | `/metrics` is NOT routed to backend, so Traefik sends it to frontend catch-all which returns `index.html` with 200 OK. |
| **Notes / Risk** | `curl -fsS` gets a 200 HTML response, so the validation "passes" even though metrics aren't accessible. False positive in deploy validation. |
| **Next action** | Either add a Traefik router for `/metrics` → backend, or change the script to check `http://backend:8000/metrics` directly inside the Docker network. |

### F17 (P2) — onboarding_completed server_default mismatch

| Field | Value |
|-------|-------|
| **Status** | **Not Fixed** |
| **Evidence** | Migration `backend/alembic/versions/0016_add_onboarding_state.py:22-24`: |
|              | Adds column with `server_default=sa.false()`, then immediately removes it: `op.alter_column("users", "onboarding_completed", server_default=None)`. |
|              | Model `backend/app/models/user.py:32-34`: `server_default=false()` — declares a server_default. |
| **Notes / Risk** | DB has no server_default (removed by migration). Model expects one. Alembic autogenerate will flag this as a diff. New rows inserted outside ORM (raw SQL, migrations) won't get the default. |
| **Next action** | Add a migration to reinstate `server_default=sa.false()` on `users.onboarding_completed`, or remove `server_default=false()` from the model. |

### F18 (P2) — ErrorPage feedback opens DSN URL

| Field | Value |
|-------|-------|
| **Status** | **Not Fixed** |
| **Evidence** | `frontend/src/pages/ErrorPage.tsx:22` → `const sentryDsn = import.meta.env.VITE_SENTRY_DSN;` |
|              | `frontend/src/pages/ErrorPage.tsx:41` → `onClick={() => window.open(sentryDsn, "_blank")}` |
| **Notes / Risk** | Opens `https://<key>@sentry.io/<project>` in a new tab. Leaks the Sentry DSN (ingest key + project ID) to the user and any extensions. |
| **Next action** | Replace with Sentry User Feedback widget (`Sentry.showReportDialog()`) or a mailto/support link. |

### F19 (P2) — ErrorBoundary shows raw error.message in prod

| Field | Value |
|-------|-------|
| **Status** | **Not Fixed** |
| **Evidence** | `frontend/src/components/ErrorBoundary.tsx:70-73`: |
|              | `{this.state.error && (<pre ...>{this.state.error.message}</pre>)}` |
|              | Shown unconditionally — no `import.meta.env.DEV` guard. |
| **Notes / Risk** | Stack traces or internal error messages shown to end users in production. Information disclosure. |
| **Next action** | Gate with `{import.meta.env.DEV && this.state.error && ...}`. |

### F20 (P2) — verify_account_duration_seconds buckets

| Field | Value |
|-------|-------|
| **Status** | **Not Fixed** |
| **Evidence** | `backend/app/core/metrics.py:20-23`: |
|              | `verify_account_duration_seconds = Histogram("verify_account_duration_seconds", ...)` — no `buckets` argument. |
|              | Default prometheus_client buckets: .005, .01, .025, .05, .075, .1, .25, .5, .75, 1.0, 2.5, 5.0, 7.5, 10.0, +Inf |
| **Notes / Risk** | Pyrogram verify calls take 2–60+ seconds. Almost all observations fall into the `+Inf` bucket, making the histogram useless for latency analysis. Note: `floodwait_seconds_hist` (line 32) does have proper custom buckets. |
| **Next action** | Add `buckets=(1, 2, 5, 10, 15, 30, 60, 120, 300)` to the Histogram constructor. |

### F21 (P2) — Few alert rules + no Alertmanager

| Field | Value |
|-------|-------|
| **Status** | **Not Fixed** |
| **Evidence** | `prometheus_rules.yml` — only 2 rules: `HighQueue` and `ManyBlockedAccounts`. |
|              | `docker-compose.prod.yml` — no `alertmanager` service defined. |
| **Notes / Risk** | No alerts for: backend down, high error rate, Redis down, certificate expiry, disk usage, etc. Even existing rules have no notification route (no Alertmanager). |
| **Next action** | Add Alertmanager service + config. Add rules for: InstanceDown, HighErrorRate, CertExpirySoon, DiskSpaceLow, RedisDown. |

### F22 (P2) — No distributed locks/throttling per account

| Field | Value |
|-------|-------|
| **Status** | **Partial** |
| **Evidence — partial fix** | `backend/app/models/telegram_account.py:98-120` — `acquire_verify_lease()` provides DB-level lease with TTL for the verify pipeline. |
| **Evidence — not fixed** | `backend/app/workers/tasks.py` — `campaign_dispatch()` and `start_warming()` have no per-account distributed lock. Two Celery tasks can operate on the same account simultaneously. |
| **Notes / Risk** | Concurrent dispatch/warming on the same account can cause double FloodWait, duplicate invites, session conflicts. |
| **Next action** | Add Redis `SET account_lock:{account_id} {task_id} NX EX 900` before dispatch/warming. Skip if lock not acquired. |

### F23 (P2) — Root nginx.conf dead code

| Field | Value |
|-------|-------|
| **Status** | **Not Fixed** |
| **Evidence** | `nginx.conf` (repo root) — full reverse-proxy config with `server_name kass.freestorms.top`, SSL, upstream references to `backend:8020` and `frontend:5173`. |
|              | `docker-compose.prod.yml` — no nginx service defined. Traefik handles all routing. |
|              | Also references port 8020 (line 69, 84) but backend runs on 8000. |
| **Notes / Risk** | Confusing for operators. May be accidentally used instead of Traefik. Contains hardcoded domain and wrong port. |
| **Next action** | Remove or move to `docs/legacy-nginx.conf.example`. If kept for non-Traefik deployments, update port to 8000 and parameterize domain. |

### F24 (P2) — .env.example contradiction PRODUCTION/ENVIRONMENT

| Field | Value |
|-------|-------|
| **Status** | **Not Fixed** |
| **Evidence** | `.env.example:3` → `ENVIRONMENT=development` |
|              | `.env.example:4` → `PRODUCTION=true` |
| **Notes / Risk** | Contradictory defaults. Developers copying `.env.example` get production security checks (JWT_SECRET validation, CORS restrictions) while ENVIRONMENT says "development". Confusing and causes startup failures. |
| **Next action** | Set `PRODUCTION=false` in `.env.example` (consistent with `ENVIRONMENT=development`), or set both to production values and comment clearly. |

### F25 (P2) — Missing index on telegram_accounts.tg_user_id

| Field | Value |
|-------|-------|
| **Status** | **Not Fixed** |
| **Evidence** | `backend/app/models/telegram_account.py:61` → `tg_user_id: Mapped[int \| None] = mapped_column(BigInteger, nullable=True)` — no `index=True`. |
|              | Table `__table_args__` (lines 52-56): only indexes on `owner_user_id+phone_e164`, `owner_user_id`, `status`. No index on `tg_user_id`. |
|              | No migration adds this index. |
| **Notes / Risk** | Queries filtering by `tg_user_id` (e.g., dedup checks, account lookups by Telegram user ID) do full table scans. Performance degrades with scale. |
| **Next action** | Add `index=True` to the `tg_user_id` column definition and create a migration. |

---

## Summary Table

| ID  | Priority | Status        |
|-----|----------|---------------|
| F01 | P0       | Not Fixed     |
| F02 | P0       | Fixed         |
| F03 | P0       | Fixed         |
| F04 | P0       | Partial       |
| F05 | P1       | Not Fixed     |
| F06 | P1       | Not Fixed     |
| F07 | P1       | Not Fixed     |
| F08 | P1       | Fixed         |
| F09 | P1       | Not Fixed     |
| F10 | P1       | Not Fixed     |
| F11 | P1       | Not Fixed     |
| F12 | P1       | Not Fixed     |
| F13 | P2       | Not Fixed     |
| F14 | P2       | Fixed         |
| F15 | P2       | Not Fixed     |
| F16 | P2       | Not Fixed     |
| F17 | P2       | Not Fixed     |
| F18 | P2       | Not Fixed     |
| F19 | P2       | Not Fixed     |
| F20 | P2       | Not Fixed     |
| F21 | P2       | Not Fixed     |
| F22 | P2       | Partial       |
| F23 | P2       | Not Fixed     |
| F24 | P2       | Not Fixed     |
| F25 | P2       | Not Fixed     |

---

## Diff / Patch Suggestions

### F01 — Fix Alembic chain break

**File:** `backend/alembic/versions/0019_widen_telegram_id_bigint.py`

```python
# Line 15: change
revision = "0019"
# to
revision = "0019_widen_telegram_id_bigint"
```

**Safe rollout:** This is a metadata-only change. No table alterations. Safe to deploy directly.

---

### F04 — Add security headers to frontend nginx

**File:** `frontend/nginx.conf`

```nginx
server {
    listen 5173;
    server_name _;

    root /usr/share/nginx/html;
    index index.html;

    # Security headers
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'self' https://web.telegram.org https://t.me; base-uri 'self';" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    location / {
        try_files $uri /index.html;
    }
}
```

---

### F05 — Fix sync calls in async startup

**File:** `backend/app/main.py`, inside `on_startup()`

```python
# Replace lines 138-143:
    try:
        redis_client = Redis.from_url(settings.redis_url)
        redis_client.ping()
        logger.info("Redis connected")
    except Exception as exc:
        logger.warning("Redis connection failed", extra={"error": str(exc)})

# With:
    try:
        await asyncio.to_thread(lambda: Redis.from_url(settings.redis_url).ping())
        logger.info("Redis connected")
    except Exception as exc:
        logger.warning("Redis connection failed", extra={"error": str(exc)})

# Replace line 144:
    _bootstrap_admin()
# With:
    await asyncio.to_thread(_bootstrap_admin)
```

---

### F06 — Fix sync DB in async handlers

**File:** `backend/app/main.py`

Option A: Convert `stripe_webhook` and `websocket_status` DB access to use `asyncio.to_thread()`.

Option B (simpler for stripe_webhook): Change `async def stripe_webhook` to `def stripe_webhook` — FastAPI will run it in a threadpool automatically.

For `websocket_status` (must remain async for WebSocket), wrap DB call:
```python
# Replace lines 515-519:
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if not user or not user.is_active:
            await websocket.close(code=1008)
            return
# With:
    def _check_user():
        with SessionLocal() as db:
            user = db.get(User, user_id)
            return user and user.is_active
    if not await asyncio.to_thread(_check_user):
        await websocket.close(code=1008)
        return
```

---

### F09 — Fix 500 response schema

**File:** `backend/app/main.py`

```python
# Line 72-73: change
            content={"type": "internal_error"},
# to
            content={"error": {"code": "500", "message": "Internal error"}},
```

---

### F10 — Add safeguard to deploy-bootstrap.sh

**File:** `scripts/deploy-bootstrap.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail

COMMIT_SHA="$(git rev-parse --short HEAD)"
export COMMIT_SHA

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "${FIRST_RUN:-}" != "1" ]]; then
  echo "WARNING: This script runs 'docker compose down -v' which DESTROYS ALL DATA."
  echo "Set FIRST_RUN=1 to confirm, e.g.: FIRST_RUN=1 $0"
  exit 1
fi

"${SCRIPT_DIR}/pre-deploy-clean.sh"

docker compose -f docker-compose.prod.yml down -v
docker compose -f docker-compose.prod.yml up -d --build
```

---

### F11 — Add initData replay protection

**File:** `backend/app/api/v1/auth.py`

After `data = validate_init_data(payload.init_data)` (line 67), add:

```python
    # Replay dedup: reject reused initData within TTL window
    import hashlib
    from app.core.cache import _get_redis_client
    init_hash = hashlib.sha256(payload.init_data.encode()).hexdigest()
    dedup_key = f"initdata_dedup:{init_hash}"
    redis_client = await _get_redis_client()
    if redis_client:
        was_set = await redis_client.set(dedup_key, "1", nx=True, ex=settings.telegram_auth_ttl_seconds)
        if not was_set:
            telegram_auth_reject_total.labels(reason="replay").inc()
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"error": {"code": "401", "message": "Authentication failed", "reason_code": "replay"}},
            )
```

**Note:** The auth endpoint is currently `def` (sync). This dedup code uses async Redis. Either convert the endpoint to `async def` or use sync Redis for the dedup check.

---

### F12 — Parallel WS broadcast

**File:** `backend/app/services/websocket_manager.py`

```python
    async def broadcast(self, payload: dict[str, Any]) -> None:
        if not self._connections:
            return
        message = json.dumps(payload)
        results = await asyncio.gather(
            *[conn.send_text(message) for conn in list(self._connections.keys())],
            return_exceptions=True,
        )
        for conn, result in zip(list(self._connections.keys()), results):
            if isinstance(result, Exception):
                logger.info("WebSocket send failed", extra={"error": str(result)})
                self._connections.pop(conn, None)
```

Same pattern for `send_to_user()`.

---

### F15 — Fix Prometheus target port

**File:** `prometheus.yml`

```yaml
# Line 12: change
      - targets: ["backend:8020"]
# to
      - targets: ["backend:8000"]
```

---

### F16 — Fix validate-deploy.sh metrics check

**File:** `scripts/validate-deploy.sh`

```bash
# Line 8: change
metrics_url="https://${DOMAIN}/metrics"
# to (check internally via Docker network):
metrics_url="http://backend:8000/metrics"
```

Or add a Traefik router rule for `/metrics` → backend (consider restricting access).

---

### F17 — Fix onboarding_completed server_default

**Option A** — Remove `server_default` from model (minimal change):

**File:** `backend/app/models/user.py`
```python
# Line 32-34: change
    onboarding_completed: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default=false()
    )
# to
    onboarding_completed: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
```

**Option B** — Add migration to reinstate server_default (if raw SQL inserts need it).

---

### F18 — Fix ErrorPage DSN leak

**File:** `frontend/src/pages/ErrorPage.tsx`

```tsx
// Replace lines 38-45:
          {sentryDsn && (
            <button
              type="button"
              onClick={() => window.open(sentryDsn, "_blank")}
              className="..."
            >
              Отправить feedback
            </button>
          )}
// With:
          <button
            type="button"
            onClick={() => window.location.href = "mailto:support@example.com?subject=Bug Report"}
            className="..."
          >
            Отправить feedback
          </button>
```

Or use Sentry User Feedback SDK: `Sentry.showReportDialog()`.

---

### F19 — Gate error message to DEV

**File:** `frontend/src/components/ErrorBoundary.tsx`

```tsx
// Replace lines 70-73:
          {this.state.error && (
            <pre className="...">
              {this.state.error.message}
            </pre>
          )}
// With:
          {import.meta.env.DEV && this.state.error && (
            <pre className="...">
              {this.state.error.message}
            </pre>
          )}
```

---

### F20 — Fix histogram buckets

**File:** `backend/app/core/metrics.py`

```python
# Lines 20-23: change
verify_account_duration_seconds = Histogram(
    "verify_account_duration_seconds",
    "Time spent in verify_account Pyrogram call",
)
# to
verify_account_duration_seconds = Histogram(
    "verify_account_duration_seconds",
    "Time spent in verify_account Pyrogram call",
    buckets=(1, 2, 5, 10, 15, 30, 60, 120, 300),
)
```

---

### F24 — Fix .env.example contradiction

**File:** `.env.example`

```bash
# Lines 3-4: change
ENVIRONMENT=development
PRODUCTION=true
# to
ENVIRONMENT=development
PRODUCTION=false
```

---

### F25 — Add index on tg_user_id

**File:** `backend/app/models/telegram_account.py`

```python
# Line 61: change
    tg_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
# to
    tg_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
```

Then create a new Alembic migration:
```bash
cd backend && alembic revision -m "add_index_tg_user_id" --autogenerate
```

---

## Verification Commands

### F01 — After fix

```bash
cd backend
grep -n 'revision\s*=' alembic/versions/0019_widen_telegram_id_bigint.py
grep -n 'down_revision\s*=' alembic/versions/0020_add_verify_lease_fields.py
# Both should show "0019_widen_telegram_id_bigint"

# If Docker available:
docker compose exec backend alembic heads
docker compose exec backend alembic check
```

### F04 — After fix

```bash
grep -c 'add_header' frontend/nginx.conf
# Should be >= 5

# If deployed:
curl -sI https://${DOMAIN}/ | grep -iE 'content-security|strict-transport|x-content-type|x-frame'
```

### F09 — After fix

```bash
grep -A2 'content={"type"' backend/app/main.py
# Should return no matches
grep 'content={"error"' backend/app/main.py
# Should show all error responses
```

### F10 — After fix

```bash
bash scripts/deploy-bootstrap.sh 2>&1 | head -5
# Should show warning and exit 1 without FIRST_RUN=1
```

### F15 — After fix

```bash
grep 'targets:' prometheus.yml
# Should show backend:8000

# If Docker available:
docker compose exec prometheus wget -qO- http://backend:8000/metrics | head -5
```

### F16 — After fix

```bash
# If deployed, check /metrics is NOT routed to SPA:
curl -sI https://${DOMAIN}/metrics | head -3
# Should show Prometheus content-type, not text/html
```

### F18 — After fix

```bash
grep -n 'window.open' frontend/src/pages/ErrorPage.tsx
# Should return no matches
```

### F19 — After fix

```bash
grep -n 'import.meta.env.DEV' frontend/src/components/ErrorBoundary.tsx
# Should show the DEV guard
```

### F20 — After fix

```bash
grep -A1 'verify_account_duration_seconds' backend/app/core/metrics.py | grep 'buckets'
# Should show custom buckets
```

### F24 — After fix

```bash
grep -E '^(ENVIRONMENT|PRODUCTION)=' .env.example
# ENVIRONMENT=development
# PRODUCTION=false
```

### F25 — After fix

```bash
grep 'tg_user_id' backend/app/models/telegram_account.py
# Should show index=True
```

---

## Limitations

- **No runtime verification:** Docker/DB/Redis not available. All checks are static file analysis only.
- **Migration chain (F01):** Cannot verify `alembic upgrade head` actually succeeds.
- **Security headers (F04):** Cannot curl the live site to verify Traefik behavior.
- **Replay dedup (F11):** Cannot test actual Redis SET NX behavior.
- **Alertmanager (F21):** Cannot verify alert routing without Alertmanager config.
