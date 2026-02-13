import inspect
import logging
from typing import Any

from pyrogram import Client

from app.core.settings import get_settings
from app.clients.device_generator import generate_device_config
from app.models.proxy import Proxy
from app.services.session_crypto import decrypt_session

logger = logging.getLogger(__name__)
settings = get_settings()

# Collect valid Client.__init__ parameter names once at import time
_CLIENT_INIT_PARAMS: set[str] = set(inspect.signature(Client.__init__).parameters.keys()) - {"self"}


class TelegramClientDisabledError(RuntimeError):
    """Raised when Telegram client operations are disabled."""


def _build_proxy(proxy: Proxy | None) -> dict[str, Any] | None:
    if not proxy:
        return None
    proxy_config: dict[str, Any] = {
        "scheme": proxy.type,
        "hostname": proxy.host,
        "port": proxy.port,
    }
    if proxy.login:
        proxy_config["username"] = proxy.login
    if proxy.password:
        proxy_config["password"] = proxy.password
    return proxy_config


def build_pyrogram_client_kwargs(
    device_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build kwargs dict safe to pass to Client.__init__, filtering unknown params."""
    if not device_config:
        return {}
    allowed_device_keys = {"device_model", "system_version", "app_version", "lang_code", "system_lang_code"}
    raw = {k: device_config[k] for k in allowed_device_keys if device_config.get(k)}
    # Filter to only params that Client.__init__ actually accepts
    return {k: v for k, v in raw.items() if k in _CLIENT_INIT_PARAMS}


def _ensure_enabled() -> None:
    if not settings.telegram_client_enabled:
        raise TelegramClientDisabledError()
    if not settings.telegram_api_id or not settings.telegram_api_hash:
        raise RuntimeError("TELEGRAM_API_ID/HASH not configured")


def get_client(account: Any, proxy: Proxy | None = None) -> Client:
    """Create Pyrogram client for an existing Account (legacy model)."""
    _ensure_enabled()
    proxy_config = _build_proxy(proxy)
    device_config = getattr(account, "device_config", None) or generate_device_config()
    device_params = build_pyrogram_client_kwargs(device_config)

    logger.info(
        "Pyrogram client init | account_id=%s | proxy=%s",
        account.id,
        "enabled" if proxy_config else "none",
    )

    return Client(
        name=str(account.id),
        api_id=int(settings.telegram_api_id),
        api_hash=settings.telegram_api_hash,
        proxy=proxy_config,
        **device_params,
    )


def create_tg_account_client(
    account: Any,
    proxy: Proxy | None = None,
    *,
    phone: str | None = None,
    in_memory: bool = True,
    session_string: str | None = None,
) -> Client:
    """Create Pyrogram client for a TelegramAccount model.

    If *session_string* is provided explicitly (e.g. saved from a previous
    send_code step), it takes priority.  Otherwise falls back to the
    encrypted session stored on the account, then to phone-number auth.
    """
    _ensure_enabled()
    proxy_config = _build_proxy(proxy)
    device_config = getattr(account, "device_config", None) or generate_device_config()
    device_params = build_pyrogram_client_kwargs(device_config)

    resolved_session = session_string
    if not resolved_session and getattr(account, "session_encrypted", None):
        try:
            resolved_session = decrypt_session(account.session_encrypted)
        except Exception:
            logger.warning("Failed to decrypt session for account %s", account.id)

    logger.info(
        "TG account client init | account_id=%s | has_session=%s | proxy=%s",
        account.id,
        bool(resolved_session),
        "enabled" if proxy_config else "none",
    )

    kwargs: dict[str, Any] = {
        "api_id": int(settings.telegram_api_id),
        "api_hash": settings.telegram_api_hash,
        "proxy": proxy_config,
        "in_memory": in_memory,
        **device_params,
    }

    if resolved_session:
        kwargs["session_string"] = resolved_session
    elif phone:
        kwargs["phone_number"] = phone

    # Final safety filter — keep only params that Client.__init__ accepts.
    # "name" is passed explicitly below, so remove it from kwargs to avoid
    # TypeError("got multiple values for keyword argument 'name'").
    kwargs.pop("name", None)
    kwargs = {k: v for k, v in kwargs.items() if k in _CLIENT_INIT_PARAMS}
    return Client(name=f"tg-{account.id}", **kwargs)


def get_validator_client(proxy: Proxy) -> Client:
    _ensure_enabled()
    proxy_config = _build_proxy(proxy)
    return Client(
        name=f"validator-{proxy.id}",
        api_id=int(settings.telegram_api_id),
        api_hash=settings.telegram_api_hash,
        proxy=proxy_config,
    )
