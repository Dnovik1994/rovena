# Production Deployment Audit

## 1. docker-compose.prod.yml

### Services defined
- traefik, docker-socket-proxy, db, redis, backend, worker, proxy, frontend
- prometheus, grafana, blackbox-exporter, cron

### Dependencies (depends_on)
- backend -> db (healthy), redis (healthy)
- worker -> backend (started), db (healthy), redis (healthy)
- proxy -> backend (healthy)
- frontend -> backend (healthy)
- prometheus -> backend (healthy), proxy (healthy)
- grafana -> prometheus (healthy)
- cron -> db (healthy), redis (healthy)

### Volumes persistence
- mysql-data (named) -> /var/lib/mysql
- redis-data (named) -> /data
- prometheus-data, grafana-data, backups (named)
- 3proxy-cfg (named, shared between backend/worker/proxy)

### Health checks
- db: mysqladmin ping
- redis: redis-cli ping
- backend: Python healthcheck script (/api/v1/health)
- worker: Redis heartbeat check
- proxy: pgrep 3proxy + config exists
- frontend: wget http://127.0.0.1:5173/
- prometheus, grafana, blackbox-exporter, cron: all have healthchecks

## 2. Dockerfiles

### backend/Dockerfile
- Python 3.12-slim, requirements.txt installed
- Alembic templates copied at build time
- Non-root user (appuser)

### frontend/Dockerfile
- Multi-stage: node:20-alpine builder + nginx:alpine
- npm install (NOT npm ci), package-lock.json NOT copied

### proxy/Dockerfile
- Alpine, 3proxy built from source

### cron/Dockerfile
- Alpine, mariadb-client + redis installed

## 3. .env and settings.py

### All settings.py fields with defaults
(See analysis in body)

## 4. Startup sequence
- entrypoint.sh dispatches by APP_ROLE
- wait-for-deps.sh -> wait-for-db.sh + wait-for-redis.sh
- Migrations run via migrate_with_lock.py with MySQL advisory lock
- Admin bootstrap runs at FastAPI startup via _bootstrap_admin()
