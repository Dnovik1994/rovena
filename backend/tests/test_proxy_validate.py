from fastapi import status

from app.core.database import SessionLocal
from app.core.security import create_access_token
from app.models.proxy import Proxy, ProxyStatus, ProxyType
from app.models.user import User, UserRole


class DummyClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get_me(self):
        return True


def test_proxy_validate(monkeypatch, client):
    with SessionLocal() as db:
        admin = User(
            telegram_id=2222,
            username="admin",
            is_admin=True,
            role=UserRole.admin,
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)

        proxy = Proxy(
            host="127.0.0.1",
            port=1080,
            type=ProxyType.socks5,
            status=ProxyStatus.inactive,
        )
        db.add(proxy)
        db.commit()
        db.refresh(proxy)

    token = create_access_token(str(admin.id))

    monkeypatch.setattr(
        "app.services.proxy_validation.get_validator_client", lambda *_args, **_kwargs: DummyClient()
    )

    response = client.post(
        f"/api/v1/proxies/{proxy.id}/validate",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["status"] == "active"
