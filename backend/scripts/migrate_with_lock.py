#!/usr/bin/env python3
"""Run Alembic migrations under a MySQL advisory lock.

Holds GET_LOCK() for the full duration of migrations and post-checks
within a single MySQL session, preventing concurrent migration runs.
"""

import os
import re
import sys

from sqlalchemy import create_engine, text

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

LOG_PREFIX = "[migrations]"

ALEMBIC_INI = "/app/alembic.ini"
ALEMBIC_SCRIPT_LOCATION = "/app/alembic"

MAX_RETRIES = 3


def log(msg: str) -> None:
    print(f"{LOG_PREFIX} {msg}", flush=True)


def main() -> int:
    lock_name = os.environ.get("MIGRATIONS_LOCK_NAME", "alembic_migration_lock")
    lock_timeout = int(os.environ.get("MIGRATIONS_LOCK_TIMEOUT", "120"))

    from app.core.settings import get_settings

    settings = get_settings()
    database_url = settings.database_url

    engine = create_engine(database_url, pool_pre_ping=True)

    conn = engine.connect()
    lock_acquired = False

    try:
        # -- Acquire advisory lock ----------------------------------------
        log(f"Acquiring advisory lock '{lock_name}' (timeout {lock_timeout}s)...")
        result = conn.execute(
            text("SELECT GET_LOCK(:name, :timeout)"),
            {"name": lock_name, "timeout": lock_timeout},
        ).scalar()

        if result != 1:
            log(f"ERROR: Failed to acquire advisory lock (result: {result}).")
            log("Another migration may be running or the timeout was exceeded.")
            return 1

        lock_acquired = True
        log("Advisory lock acquired.")

        # Log MySQL server identity and session for observability.
        try:
            row = conn.execute(
                text("SELECT @@hostname, @@port, CONNECTION_ID()")
            ).one()
            log(f"MySQL session: host={row[0]}, port={row[1]}, connection_id={row[2]}")
        except Exception as exc:
            log(f"WARNING: Could not fetch server identity: {exc}")

        # Commit to close the implicit transaction so later reads get a
        # fresh snapshot (MySQL REPEATABLE READ).  The advisory lock is
        # session-scoped and survives commits.
        conn.commit()

        # -- Alembic config ------------------------------------------------
        cfg = Config(ALEMBIC_INI)
        cfg.set_main_option("script_location", ALEMBIC_SCRIPT_LOCATION)

        # -- Run migrations with retry logic -------------------------------
        attempt = 1
        log("Running Alembic migrations.")

        while attempt <= MAX_RETRIES:
            log(f"Attempt {attempt}: upgrading...")
            try:
                command.upgrade(cfg, "head")
                log("Alembic migrations complete.")
                break
            except Exception as exc:
                error_msg = str(exc)

                if re.search(r"duplicate key name|1061", error_msg, re.IGNORECASE):
                    log(
                        "CRITICAL: Duplicate key detected. "
                        "Manual intervention required — do NOT auto-downgrade."
                    )
                    log(f"Error: {error_msg}")
                    return 1

                elif re.search(
                    r"Data too long for column.*version_num|1406.*version_num",
                    error_msg,
                    re.IGNORECASE,
                ):
                    log(
                        "Detected version_num column too narrow, "
                        "widening to VARCHAR(128)..."
                    )
                    try:
                        conn.execute(
                            text(
                                "ALTER TABLE alembic_version "
                                "MODIFY version_num VARCHAR(128) NOT NULL"
                            )
                        )
                        conn.commit()
                        log("Column widened, retrying migration.")
                    except Exception:
                        log("Column widen failed, retrying anyway.")

                else:
                    log("Alembic upgrade failed with unexpected error:")
                    log(error_msg)
                    return 1

                attempt += 1
                if attempt > MAX_RETRIES:
                    log(
                        f"Migration failed after {MAX_RETRIES} retries, "
                        "manual fix required."
                    )
                    return 1

        # -- Post-migration self-heal and consistency checks ---------------
        # Commit so the next reads start a new REPEATABLE READ snapshot
        # that includes rows committed by Alembic on its own connection.
        conn.commit()

        log("Computing HEAD revision...")
        script_dir = ScriptDirectory.from_config(cfg)
        heads = script_dir.get_heads()

        if not heads:
            log("CRITICAL: Unable to determine alembic HEAD revision.")
            return 1

        alembic_head = heads[0]
        log(f"Alembic HEAD: {alembic_head}")

        db_version = conn.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar()
        log(f"DB version:   {db_version}")

        if db_version != alembic_head:
            log(f"MISMATCH: DB version '{db_version}' != HEAD '{alembic_head}'.")
            log("DDL is already applied \u2014 stamping version table to HEAD...")
            try:
                command.stamp(cfg, alembic_head)
            except Exception:
                log("CRITICAL: alembic stamp failed.")
                return 1
            log("Stamp succeeded.")
            # Re-read after stamp (new snapshot).
            conn.commit()

        # -- Strict consistency checks ------------------------------------
        log("Running post-migration consistency checks...")

        row_count = conn.execute(
            text("SELECT COUNT(*) FROM alembic_version")
        ).scalar()

        if row_count != 1:
            log(
                f"CRITICAL: alembic_version has {row_count} row(s) "
                "\u2014 expected exactly 1."
            )
            log("This indicates corruption from a concurrent migration run.")
            log(
                "Manual remediation required: DELETE extra rows "
                "and keep only the correct head."
            )
            return 1
        log("OK: alembic_version has exactly 1 row.")

        final_version = conn.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar()

        if final_version != alembic_head:
            log(
                f"CRITICAL: Final DB version '{final_version}' still does not "
                f"match HEAD '{alembic_head}'."
            )
            log("Self-heal failed \u2014 manual intervention required.")
            return 1

        log(f"OK: alembic_version matches HEAD ({final_version}).")
        log("Post-migration checks passed.")

        return 0

    finally:
        if lock_acquired:
            try:
                log(f"Releasing advisory lock '{lock_name}'...")
                release_result = conn.execute(
                    text("SELECT RELEASE_LOCK(:name)"), {"name": lock_name}
                ).scalar()
                log(f"RELEASE_LOCK result: {release_result}")
            except Exception as exc:
                log(
                    f"WARNING: Could not release advisory lock: {exc} "
                    "(may auto-release on disconnect)."
                )

        try:
            conn.close()
        except Exception:
            pass

        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
