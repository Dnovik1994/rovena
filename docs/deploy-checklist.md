# Deploy Checklist

Use this checklist before and after the first production run.

## Server readiness
- [ ] Ubuntu server is provisioned.
- [ ] Docker + Docker Compose installed.
- [ ] Git installed.
- [ ] Traefik будет выпускать сертификаты Let's Encrypt автоматически.

## Configuration
- [ ] `.env` is filled with all required secrets (JWT_SECRET, TELEGRAM keys, Stripe, Sentry).
- [ ] `PRODUCTION=true`.
- [ ] `TELEGRAM_AUTH_TTL_SECONDS` > 0 (recommended 300). App will refuse to start if <= 0 in production.

### CORS & WEB_BASE_URL (Telegram Mini App)

The preflight validator (`validate_settings()`) runs on every startup and **blocks
launch in production** if any of these conditions are not met:

| Variable | What to set | Example |
|---|---|---|
| `WEB_BASE_URL` | Public URL of your frontend (the Telegram Mini App URL) | `https://kass.freestorms.top` |
| `CORS_ORIGINS` | JSON list of allowed origins; **must include `WEB_BASE_URL`** | `["https://kass.freestorms.top"]` |

Rules enforced in production:
1. `CORS_ORIGINS` must not be empty or contain `*`.
2. `WEB_BASE_URL` must not be empty.
3. `WEB_BASE_URL` must be listed in `CORS_ORIGINS`.
4. Localhost URLs (`localhost`, `127.0.0.1`) are rejected unless `DEV_ALLOW_LOCALHOST=true`.

Step-by-step to avoid CORS errors with Telegram Mini App:

```bash
# 1. Set your domain (must match the URL registered in @BotFather → Web App URL)
WEB_BASE_URL=https://kass.freestorms.top

# 2. Allow that domain (and optionally web.telegram.org) in CORS
CORS_ORIGINS=["https://kass.freestorms.top"]

# 3. Ensure production mode
PRODUCTION=true

# 4. Verify — the app will log "Effective config" on startup.
#    If misconfigured, it will refuse to start with a clear error.
docker compose -f docker-compose.prod.yml logs backend | grep "Effective config"
```

- [ ] `WEB_BASE_URL` is set to the real Telegram Mini App URL.
- [ ] `CORS_ORIGINS` includes `WEB_BASE_URL`. Wildcard `*` is rejected in production.
- [ ] `DEV_ALLOW_LOCALHOST` is **not** set (or `false`) in real production.
- [ ] `DOMAIN` и `LE_EMAIL` заданы в `.env`.
- [ ] `letsencrypt/acme.json` создан и имеет права `600`.

## Deploy steps
- [ ] `git pull origin main`
- [ ] `docker compose -f docker-compose.prod.yml pull`
- [ ] `docker compose -f docker-compose.prod.yml up -d --build`
- [ ] `docker compose -f docker-compose.prod.yml exec backend alembic upgrade head`
- [ ] Проверить Traefik логи на успешный выпуск сертификата.
- [ ] `ufw status` shows ports 22, 80, 443 open.

## Validation
- [ ] `curl -i https://kass.freestorms.top/health` returns 200.
- [ ] `docker compose -f docker-compose.prod.yml logs --tail=200 cron` shows backup success.
- [ ] Grafana reachable at `http://<server-ip>:3000`.
- [ ] Prometheus datasource added in Grafana.
- [ ] Test login → onboarding → full flow (see `docs/user-testing.md`).
- [ ] Check startup logs for `Effective config` line — confirms preflight passed.
