def get_client(*args, **kwargs):
    from app.clients.telegram_client import get_client as _get_client

    return _get_client(*args, **kwargs)

__all__ = ["get_client"]
