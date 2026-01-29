from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urlparse

import pymysql


@dataclass(frozen=True)
class DbConfig:
    host: str
    port: int
    user: str
    password: str
    database: str


def _config() -> DbConfig:
    db_url = os.getenv("DATABASE_URL") or os.getenv("database_url")
    if db_url:
        parsed = urlparse(db_url)
        scheme = parsed.scheme.split("+")[0]
        if scheme not in {"mysql", "mariadb"}:
            raise ValueError(f"Unsupported database scheme: {parsed.scheme}")
        return DbConfig(
            host=parsed.hostname or "db",
            port=parsed.port or 3306,
            user=parsed.username or "rovena",
            password=parsed.password or "rovena",
            database=(parsed.path or "/rovena").lstrip("/") or "rovena",
        )
    return DbConfig(
        host=os.getenv("DB_HOST", "db"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER", "rovena"),
        password=os.getenv("DB_PASSWORD", "rovena"),
        database=os.getenv("DB_NAME", "rovena"),
    )


def _connect(database: str | None = None) -> pymysql.connections.Connection:
    config = _config()
    return pymysql.connect(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        database=database,
        connect_timeout=3,
        read_timeout=3,
        write_timeout=3,
        charset="utf8mb4",
        autocommit=True,
    )


def ping() -> bool:
    try:
        connection = _connect(database=None)
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        return False
    finally:
        try:
            connection.close()
        except Exception:
            pass
    return True


def ensure_database() -> bool:
    config = _config()
    try:
        connection = _connect(database=None)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name=%s",
                (config.database,),
            )
            if cursor.fetchone()[0] == 0:
                cursor.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{config.database}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
    except Exception:
        return False
    finally:
        try:
            connection.close()
        except Exception:
            pass
    return True


def check_tables(required_tables: Iterable[str] | None = None) -> bool:
    config = _config()
    tables = list(required_tables or ["alembic_version"])
    try:
        connection = _connect(database=config.database)
        with connection.cursor() as cursor:
            for table in tables:
                cursor.execute(
                    "SELECT COUNT(*) FROM information_schema.tables "
                    "WHERE table_schema=%s AND table_name=%s",
                    (config.database, table),
                )
                if cursor.fetchone()[0] == 0:
                    return False
    except Exception:
        return False
    finally:
        try:
            connection.close()
        except Exception:
            pass
    return True


def main() -> None:
    import sys

    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "ping":
        ok = ping()
    elif command == "ensure-db":
        ok = ensure_database()
    elif command == "check-tables":
        tables = []
        if len(sys.argv) > 2 and sys.argv[2]:
            tables = [t.strip() for t in sys.argv[2].split(",") if t.strip()]
        ok = check_tables(tables)
    else:
        raise SystemExit("Usage: python -m app.utils.db_readiness [ping|ensure-db|check-tables]")

    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
