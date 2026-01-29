from __future__ import annotations

from pathlib import Path

import importlib.util

from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Boolean, Column, Integer, MetaData, String, Table, create_engine, inspect

from app.core.settings import get_settings

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
INIT_SQL = REPO_ROOT / "docker-entrypoint-initdb.d" / "init-rovena.sql"


def _alembic_config() -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return config


def test_idempotent_migration(mock_alembic):
    config = _alembic_config()
    mock_alembic.clear()
    from alembic import command

    command.upgrade(config, "head")
    command.upgrade(config, "head")

    assert [call[1] for call in mock_alembic] == ["head", "head"]


def test_idempotent_0015(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata = MetaData()
    Table("users", metadata, Column("id", Integer, primary_key=True), Column("tariff_id", Integer))
    Table("accounts", metadata, Column("id", Integer, primary_key=True), Column("status", String(32)))
    Table("campaigns", metadata, Column("id", Integer, primary_key=True), Column("status", String(32)))
    Table("proxies", metadata, Column("id", Integer, primary_key=True), Column("status", String(32)))
    Table("contacts", metadata, Column("id", Integer, primary_key=True), Column("blocked", Boolean))
    metadata.create_all(engine)

    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        op_obj = Operations(context)
        migration_path = BACKEND_ROOT / "alembic" / "versions" / "0015_add_performance_indexes.py"
        spec = importlib.util.spec_from_file_location("migration_0015", migration_path)
        assert spec and spec.loader
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        monkeypatch.setattr(migration, "op", op_obj)

        migration.upgrade()
        migration.upgrade()

        inspector = inspect(connection)
        users_indexes = {index["name"] for index in inspector.get_indexes("users")}
        assert "ix_users_tariff_id" in users_indexes


def test_database_exists(tmp_path, monkeypatch):
    db_path = tmp_path / "rovena.sqlite"
    db_url = f"sqlite+pysqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    get_settings.cache_clear()

    engine = create_engine(db_url)
    metadata = MetaData()
    Table(
        "alembic_version",
        metadata,
        Column("version_num", String(32), primary_key=True),
    )
    metadata.create_all(engine)

    inspector = inspect(engine)
    assert "alembic_version" in inspector.get_table_names()

    init_sql = INIT_SQL.read_text(encoding="utf-8")
    assert "CREATE DATABASE IF NOT EXISTS rovena" in init_sql

    get_settings.cache_clear()


def test_user_privileges():
    init_sql = INIT_SQL.read_text(encoding="utf-8")
    assert "CREATE USER IF NOT EXISTS 'rovena'@'%'" in init_sql
    assert "GRANT ALL PRIVILEGES ON rovena.* TO 'rovena'@'%'" in init_sql
