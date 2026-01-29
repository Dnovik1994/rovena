from __future__ import annotations

import importlib.util
from pathlib import Path


class FakeResult:
    def __init__(self, value: int):
        self._value = value

    def scalar(self) -> int:
        return self._value


class FakeBind:
    def __init__(self):
        self.dialect = type("Dialect", (), {"name": "mysql"})()
        self.last_query: str | None = None

    def execute(self, sql, params):
        self.last_query = str(sql)
        return FakeResult(0)


class FakeOp:
    def __init__(self):
        self.bind = FakeBind()
        self.executed_sql: list[str] = []

    def get_bind(self):
        return self.bind

    def execute(self, sql: str):
        self.executed_sql.append(sql)


def _load_migration():
    repo_root = Path(__file__).resolve().parents[2]
    migration_path = repo_root / "backend" / "alembic" / "versions" / "0017_add_performance_indexes.py"
    spec = importlib.util.spec_from_file_location("migration_0017", migration_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_refresh_token_prefix_index(monkeypatch):
    migration = _load_migration()
    fake_op = FakeOp()
    monkeypatch.setattr(migration, "op", fake_op)

    migration._create_index_if_missing(
        "ix_users_refresh_token",
        "users",
        "refresh_token",
        mysql_columns="refresh_token(191)",
    )

    assert fake_op.bind.last_query is not None
    assert "information_schema.statistics" in fake_op.bind.last_query
    assert "table_schema = DATABASE()" in fake_op.bind.last_query
    assert any("refresh_token(191)" in sql for sql in fake_op.executed_sql)
