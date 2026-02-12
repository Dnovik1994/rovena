# Post-Fix Verification Audit Report

**Date:** 2026-02-12
**Auditor:** Claude (Opus 4.6) — automated strict verification
**Scope:** All P0/P1/P2 deployment safety fixes (F01–F11) + validation script
**Branch:** main (read-only audit)
**Methodology:** Evidence-based, file+line citation required for every claim

---

## Executive Summary

| # | Section                        | Verdict    | Severity of Findings |
|---|--------------------------------|------------|----------------------|
| 1 | Migration Safety (P0)          | **PASS**   | —                    |
| 2 | Volume Safety (P1)             | **PASS**   | —                    |
| 3 | Deploy Safety (P1)             | **PASS**   | —                    |
| 4 | Docs Consistency (P2)          | **PARTIAL**| P3 (low)             |
| 5 | Validation Script (P1/P2)      | **PASS**   | —                    |
| 6 | Worker Migration Safety        | **PASS**   | —                    |
| 7 | Traefik / Router Consistency   | **PASS**   | P3 (docs-only)       |

**Overall verdict:** Production deployment pipeline is internally consistent and no
high-severity risks remain. Two low-severity documentation inconsistencies found (P3).

---

## 1. Migration Safety (P0) — PASS

### Advisory lock session continuity

The advisory lock is acquired, held, and released on a **single** `conn` object
throughout the entire lifecycle:

| Phase               | Evidence                                                      |
|---------------------|---------------------------------------------------------------|
| Connection created  | `backend/scripts/migrate_with_lock.py:41` — `conn = engine.connect()` |
| GET_LOCK acquired   | `migrate_with_lock.py:47-50` — `SELECT GET_LOCK(:name, :timeout)` on `conn` |
| Alembic upgrade     | `migrate_with_lock.py:85` — `command.upgrade(cfg, "head")` (in-process call) |
| Consistency checks  | `migrate_with_lock.py:149-198` — all queries executed on `conn` |
| RELEASE_LOCK        | `migrate_with_lock.py:207-209` — `SELECT RELEASE_LOCK(:name)` on `conn` |
| Connection closed   | `migrate_with_lock.py:217-218` — `conn.close()` in `finally` block |

The `conn` object is never closed or replaced between GET_LOCK and RELEASE_LOCK.
The `finally` block (`migrate_with_lock.py:203-222`) guarantees cleanup on all exit paths.

### Alembic does NOT spawn a subprocess

`command.upgrade(cfg, "head")` at line 85 is an **in-process** Python API call
(from `alembic.command`). It does NOT use `subprocess.run()`, `os.system()`, or
any other subprocess mechanism. The lock connection `conn` stays alive throughout.

**Architectural note:** Alembic's `env.py:64-70` creates its own engine
(`engine_from_config()` with `pool.NullPool`) and connection for DDL execution.
This is a **separate MySQL session** from `conn`. The advisory lock remains valid
because:

1. MySQL `GET_LOCK()` is **session-scoped** — it survives commits/rollbacks
   (`migrate_with_lock.py:70-72` comment confirms this design intent)
2. The lock's purpose is to serialize migration runs across processes, not to
   share a transaction with DDL
3. `conn` remains open (and thus the lock held) for the entire duration

### Lock name consistency

- Acquire: `migrate_with_lock.py:48` — uses `lock_name` variable
- Release: `migrate_with_lock.py:208` — uses same `lock_name` variable
- Default: `"alembic_migration_lock"` (`migrate_with_lock.py:31`)
- Configurable via `MIGRATIONS_LOCK_NAME` env var — single source of truth

### Lock timeout behavior

- Timeout: `migrate_with_lock.py:32` — `int(os.environ.get("MIGRATIONS_LOCK_TIMEOUT", "120"))`
- Check: `migrate_with_lock.py:52-55` — if `result != 1`, logs error and `return 1`
- MySQL semantics: `GET_LOCK(name, 0)` = non-blocking; `GET_LOCK(name, N)` = wait up to N seconds
- Default 120s timeout is reasonable for migration workloads

### Failure paths exit non-zero

| Failure Condition                     | Line(s)   | Exit Code |
|---------------------------------------|-----------|-----------|
| Lock acquisition failed               | 52-55     | `return 1`|
| Downgrade after duplicate key failed  | 96-97     | `return 1`|
| Unexpected alembic error              | 120-123   | `return 1`|
| Max retries exceeded                  | 126-131   | `return 1`|
| No HEAD revision found                | 142-144   | `return 1`|
| Stamp failed                          | 159-161   | `return 1`|
| Row count != 1 (corruption)           | 173-183   | `return 1`|
| Final version mismatch                | 190-196   | `return 1`|
| Normal success                        | 201       | `return 0`|

All failure paths return non-zero. The `run-migrations.sh` wrapper uses
`exec python /app/scripts/migrate_with_lock.py` (line 16), so the exit code
propagates directly.

---

## 2. Volume Safety (P1) — PASS

### rovena_mysql-data is never removed except via --wipe-volumes

**pre-deploy-clean.sh** (`scripts/pre-deploy-clean.sh:6`):
```bash
docker volume rm rovena_postgres-data || true
```
Only removes the **legacy** postgres volume. The comment at line 4-5 explicitly
states: "mysql-data is the active production volume and must NEVER be removed here."

**deploy-bootstrap.sh** — volume deletion paths:
- Normal deploy (line 43): `docker compose -f docker-compose.prod.yml down --remove-orphans`
  — NO `-v` flag, volumes preserved
- Wipe deploy (line 41): `docker compose ... down --remove-orphans -v`
  — ONLY reachable when `$WIPE_VOLUMES = true` (line 32), which requires `--wipe-volumes` flag
  — Without `--force`, requires interactive confirmation: type `WIPE` (lines 33-38)

**Full codebase search for `docker volume rm`:**
- `scripts/pre-deploy-clean.sh:6` — only `rovena_postgres-data`
- All other references are in documentation/audit files (not executable scripts)

**Full codebase search for `mysql-data` deletion:**
- No script contains `docker volume rm rovena_mysql-data`
- `docker-compose.prod.yml:84,404` — defines and mounts the volume (read/write)
- `deploy-bootstrap.sh:8` — warning comment only

**dev-clean.sh** (`scripts/dev-clean.sh:4`):
```bash
docker compose down -v --remove-orphans
```
Uses the **default** compose file (`docker-compose.yml`), which defines
`postgres-data` / `redis-data` / `3proxy-cfg` — **not** `mysql-data`.
The prod compose file (`docker-compose.prod.yml`) is not referenced.

---

## 3. Deploy Safety (P1) — PASS

### deploy-bootstrap.sh flag parsing

Flags are parsed at **lines 20-27**, before ANY destructive action:

```
Line 17: WIPE_VOLUMES=false
Line 18: FORCE=false
Line 20-27: for arg in "$@"; do ... done   ← flag parsing
Line 30: pre-deploy-clean.sh               ← first action (safe — postgres only)
Line 32: if [ "$WIPE_VOLUMES" = true ]      ← guarded destructive path
```

### --remove-orphans usage

| Command                        | Line | --remove-orphans |
|--------------------------------|------|------------------|
| `down` (normal)                | 43   | Yes              |
| `down -v` (wipe)              | 41   | Yes              |
| `up -d --build`               | 46   | Yes              |

### pre-deploy-clean.sh is non-destructive

Called at line 30, it only removes `rovena_postgres-data` (legacy volume).
It does NOT touch mysql-data, redis-data, or any other active volume.

### No other script uses `down -v` for prod compose

| File                    | `down -v` usage                                        | Prod compose? |
|-------------------------|--------------------------------------------------------|---------------|
| `deploy-bootstrap.sh:41`| Guarded by `--wipe-volumes` + confirmation             | Yes (safe)    |
| `scripts/dev-clean.sh:4`| `docker compose down -v` — uses default compose (dev)  | No            |
| `Makefile:9`            | `$(COMPOSE) down --remove-orphans` — no `-v`           | No            |

---

## 4. Docs Consistency (P2) — PARTIAL (P3 findings)

### `down -v` for prod

README.md does **NOT** contain any instruction to run
`docker compose -f docker-compose.prod.yml down -v` as an operational step.

References to `down -v` in README are **warnings not to do it**:
- Line 73: `> - **Never** run \`docker compose … down -v\` on production...`
- Line 265: `> **WARNING:** Never run \`docker compose -f docker-compose.prod.yml down -v\` directly.`

**PASS** — F03 fix verified.

### `alembic upgrade head` for prod

README.md line 50:
```
docker compose exec backend alembic upgrade head
```

This is under section header (line 47): "4. Примените миграции **(development only
— в production миграции запускаются автоматически)**"

- The instruction does NOT use `-f docker-compose.prod.yml` (uses default/dev compose)
- It is labeled "development only"
- Lines 68-69: "Do NOT run `alembic upgrade head` manually in production."
- Line 74: Explicit warning against it
- Line 591: Repeated warning

**PASS** — F11 fix verified. Dev-only instructions are labeled as such.

### FINDING: README router priority documentation mismatch (P3)

README.md lines 196-199 document the routing architecture:
```
- `kass-api` (priority 100): ...
- `kass-health` (priority 110): ...
- `kass-ws` (priority 110): ...
- `kass-ui` (priority 10): ...
```

Actual values in `docker-compose.prod.yml`:
- `kass-api`: priority **20** (line 168), not 100
- Router named `kass-web` (line 311), not `kass-ui`

**Severity: P3** — Documentation inconsistency only. The actual routing config is
correct and non-ambiguous. The relative priority ordering still works
(110 > 20 > 10).

---

## 5. Validation Script Correctness (P1/P2) — PASS

### Full revision ID extraction

`scripts/validate-deploy.sh:74`:
```bash
alembic_head=$($COMPOSE exec -T backend sh -lc \
  "alembic heads 2>/dev/null | head -n1 | awk '{print \$1}'" \
  2>/dev/null | tr -d '[:space:]') || alembic_head="error"
```

- `alembic heads` outputs: `<revision_id> (head)`
- `awk '{print $1}'` extracts the full first field (complete revision ID)
- `tr -d '[:space:]'` strips trailing whitespace/newlines
- No truncation or substring extraction — full revision ID preserved

### Full string comparison

`validate-deploy.sh:79`:
```bash
[ "$db_version" = "$alembic_head" ]
```
Shell `=` operator performs exact full-string comparison. Not partial, not regex.

### Reliable curl invocation

`validate-deploy.sh:43-44`:
```bash
http_code=$(curl -sk -o /dev/null -w '%{http_code}' \
  "https://localhost${path}" -H "Host: ${DOMAIN}" 2>/dev/null || echo "000")
```

- Connects to `localhost` directly — no DNS ambiguity
- `-k` skips TLS verification (necessary for localhost with a domain cert)
- `-H "Host: ${DOMAIN}"` sets the correct Host header for Traefik routing
- Fallback to `"000"` on curl failure — prevents empty string comparison
- `DOMAIN` defaults to `kass.freestorms.top` (line 19)

### FAILURES counter

- Initialized: `validate-deploy.sh:20` — `FAILURES=0`
- Incremented: `validate-deploy.sh:23` — `FAILURES=$((FAILURES + 1))` (proper arithmetic)
- Checked: `validate-deploy.sh:99` — `[ "$FAILURES" -eq 0 ]`

### Exit code behavior

- `set -uo pipefail` (line 16) — note: no `-e`, which is intentional for a
  validation script (collects all failures rather than stopping at the first)
- Line 103: `exit 1` on any failure
- Implicit `exit 0` if all checks pass (no explicit exit; script ends after the
  success echo at line 100)

### Shell quoting

All variable expansions are properly double-quoted. No unquoted `$variable`
usage that could cause word splitting or globbing. The `$1` in the inner awk
is properly escaped as `\$1` inside the double-quoted shell string.

---

## 6. Worker Migration Safety — PASS

### Defense in depth: three layers

**Layer 1 — docker-compose.prod.yml:233:**
```yaml
RUN_MIGRATIONS: ${RUN_MIGRATIONS_WORKER:-0}
```
Default `0`; only overridable if someone explicitly sets `RUN_MIGRATIONS_WORKER=1`
in `.env`.

**Layer 2 — entrypoint-worker.sh:15:**
```bash
export RUN_MIGRATIONS=0
```
**Hardcoded override** — even if compose passes `RUN_MIGRATIONS=1`, the entrypoint
forces it to `0` before `wait-for-deps.sh` is called.

**Layer 3 — wait-for-db.sh:33:**
```bash
if [[ "${RUN_MIGRATIONS:-1}" == "1" ]]; then
```
Respects the `RUN_MIGRATIONS` variable. With `RUN_MIGRATIONS=0` (from layer 2),
the migration block is skipped entirely.

### No alternate bypass

- `backend/entrypoint.sh:10` — routes to `entrypoint-worker.sh` when
  `APP_ROLE=worker` (compose sets `APP_ROLE: worker` at line 238)
- Worker `command:` in compose (line 243) passes celery args to entrypoint —
  entrypoint-worker.sh runs wait-for-deps, then exec's celery
- No other entrypoint or init script can trigger migrations for the worker

---

## 7. Traefik / Router Consistency — PASS

### Router inventory (docker-compose.prod.yml)

| Router        | Rule                                          | Priority | Service   | Source Lines |
|---------------|-----------------------------------------------|----------|-----------|-------------|
| `kass-api`    | `Host(...) && PathPrefix(\`/api/v1\`)`         | 20       | kass-api  | 166-172     |
| `kass-health` | `Host(...) && Path(\`/health\`)`               | 110      | kass-api  | 175-180     |
| `kass-ws`     | `Host(...) && PathPrefix(\`/ws\`)`             | 110      | kass-api  | 183-188     |
| `kass-web`    | `Host(...)`                                    | 10       | kass-web  | 311-317     |

### No duplicate routers for /health

- `/health` matches `kass-health` (priority 110, exact Path match) and
  `kass-web` (priority 10, catch-all Host match)
- Higher priority wins → `kass-health` → backend:8000
- No other router defines a `/health` path or prefix
- No duplicate router names

### Health endpoint conflicts

- `/health` → `kass-health` (priority 110) → backend
- `/api/v1/health` → `kass-api` (priority 20, PathPrefix `/api/v1`) → backend
- No frontend route intercepts health endpoints
- Service `kass-api` serves both health routes (port 8000) — consistent

### Priority chain (highest to lowest)

```
kass-health (110) — /health exact
kass-ws     (110) — /ws prefix
kass-api    (20)  — /api/v1 prefix
kass-web    (10)  — catch-all (frontend)
```

No ambiguity. Traefik resolves ties by specificity (Path > PathPrefix), and
these two 110-priority routers have non-overlapping rules.

---

## Findings Table

| ID  | Severity | Section              | Description                                                        | File + Line                    | Recommendation                           |
|-----|----------|----------------------|--------------------------------------------------------------------|-------------------------------|------------------------------------------|
| V01 | **P3**   | Docs Consistency     | README documents `kass-api` priority as 100; actual is 20          | `README.md:196` vs `docker-compose.prod.yml:168` | Update README line 196 to say "priority 20" |
| V02 | **P3**   | Docs Consistency     | README references router `kass-ui`; actual name is `kass-web`       | `README.md:199` vs `docker-compose.prod.yml:311` | Update README line 199 to say `kass-web` |

---

## Conclusion

**Production deployment pipeline is internally consistent and no high-severity
risks remain.**

All P0/P1/P2 fixes (F01, F02, F03, F04, F11, validate-deploy.sh) have been
verified against source code with exact file+line evidence:

- **F01 (P0):** Advisory lock held in single session — `migrate_with_lock.py:41-218`
- **F02 (P1):** mysql-data not deleted by pre-deploy-clean.sh — `pre-deploy-clean.sh:6`
- **F03 (P1):** README no longer instructs `down -v` — `README.md:73,265` (warnings only)
- **F04 (P1):** deploy-bootstrap.sh uses `--remove-orphans` — lines 41, 43, 46
- **F11 (P2):** Docs no longer instruct raw `alembic upgrade head` for prod —
  `README.md:47` (dev-only label), lines 68, 74, 591 (warnings)
- **validate-deploy.sh:** Correctly parses full revision IDs, full string
  comparison, reliable curl, proper failure counting, exits non-zero on failure

Two P3 documentation inconsistencies found (V01, V02) with no operational impact.
