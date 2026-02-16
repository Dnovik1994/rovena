# Frontend Audit: types/admin.ts, services/resources.ts, Admin.tsx

## 1. Types (types/admin.ts) vs Backend Pydantic schemas

### AdminStats
- OK: all 8 fields match `GET /admin/stats` response

### AdminUser
- OK: fields match `GET /admin/users` response
- WARN: PATCH endpoints return extra `first_name`, `last_name`, `onboarding_completed` not in type

### AdminProxy
- OK: matches `GET /admin/proxies` response

### AdminAccount
- BUG: `api_app: ApiAppBrief | null` declared in type but backend `GET /admin/accounts` does NOT return this field. UI always shows "none".

### AdminTariff
- OK: matches `TariffResponse`

### AdminApiApp
- OK: matches `ApiAppListResponse`
- NOTE: `api_hash` comes masked from list endpoint

### ApiAppCreateResponse / ApiAppHashReveal
- OK: match backend schemas

## 2. API Calls (services/resources.ts)

### URLs and HTTP methods
- All 17 admin-related endpoints have correct URLs and HTTP methods

### Issues
- BUG: `apiFetch` calls `response.json()` unconditionally — breaks on 204 No Content (DELETE endpoints)
- WARN: `updateApiApp` sends `registered_phone` but backend `ApiAppUpdate` schema lacks this field — silently ignored
- WARN: No pagination params sent for list endpoints (backend default limit=50)

## 3. Admin.tsx

### Imports
- OK: all imports resolve

### State handling per tab
- stats: loading OK, error OK
- users: loading OK, error NOT HANDLED, empty NOT HANDLED
- tariffs: loading OK, error NOT HANDLED, empty NOT HANDLED
- proxies: loading OK, error NOT HANDLED, empty NOT HANDLED
- accounts: loading OK, error NOT HANDLED, empty NOT HANDLED
- api-apps: loading OK, error NOT HANDLED, empty OK

### Forms
- Tariff form: zod validation works, but `max_accounts`/`max_invites_day` errors not shown in UI
- API App form: validation works, errors shown for key fields

### Delete confirmation
- deleteApiApp: has window.confirm() and onError for 409 — but 204 bug makes success look like error
- deleteTariff: NO confirm dialog, NO onError handler

## 4. Console statements in production
- App.tsx:48 console.error
- websocket.ts:181,200,212 console.warn
- ErrorBoundary.tsx:29 console.error
- Login.tsx:23 console.log (DEV-only, OK)

## 5. TypeScript `any`
- No explicit `any` types found
- One `as unknown as number` cast in form defaults
- One `error as { status?: number }` cast in onError handler
