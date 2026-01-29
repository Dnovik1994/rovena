from __future__ import annotations

from pathlib import Path

from app.utils import db_readiness

REPO_ROOT = Path(__file__).resolve().parents[2]
INIT_SQL = REPO_ROOT / "docker-entrypoint-initdb.d" / "init-rovena.sql"


def test_db_init_creates_database(monkeypatch):
    created = {}

    def fake_config():
        return db_readiness.DbConfig(
            host="db",
            port=3306,
            user="rovena",
            password="rovena",
            database="rovena",
        )

    class FakeCursor:
        def __init__(self) -> None:
            self.seen_queries = []
            self.schema_exists = False

        def execute(self, query, params=None):
            self.seen_queries.append((query, params))
            if "information_schema.schemata" in query:
                self.schema_exists = created.get("schema_exists", False)
                return None
            if query.startswith("CREATE DATABASE"):
                created["created"] = True
                created["schema_exists"] = True
            return None

        def fetchone(self):
            return (1 if created.get("schema_exists") else 0,)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def close(self):
            return None

    monkeypatch.setattr(db_readiness, "_config", fake_config)
    monkeypatch.setattr(db_readiness, "_connect", lambda database=None: FakeConnection())

    assert db_readiness.ensure_database() is True
    assert created.get("created") is True


def test_db_init_grants_in_init_sql():
    init_sql = INIT_SQL.read_text(encoding="utf-8")
    assert "CREATE DATABASE IF NOT EXISTS rovena" in init_sql
    assert "CREATE USER IF NOT EXISTS 'rovena'@'%'" in init_sql
    assert "GRANT ALL PRIVILEGES ON rovena.* TO 'rovena'@'%'" in init_sql
