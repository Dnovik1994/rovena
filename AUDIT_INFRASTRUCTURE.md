# Infrastructure Layer Audit Report

**Date:** 2026-02-20
**Scope:** Everything OUTSIDE backend/app/ and frontend/src/ — deployment, migrations, CI/CD, config, monitoring, security, scripts
**Files audited:** 90+ infrastructure files
**Total issues found:** 116

---

## Executive Summary

| Severity | Count | Description |
|----------|-------|-------------|
| :red_circle: CRITICAL | **24** | Production blockers, security vulnerabilities, data loss risks |
| :yellow_circle: MEDIUM | **60** | Operational risks, missing best practices, degraded reliability |
| :green_circle: LOW | **32** | Code quality, cosmetic, minor improvements |

### Top 5 Most Dangerous Findings

1. **:red_circle: Open SOCKS proxy with NO authentication** (`proxy/3proxy.cfg`) — anyone on the network can route traffic through your server
2. **:red_circle: Redis has NO password in production** (`docker-compose.prod.yml`) — any compromised container on the `data` network gets full Redis access
3. **:red_circle: Migration failures silently ignored** (`entrypoint-backend.sh`) — backend starts against wrong schema, causing data corruption
4. **:red_circle: No Alertmanager configured** (`prometheus.yml`) — alerts fire but nobody is ever notified
5. **:red_circle: Docker socket proxy exposes container env vars** (`docker-compose.prod.yml`) — CONTAINERS=1 leaks JWT_SECRET, DB passwords to any service reaching the proxy

---

## 1. Deployment & Entrypoints

### 1.1 Dockerfiles

| # | File | Issue | Severity |
|---|------|-------|----------|
| 1 | `proxy/Dockerfile:6-7` | :red_circle: Unpinned `git clone` (no tag/commit) — every build compiles unpredictable 3proxy version | CRITICAL |
| 2 | `backend/Dockerfile:12-14` | :yellow_circle: `build-essential` + `git` remain in final image (~200MB bloat + attack surface); no multi-stage build | MEDIUM |
| 3 | `frontend/Dockerfile:10-21` | :yellow_circle: Poor layer caching — `tsconfig.json`, `vite.config.ts`, `src/` copied BEFORE `npm ci`, invalidating cache on every code change | MEDIUM |
| 4 | `frontend/Dockerfile:23` | :yellow_circle: `FROM nginx:alpine` — unpinned floating tag, different builds get different nginx versions | MEDIUM |
| 5 | `frontend/Dockerfile.dev:8,14` | :yellow_circle: Missing `package-lock.json` in COPY + uses `npm install` instead of `npm ci` — non-deterministic builds | MEDIUM |
| 6 | ALL Dockerfiles | :yellow_circle: No `.dockerignore` files anywhere — entire build contexts (`.git/`, `node_modules/`, `__pycache__/`) sent to Docker daemon | MEDIUM |
| 7 | `cron/Dockerfile` | :yellow_circle: Runs as root with no `USER` instruction | MEDIUM |
| 8 | `proxy/Dockerfile` | :yellow_circle: Runs as root in final stage | MEDIUM |
| 9 | ALL Dockerfiles | :green_circle: No `HEALTHCHECK` instructions (compose defines them, but standalone usage has no health monitoring) | LOW |

### 1.2 Entrypoint Scripts

| # | File | Issue | Severity |
|---|------|-------|----------|
| 10 | `backend/scripts/entrypoint-backend.sh:28-30` | :red_circle: **Migration failure swallowed** — `alembic upgrade heads \|\| { log "WARNING..." }` lets backend start against wrong schema | CRITICAL |
| 11 | `backend/scripts/entrypoint-backend.sh:28` | :yellow_circle: Uses `alembic upgrade heads` (plural) — upgrades to ALL heads, can leave DB in multi-head state | MEDIUM |
| 12 | `backend/scripts/entrypoint-backend.sh:25` | :yellow_circle: `alembic merge heads ... \|\| true` — silently swallows merge failures | MEDIUM |
| 13 | `proxy/entrypoint.sh:2` | :green_circle: Uses `set -e` but not `-uo pipefail` (inconsistent with backend scripts) | LOW |

### 1.3 Docker Compose

| # | File | Issue | Severity |
|---|------|-------|----------|
| 14 | `docker-compose.yml:58-61` | :red_circle: **Hardcoded MySQL credentials** in plaintext in version-controlled file: `MYSQL_PASSWORD: rovena` | CRITICAL |
| 15 | `docker-compose.yml:93` | :red_circle: **Broken Redis healthcheck** — `$(redis-cli ...)` should be `$$(redis-cli ...)` for runtime evaluation; currently always evaluates empty at compose parse time | CRITICAL |
| 16 | `docker-compose.yml:78-98` | :red_circle: Redis has NO password + port exposed (`16379:6379`) — completely open data store | CRITICAL |
| 17 | `docker-compose.prod.yml:129-142` | :red_circle: **Redis has NO password in PRODUCTION** — any container on `data` network has full access | CRITICAL |
| 18 | `docker-compose.prod.yml:97` | :red_circle: Docker socket proxy `CONTAINERS=1` exposes `/containers/{id}/json` — leaks env vars (JWT_SECRET, DB passwords) of ALL containers | CRITICAL |
| 19 | `docker-compose.yml:17-18` | :yellow_circle: Default DB fallback `DB_PASSWORD: ${DB_PASSWORD:-rovena}` — weak password if `.env` missing | MEDIUM |
| 20 | `docker-compose.yml:62-63` | :yellow_circle: MySQL port `13306:3306` exposed to host | MEDIUM |
| 21 | `docker-compose.yml:155-163` | :yellow_circle: Proxy exposes 1001-port range (`10000-11000`) + uses `:latest` tag | MEDIUM |
| 22 | `docker-compose.prod.yml:115-118` | :yellow_circle: Production secrets as env vars (visible via `docker inspect`) — should use Docker secrets | MEDIUM |
| 23 | `docker-compose.prod.yml` | :yellow_circle: No resource limits (`deploy.resources.limits`) on ANY service | MEDIUM |
| 24 | `docker-compose.prod.yml:48-88` | :yellow_circle: Traefik has no healthcheck | MEDIUM |
| 25 | `docker-compose.prod.yml:351-367` | :yellow_circle: Grafana deployed with default `admin/admin` — `GRAFANA_ADMIN_PASSWORD` env var never passed to container | MEDIUM |
| 26 | `docker-compose.prod.yml:172,181,189` | :green_circle: Hardcoded domain `kass.freestorms.top` in Traefik labels instead of `${DOMAIN}` | LOW |

---

## 2. Alembic Migrations

### 2.1 env.py & alembic.ini

| # | File | Issue | Severity |
|---|------|-------|----------|
| 27 | `alembic.ini:3` | :red_circle: **Hardcoded DB credentials** — `mysql+pymysql://rovena:rovena@db:3306/rovena` in version-controlled file | CRITICAL |
| 28 | `alembic/env.py:78` | :red_circle: **`transaction_per_migration=False`** — all migrations run in one transaction. On MySQL (implicit DDL commit), a mid-chain failure leaves schema changed but `alembic_version` NOT updated. Re-run tries to re-apply already-applied migrations | CRITICAL |
| 29 | `alembic/env.py:23-49` | :green_circle: `_ensure_version_num_width` targets 128 chars but migration 0017b only widens to 64 — env.py may ALTER on every run | LOW |

### 2.2 Migration Chain Integrity

The linear chain is **intact** — no broken links, no orphaned revisions, no circular dependencies.

### 2.3 Individual Migration Issues

| # | Migration | Issue | Severity |
|---|-----------|-------|----------|
| 30 | `0002` | :red_circle: `owner_id` already exists from 0001 — migration 0002 is dead code on fresh DB, potential FK name collision if manually triggered | CRITICAL |
| 31 | `0012:37` | :red_circle: Unbounded `UPDATE contacts SET blocked = is_blocked` — locks entire table on large datasets. Data migration mixed with schema migration | CRITICAL |
| 32 | `0022b:37-43` | :red_circle: `create_foreign_key()` NOT guarded by idempotency check — will fail on re-run (column addition IS guarded, FK creation is NOT) | CRITICAL |
| 33 | `0032:38-46` | :red_circle: f-string SQL interpolation: `f"AND TABLE_NAME = '{_TABLE}'"` — SQL injection anti-pattern (values are constants, but pattern is dangerous) | CRITICAL |
| 34 | `0014`, `0016` | :yellow_circle: Not idempotent — bare `op.add_column()` without existence checks, will fail on re-run | MEDIUM |
| 35 | `0015` vs `0017` | :yellow_circle: Duplicate indexes — 0015 creates same indexes as 0017; 0015 is dead code. Sequential downgrade through both will fail | MEDIUM |
| 36 | `0015:51-56` | :yellow_circle: Downgrade not idempotent — bare `op.drop_index()` without existence checks | MEDIUM |
| 37 | `0019`, `0021` downgrades | :yellow_circle: BIGINT narrowed back to INT — data loss if values exceed 2^31-1 | MEDIUM |
| 38 | `0020` | :yellow_circle: `last_error` column addition not idempotent; MySQL ENUM not actually modified (only PostgreSQL path works) | MEDIUM |
| 39 | `0024:53-57` | :yellow_circle: Unbounded `UPDATE campaign_dispatch_logs` before ALTER NOT NULL — locks table on large datasets | MEDIUM |
| 40 | `0025` | :yellow_circle: Mixes seed data (30 rows) with schema migration — downgrade drops ALL data, not just seed | MEDIUM |
| 41 | `0027:30-38` | :yellow_circle: ENUM ALTER via `op.alter_column()` — fragile on MySQL if actual ENUM values have drifted | MEDIUM |
| 42 | `0029:34-47` | :yellow_circle: `alter_column()` not idempotent — unnecessary ALTER TABLE locks on already-nullable columns | MEDIUM |
| 43 | `0030` | :yellow_circle: Pure data migration — downgrade blindly reactivates channels that may have been manually deactivated | MEDIUM |
| 44 | `0008` | :yellow_circle: Pure data migration mixed with schema chain — downgrade assumptions may not hold | MEDIUM |
| 45 | `0011:32-35` | :yellow_circle: Raw `op.execute()` for ENUM modification without checking if value already exists | MEDIUM |
| 46 | `0018:109-117` | :yellow_circle: Downgrade not idempotent — bare `op.drop_index()` and `op.drop_table()` | MEDIUM |
| 47 | `0001:41-45` | :yellow_circle: Downgrade `op.drop_index()` without existence checks | MEDIUM |

---

## 3. CI/CD

### 3.1 `.github/workflows/ci.yml`

| # | Issue | Severity |
|---|-------|----------|
| 48 | :yellow_circle: No `timeout-minutes` on any of 4 jobs — stuck builds burn runner minutes up to 6-hour GitHub cap | MEDIUM |
| 49 | :yellow_circle: No `permissions` key — all jobs get default broad token permissions instead of least-privilege | MEDIUM |
| 50 | :yellow_circle: `workflow_dispatch` with no input guards — anyone with write access can trigger deploy-prod | MEDIUM |
| 51 | :yellow_circle: No pip cache in `backend-test` job (re-downloads all deps every run) | MEDIUM |
| 52 | :yellow_circle: No npm cache in `frontend-build` job (re-downloads all deps every run) | MEDIUM |
| 53 | :green_circle: Overly broad `on: push` — no branch filter, every push to every branch triggers full CI | LOW |
| 54 | :green_circle: Inline `pip install pyyaml` not version-pinned | LOW |
| 55 | :green_circle: `deploy-prod` job is a no-op placeholder (`echo`) | LOW |
| 56 | :green_circle: No failure notifications | LOW |

### 3.2 `.github/workflows/deploy.yml`

| # | Issue | Severity |
|---|-------|----------|
| 57 | `deploy.yml:19-23` | :red_circle: **Secrets interpolated directly in `run:` shell commands** — `${{ secrets.REGISTRY_URL }}` in `docker build -t ${{ secrets.REGISTRY_URL }}/...` risks secret leakage and command injection | CRITICAL |
| 58 | `deploy.yml:30-39` | :red_circle: **No smoke test / health check after deployment** — broken deploys reported as successful | CRITICAL |
| 59 | `deploy.yml:1-39` | :red_circle: **No `concurrency` control** — two releases in quick succession cause parallel SSH deploys, leaving production in inconsistent state | CRITICAL |
| 60 | :yellow_circle: No `timeout-minutes` on any job | MEDIUM |
| 61 | :yellow_circle: No `permissions` key | MEDIUM |
| 62 | :yellow_circle: No Docker build cache strategy (`docker build` without `--cache-from`) | MEDIUM |
| 63 | :yellow_circle: No rollback mechanism on deployment failure | MEDIUM |
| 64 | `deploy.yml:31` | :yellow_circle: `appleboy/ssh-action@v1.0.3` pinned to tag, not commit SHA — tag can be force-pushed | MEDIUM |
| 65 | :yellow_circle: No failure notifications | MEDIUM |
| 66 | :yellow_circle: No `environment: production` protection rules — no approval gate | MEDIUM |
| 67 | :green_circle: Backend + frontend images built sequentially, not in parallel | LOW |
| 68 | :green_circle: Release trigger includes pre-releases | LOW |

---

## 4. Configuration

### 4.1 `.env.example`

| # | Issue | Severity |
|---|-------|----------|
| 69 | `:4` | :red_circle: **`PRODUCTION=true` as default** — developer copying `.env.example` immediately runs in production mode | CRITICAL |
| 70 | `:27-30` | :red_circle: Weak default DB credentials `rovena:rovena` — if URL is tweaked slightly, production check passes but password remains weak | CRITICAL |
| 71 | `:61` | :red_circle: `GRAFANA_ADMIN_PASSWORD=change-me` — no validation enforces changing this | CRITICAL |
| 72 | `:3-4` | :yellow_circle: `ENVIRONMENT=development` contradicts `PRODUCTION=true` — confusing | MEDIUM |
| 73 | `:76` | :yellow_circle: `LE_EMAIL=your@email.com` — placeholder not documented as mandatory for production TLS | MEDIUM |
| 74 | `:56` | :green_circle: No docs on `SENTRY_DSN` re: error vs trace sampling | LOW |
| 75 | `:59-68` | :green_circle: Several variables missing explanatory comments | LOW |

### 4.2 `backend/app/core/settings.py`

| # | Issue | Severity |
|---|-------|----------|
| 76 | `:35` | :red_circle: **`telegram_bot_token` defaults to `""` with NO production validation** — core functionality silently broken | CRITICAL |
| 77 | `:42` | :yellow_circle: `session_enc_key` has no format/length validation — 1-char string passes production check | MEDIUM |
| 78 | `:65-70` | :yellow_circle: `telegram_api_id` validator raises unhandled `ValueError` on non-numeric input | MEDIUM |
| 79 | settings.py vs .env.example | :yellow_circle: `jwt_expiration_minutes` defaults to 15 in code but 1440 (24h) in `.env.example` — confusing mismatch | MEDIUM |
| 80 | Sentry init (`main.py:47-52`) | :yellow_circle: No `environment`, `release`, or `send_default_pii` in Sentry config — all envs show as "production" in dashboard | MEDIUM |
| 81 | `:31-32` | :green_circle: `csrf_enabled: bool = False` never validated for production | LOW |

### 4.3 `nginx.conf` (root)

| # | Issue | Severity |
|---|-------|----------|
| 82 | `:47-51` | :yellow_circle: SSL missing `ssl_protocols TLSv1.2 TLSv1.3`, `ssl_ciphers`, `ssl_prefer_server_ciphers`, `ssl_stapling` | MEDIUM |
| 83 | http block | :yellow_circle: Missing `server_tokens off;` — nginx version exposed in headers | MEDIUM |
| 84 | | :yellow_circle: No `proxy_buffer_size` / `large_client_header_buffers` directives | MEDIUM |
| 85 | `:91` | :yellow_circle: WebSocket `proxy_read_timeout 60s` too short — idle WS connections drop every minute | MEDIUM |
| 86 | `:83-92` | :yellow_circle: No rate limiting on WebSocket endpoint handshake | MEDIUM |
| 87 | `:58-61` | :green_circle: `/health` endpoint doesn't inherit security headers (nginx context scoping) | LOW |

### 4.4 `frontend/nginx.conf`

| # | Issue | Severity |
|---|-------|----------|
| 88 | | :yellow_circle: No `gzip` compression configured — uncompressed JS/CSS served | MEDIUM |
| 89 | `:15-17` | :yellow_circle: No `Cache-Control` headers for static assets | MEDIUM |
| 90 | `:12` | :green_circle: `Strict-Transport-Security` on plain HTTP listener (port 5173) — ignored by browsers per RFC 6797 | LOW |
| 91 | | :green_circle: Missing `server_tokens off;` | LOW |

---

## 5. Monitoring

### 5.1 Prometheus

| # | File | Issue | Severity |
|---|------|-------|----------|
| 92 | `prometheus.yml` | :red_circle: **No `alerting:` section / Alertmanager configured** — alerts fire internally but NOBODY is ever notified | CRITICAL |
| 93 | `prometheus_rules.yml` | :red_circle: **No alerts for service downtime** — missing `up == 0`, 5xx rate, disk space, cert expiry, DB/Redis down | CRITICAL |
| 94 | `prometheus.yml` | :yellow_circle: No MySQL exporter scrape target — DB health invisible | MEDIUM |
| 95 | `prometheus.yml` | :yellow_circle: No Redis exporter scrape target | MEDIUM |
| 96 | `prometheus.yml` | :yellow_circle: No nginx exporter (even though `/nginx_status` is exposed) | MEDIUM |
| 97 | `prometheus.yml` | :yellow_circle: No `node_exporter` — host CPU/memory/disk metrics not collected | MEDIUM |
| 98 | `prometheus_rules.yml:5` | :yellow_circle: `HighQueue` threshold 1000 too high — app's own `health_queue_warn_threshold` is 100 | MEDIUM |
| 99 | `prometheus_rules.yml` | :yellow_circle: No critical-severity alerts — both rules are `severity: warning` only | MEDIUM |
| 100 | `blackbox.yml` | :yellow_circle: Only TCP connect probe, no HTTP probe — checks port open, not app functional | MEDIUM |

### 5.2 Sentry

| # | Issue | Severity |
|---|-------|----------|
| 101 | `main.py:47-52` | :yellow_circle: `traces_sample_rate=0.1` set, but no explicit error sample rate, no `environment`, no `release` tag | MEDIUM |

### 5.3 Logging

No structured logging configuration found at infrastructure level. Container logs go to Docker's default json-file driver with no rotation config in compose files.

---

## 6. Security

### 6.1 3proxy / SOCKS Proxy

| # | File | Issue | Severity |
|---|------|-------|----------|
| 102 | `proxy/3proxy.cfg:3` | :red_circle: **SOCKS proxy open with NO authentication, NO ACLs, NO IP restrictions** — immediate abuse vector | CRITICAL |
| 103 | `proxy/3proxy.cfg` | :red_circle: **No logging configured** — all proxy activity invisible | CRITICAL |
| 104 | `proxy/3proxy.cfg` | :yellow_circle: No `maxconn` — unlimited connections, resource exhaustion risk | MEDIUM |

### 6.2 Redis

| # | Issue | Severity |
|---|-------|----------|
| 105 | `docker-compose.prod.yml` | :red_circle: No `requirepass` in production Redis (already listed as #17 above) | CRITICAL |
| 106 | `docker-compose.yml` | :red_circle: No password + port exposed externally (already listed as #16) | CRITICAL |

### 6.3 MySQL

| # | File | Issue | Severity |
|---|------|-------|----------|
| 107 | `docker-entrypoint-initdb.d/init-rovena.sql:2-3` | :red_circle: **Hardcoded password `'rovena'` in version-controlled SQL** + user created with `'%'` host wildcard | CRITICAL |
| 108 | `init-rovena.sql:3` | :yellow_circle: `GRANT ALL PRIVILEGES` — overly broad, app only needs SELECT/INSERT/UPDATE/DELETE/ALTER | MEDIUM |

### 6.4 Docker Socket

| # | Issue | Severity |
|---|-------|----------|
| 109 | `docker-compose.prod.yml:97,106` | :red_circle: `CONTAINERS=1` on socket proxy exposes env vars of all containers (already listed as #18) | CRITICAL |

### 6.5 Traefik / TLS

TLS is configured via Let's Encrypt ACME with HTTP->HTTPS redirect. The main concern is the nginx SSL hardening (issue #82) and the missing `server_tokens off`.

---

## 7. Scripts & Cron

### 7.1 Backend Scripts

| # | File | Issue | Severity |
|---|------|-------|----------|
| 110 | `scripts/migrate_with_lock.py:89-97` | :red_circle: **Automatic downgrade to hardcoded revision `0014`** on duplicate key errors — auto-downgrade in production is destructive and the target revision will become stale | CRITICAL |
| 111 | `scripts/migrate_with_lock.py:122` | :yellow_circle: Full exception message logged — may contain connection strings / passwords | MEDIUM |
| 112 | `scripts/validate-deploy.sh:55-59` | :yellow_circle: Inline Python creates SQLAlchemy connection never closed — connection leak | MEDIUM |
| 113 | `scripts/check-auth-flow.sh:35` | :yellow_circle: Redis URL printed to stdout — may contain password | MEDIUM |
| 114 | `scripts/wait-for-db.sh:14-17` | :green_circle: Variables `db_host`, `db_port`, `db_user`, `db_password` defined but never used | LOW |

### 7.2 Deployment Scripts

| # | File | Issue | Severity |
|---|------|-------|----------|
| 115 | `scripts/dev-clean.sh:4-5` | :red_circle: **`docker compose down -v` + `docker system prune -f` with NO confirmation prompt** — total data loss if accidentally run in production | CRITICAL |

### 7.3 Cron Jobs (`crontab.txt`)

| # | Issue | Severity |
|---|-------|----------|
| 116 | :red_circle: **No logging on either backup job** — if backups fail, there is zero visibility. Discovered only when restore is needed | CRITICAL |
| 117 | :yellow_circle: No `flock` / overlap protection — concurrent backups possible | MEDIUM |
| 118 | :yellow_circle: `$(date)` called twice in each command — midnight race condition can cause `gzip` on wrong filename | MEDIUM |
| 119 | :yellow_circle: No backup integrity verification (`gunzip -t`, etc.) | MEDIUM |
| 120 | :yellow_circle: No off-site backup copy — host disk failure loses all backups | MEDIUM |

---

## Priority Fix Order

### Immediate (Production Risk NOW)

1. **Add Redis password** in production — `command: redis-server --requirepass ${REDIS_PASSWORD}` + update all `REDIS_URL`
2. **Add authentication to 3proxy** — `auth strong`, `users`, `allow/deny` ACLs
3. **Stop ignoring migration failures** — change `entrypoint-backend.sh:28` to `alembic upgrade head || exit 1`
4. **Remove auto-downgrade to 0014** from `migrate_with_lock.py` — log and fail instead
5. **Fix Docker socket proxy** — remove `CONTAINERS=1` or restrict to specific API paths
6. **Fix Redis healthcheck** — change `$(redis-cli ...)` to `$$(redis-cli ...)`

### This Week

7. Configure Alertmanager + add service-down alerts
8. Add deployment concurrency control + post-deploy health check
9. Pin 3proxy version in `proxy/Dockerfile`
10. Add cron job logging + flock
11. Fix `.env.example` to default `PRODUCTION=false`
12. Add `telegram_bot_token` validation in production settings
13. Remove hardcoded credentials from `init-rovena.sql` (parameterize)
14. Set `transaction_per_migration=True` in `alembic/env.py`
15. Fix secrets handling in `deploy.yml` (env vars, not inline interpolation)

### Next Sprint

16. Add `.dockerignore` files to all build contexts
17. Implement multi-stage Docker build for backend
18. Pin all base image versions
19. Add nginx SSL hardening + `server_tokens off`
20. Add frontend gzip + cache headers
21. Add resource limits to all compose services
22. Add MySQL/Redis/Node exporters to Prometheus
23. Make non-idempotent migrations idempotent (0014, 0016, 0022b)
24. Add npm/pip caching to CI workflows
