from sqlalchemy import event

from app.core.database import clear_local_cache, get_db
from app.core.security import create_access_token
from app.models.project import Project
from app.models.user import User


def _create_user_and_project(client) -> User:
    override = client.app.dependency_overrides[get_db]
    db_gen = override()
    db = next(db_gen)
    try:
        user = User(
            telegram_id=777777,
            username="perf",
            first_name="Perf",
            last_name="Test",
            is_admin=False,
            is_active=True,
            role="user",
            tariff_id=1,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        project = Project(owner_id=user.id, name="Perf project", description=None)
        db.add(project)
        db.commit()
        return user
    finally:
        db_gen.close()


def test_user_cache_reduces_user_queries(client):
    clear_local_cache()
    user = _create_user_and_project(client)
    token = create_access_token(str(user.id))

    override = client.app.dependency_overrides[get_db]
    db_gen = override()
    db = next(db_gen)
    engine = db.get_bind()
    db_gen.close()

    statements: list[str] = []

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        client.get("/api/v1/projects", headers={"Authorization": f"Bearer {token}"})
        statements.clear()
        client.get("/api/v1/projects", headers={"Authorization": f"Bearer {token}"})
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)

    user_queries = [stmt for stmt in statements if "FROM users" in stmt]
    assert user_queries == []
