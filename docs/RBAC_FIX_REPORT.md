# RBAC Unification Report

## Decision: `role` is the single source of truth

The `User.role` enum (`user` / `admin` / `superadmin`) is the **authoritative field** for determining access level. The boolean `is_admin` column is kept in the DB for backward compatibility but is **never read for access decisions** — it is always derived from `role` at the API boundary.

### Why `role` and not `is_admin`

| Criterion | `role` (enum) | `is_admin` (bool) |
|---|---|---|
| Granularity | 3 levels (user/admin/superadmin) | 2 levels (true/false) |
| Extensibility | New roles can be added | Binary only |
| Clarity | Self-documenting | Ambiguous (what level of admin?) |

### How it works

1. **Model property** `User.has_admin_access` — single Python-level check: `self.role in ADMIN_ROLES`
2. **Dependency** `get_current_admin()` in `deps.py` — uses `has_admin_access`
3. **Schema validator** `UserBase.derive_is_admin_from_role()` — overrides `is_admin` in all API responses to match `role`
4. **DB sync** — whenever `role` changes (admin update, bootstrap, login), `is_admin` is written to match, so raw DB queries stay consistent

---

## Changes made

### Backend

| File | Lines | Change |
|---|---|---|
| `backend/app/api/v1/admin.py` | 97, 132, 180, 222 | `user.is_admin` → `user.has_admin_access` in all dict responses (admin user list, detail, update, tariff update) |
| `backend/app/main.py` | 237-243 | Bootstrap: changed `logger.info` → `logger.warning` when target user not found; added `admin_user_id` / `admin_telegram_id` to log message |
| `.env.example` | 35-38 | Added `ADMIN_TELEGRAM_ID` and `ADMIN_USER_ID` documentation |

### Frontend

| File | Lines | Change |
|---|---|---|
| `frontend/src/App.tsx` | 78, 89 | Extracted `isAdmin` variable; added route guard — non-admins are redirected from `/admin` to `/` |
| `frontend/src/pages/Admin.tsx` | 331-342 | Toggle button now checks both `admin` and `superadmin`; label changes to "Grant Admin" / "Revoke Admin" |
| `frontend/src/types/user.ts` | 9 | `role` field changed from optional (`role?: string \| null`) to required (`role: string`) |

### Tests

| File | Lines | Change |
|---|---|---|
| `backend/tests/test_admin.py` | new | `test_admin_users_list_derives_is_admin_from_role` — verifies admin list endpoint derives `is_admin` from `role` when DB column is stale |
| `backend/tests/test_admin.py` | new | `test_admin_user_detail_derives_is_admin_from_role` — same for detail endpoint |
| `backend/tests/test_admin.py` | new | `test_bootstrap_logs_warning_when_user_not_found` — verifies warning log level |
| `backend/tests/test_admin.py` | new | `test_bootstrap_noop_when_env_not_set` — verifies no error when env vars absent |

---

## Pre-existing safeguards (no changes needed)

These were already correctly implemented:

- `has_admin_access` property on User model — `role in ADMIN_ROLES`
- `get_current_admin` dependency — checks `has_admin_access`, not `is_admin`
- `UserBase` schema — derives `is_admin` from `role` in all serialized responses
- `TokenResponse` — includes both `is_admin` and `role` on login/refresh
- `/me` endpoint — uses `UserResponse` which derives `is_admin` from `role`
- Bootstrap — only promotes, never downgrades (preserves superadmin)
- Login — only promotes when `ADMIN_TELEGRAM_ID` matches, never downgrades

---

## How to verify

```bash
# Run all admin-related tests
cd backend
pytest tests/test_admin.py -v

# Key test scenarios:
# 1. Bootstrap promotes but never downgrades:
#    - test_admin_bootstrap_sets_flag
#    - test_bootstrap_does_not_downgrade_superadmin
#    - test_bootstrap_logs_warning_when_user_not_found
#    - test_bootstrap_noop_when_env_not_set
#
# 2. Guards allow admin/superadmin:
#    - test_role_admin_grants_admin_access
#    - test_role_superadmin_grants_admin_access
#    - test_role_user_with_is_admin_flag_denied
#
# 3. /me returns correct rights:
#    - test_me_returns_is_admin_consistent_with_role
#    - test_token_response_includes_role_and_is_admin
#
# 4. Admin toggle syncs role/is_admin:
#    - test_admin_user_update_syncs_is_admin
#    - test_admin_users_list_derives_is_admin_from_role
#    - test_admin_user_detail_derives_is_admin_from_role
```

## Migration impact

No new migrations required. The `role` and `is_admin` columns already exist (migrations 0005 and 0006). The changes are purely in application logic and API response generation.
