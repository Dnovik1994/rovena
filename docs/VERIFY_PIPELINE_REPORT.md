# Verify Pipeline Stabilization Report

## Summary

Stabilized the `verify_account` process (MTProto/Pyrogram) and the entire verification pipeline to prevent API blocking, eliminate race conditions, normalize statuses/errors, and add observability.

---

## What Changed

### 1. Lease/Lock-Based Idempotency (P0)

**File:** `backend/app/models/telegram_account.py`

Added five new columns to `TelegramAccount`:

| Column | Type | Purpose |
|---|---|---|
| `verifying` | `Boolean` | Lock flag — is a verify task running? |
| `verifying_started_at` | `DateTime(tz)` | When the lease was acquired |
| `verifying_task_id` | `String(255)` | Celery task ID holding the lease |
| `verify_status` | `String(32)` | Last verify result (VerifyStatus enum) |
| `verify_reason` | `String(64)` | Failure reason code (VerifyReasonCode enum) |

**Model methods:**
- `acquire_verify_lease(task_id)` — atomic lease acquisition with 15-min TTL expiry
- `release_verify_lease(status, reason)` — release + record outcome

**Behavior:**
- Repeated `POST /tg-accounts/{id}/verify` while a lease is active returns `{"verifying": true, "verify_status": "running"}` without spawning a new task
- If the worker crashes, the lease expires after 15 minutes (configurable via `VERIFY_LEASE_TTL_SECONDS`)

### 2. Async / Non-Blocking HTTP Endpoints (P0)

**Files:** `backend/app/api/v1/tg_accounts.py`, `backend/app/api/v1/accounts.py`

- **New endpoint:** `POST /api/v1/tg-accounts/{id}/verify` — dispatches `verify_account_task` to Celery, returns immediately
- **Legacy endpoint:** `POST /api/v1/accounts/{id}/verify` — refactored from blocking `async with client: get_me()` to dispatching `legacy_verify_account` Celery task
- Both endpoints use `_safe_dispatch()` with a 10-second bounded timeout for task publishing

### 3. Unified Status Enums (P0)

**File:** `backend/app/models/telegram_account.py`

```python
class VerifyStatus(str, Enum):
    pending = "pending"       # Task dispatched, not yet started
    running = "running"       # Worker is actively verifying
    needs_password = "needs_password"  # 2FA required
    ok = "ok"                 # Session is valid
    failed = "failed"         # Verification failed
    cooldown = "cooldown"     # FloodWait, must wait

class VerifyReasonCode(str, Enum):
    floodwait = "floodwait"
    bad_proxy = "bad_proxy"
    invalid_code = "invalid_code"
    password_required = "password_required"
    network = "network"
    client_disabled = "client_disabled"
    phone_invalid = "phone_invalid"
    code_expired = "code_expired"
    unknown = "unknown"
```

### 4. FloodWait / Retry Policy (P0)

**File:** `backend/app/workers/tg_auth_tasks.py`

- **`_handle_floodwait()`** — unified handler: sets `TelegramAccountStatus.cooldown`, records `cooldown_until = now + wait_s`, emits `floodwait_seconds_hist` metric
- **`_mark_proxy_unhealthy()`** — marks proxy as `ProxyStatus.error` on network failures, emits `proxy_marked_unhealthy_total` counter
- **`_is_network_error()`** — heuristic detection of timeout/connection/EOF/refused errors
- **Network retries:** `verify_account_task` has `max_retries=2` with 5s default delay
- All FloodWait handlers across `send_code`, `confirm_code`, `confirm_password`, and `verify_account` use the unified `_handle_floodwait()`

### 5. Observability (P1)

**File:** `backend/app/core/metrics.py`

New Prometheus metrics:

| Metric | Type | Labels | Description |
|---|---|---|---|
| `verify_fail_total` | Counter | `reason` | Failures by reason code |
| `floodwait_seconds_hist` | Histogram | — | FloodWait duration distribution |
| `active_verifications` | Gauge | — | Currently running verify tasks |
| `verify_lease_acquired_total` | Counter | — | Successful lease acquisitions |
| `verify_lease_rejected_total` | Counter | — | Rejected acquisitions (already running) |
| `proxy_marked_unhealthy_total` | Counter | — | Proxies marked unhealthy |

**Structured logging** throughout all tasks with consistent format:
```
event=verify_account_ok account_id=42 task_id=abc user_id=1 proxy_id=5 result=ok elapsed_ms=1234
```

### 6. RBAC Policy Update

**File:** `backend/app/core/rbac.py`

Added `"verify"` action to `tg_accounts` policy (all roles: user, admin, superadmin).

---

## Files Changed

| File | Change |
|---|---|
| `backend/app/models/telegram_account.py` | Added `VerifyStatus`, `VerifyReasonCode` enums, lease columns, `acquire/release_verify_lease()` methods |
| `backend/app/models/__init__.py` | Exported new enums and constants |
| `backend/app/core/metrics.py` | Added 6 new Prometheus metrics |
| `backend/app/core/rbac.py` | Added `verify` permission for `tg_accounts` |
| `backend/app/workers/tg_auth_tasks.py` | Added `verify_account_task`, unified FloodWait/proxy/network error handling |
| `backend/app/workers/tasks.py` | Added `legacy_verify_account` task for legacy Account model |
| `backend/app/api/v1/tg_accounts.py` | Added `POST /{id}/verify` endpoint with idempotency |
| `backend/app/api/v1/accounts.py` | Refactored verify to non-blocking Celery dispatch |
| `backend/app/schemas/telegram_account.py` | Added `VerifyAccountResponse` schema |
| `backend/alembic/versions/0020_add_verify_lease_fields.py` | DB migration for new columns |
| `backend/tests/test_verify_pipeline.py` | 22 new tests covering all requirements |
| `backend/tests/test_verify.py` | Updated for new non-blocking verify |
| `backend/tests/test_post_fix_hardening.py` | Updated static check for new pattern |

---

## How to Verify

### Run the new tests

```bash
cd backend
python -m pytest tests/test_verify_pipeline.py tests/test_verify.py -v
```

Expected: **22 passed**

### Run the full test suite

```bash
python -m pytest tests/ --ignore=tests/test_db_init.py --ignore=tests/test_deploy_stability.py --ignore=tests/test_migrations.py -v
```

### Apply the migration

```bash
alembic upgrade head
```

This adds the 5 new columns to `telegram_accounts`. The migration is idempotent (checks if columns exist before adding).

### Verify the endpoint

```bash
# Dispatch a verify job (returns immediately)
curl -X POST /api/v1/tg-accounts/{id}/verify -H "Authorization: Bearer <token>"

# Response (idempotent — returns running status if already in progress):
# {"account_id": 1, "verify_status": "pending", "verifying": false, "message": "Verification task dispatched"}

# Poll status:
curl /api/v1/tg-accounts/{id} -H "Authorization: Bearer <token>"
# Check verify_status field: pending | running | ok | failed | cooldown | needs_password
```

### Check metrics

```
curl /metrics | grep verify
# verify_fail_total{reason="floodwait"} 0.0
# active_verifications 0.0
# verify_lease_acquired_total 0.0
# floodwait_seconds_hist_bucket{le="5.0"} 0.0
```

---

## Architecture Diagram

```
  Client                     FastAPI                      Celery Worker
    │                           │                              │
    │  POST /verify             │                              │
    │─────────────────────────>│                              │
    │                           │  check lease                │
    │                           │  (verifying? started_at?)   │
    │                           │                              │
    │                           │  if active: return running   │
    │  <─ 200 {running}        │                              │
    │                           │                              │
    │                           │  if expired/free:            │
    │                           │  dispatch task               │
    │  <─ 200 {pending}        │─────────────────────────────>│
    │                           │                              │
    │                           │                     acquire_verify_lease()
    │                           │                     connect + get_me()
    │                           │                              │
    │                           │                     on success:
    │                           │                       release_lease(ok)
    │                           │                       broadcast WS
    │                           │                              │
    │                           │                     on FloodWait:
    │                           │                       set cooldown_until
    │                           │                       release_lease(cooldown)
    │                           │                              │
    │                           │                     on network error:
    │                           │                       mark_proxy_unhealthy
    │                           │                       release_lease(failed, network)
```
