# Deployment / Migrations Safety Audit Report

**Repo:** rovena | **Date:** 2026-02-12 | **Auditor:** Claude Opus 4.6

---

## 1. Executive Summary

**Overall assessment: 7 of 11 checks PASS; 1 critical (P0), 2 high (P1), 1 medium (P2) failures found.**

**What's OK:**
- Post-migration self-heal logic (compute HEAD -> read DB version -> stamp if
  mismatch -> enforce COUNT=1 -> enforce version=HEAD) is correctly implemented
  in `run-migrations.sh:97-173`.
- Only the backend runs migrations. Worker has double protection:
  entrypoint hardcodes `RUN_MIGRATIONS=0` AND compose sets
  `RUN_MIGRATIONS_WORKER=0`. Cron has no alembic access at all.
- Startup sequence uses a single orchestrator (`wait-for-deps.sh`). No
  redundant `wait-for-db.sh`/`wait-for-redis.sh` calls from entrypoints.
- `deploy-bootstrap.sh` requires `--wipe-volumes` flag + interactive "WIPE"
  confirmation (or `--force`) before `down -v`.

**What's still risky:**
- **P0 -- Advisory lock is ineffective.** `GET_LOCK` is acquired inside a
  `python -c` subprocess. When that subprocess exits, MySQL auto-releases the
  session-scoped lock. The actual `alembic upgrade head` command then runs
  *without any lock*. Concurrent migration protection is **completely broken**.
- **P1 -- `pre-deploy-clean.sh` unconditionally attempts
  `docker volume rm rovena_mysql-data`.** If containers are stopped (crash,
  reboot, failed deploy), this silently deletes all MySQL data.
- **P1 -- README.md line 229 instructs raw `down -v` for production** in the
  "Server deploy commands" section, bypassing `deploy-bootstrap.sh` safeguards.
- **P2 -- `deploy-bootstrap.sh` does not pass `--remove-orphans`** to
  `docker compose down` or `up`, leaving stale containers from
  renamed/removed services.

---

## 2. Findings Table

| ID | Sev | Status | Check Area | Evidence | Impact | Fix Recommendation |
|----|-----|--------|-----------|----------|--------|--------------------|
| **F01** | **P0** | **FAIL** | A. Advisory lock | `run-migrations.sh:19-26` -- `GET_LOCK` runs inside `$(python -c "...")` subprocess. When subprocess exits, MySQL releases session-scoped lock. Alembic runs afterwards with no lock. | Two backend replicas (or restart race) can run migrations simultaneously -> `alembic_version` corruption, partial DDL | Rewrite so lock is acquired, migrations run, and lock is released **within the same Python process / MySQL session**. E.g., a single Python script that holds the connection open while invoking `alembic.command.upgrade()`. |
| **F02** | **P1** | **FAIL** | C. Volume wipe | `scripts/pre-deploy-clean.sh:5` -- `docker volume rm rovena_mysql-data \|\| true`. Called unconditionally from `deploy-bootstrap.sh:12`. | If containers are stopped (crash/reboot), this deletes the production MySQL data volume silently. | Guard behind a flag (e.g. `--clean-legacy`) or remove the `rovena_mysql-data` line -- it is the active prod volume, not legacy. |
| **F03** | **P1** | **FAIL** | C/D. Docs safety | `README.md:229` -- `docker compose -f docker-compose.prod.yml down -v`. Listed in "Server deploy commands" as standard step. | Operator following README on running prod wipes all volumes (MySQL, Redis, Prometheus, Grafana, backups). | Replace with reference to `deploy-bootstrap.sh --wipe-volumes`. Add warning that `down -v` should NEVER be run on prod outside that script. |
| **F04** | **P2** | **FAIL** | C. Orphan cleanup | `deploy-bootstrap.sh:35,37,40` -- none of the `docker compose down` or `up` commands include `--remove-orphans`. | Renamed/removed services leave zombie containers consuming resources and potentially conflicting on ports/volumes. | Add `--remove-orphans` to both `down` (lines 35, 37) and `up` (line 40). |
| **F05** | -- | **PASS** | A. Post-migration checks | `run-migrations.sh:106-171` -- Computes HEAD (`alembic heads`), reads DB version via SQL, stamps if mismatch, enforces `COUNT(*)=1`, enforces `version==HEAD`. Exits non-zero on any failure. | N/A | -- |
| **F06** | -- | **PASS** | A. Single migration runner | `entrypoint-worker.sh:15` -- `export RUN_MIGRATIONS=0`. `docker-compose.prod.yml:233` -- `RUN_MIGRATIONS: ${RUN_MIGRATIONS_WORKER:-0}`. `docker-compose.prod.yml:144` -- `RUN_MIGRATIONS: ${RUN_MIGRATIONS:-1}` (backend only). `crontab.txt` -- only mysqldump + redis-cli. | N/A | -- |
| **F07** | -- | **PASS** | B. Single orchestrator | `entrypoint-backend.sh:13-14` calls `wait-for-deps.sh` only. `entrypoint-worker.sh:18-19` calls `wait-for-deps.sh` only. `wait-for-deps.sh:8-16` dispatches to `wait-for-db.sh` + `wait-for-redis.sh`. No duplicate calls. | N/A | -- |
| **F08** | -- | **PASS** | B. Worker migration guard | `entrypoint-worker.sh:15` -- `export RUN_MIGRATIONS=0` appears BEFORE `wait-for-deps.sh` call on line 19. | N/A | -- |
| **F09** | -- | **PASS** | C. Wipe safeguard | `deploy-bootstrap.sh:14-32` -- `WIPE_VOLUMES=false` default; requires `--wipe-volumes` flag; prompts for "WIPE" confirmation unless `--force`. | N/A | -- |
| **F10** | -- | **PASS** | C. Dev-only `down -v` | `scripts/dev-clean.sh:4` -- `docker compose down -v --remove-orphans`. Uses default `docker-compose.yml` (dev), not prod. | N/A | -- |
| **F11** | P2 | **FAIL** | D. Docs drift | README.md lines 50, 65, 560 and RELEASE_NOTES.md line 21 instruct `docker compose exec backend alembic upgrade head` for prod. Bypasses `run-migrations.sh` safety wrapper (advisory lock, self-heal, consistency checks). `deploy-checklist.md:112` correctly says "Migrations run automatically on backend startup." | Operators run migrations without safety checks. | Remove/replace manual `alembic upgrade head` instructions. State migrations are automatic on backend startup. |

---

## 3. Detailed Evidence for Critical/High Findings

### F01 -- Advisory Lock Subprocess Bug (P0)

The lock is acquired in a **child Python process** via `$(python -c "...")`:

```bash
# run-migrations.sh:17-34
acquire_lock() {
  log "Acquiring advisory lock '${LOCK_NAME}' (timeout ${LOCK_TIMEOUT}s)..."
  lock_result=$(python -c "
from sqlalchemy import create_engine, text
from app.core.settings import get_settings
engine = create_engine(get_settings().database_url)
with engine.connect() as conn:
    result = conn.execute(text(\"SELECT GET_LOCK('${LOCK_NAME}', ${LOCK_TIMEOUT})\")).scalar()
    print(result)
" 2>&1) || true
  # ^^^ Python subprocess EXITS here. MySQL auto-releases GET_LOCK.
  ...
}
```

MySQL docs: *"If the connection for a client session terminates, whether
normally or abnormally, the server implicitly releases all table locks and
advisory locks held by the session."*

**Timeline:**
1. `$(python -c "...")` starts -> connects to MySQL -> `GET_LOCK` returns 1 ->
   prints "1" -> **process exits**
2. MySQL releases the lock (session ended)
3. Bash stores `lock_result="1"` and proceeds
4. `alembic upgrade head` (line 62) runs **with no lock held**
5. On EXIT trap, `release_lock()` starts a NEW Python subprocess with a NEW
   MySQL session -> `RELEASE_LOCK` has nothing to release

### F02 -- pre-deploy-clean.sh Data Loss Risk (P1)

```bash
# deploy-bootstrap.sh:12 -- called UNCONDITIONALLY
"${SCRIPT_DIR}/pre-deploy-clean.sh"

# pre-deploy-clean.sh:4-5
docker volume rm rovena_postgres-data || true
docker volume rm rovena_mysql-data || true   # <-- THIS IS THE ACTIVE PROD VOLUME
```

`rovena_mysql-data` is the Docker Compose project-prefixed name for the
`mysql-data` volume defined in `docker-compose.prod.yml:404`. If containers
are not running when `deploy-bootstrap.sh` is invoked (e.g. server rebooted,
previous deploy failed), this `docker volume rm` succeeds and **deletes all
production MySQL data**.

### F03 -- README Instructs Raw `down -v` for Prod (P1)

```markdown
# README.md:218-233 "Server deploy commands (Ubuntu)"
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml down -v  # first run or after old volumes
COMMIT_SHA=$(git rev-parse --short HEAD) docker compose -f docker-compose.prod.yml up -d --build
```

This presents `down -v` as a normal deploy step with only a comment qualifier.
An operator following this on an existing prod server would lose all data
(MySQL, Redis, Prometheus, Grafana, backups).

---

## 4. Commands / Smoke Checks for Test-Prod

### 4.1 Verify advisory lock effectiveness (currently broken)

```bash
# Reproduce the bug: start two migration runs simultaneously
# In terminal 1:
docker compose -f docker-compose.prod.yml exec backend /app/scripts/run-migrations.sh &

# In terminal 2 (within 1 second):
docker compose -f docker-compose.prod.yml exec backend /app/scripts/run-migrations.sh &

# Expected (if lock works): second process blocks until first completes
# Actual (with bug): both run concurrently -- check logs for interleaved output
docker compose -f docker-compose.prod.yml logs backend 2>&1 | grep -E '\[migrations\]'
```

### 4.2 Verify alembic_version consistency

```bash
docker compose -f docker-compose.prod.yml exec backend python -c "
from sqlalchemy import create_engine, text
from app.core.settings import get_settings
engine = create_engine(get_settings().database_url)
with engine.connect() as conn:
    rows = conn.execute(text('SELECT * FROM alembic_version')).fetchall()
    count = len(rows)
    print(f'Row count: {count}')
    for r in rows:
        print(f'  version: {r[0]}')
    assert count == 1, f'CORRUPTION: expected 1 row, got {count}'
    print('OK: single revision')
"
```

### 4.3 Verify HEAD matches DB

```bash
docker compose -f docker-compose.prod.yml exec backend bash -c '
  head=$(alembic heads 2>&1 | grep -oP "^\S+" | head -n1)
  db=$(python -c "
from sqlalchemy import create_engine, text
from app.core.settings import get_settings
e = create_engine(get_settings().database_url)
with e.connect() as c:
    print(c.execute(text(\"SELECT version_num FROM alembic_version\")).scalar())
")
  echo "Alembic HEAD: $head"
  echo "DB version:   $db"
  [ "$head" = "$db" ] && echo "PASS: match" || echo "FAIL: mismatch"
'
```

### 4.4 Verify worker does NOT run migrations

```bash
docker compose -f docker-compose.prod.yml exec worker bash -c 'echo "RUN_MIGRATIONS=$RUN_MIGRATIONS"'
# Expected output: RUN_MIGRATIONS=0

# Also check worker logs for migration skip message:
docker compose -f docker-compose.prod.yml logs worker 2>&1 | grep -i "migration"
# Expected: "Migrations disabled for worker" and "Skipping migrations"
```

### 4.5 Verify deploy-bootstrap.sh wipe protection

```bash
# Test 1: default (no wipe)
bash scripts/deploy-bootstrap.sh --help 2>&1 || true
# Should NOT wipe volumes

# Test 2: wipe without confirmation (should prompt and reject on "n")
echo "n" | bash -c 'source scripts/deploy-bootstrap.sh --wipe-volumes' 2>&1 || true
# Should print "Aborted."

# Test 3: verify --force path (dry-run review only)
grep -n 'down -v' scripts/deploy-bootstrap.sh
# Line 35 should be inside the WIPE_VOLUMES=true block
```

### 4.6 Verify no orphan containers

```bash
docker compose -f docker-compose.prod.yml ps -a --format '{{.Name}} {{.Status}}'
# Look for containers from old/renamed services
```

### 4.7 Verify pre-deploy-clean.sh risk

```bash
# Check if the active mysql-data volume would be at risk
docker volume ls --format '{{.Name}}' | grep mysql-data
# If "rovena_mysql-data" exists AND containers are stopped,
# pre-deploy-clean.sh would delete it
```

### 4.8 Full post-deploy validation

```bash
# Health endpoints
curl -sf https://YOUR_DOMAIN/health && echo "Backend: OK" || echo "Backend: FAIL"
curl -sf https://YOUR_DOMAIN/api/v1/health && echo "API: OK" || echo "API: FAIL"
curl -sf https://YOUR_DOMAIN/ | head -1 && echo "Frontend: OK" || echo "Frontend: FAIL"

# All containers healthy
docker compose -f docker-compose.prod.yml ps --format '{{.Name}}\t{{.Status}}' | column -t

# Migration success log
docker compose -f docker-compose.prod.yml logs backend 2>&1 | grep "Post-migration checks passed"
```
