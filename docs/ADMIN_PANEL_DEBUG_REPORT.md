# Admin Panel Debug Report

**Branch**: `claude/debug-admin-panel-4rq2P`
**Date**: 2026-02-11
**Mode**: READ-ONLY analysis

---

## 1. Executive Summary

1. **Bootstrap works correctly** — `_bootstrap_admin()` in `main.py:222-253` finds the user by `ADMIN_TELEGRAM_ID`, sets `is_admin=True` and `role=admin`, commits. Logs confirm: "Admin bootstrap applied".
2. **DB state is correct** — `telegram_id=6887867394` has `is_admin=1` and `role=admin`.
3. **Backend `/me` endpoint (`users.py:13-15`) correctly serializes `is_admin`** — `UserResponse` schema includes `is_admin: bool` with `from_attributes = True`; Pydantic reads directly from the ORM object.
4. **Frontend correctly checks `user?.is_admin`** — `AppShell` (`AppShell.tsx:57,62`) conditionally renders the "Admin Panel" link based on the `isAdmin` prop which comes from `user?.is_admin ?? false` (`App.tsx:57`).
5. **CRITICAL BUG: The `/me` API call failure is silently swallowed** — `App.tsx:42-44` catches all errors and sets `user = null` with zero logging. If `/me` fails for ANY reason, admin panel is hidden with no visible symptom.
6. **CRITICAL BUG: Login can reset admin status** — `auth.py:126-129` compares `user.is_admin` against `_is_configured_admin(telegram_id)`. If `ADMIN_TELEGRAM_ID` is not loaded correctly at runtime, each login RESETS `is_admin=False`.
7. **STRUCTURAL BUG: Dual admin source of truth** — `is_admin` (boolean) and `role` (enum) can diverge. RBAC guard (`deps.py:70`) and frontend both use `is_admin`, but the admin panel "Toggle Admin" button (`Admin.tsx:334`) only changes `role`, not `is_admin`.
8. **CSP `frame-ancestors 'self'` blocks Telegram Web** — Both nginx (`nginx.conf:54`) and backend middleware (`main.py:292`) emit `frame-ancestors 'self'`, which prevents the Mini App from loading inside Telegram Web's iframe.
9. **Nginx CSP breaks inline scripts/styles** — `default-src 'self'` without `'unsafe-inline'` blocks Vite's injected styles and any inline JavaScript, potentially breaking the app in production.
10. **.env.example is missing `ADMIN_TELEGRAM_ID`** — Easy to forget when setting up a new deployment.

---

## 2. Root-Cause Analysis

### Cause #1 (P0, Most Likely): Silent `/me` failure in frontend

**Evidence**:
- `App.tsx:37-45` — After login, `apiFetch("/me", {}, token)` is called in a `useEffect`.
- `App.tsx:42-44` — The `.catch()` handler sets `user = null` and `onboardingNeeded = false` **without any logging or error display**.
- If `user` is `null`, then `user?.is_admin ?? false` evaluates to `false` → admin link is hidden.
- ANY failure of `/me` (network timeout, CORS preflight failure, 500 error, JWT decode error) silently results in no admin panel.

```typescript
// App.tsx:42-44 — THE PROBLEM
.catch(() => {
    setUser(null);        // <-- admin panel disappears
    setOnboardingNeeded(false);
    // NO LOGGING, NO ERROR DISPLAY
});
```

**Why `/me` might fail**:
- `Content-Security-Policy: default-src 'self'` from nginx (`nginx.conf:54`) could interfere with fetch requests in some browser configurations.
- A timing issue where the JWT token is written to state but not yet available when the effect fires.
- The 15-second default timeout in `apiFetch` might be too short if the backend is under load.
- The backend `read_me()` could throw an unhandled exception during `UserResponse.model_validate()` if the `tariff` relationship fails to lazy-load.

**Files**:
- `frontend/src/App.tsx:37-45` — the failing call
- `frontend/src/shared/api/client.ts:57-132` — the `apiFetch` function

---

### Cause #2 (P0, Ticking Time Bomb): Login endpoint resets admin status

**Evidence**:
- `auth.py:111-130` — Every login through `/auth/telegram` recalculates `should_be_admin`:

```python
# auth.py:112
should_be_admin = _is_configured_admin(telegram_id)
# ...
# auth.py:126-129
elif user.is_admin != should_be_admin:
    user.is_admin = should_be_admin          # OVERWRITES!
    user.role = UserRole.admin if should_be_admin else user.role
    db.commit()
```

- `_is_configured_admin()` (`auth.py:29-36`) calls `get_settings().admin_telegram_id`.
- If `ADMIN_TELEGRAM_ID` is missing from the environment (not in `.env`, container env override, or parsing failure), `admin_telegram_id` is `None`, and `_is_configured_admin()` returns `False`.
- On the NEXT login, `user.is_admin (True) != should_be_admin (False)` → `user.is_admin = False`.
- Bootstrap runs ONCE at startup. Login runs on EVERY auth. So login can undo bootstrap.

**The DB currently shows `is_admin=1`**, which means either:
- (a) `ADMIN_TELEGRAM_ID` IS correctly loaded and login is not resetting it, OR
- (b) The user hasn't logged in since the last restart (bootstrap set it, but no login has occurred yet to potentially reset it).

**Files**:
- `backend/app/api/v1/auth.py:29-36` — `_is_configured_admin()`
- `backend/app/api/v1/auth.py:111-130` — admin status recalculation on login
- `backend/app/main.py:222-253` — `_bootstrap_admin()`

---

### Cause #3 (P1, Structural): `is_admin` and `role` are decoupled

**Evidence**:
- **Backend RBAC** (`deps.py:70`): `if not current_user.is_admin: raise forbidden("Admin access required")` — uses `is_admin`.
- **Frontend visibility** (`App.tsx:57`): `isAdmin={user?.is_admin ?? false}` — uses `is_admin`.
- **Admin panel "Toggle Admin"** (`Admin.tsx:334-337`): sends `{ role: "admin" }` or `{ role: "user" }` — changes ONLY `role`.
- **Backend handler** (`admin.py:162-164`): `user.role = UserRole(payload.role)` — sets ONLY `role`, never touches `is_admin`.

This means:
- Toggling admin via the admin panel changes `role` but NOT `is_admin`.
- The user appears as "admin" in the users list (by `role`) but the RBAC guard still denies access (by `is_admin`).
- There is no codepath that synchronizes `role` → `is_admin` or vice versa.

**Files**:
- `backend/app/api/deps.py:67-72` — `get_current_admin` dependency
- `backend/app/api/v1/admin.py:149-170` — `admin_user_update` handler
- `frontend/src/pages/Admin.tsx:331-341` — "Toggle Admin" button
- `backend/app/models/user.py:24,26` — dual columns

---

## 3. Detailed Trace: Source of Truth for Admin Status

### 3.1 Where admin status is SET

| Location | File:Line | What it sets | When |
|---|---|---|---|
| Bootstrap | `main.py:240-246` | `is_admin=True`, `role=admin` | App startup (once) |
| Auth (new user) | `auth.py:114-125` | `is_admin`, `role` | First login |
| Auth (existing) | `auth.py:126-129` | `is_admin`, `role` (partial) | Every login |
| Admin toggle | `admin.py:162-164` | `role` ONLY | Admin panel action |

### 3.2 Where admin status is READ

| Location | File:Line | Field checked | Effect |
|---|---|---|---|
| Backend RBAC | `deps.py:70` | `is_admin` | 403 if not admin |
| Frontend nav | `App.tsx:57` → `AppShell.tsx:62` | `is_admin` | Hide/show link |
| Frontend admin page | `Admin.tsx:49` | None (no guard) | Accessible to anyone with URL |

### 3.3 API response for `/me`

**Endpoint**: `GET /api/v1/me` → `users.py:13-15`
**Schema**: `UserResponse` → `UserBase` (`schemas/user.py:6-27`)

Fields returned:
```json
{
  "id": 123,
  "telegram_id": 6887867394,
  "username": "...",
  "first_name": "...",
  "last_name": "...",
  "is_admin": true,        // <-- used by frontend
  "is_active": true,
  "role": "admin",          // <-- returned but NOT used by frontend for visibility
  "tariff": { ... },
  "onboarding_completed": true
}
```

**Frontend type** (`types/user.ts:1-18`):
```typescript
export interface UserProfile {
  is_admin: boolean;   // used for admin panel visibility
  role?: string | null; // NOT used for admin panel visibility
}
```

### 3.4 TokenResponse does NOT include admin status

The auth endpoint (`auth.py:137-141`) returns `TokenResponse` which contains ONLY:
```json
{
  "access_token": "...",
  "refresh_token": "...",
  "onboarding_needed": true,
  "token_type": "bearer"
}
```
No `is_admin`, no `role`. Admin status is ONLY available from the `/me` endpoint.

---

## 4. Symptom → Verification Table

| # | Symptom | Verification | Expected Fact | Likely Cause | Recommended Fix |
|---|---------|-------------|---------------|-------------|-----------------|
| 1 | No admin link in header | Check browser DevTools Network tab for `/api/v1/me` response | Response body should have `"is_admin": true` | `/me` call fails silently (`App.tsx:42-44`) | Add error logging to catch block; add console.error |
| 2 | `/me` returns `is_admin: false` despite DB=1 | `curl /api/v1/me` with valid token | Should return `true` | Login endpoint reset `is_admin` (`auth.py:126`) | Verify `ADMIN_TELEGRAM_ID` in running container env |
| 3 | Admin link visible but `/admin` page shows "no access" | Check `statsQuery.isError` state in Admin.tsx:215 | Admin API calls return 403 | `get_current_admin` checks `is_admin` not `role` | Sync `is_admin` and `role` |
| 4 | App doesn't load in Telegram Web (desktop) | Open in Telegram Web, check browser console | CSP violation: `frame-ancestors 'self'` blocks iframe | nginx.conf:54, main.py:292 | Add `frame-ancestors https://web.telegram.org https://*.telegram.org` |
| 5 | Styles broken / blank page | Browser console shows CSP violations | `default-src 'self'` blocks inline styles from Vite | nginx.conf:54 | Add `style-src 'self' 'unsafe-inline'` |
| 6 | Admin toggle in admin panel doesn't actually grant admin | After toggling, check DB `is_admin` column | `is_admin` unchanged, only `role` changed | `admin_user_update` sets `role` not `is_admin` | Also set `is_admin = (role == 'admin')` in handler |

---

## 5. Checklist of Required Fixes

### P0 — Critical (Admin Panel Broken)

- [ ] **A1. Add error logging to `/me` catch block** (`frontend/src/App.tsx:42-44`)
  - Add `console.error("Failed to fetch /me:", err)` in the catch block.
  - Consider showing a toast or error state instead of silently failing.
  - This is the #1 diagnostic priority: without it, you're debugging blind.

- [ ] **A2. Verify `ADMIN_TELEGRAM_ID` in running container environment**
  - Run: `docker exec <backend-container> env | grep ADMIN_TELEGRAM_ID`
  - Ensure the value matches `6887867394` exactly (no quotes, no spaces, no extra chars).
  - If missing: the login endpoint will reset `is_admin=False` on next auth.

- [ ] **A3. Add startup log for resolved admin_telegram_id value** (`backend/app/main.py:144-148`)
  - Currently logs `admin_telegram_id_configured` as boolean. Should also log the actual value (or masked) for debugging.

- [ ] **A4. Sync `is_admin` ↔ `role` in `admin_user_update`** (`backend/app/api/v1/admin.py:149-170`)
  - When `role` is set to `"admin"`, also set `is_admin = True`.
  - When `role` is set to `"user"`, also set `is_admin = False`.
  - OR: eliminate `is_admin` column entirely and derive it from `role`.

- [ ] **A5. Unify admin source of truth**
  - Decision: use EITHER `is_admin` OR `role == 'admin'` everywhere, not both.
  - Recommended: keep `role` as the canonical source, make `is_admin` a property:
    ```python
    @property
    def is_admin(self):
        return self.role == UserRole.admin
    ```
  - Update deps.py, auth.py, main.py bootstrap, schemas, and frontend accordingly.

- [ ] **A6. Fix CSP `frame-ancestors` for Telegram Web** (`nginx.conf:54`, `backend/app/main.py:292`)
  - Change to: `frame-ancestors 'self' https://web.telegram.org https://*.telegram.org`
  - This allows the Mini App to load inside Telegram Web's iframe.
  - Note: TWO places set this header (nginx AND backend middleware) — fix both or remove one.

### P1 — Important

- [ ] **B1. Add `is_admin` and `role` to `TokenResponse`** (`backend/app/schemas/auth.py:18-22`)
  - Frontend shouldn't depend solely on a separate `/me` call to know admin status.
  - Return `is_admin` and `role` in the auth response so the frontend can set user context immediately.

- [ ] **B2. Add frontend route guard for `/admin`** (`frontend/src/App.tsx:68`)
  - Currently: `<Route path="/admin" element={<Admin />} />` — no guard.
  - Any authenticated user can navigate to `/admin` directly (then gets 403 from API calls → tokens cleared → forced logout).
  - Add: `element={user?.is_admin ? <Admin /> : <Navigate to="/" />}`

- [ ] **B3. Remove nuclear 403 handler in `apiFetch`** (`frontend/src/shared/api/client.ts:105-110`)
  - Currently: ANY 403 → `clearStoredTokens()` + redirect to `/`.
  - This means a non-admin accessing any admin endpoint loses their session.
  - Fix: Only clear tokens on 401, not 403. For 403, show an "Access Denied" message instead.

- [ ] **B4. Protect bootstrap against role=None** (`backend/app/main.py:243`)
  - `getattr(user, "role", None)` returns `None` if role column is NULL → role not updated.
  - Fix: `if user.role is None or user.role.value != "admin":`

- [ ] **B5. `.env.example` should include `ADMIN_TELEGRAM_ID`** (`.env.example`)
  - Add: `ADMIN_TELEGRAM_ID=` with a comment explaining its purpose.

### P2 — Hardening

- [ ] **C1. Telegram auth TTL enforcement** (`backend/app/core/settings.py:110-113`)
  - Already enforced: `get_settings()` raises `ValueError` if `telegram_auth_ttl_seconds <= 0` in production. Good.
  - Verify: in production `.env`, `TELEGRAM_AUTH_TTL_SECONDS=300` (or similar > 0).

- [ ] **C2. initData canonicalization** (`backend/app/services/telegram_auth.py:25-58`)
  - Already implemented: `_parse_init_data_pairs()` rejects duplicate keys. Good.
  - Verify: test coverage exists (`backend/tests/test_telegram_auth_validation.py`).

- [ ] **C3. Async endpoint / sync DB mismatch** (`backend/app/api/v1/admin.py`)
  - Several admin endpoints are `async def` but use sync SQLAlchemy:
    - `admin_user_update` (line 150) — `async def` + sync `db.get()`, `db.commit()`
    - `admin_user_tariff_update` (line 196) — same
    - `admin_tariff_create` (line 257) — same
    - `admin_tariff_update` (line 281) — same
    - `admin_tariff_delete` (line 304) — same
    - `admin_tariffs` (line 239) — same
  - These block the event loop when executing DB queries. Convert to `def` (FastAPI auto-threads) or use async SQLAlchemy.
  - Note: The `users.py:18` endpoint `complete_onboarding` has the same issue.

- [ ] **C4. CORS_ORIGINS must include actual Mini App domain** (`backend/app/core/settings.py:115-119`)
  - Already validated in production: rejects `*` and empty list. Good.
  - Verify: the `.env` `CORS_ORIGINS` includes `https://kass.freestorms.top`.

- [ ] **C5. Remove duplicate CSP headers** — nginx (`nginx.conf:54`) AND backend (`main.py:292-297`) both set CSP.
  - Having two CSP headers means the browser enforces the MOST RESTRICTIVE union.
  - Pick one location (recommendation: backend middleware only, so it's version-controlled with the app).

- [ ] **C6. CSP `default-src 'self'` may break Vite assets**
  - Vite may inject inline `<style>` tags or use `blob:` URLs for HMR.
  - In production builds, this is usually fine (external CSS files).
  - But verify: check browser console for CSP violations.

- [ ] **C7. Add observability for auth failures**
  - Already partially implemented: `telegram_auth_reject_total` counter (`core/metrics.py`).
  - Add: Prometheus metric for `/me` endpoint failures (4xx/5xx).
  - Add: structured log for admin status changes (bootstrap + login + admin toggle).

- [ ] **C8. Sync Redis operations in async context** (`backend/app/main.py:138-139`)
  - `Redis.from_url(settings.redis_url)` + `redis_client.ping()` in the `on_startup` async handler uses the sync Redis client.
  - This blocks the event loop during startup. Use `redis.asyncio` instead.

---

## 6. Detailed File References

### Backend — Admin Bootstrap
- `backend/app/main.py:143` — `_bootstrap_admin()` called during startup
- `backend/app/main.py:222-253` — `_bootstrap_admin()` function
- `backend/app/main.py:240` — checks `user.is_admin`
- `backend/app/main.py:243` — checks `user.role` (defensive, may skip NULL roles)
- `backend/app/main.py:246` — sets `user.role = UserRole.admin`

### Backend — Auth Flow
- `backend/app/api/v1/auth.py:29-36` — `_is_configured_admin()`
- `backend/app/api/v1/auth.py:59-141` — `auth_via_telegram()`
- `backend/app/api/v1/auth.py:111-112` — find existing user + compute `should_be_admin`
- `backend/app/api/v1/auth.py:126-129` — **DANGER**: overwrites `is_admin` on login
- `backend/app/schemas/auth.py:18-22` — `TokenResponse` (no `is_admin` field!)

### Backend — `/me` Endpoint
- `backend/app/api/v1/users.py:13-15` — `read_me()` handler
- `backend/app/api/deps.py:54-64` — `get_current_active_user()`
- `backend/app/api/deps.py:67-72` — `get_current_admin()` (checks `is_admin`)
- `backend/app/schemas/user.py:6-30` — `UserResponse` schema (includes `is_admin`, `role`)

### Backend — Admin RBAC
- `backend/app/api/deps.py:70` — `if not current_user.is_admin:` — THE gate
- `backend/app/api/v1/admin.py:7` — `from app.api.deps import get_current_admin`
- `backend/app/api/v1/admin.py:149-170` — `admin_user_update()` sets `role` only
- `backend/app/api/v1/router.py:31` — admin router mounted at `/admin` prefix

### Frontend — Admin Visibility
- `frontend/src/App.tsx:37-45` — `/me` call with silent catch
- `frontend/src/App.tsx:57` — `isAdmin={user?.is_admin ?? false}`
- `frontend/src/components/AppShell.tsx:18-21` — `isAdmin` prop definition
- `frontend/src/components/AppShell.tsx:62-68` — conditional admin link render
- `frontend/src/pages/Admin.tsx:49-536` — Admin page (no access guard)
- `frontend/src/types/user.ts:1-18` — `UserProfile` type (has `is_admin: boolean`)

### Frontend — Auth Flow
- `frontend/src/pages/Login.tsx:43-56` — login request + token storage
- `frontend/src/stores/auth.tsx:24-84` — `AuthProvider` (user state management)
- `frontend/src/shared/api/client.ts:105-110` — 403 handler (nuclear: clears all tokens)

### Configuration
- `backend/app/core/settings.py:47-48` — `admin_user_id`, `admin_telegram_id`
- `backend/app/core/settings.py:110-113` — TTL validation in production
- `backend/app/core/settings.py:115-119` — CORS validation in production
- `.env.example` — missing `ADMIN_TELEGRAM_ID`

### CSP Headers
- `nginx.conf:54` — `frame-ancestors 'self'` (blocks Telegram Web)
- `backend/app/main.py:292` — `frame-ancestors 'self'` (duplicate)

---

## 7. Next Commands to Run (on server, manually)

```bash
# 1. Verify ADMIN_TELEGRAM_ID is in the running backend container
docker exec $(docker ps -qf "name=backend") env | grep ADMIN_TELEGRAM_ID

# 2. Verify the DB state
docker exec $(docker ps -qf "name=db") mysql -u rovena -provena rovena \
  -e "SELECT id, telegram_id, is_admin, role, is_active FROM users WHERE telegram_id=6887867394;"

# 3. Get a valid JWT token (replace <init_data> with actual Telegram initData)
curl -s -X POST https://kass.freestorms.top/api/v1/auth/telegram \
  -H 'Content-Type: application/json' \
  -d '{"init_data": "<VALID_INIT_DATA>"}' | jq .

# 4. Check /me response with the token
curl -s https://kass.freestorms.top/api/v1/me \
  -H 'Authorization: Bearer <TOKEN_FROM_STEP_3>' | jq '.is_admin, .role'

# 5. Check if /me returns is_admin: true
# Expected: true, "admin"

# 6. Check backend logs for admin bootstrap and recent auth events
docker logs $(docker ps -qf "name=backend") 2>&1 | grep -E "Admin bootstrap|is_admin|admin_telegram"

# 7. Check CORS_ORIGINS in running config
docker exec $(docker ps -qf "name=backend") env | grep CORS_ORIGINS

# 8. Check CSP headers on the frontend response
curl -sI https://kass.freestorms.top/ | grep -i "content-security-policy"

# 9. Check CSP headers on API response
curl -sI https://kass.freestorms.top/api/v1/me | grep -i "content-security-policy"

# 10. Check if the DB has is_admin=1 AFTER a fresh login
# (login, then immediately re-query the DB to see if auth.py reset it)
docker exec $(docker ps -qf "name=db") mysql -u rovena -provena rovena \
  -e "SELECT is_admin, role FROM users WHERE telegram_id=6887867394;"
```

---

## 8. Architecture Diagram: Admin Status Flow

```
                         .env
                     ADMIN_TELEGRAM_ID=6887867394
                              |
              +-----------+---+-----------+
              |                           |
     [App Startup]                [Each Login]
     _bootstrap_admin()        auth_via_telegram()
     main.py:222               auth.py:59
              |                           |
     Find user by TG ID        _is_configured_admin()
     Set is_admin=True          auth.py:29
     Set role=admin                    |
              |                should_be_admin?
              |                        |
              v               +--------+--------+
         DB: is_admin=1       | True             | False
             role=admin       | (no change if    | (RESETS is_admin!)
              |               |  already admin)  | auth.py:127
              v               +--------+---------+
         GET /me                       |
         users.py:13                   v
              |                   DB: is_admin=0 !!!
     UserResponse.model_validate()
              |
     JSON: { "is_admin": true/false }
              |
              v
     Frontend: apiFetch("/me")
     App.tsx:37
              |
     +--------+---------+
     | Success           | Failure (ANY error)
     | setUser(data)     | setUser(null)   <-- SILENT!
     | App.tsx:39        | App.tsx:43
     |                   |
     v                   v
     user?.is_admin      null?.is_admin ?? false
     = true/false        = false
              |                   |
              v                   v
     AppShell isAdmin=...   AppShell isAdmin=false
     AppShell.tsx:57        → NO ADMIN LINK
```
