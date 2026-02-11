from __future__ import annotations

import asyncio
import inspect
import os
import sys
import types
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Provide a minimal pyaes stub so pyrogram can be imported in test
# environments where pyaes fails to build from source.
if "pyaes" not in sys.modules:
    try:
        import pyaes  # noqa: F401
    except ImportError:
        _pyaes = types.ModuleType("pyaes")
        _pyaes.AESModeOfOperationCTR = type(  # type: ignore[attr-defined]
            "AESModeOfOperationCTR", (), {"__init__": lambda *a, **kw: None}
        )
        _pyaes.AESModeOfOperationIGE = type(  # type: ignore[attr-defined]
            "AESModeOfOperationIGE", (), {"__init__": lambda *a, **kw: None}
        )
        sys.modules["pyaes"] = _pyaes

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("PRODUCTION", "false")

from app.core import database  # noqa: E402
from app.core.database import Base, get_db  # noqa: E402
from app.core.settings import get_settings  # noqa: E402
from app import models  # noqa: F401, E402
from app.models.tariff import Tariff  # noqa: E402

get_settings.cache_clear()


@pytest.fixture(scope="session")
def db_engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    database.engine = engine
    database.SessionLocal.configure(bind=engine)
    Base.metadata.create_all(bind=engine)
    return engine


@pytest.fixture(autouse=True)
def reset_db(db_engine):
    Base.metadata.drop_all(bind=db_engine)
    Base.metadata.create_all(bind=db_engine)
    with database.SessionLocal() as session:
        session.add_all(
            [
                Tariff(name="Free", max_accounts=1, max_invites_day=50, price=0.0),
                Tariff(name="Pro", max_accounts=5, max_invites_day=200, price=19.0),
            ]
        )
        session.commit()
    yield


@pytest.fixture()
def db_session(db_engine):
    session = database.SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def mock_db(db_engine):
    return db_engine


@pytest.fixture()
def mock_redis(monkeypatch):
    class DummyRedis:
        def ping(self):
            return True

        def llen(self, *_args, **_kwargs):
            return 0

    dummy = DummyRedis()

    def fake_from_url(_url):
        return dummy

    from app import main as main_module

    monkeypatch.setattr(main_module.Redis, "from_url", staticmethod(fake_from_url))
    return dummy


@pytest.fixture()
def mock_alembic(monkeypatch):
    from alembic import command

    calls = []

    def fake_upgrade(config, revision):
        calls.append((config, revision))

    monkeypatch.setattr(command, "upgrade", fake_upgrade)
    return calls


@pytest.fixture()
def client(db_session):
    try:
        import httpx  # noqa: F401
    except ModuleNotFoundError:
        pytest.skip("httpx is required for TestClient-based tests")

    from fastapi.testclient import TestClient
    from app.main import app as main_app

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    main_app.dependency_overrides[get_db] = override_get_db
    with TestClient(main_app) as test_client:
        yield test_client
    main_app.dependency_overrides.clear()


def pytest_pyfunc_call(pyfuncitem):
    if inspect.iscoroutinefunction(pyfuncitem.obj):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        funcargs = {
            name: pyfuncitem.funcargs[name]
            for name in pyfuncitem._fixtureinfo.argnames
        }
        loop.run_until_complete(pyfuncitem.obj(**funcargs))
        loop.close()
        return True
    return None
