# Release Notes — v1.0.0 MVP

## Highlights
- Telegram Mini App authentication with JWT access + refresh.
- Campaign management and warming workflows.
- Admin dashboard with stats and user/tariff management.
- Security headers, input sanitization, and rate limits.
- Performance indexes and cache helpers for hot paths.
- Onboarding wizard, global error handler, and 404/offline UX.
- Backups (MySQL + Redis) with daily rotation and retention.

## Known Issues
- Account verification may require manual phone code entry.
- Load testing requires valid Telegram initData and admin token.
- 2FA login flow is not automated.
- Proxy validation still requires manual action in admin.

## Upgrade Notes
1. Apply migrations:
   ```
   docker compose -f docker-compose.prod.yml exec backend alembic upgrade head
   ```
2. Rebuild and restart services:
   ```
   docker compose -f docker-compose.prod.yml up -d --build
   ```
