import logging
from typing import Any

from pyrogram import Client

from app.core.settings import get_settings
from app.clients.device_generator import generate_device_config
from app.models.account import Account
from app.models.proxy import Proxy

logger = logging.getLogger(__name__)
settings = get_settings()


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


def get_client(account: Account, proxy: Proxy | None = None) -> Client:
    if not settings.telegram_client_enabled:
        raise RuntimeError("Telegram client is disabled")
    if not settings.telegram_api_id or not settings.telegram_api_hash:
        raise RuntimeError("TELEGRAM_API_ID/HASH not configured")

    proxy_config = _build_proxy(proxy)
    device_config = account.device_config or generate_device_config()
    device_params = {
        key: device_config.get(key)
        for key in ["device_model", "system_version", "app_version", "lang_code", "system_lang_code"]
        if device_config.get(key)
    }

    proxy_status = "enabled" if proxy_config else "none"
    logger.info(
        "Pyrogram client init | account_id=%s | proxy=%s",
        account.id,
        proxy_status,
    )

    try:
        return Client(
            name=str(account.id),
            api_id=int(settings.telegram_api_id),
            api_hash=settings.telegram_api_hash,
            proxy=proxy_config,
            **device_params,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to initialize Pyrogram client", extra={"error": str(exc)})
        raise


def get_validator_client(proxy: Proxy) -> Client:
    if not settings.telegram_client_enabled:
        raise RuntimeError("Telegram client is disabled")
    if not settings.telegram_api_id or not settings.telegram_api_hash:
        raise RuntimeError("TELEGRAM_API_ID/HASH not configured")

    proxy_config = _build_proxy(proxy)
    try:
        return Client(
            name=f"validator-{proxy.id}",
            api_id=int(settings.telegram_api_id),
            api_hash=settings.telegram_api_hash,
            proxy=proxy_config,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to initialize validator client", extra={"error": str(exc)})
        raise
