import logging
import time
from datetime import datetime, timezone

from app.clients.telegram_client import get_validator_client
from app.core.settings import get_settings
from app.core.database import SessionLocal
from app.models.proxy import Proxy, ProxyStatus

logger = logging.getLogger(__name__)
settings = get_settings()


async def validate_proxy(proxy_id: int) -> Proxy | None:
    if not settings.telegram_client_enabled:
        logger.info("Telegram client disabled; proxy validation skipped", extra={"proxy_id": proxy_id})
        return None
    with SessionLocal() as db:
        proxy = db.get(Proxy, proxy_id)
        if not proxy:
            logger.info("Proxy not found", extra={"proxy_id": proxy_id})
            return None

        client = get_validator_client(proxy)
        start = time.monotonic()
        try:
            async with client:
                await client.get_me()
            proxy.status = ProxyStatus.active
        except Exception as exc:  # noqa: BLE001
            proxy.status = ProxyStatus.error
            logger.info("Proxy validation failed", extra={"proxy_id": proxy_id, "error": str(exc)})
        finally:
            proxy.last_check = datetime.now(timezone.utc)
            proxy.latency_ms = int((time.monotonic() - start) * 1000)
            db.commit()
            db.refresh(proxy)
            return proxy
