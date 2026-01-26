import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


def _create_engine(tmp_path: Path):
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        db_path = tmp_path / "test.db"
        database_url = f"sqlite+pysqlite:///{db_path}"
    os.environ["DATABASE_URL"] = database_url
    os.environ["TELEGRAM_BOT_TOKEN"] = "test-token"
    os.environ["TELEGRAM_API_ID"] = "12345"
    os.environ["TELEGRAM_API_HASH"] = "hash"
    return create_engine(database_url, connect_args={"check_same_thread": False})


@pytest.fixture()

def client(tmp_path):
    from app.core.settings import get_settings

    get_settings.cache_clear()

    engine = _create_engine(tmp_path)

    from app.core.database import Base
    from app.main import app
    from app.core.database import get_db

    TestingSessionLocal = sessionmaker(bind=engine, class_=Session, autoflush=False)

    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestingSessionLocal() as db:
        from app.models.tariff import Tariff

        if db.query(Tariff).count() == 0:
            db.add_all(
                [
                    Tariff(name="Free", max_accounts=5, max_invites_day=50, price=None),
                    Tariff(name="Pro", max_accounts=20, max_invites_day=200, price=None),
                ]
            )
            db.commit()

    from fastapi.testclient import TestClient

    with TestClient(app) as test_client:
        yield test_client

    Base.metadata.drop_all(bind=engine)
    app.dependency_overrides.clear()
