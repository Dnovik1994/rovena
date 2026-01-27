# Deploy Checklist

Use this checklist before and after the first production run.

## Server readiness
- [ ] Ubuntu server is provisioned.
- [ ] Docker + Docker Compose installed.
- [ ] Git installed.
- [ ] Certbot installed.

## Configuration
- [ ] `.env` is filled with all required secrets (JWT_SECRET, TELEGRAM keys, Stripe, Sentry).
- [ ] `PRODUCTION=true`.

## Deploy steps
- [ ] `git pull origin main`
- [ ] `docker compose -f docker-compose.prod.yml pull`
- [ ] `docker compose -f docker-compose.prod.yml up -d --build`
- [ ] `docker compose -f docker-compose.prod.yml exec backend alembic upgrade head`
- [ ] Run certbot and validate HTTPS.
- [ ] `ufw status` shows ports 22, 80, 443 open.

## Validation
- [ ] `curl -i https://kass.freecrm.biz/health` returns 200.
- [ ] `docker compose -f docker-compose.prod.yml logs --tail=200 cron` shows backup success.
- [ ] Grafana reachable at `http://<server-ip>:3000`.
- [ ] Prometheus datasource added in Grafana.
- [ ] Test login → onboarding → full flow (see `docs/user-testing.md`).
