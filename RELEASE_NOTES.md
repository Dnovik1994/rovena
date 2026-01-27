# Release Notes — v1.0 MVP

## Highlights
- Telegram Mini App authentication with JWT access + refresh.
- Campaign management and warming workflows.
- Admin dashboard with stats and user/tariff management.
- Security headers, input sanitization, and rate limits.
- Performance indexes and cache helpers for hot paths.
- Onboarding wizard and global error handler for safer UX.

## Known Issues
- Account verification may require manual phone code entry.
- Load testing requires valid Telegram initData and admin token.
- Backup cron assumes backup tools are available in the cron container.

## Upgrade Notes
1. Apply migrations:
   ```
   docker compose -f docker-compose.prod.yml exec backend alembic upgrade head
   ```
2. Rebuild and restart services:
   ```
   docker compose -f docker-compose.prod.yml up -d --build
   ```
