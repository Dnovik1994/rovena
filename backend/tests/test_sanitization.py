import pytest
from pydantic import Field, ValidationError

from app.core.database import get_db
from app.core.security import create_access_token
from app.models.user import User
from app.schemas.sanitization import SanitizedModel


def _create_user(client) -> User:
    override = client.app.dependency_overrides[get_db]
    db_gen = override()
    db = next(db_gen)
    try:
        user = User(
            telegram_id=888888,
            username="sanitize",
            first_name="San",
            last_name="Test",
            is_admin=False,
            is_active=True,
            role="user",
            tariff_id=1,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db_gen.close()


def test_html_sanitization(client):
    user = _create_user(client)
    token = create_access_token(str(user.id))
    response = client.post(
        "/api/v1/projects",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "<script>alert(1)</script>", "description": "ok"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "&lt;script&gt;alert(1)&lt;/script&gt;"


def test_sql_injection_rejected(client):
    user = _create_user(client)
    token = create_access_token(str(user.id))
    response = client.post(
        "/api/v1/projects",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Project'; DROP TABLE users; --", "description": "bad"},
    )
    assert response.status_code == 422


class _SanitizedPayload(SanitizedModel):
    name: str
    tags: list[str]
    optional: str | None = None


def test_sanitized_model_trims_and_escapes_strings():
    payload = _SanitizedPayload(name="  <b>ok</b>  ", tags=[" one ", "two"])
    assert payload.name == "&lt;b&gt;ok&lt;/b&gt;"
    assert payload.tags == ["one", "two"]


def test_sanitized_model_allows_none():
    payload = _SanitizedPayload(name="value", tags=["tag"], optional=None)
    assert payload.optional is None


def test_sanitized_model_enforces_length_limit():
    with pytest.raises(ValidationError):
        _SanitizedPayload(name="x" * 3000, tags=["tag"])


class _SkipSanitizePayload(SanitizedModel):
    init_data: str = Field(json_schema_extra={"skip_sanitize": True})


def test_skip_sanitize_bypasses_sanitization():
    payload = _SkipSanitizePayload(init_data="  <b>keep</b>  ")
    assert payload.init_data == "  <b>keep</b>  "
