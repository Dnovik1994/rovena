from __future__ import annotations

import importlib.util
import re
from pathlib import Path


class FakeResult:
    def __init__(self, value: int):
        self._value = value

    def scalar(self) -> int:
        return self._value


class FakeBind:
    def __init__(self, created_indexes: set[tuple[str, str]]):
        self.created_indexes = created_indexes
        self.dialect = type("Dialect", (), {"name": "mysql"})()

    def execute(self, _sql, params):
        key = (params["index_name"], params["table_name"])
        return FakeResult(1 if key in self.created_indexes else 0)


class FakeOp:
    def __init__(self):
        self.created_indexes: set[tuple[str, str]] = set()
        self.bind = FakeBind(self.created_indexes)

    def get_bind(self):
        return self.bind

    def execute(self, sql: str):
        match = re.search(r"CREATE INDEX\s+(\S+)\s+ON\s+(\S+)", sql)
        if match:
            index_name = match.group(1)
            table_name = match.group(2)
            self.created_indexes.add((index_name, table_name))


def _load_migration():
    repo_root = Path(__file__).resolve().parents[2]
    migration_path = repo_root / "backend" / "alembic" / "versions" / "0015_add_performance_indexes.py"
    spec = importlib.util.spec_from_file_location("migration_0015", migration_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_idempotent_migration(monkeypatch):
    migration = _load_migration()
    fake_op = FakeOp()
    monkeypatch.setattr(migration, "op", fake_op)

    migration.upgrade()
    migration.upgrade()

    expected = {
        ("ix_users_tariff_id", "users"),
        ("ix_accounts_status", "accounts"),
        ("ix_campaigns_status", "campaigns"),
        ("ix_proxies_status", "proxies"),
        ("ix_contacts_blocked", "contacts"),
    }
    assert fake_op.created_indexes == expected
