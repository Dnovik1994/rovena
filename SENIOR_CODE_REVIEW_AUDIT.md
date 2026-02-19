# Senior Developer Code Review Audit

**Project:** FreeCRM Inviter (Rovena)
**Date:** 2026-02-19
**Reviewer:** Senior Developer (pre-release audit)
**Stack:** FastAPI + React 18 + MySQL + Redis + Celery + Docker

---

## 1. Structure and Architecture

### Overall Assessment: Good

The project follows a clean monorepo structure with clear separation between `backend/` (FastAPI + Python) and `frontend/` (React + Vite + TypeScript). The backend follows a layered architecture: `api/` -> `services/` -> `models/` with Pydantic schemas for validation.

### Issues Found

#### 1.1 Legacy Model Duplication (Account vs TelegramAccount)

- **File:** `backend/app/models/account.py:1-3`
- **Severity:** :yellow_circle: Important
- **Description:** The `Account` model is explicitly marked `DEPRECATED` with 14 TODO comments across the codebase referencing migration to `TelegramAccount`. Both models coexist, causing dual maintenance burden. The `accounts.py` API still creates legacy `Account` objects while `tg_accounts.py` uses `TelegramAccount`.
- **Fix:** Complete the migration to `TelegramAccount`. Remove `Account` model, update `tasks.py` legacy tasks, and drop the `accounts` table via Alembic migration.

#### 1.2 Docker Volume Name Mismatch

- **File:** `docker-compose.yml:236`
- **Severity:** :yellow_circle: Important
- **Description:** The MySQL volume is named `postgres-data` but the database is MySQL 8.4. This is a naming inconsistency from a migration.
- **Fix:**
```yaml
# Before
volumes:
  postgres-data:

# After
volumes:
  mysql-data:
```
Also update the volume reference at line 23:
```yaml
volumes:
  - mysql-data:/var/lib/mysql
```

#### 1.3 RBAC Policy Uses String Comparison Instead of Enum

- **File:** `backend/app/core/rbac.py:56`
- **Severity:** :green_circle: Recommendation
- **Description:** `current_user.role not in allowed_roles` compares `UserRole` enum against string list. This works because `UserRole` inherits from `str`, but it's fragile.
- **Fix:**
```python
# Before
allowed_roles = POLICY.get(resource, {}).get(action, [])
if current_user.role not in allowed_roles:

# After
allowed_roles = POLICY.get(resource, {}).get(action, [])
if current_user.role.value not in allowed_roles:
```

---

## 2. Code Quality

### Issues Found

#### 2.1 Dead Code: `perform_warming_action` Task Is a No-Op

- **File:** `backend/app/workers/tasks.py:575-581`
- **Severity:** :yellow_circle: Important
- **Description:** The `perform_warming_action` Celery task does nothing except log a message. The `try/except SoftTimeLimitExceeded` wraps only a `logger.info()` call, making the exception handler unreachable.
- **Fix:** Remove the task entirely or implement the actual warming logic.

#### 2.2 `get_cached_user` Ignores the `db` Parameter

- **File:** `backend/app/core/database.py:57-81`
- **Severity:** :yellow_circle: Important
- **Description:** `get_cached_user(db, user_id)` accepts a `db: Session` parameter but creates its own `SessionLocal()` inside `_load_user()`, completely ignoring the passed session. It also always writes to cache (even when not reading from it first), defeating the "cached" purpose on every call.
- **Fix:**
```python
async def get_cached_user(db: Session, user_id: int):
    from app.models.user import User

    cache_key = f"user:{user_id}"
    cached = await get_json(cache_key)
    if cached is not None:
        # Return from cache (need to reconstruct or return dict)
        return cached

    def _load_user(uid: int):
        return db.get(User, uid)

    user = await asyncio.to_thread(_load_user, user_id)
    if not user:
        return None
    # ... cache and return
```

#### 2.3 Verbose Cache Logging on Every Hit/Miss

- **File:** `backend/app/core/cache.py:35,42`
- **Severity:** :green_circle: Recommendation
- **Description:** `logger.info("Cache miss for key %s")` and `logger.info("Cache hit for key %s")` run on every single cache operation. With endpoints hitting cache on every request, this generates massive log volume in production.
- **Fix:** Change to `logger.debug()`:
```python
logger.debug("Cache hit for key %s", key)
logger.debug("Cache miss for key %s", key)
```

#### 2.4 Duplicated `extractError` Helper in Frontend

- **File:** `frontend/src/pages/Accounts.tsx:92-97`, `frontend/src/pages/InviteCampaigns.tsx:27-32`
- **Severity:** :green_circle: Recommendation
- **Description:** Identical `extractError()` function is duplicated in two files.
- **Fix:** Move to a shared utility:
```typescript
// src/utils/errors.ts
export function extractError(err: unknown): string {
  if (err && typeof err === "object" && "message" in err) {
    return (err as { message: string }).message;
  }
  return "Unexpected error";
}
```

#### 2.5 Console.log in Production Path

- **File:** `frontend/src/pages/Login.tsx:23`
- **Severity:** :green_circle: Recommendation
- **Description:** `console.log("Telegram initData length:", ...)` is gated behind `import.meta.env.DEV` which is correct, but the ESLint disable comment suggests it was flagged before. This is fine but should be reviewed.

#### 2.6 Admin Response Serialization Without Schema

- **File:** `backend/app/api/v1/admin.py:93-115,127-147,185-205`
- **Severity:** :yellow_circle: Important
- **Description:** Multiple admin endpoints return hand-built dicts instead of using Pydantic response models. This bypasses type validation and creates maintenance risk when fields change.
- **Fix:** Define proper response schemas:
```python
# Use response_model consistently
@router.get("/users/{user_id}", response_model=AdminUserDetailResponse)
```

---

## 3. Bugs and Potential Problems

### Issues Found

#### 3.1 Race Condition in `increment_daily_invites` (Non-Atomic Expire)

- **File:** `backend/app/core/limits.py:40-43`
- **Severity:** :red_circle: Critical
- **Description:** `incrby` and `expire` are two separate Redis commands. If the process crashes between them, the key persists without TTL, permanently blocking invites for that day's counter indefinitely.
- **Fix:** Use a Lua script or pipeline:
```python
def increment_daily_invites(user_id: int, amount: int = 1, client: Redis | None = None) -> None:
    now = datetime.now(timezone.utc)
    client = client or get_redis_client()
    if client is None:
        return
    key = _invite_key(user_id, now)
    try:
        pipe = client.pipeline()
        pipe.incrby(key, amount)
        pipe.expire(key, 86400)
        pipe.execute()
    except Exception:
        logger.exception("Failed to update daily invite counter")
```

#### 3.2 WebSocket Manager `disconnect` Is Not Async-Safe

- **File:** `backend/app/services/websocket_manager.py:47-49`
- **Severity:** :yellow_circle: Important
- **Description:** `disconnect()` is a sync method that mutates `self._connections` dict without acquiring `self._lock`. Meanwhile `connect()` and `_send_concurrent` use the async lock. Concurrent disconnect + connect could corrupt the dict.
- **Fix:**
```python
async def disconnect(self, websocket: WebSocket) -> None:
    async with self._lock:
        user_id = self._connections.pop(websocket, None)
    logger.info("WS disconnected | user_id=%s | total=%s", user_id, len(self._connections))
```
And update the caller in `main.py:560` to use `await manager.disconnect(websocket)`.

#### 3.3 `_publish_to_redis` Creates New Connection Every Call

- **File:** `backend/app/services/websocket_manager.py:121-130`
- **Severity:** :yellow_circle: Important
- **Description:** Each `broadcast_sync` from Celery creates a new `Redis.from_url()` connection and closes it. Under load this causes connection churn. Should reuse the shared sync Redis client.
- **Fix:**
```python
def _publish_to_redis(self, payload: dict[str, Any]) -> None:
    if not self._redis_url:
        return
    try:
        from app.core.redis_client import get_sync_redis
        client = get_sync_redis()
        if client:
            client.publish(REDIS_WS_CHANNEL, json.dumps(payload))
    except Exception:
        logger.exception("Failed to publish WS event to Redis")
```

#### 3.4 `Sentry traces_sample_rate=1.0` in Production

- **File:** `backend/app/main.py:47`
- **Severity:** :yellow_circle: Important
- **Description:** `traces_sample_rate=1.0` sends 100% of transactions to Sentry, which is expensive and unnecessary in production.
- **Fix:**
```python
sentry_sdk.init(
    dsn=settings.sentry_dsn,
    traces_sample_rate=0.1 if settings.production else 1.0,
    integrations=[FastApiIntegration(), CeleryIntegration()],
)
```

#### 3.5 Campaign Dispatch Silently Swallowed on Queue Failure

- **File:** `backend/app/api/v1/campaigns.py:188-191`
- **Severity:** :red_circle: Critical
- **Description:** When `campaign_dispatch.delay()` fails, the campaign status is already set to `active` and committed. The user sees "campaign started" but no Celery task is dispatched. The campaign hangs in `active` state forever.
- **Fix:** Either roll back the status change on failure, or use the `_safe_dispatch` pattern from accounts:
```python
campaign.status = CampaignStatus.active
campaign.progress = 0.0
db.commit()
db.refresh(campaign)

try:
    campaign_dispatch.delay(campaign.id)
except Exception as exc:
    logger.warning("Campaign dispatch enqueue failed", extra={"error": str(exc)})
    # Roll back campaign status so user can retry
    campaign.status = CampaignStatus.draft
    db.commit()
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="Task queue unavailable. Campaign was not started.",
    ) from exc
```

#### 3.6 Deprecated `on_event` Usage

- **File:** `backend/app/main.py:107,158`
- **Severity:** :green_circle: Recommendation
- **Description:** `@app.on_event("startup")` and `@app.on_event("shutdown")` are deprecated in FastAPI. Should use lifespan context manager.
- **Fix:**
```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    await on_startup()
    yield
    await on_shutdown()

app = FastAPI(title=settings.app_name, lifespan=lifespan)
```

#### 3.7 `admin_user_tariff_update` Returns Dict but Declares `response_model=UserResponse`

- **File:** `backend/app/api/v1/admin.py:208-248`
- **Severity:** :yellow_circle: Important
- **Description:** The endpoint declares `response_model=UserResponse` but returns a raw dict. FastAPI will try to validate it through `UserResponse`, which may silently drop fields or fail if the dict structure doesn't match.
- **Fix:** Return `UserResponse.model_validate(user)` or build the response using the Pydantic model.

---

## 4. Security

### Overall Assessment: Strong

The project has solid security fundamentals: JWT with enforced minimum strength, Telegram initData signature validation with replay protection, comprehensive input sanitization, CSP headers, and CORS validation. No dangerous functions (`eval`, `exec`, `innerHTML`) found.

### Issues Found

#### 4.1 CSRF Token Is Static (Config-Based)

- **File:** `backend/app/api/deps.py:22-24`
- **Severity:** :yellow_circle: Important
- **Description:** CSRF protection compares against `settings.csrf_token` — a single static token from config. This means all sessions share the same CSRF token, which defeats the purpose (attacker can extract it once and reuse). Currently disabled (`csrf_enabled: bool = False`), but if enabled, it's insecure.
- **Fix:** If CSRF is needed, implement per-session CSRF tokens. Given this is a Telegram Mini App with JWT auth (not cookie-based), CSRF is likely not needed. Remove the dead CSRF code to avoid confusion.

#### 4.2 Stripe Error Message Leaks Internal Details

- **File:** `backend/app/api/v1/admin.py:399`
- **Severity:** :yellow_circle: Important
- **Description:** `detail=f"Stripe error: {str(e)}"` forwards the raw Stripe error message to the API response. This can leak internal API key prefixes, account IDs, or configuration details.
- **Fix:**
```python
except stripe.error.StripeError as e:
    logger.error("Stripe API error: %s", str(e))
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="Payment service error. Please try again later.",
    ) from e
```

#### 4.3 `.gitignore` Missing Some Sensitive Patterns

- **File:** `.gitignore`
- **Severity:** :green_circle: Recommendation
- **Description:** Missing patterns for common secret files: `*.pem`, `*.key`, `.env.local`, `.env.*.local`, `*.secret`.
- **Fix:** Add to `.gitignore`:
```
*.pem
*.key
*.secret
.env.local
.env.*.local
```

#### 4.4 WebSocket Accepts Connection Before Auth Validation

- **File:** `backend/app/main.py:506`
- **Severity:** :yellow_circle: Important
- **Description:** `await websocket.accept()` is called at line 506 before token validation. This means any client can establish a WebSocket connection and hold it for up to 10 seconds (the auth timeout) before being rejected. Under load, this enables connection exhaustion.
- **Fix:** For query-param auth, validate token before accepting:
```python
@app.websocket("/ws/status")
async def websocket_status(websocket: WebSocket) -> None:
    token = websocket.query_params.get("token")
    if token:
        try:
            payload = decode_access_token(token)
            user_id = int(payload.get("sub", 0))
        except Exception:
            await websocket.close(code=1008)
            return
        if not await asyncio.to_thread(_check_user_active, user_id):
            await websocket.close(code=1008)
            return
        await websocket.accept()
    else:
        await websocket.accept()
        # ... first-message auth flow
```

---

## 5. Performance

### Issues Found

#### 5.1 N+1 Queries in `/metrics` Endpoint

- **File:** `backend/app/main.py:414-432`
- **Severity:** :red_circle: Critical
- **Description:** The metrics endpoint runs N+1 queries: one `COUNT(*)` for total accounts, then one `COUNT(*)` per `AccountStatus` enum value (7 statuses = 7 queries). This runs on every Prometheus scrape (typically every 15s).
- **Fix:** Use a single aggregation query:
```python
@app.get("/metrics")
def metrics() -> Response:
    with SessionLocal() as db:
        from sqlalchemy import func
        status_counts = (
            db.query(Account.status, func.count(Account.id))
            .group_by(Account.status)
            .all()
        )
        total = sum(count for _, count in status_counts)
        accounts_total.set(total)
        for status_enum in AccountStatus:
            count = next((c for s, c in status_counts if s == status_enum), 0)
            accounts_by_status.labels(status=status_enum.value).set(count)
    # ... redis part
```

#### 5.2 `admin_stats` Runs 8 Separate COUNT Queries

- **File:** `backend/app/api/v1/admin.py:43-67`
- **Severity:** :yellow_circle: Important
- **Description:** Each stat is a separate `COUNT(*)` query (8 total). For an admin dashboard loaded on page visit, this is fine but suboptimal.
- **Fix:** Combine into fewer queries using conditional aggregation or `func.count(case(...))`.

#### 5.3 Frontend Polling Without Visibility API

- **File:** `frontend/src/pages/InviteCampaigns.tsx:134-158`
- **Severity:** :green_circle: Recommendation
- **Description:** The 5-second polling interval continues even when the browser tab is in the background, wasting bandwidth and server resources.
- **Fix:** Pause polling when `document.visibilityState === "hidden"`:
```typescript
useEffect(() => {
  const hasActive = campaigns.some((c) => c.status === "active");
  if (!hasActive || !token) return;

  const poll = async () => {
    if (document.visibilityState === "hidden") return;
    try {
      const data = await fetchInviteCampaigns(token);
      setCampaigns(data);
    } catch { /* ignore */ }
  };

  const interval = setInterval(poll, 5000);
  return () => clearInterval(interval);
}, [campaigns, token]);
```

#### 5.4 `contact_ids` Loads All Contacts Into Memory

- **File:** `backend/app/workers/tasks.py:158`
- **Severity:** :yellow_circle: Important
- **Description:** `contact_ids = [c.id for c in contacts_query.order_by(...).all()]` loads ALL contacts for a project into memory. For large projects with 100K+ contacts, this can cause OOM.
- **Fix:** Use server-side cursor or batch processing:
```python
contact_ids = [row[0] for row in contacts_query.with_entities(Contact.id).order_by(Contact.id.asc()).all()]
```
This at least avoids hydrating full Contact objects.

---

## 6. Compatibility and Configuration

### Issues Found

#### 6.1 `python-jose` Is Unmaintained

- **File:** `backend/requirements.txt`
- **Severity:** :yellow_circle: Important
- **Description:** `python-jose==3.3.0` has not been updated since 2021 and has known CVEs. The recommended replacement is `PyJWT` or `joserfc`.
- **Fix:** Migrate to `PyJWT`:
```
# requirements.txt
PyJWT[crypto]==2.9.0  # replaces python-jose
```

#### 6.2 `faker` in Production Dependencies

- **File:** `backend/requirements.txt`
- **Severity:** :green_circle: Recommendation
- **Description:** `faker==29.0.0` is a test data generation library listed in production requirements. It should be in `requirements-dev.txt` only, unless used at runtime for device generation.
- **Note:** After checking `device_generator.py`, Faker IS used at runtime for generating realistic device configs. This is acceptable but should be documented with a comment in requirements.txt.

#### 6.3 `Sentry traces_sample_rate` Not Configurable

- **File:** `backend/app/main.py:47`
- **Severity:** :green_circle: Recommendation
- **Description:** The Sentry sample rate is hardcoded to 1.0. Should be configurable via env.
- **Fix:** Add `sentry_traces_sample_rate: float = 0.1` to Settings.

---

## 7. Tests

### Overall Assessment: Good Coverage, Some Gaps

The project has 50+ test files with ~976 test functions covering security, auth, config validation, admin flows, and Telegram auth. Quality is high for tested areas.

### Critical Gaps

#### 7.1 No Frontend Tests

- **Severity:** :yellow_circle: Important
- **Description:** Zero React component tests. No jest, vitest, or testing-library setup. Critical user flows (login, campaign creation, account management) are untested on the frontend.
- **Fix:** Add Vitest + Testing Library. Priority test targets:
  - `Login.tsx` — auth flow
  - `Accounts.tsx` — complex state management
  - `client.ts` — API client with refresh logic
  - `websocket.ts` — reconnection logic

#### 7.2 RBAC Tests Are Minimal (3 Tests)

- **File:** `backend/tests/test_rbac.py`
- **Severity:** :yellow_circle: Important
- **Description:** Only 3 tests for a complex permission system with 5 resources and 20+ actions. No tests for cross-resource access, role escalation attempts, or edge cases.
- **Fix:** Add comprehensive RBAC tests covering each resource/action/role combination.

#### 7.3 Rate Limit Tests Are Basic (3 Tests)

- **File:** `backend/tests/test_rate_limit.py`
- **Severity:** :green_circle: Recommendation
- **Description:** Only 3 tests for rate limiting. No tests for burst behavior, distributed rate limiting, or bypass attempts.

#### 7.4 No Integration Tests for Campaign Dispatch

- **Severity:** :yellow_circle: Important
- **Description:** The campaign dispatch logic (`tasks.py`, `tg_invite_tasks.py`) has zero test coverage. This is the core business logic with complex state machines, Telegram API interactions, and error handling.

---

## Summary

### Health Score: 7 / 10

The project is well-structured with strong security foundations, proper input validation, comprehensive configuration management, and good test coverage for auth/security paths. The main concerns are technical debt from the Account -> TelegramAccount migration, several medium-severity bugs in async/Redis operations, and missing tests for core business logic.

### TOP-5 Critical Issues

| # | Severity | Issue | File | Impact |
|---|----------|-------|------|--------|
| 1 | :red_circle: Critical | Campaign dispatch silently fails — campaign stuck in `active` | `campaigns.py:188-191` | Users see campaigns "running" that will never execute |
| 2 | :red_circle: Critical | Non-atomic `incrby`/`expire` can create immortal Redis keys | `limits.py:40-43` | Invite counter never resets, blocking all invites |
| 3 | :red_circle: Critical | N+1 queries on `/metrics` (runs every 15s) | `main.py:414-432` | DB load scales linearly with enum cardinality on every scrape |
| 4 | :yellow_circle: Important | WebSocket disconnect not async-safe (dict mutation without lock) | `websocket_manager.py:47` | Potential connection dict corruption under load |
| 5 | :yellow_circle: Important | 14 legacy TODO/deprecated Account references across codebase | `tasks.py`, `account.py` | Dual model maintenance, confusion, and potential data inconsistency |

### Fix Priority Plan

**P0 — Fix Before Release:**
1. **Campaign dispatch failure handling** (`campaigns.py`) — rollback status on queue failure
2. **Atomic Redis increment** (`limits.py`) — use pipeline for `incrby` + `expire`
3. **Metrics N+1 query** (`main.py`) — single GROUP BY query

**P1 — Fix in Next Sprint:**
4. WebSocket `disconnect()` async safety
5. Stripe error message leakage in admin endpoint
6. WebSocket pre-auth connection acceptance
7. `_publish_to_redis` connection churn
8. Sentry `traces_sample_rate` to configurable/0.1
9. `admin_user_tariff_update` response model mismatch
10. Dead `perform_warming_action` task removal

**P2 — Technical Debt:**
11. Complete Account -> TelegramAccount migration (14 TODOs)
12. Docker volume rename `postgres-data` -> `mysql-data`
13. Add frontend test infrastructure (Vitest + Testing Library)
14. Expand RBAC and rate-limit test coverage
15. Replace `python-jose` with `PyJWT`
16. Add campaign dispatch integration tests
17. Reduce cache log verbosity
18. Migrate `on_event` to lifespan context manager
19. Extract shared `extractError` utility in frontend
