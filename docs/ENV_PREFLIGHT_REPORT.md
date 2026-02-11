# ENV Preflight Validation Report

## What changed

### 1. `backend/app/core/settings.py`

- **New field** `dev_allow_localhost: bool = False` — escape hatch for localhost URLs in production.
- **New function** `_is_localhost(url)` — detects localhost addresses (`localhost`, `127.0.0.1`, `0.0.0.0`, `::1`).
- **New function** `validate_settings(settings)` — production preflight validator that collects all errors and raises a single `ValueError` with a bullet list of problems. In development mode, logs warnings only.
- **`get_settings()`** now calls `validate_settings()` for both production and development modes, replacing the inline TTL/CORS checks.

Production preflight enforces:

| Check | Error if |
|---|---|
| CORS_ORIGINS | empty or contains `*` |
| WEB_BASE_URL | empty |
| WEB_BASE_URL ∈ CORS_ORIGINS | WEB_BASE_URL not in the list |
| Localhost ban | any origin or WEB_BASE_URL is localhost (unless `DEV_ALLOW_LOCALHOST=true`) |
| TELEGRAM_AUTH_TTL_SECONDS | ≤ 0 |
| ADMIN_TELEGRAM_ID | set but not numeric |

After validation, logs effective config (no secrets):
```
Effective config | ENVIRONMENT=production | WEB_BASE_URL=https://... | CORS_ORIGINS=[...] | TELEGRAM_AUTH_TTL_SECONDS=300 | admin_id_present=true
```

### 2. `backend/app/main.py`

- Added `Config preflight passed` log line in `on_startup()`.

### 3. `.env.example`

- Added `WEB_BASE_URL=https://kass.freestorms.top` with comments.
- Changed `CORS_ORIGINS` default from `["http://localhost:5173"]` to `["https://kass.freestorms.top"]`.
- Added `DEV_ALLOW_LOCALHOST` commented-out option with explanation.

### 4. `docs/deploy-checklist.md`

- Added "CORS & WEB_BASE_URL (Telegram Mini App)" section with:
  - Variable table
  - Rules enforced in production
  - Step-by-step to avoid CORS errors
  - New checklist items for WEB_BASE_URL, CORS_ORIGINS, DEV_ALLOW_LOCALHOST

### 5. `backend/tests/test_config_validation.py` (new)

16 tests in 3 groups:

| Group | Tests |
|---|---|
| `TestProductionFails` | wildcard CORS, wildcard among origins, empty CORS, empty WEB_BASE_URL, WEB_BASE_URL not in CORS, TTL=0, TTL<0, localhost CORS, localhost WEB_BASE_URL, localhost allowed with flag, multiple errors collected |
| `TestProductionPasses` | valid config, valid config with admin |
| `TestDevelopmentWarns` | wildcard warns, TTL=0 warns, bad config does not raise in dev |

## Verification commands

```bash
# Run only the new preflight tests
PYTHONPATH=backend pytest backend/tests/test_config_validation.py -v

# Run all tests (requires full deps: httpx, redis, etc.)
PYTHONPATH=backend pytest backend/tests/ -v

# Check startup logs in docker (production)
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml logs backend | grep -E "Effective config|preflight"

# Deliberately trigger a preflight failure (empty CORS)
PRODUCTION=true CORS_ORIGINS="" WEB_BASE_URL="" python -c "from app.core.settings import get_settings; get_settings()"
```
