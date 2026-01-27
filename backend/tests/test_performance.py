import asyncio

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core import cache
from app.core.database import Base, get_cached_user
from app.models.user import User


def test_cached_user_avoids_repeat_query(monkeypatch):
    store: dict[str, dict] = {}

    async def fake_get_json(key: str):
        return store.get(key)

    async def fake_set_json(key: str, payload: dict, ttl_seconds: int = 60):
        store[key] = payload

    monkeypatch.setattr(cache, "get_json", fake_get_json)
    monkeypatch.setattr(cache, "set_json", fake_set_json)

    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(bind=engine, class_=Session, autoflush=False)
    Base.metadata.create_all(bind=engine)

    query_count = {"count": 0}

    def before_cursor_execute(*args, **kwargs):
        query_count["count"] += 1

    event.listen(engine, "before_cursor_execute", before_cursor_execute)

    with SessionLocal() as db:
        user = User(telegram_id=999, username="perf", is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)

        query_count["count"] = 0
        asyncio.run(get_cached_user(db, user.id))
        first_count = query_count["count"]
        asyncio.run(get_cached_user(db, user.id))
        second_count = query_count["count"]

    assert second_count == first_count
