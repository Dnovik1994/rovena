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


def _make_admin_and_proxy(db):
    admin = User(
        telegram_id=3333,
        username="admin_err",
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
    return admin, proxy


def test_proxy_validate_connection_error(monkeypatch, client):
    with SessionLocal() as db:
        admin, proxy = _make_admin_and_proxy(db)

    token = create_access_token(str(admin.id))

    async def _raise_conn_error(pid):
        raise ConnectionError("connection refused")

    monkeypatch.setattr("app.api.v1.proxies.validate_proxy", _raise_conn_error)

    response = client.post(
        f"/api/v1/proxies/{proxy.id}/validate",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == status.HTTP_502_BAD_GATEWAY
    assert "Proxy validation failed" in response.json()["error"]["message"]


def test_proxy_validate_timeout_error(monkeypatch, client):
    with SessionLocal() as db:
        admin, proxy = _make_admin_and_proxy(db)

    token = create_access_token(str(admin.id))

    async def _raise_timeout(pid):
        raise TimeoutError("timed out")

    monkeypatch.setattr("app.api.v1.proxies.validate_proxy", _raise_timeout)

    response = client.post(
        f"/api/v1/proxies/{proxy.id}/validate",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == status.HTTP_502_BAD_GATEWAY
    assert "Proxy validation failed" in response.json()["error"]["message"]


def test_proxy_validate_os_error(monkeypatch, client):
    with SessionLocal() as db:
        admin, proxy = _make_admin_and_proxy(db)

    token = create_access_token(str(admin.id))

    async def _raise_os_error(pid):
        raise OSError("network unreachable")

    monkeypatch.setattr("app.api.v1.proxies.validate_proxy", _raise_os_error)

    response = client.post(
        f"/api/v1/proxies/{proxy.id}/validate",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == status.HTTP_502_BAD_GATEWAY
    assert "Proxy validation failed" in response.json()["error"]["message"]


def test_proxy_validate_unexpected_error(monkeypatch, client):
    with SessionLocal() as db:
        admin, proxy = _make_admin_and_proxy(db)

    token = create_access_token(str(admin.id))

    async def _raise_unexpected(pid):
        raise RuntimeError("something broke")

    monkeypatch.setattr("app.api.v1.proxies.validate_proxy", _raise_unexpected)

    response = client.post(
        f"/api/v1/proxies/{proxy.id}/validate",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert response.json()["error"]["message"] == "Internal error during proxy validation"
