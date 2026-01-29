from __future__ import annotations

class DummyCursor:
    def __init__(self) -> None:
        self.queries: list[tuple[str, tuple | None]] = []
        self._last_query: str | None = None
        self._last_params: tuple | None = None

    def execute(self, query: str, params: tuple | None = None) -> None:
        if "table_schema='mysql'" in query or "table_name='user'" in query:
            raise AssertionError("Unexpected query against mysql.user")
        self._last_query = query
        self._last_params = params
        self.queries.append((query, params))

    def fetchone(self) -> tuple[int]:
        if not self._last_query:
            return (0,)
        if "information_schema.tables" not in self._last_query:
            return (0,)
        if "table_schema=%s" in self._last_query:
            assert self._last_params is not None
            schema, table = self._last_params
            if schema == "rovena" and table == "alembic_version":
                return (1,)
        return (0,)

    def __enter__(self) -> "DummyCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class DummyConnection:
    def __init__(self, cursor: DummyCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> DummyCursor:
        return self._cursor

    def close(self) -> None:
        return None


def test_check_tables_ignores_mysql_schema(monkeypatch) -> None:
    from app.utils import db_readiness

    cursor = DummyCursor()
    connection = DummyConnection(cursor)

    def fake_connect(*args, **kwargs):
        return connection

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("database_url", raising=False)
    monkeypatch.setenv("DB_NAME", "rovena")
    monkeypatch.setattr(db_readiness.pymysql, "connect", fake_connect)

    assert db_readiness.check_tables(["alembic_version"]) is True
    assert cursor.queries
