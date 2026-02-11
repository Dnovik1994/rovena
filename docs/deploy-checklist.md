# Deploy Checklist

Use this checklist before and after the first production run.

## Server readiness
- [ ] Ubuntu server is provisioned.
- [ ] Docker + Docker Compose installed.
- [ ] Git installed.
- [ ] Traefik будет выпускать сертификаты Let’s Encrypt автоматически.

## Configuration
- [ ] `.env` is filled with all required secrets (JWT_SECRET, TELEGRAM keys, Stripe, Sentry).
- [ ] `PRODUCTION=true`.
- [ ] `TELEGRAM_AUTH_TTL_SECONDS` > 0 (recommended 300). App will refuse to start if <= 0 in production.
- [ ] `CORS_ORIGINS` set to real domain(s), e.g. `["https://kass.freestorms.top"]`. Must match `WEB_BASE_URL`. Wildcard `*` is rejected in production.
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
