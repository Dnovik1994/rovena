from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from sqlalchemy import Column, MetaData, String, Table, create_engine, inspect

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
