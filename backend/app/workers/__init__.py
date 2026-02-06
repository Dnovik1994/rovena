import logging
import os
import socket
import threading
import time

from celery import Celery
from celery.signals import worker_ready, worker_shutdown
from redis import Redis

from app.core.settings import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

CELERY_HEARTBEAT_INTERVAL_SECONDS = 5
CELERY_HEARTBEAT_TTL_SECONDS = 15
CELERY_HEARTBEAT_KEY_PREFIX = "celery:worker:heartbeat"

_heartbeat_stop_event = threading.Event()
_heartbeat_thread: threading.Thread | None = None


def _get_worker_hostname() -> str:
    return os.environ.get("HOSTNAME") or socket.gethostname()


def _heartbeat_loop(redis_url: str, hostname: str) -> None:
    client = Redis.from_url(redis_url)
    key = f"{CELERY_HEARTBEAT_KEY_PREFIX}:{hostname}"
    while not _heartbeat_stop_event.wait(CELERY_HEARTBEAT_INTERVAL_SECONDS):
        try:
            client.set(key, time.time(), ex=CELERY_HEARTBEAT_TTL_SECONDS)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to write celery worker heartbeat")


@worker_ready.connect
def _start_heartbeat(**_: object) -> None:
    global _heartbeat_thread
    if not settings.redis_url:
        return
    if _heartbeat_thread and _heartbeat_thread.is_alive():
        return
    _heartbeat_stop_event.clear()
    hostname = _get_worker_hostname()
    _heartbeat_thread = threading.Thread(
        target=_heartbeat_loop,
        args=(settings.redis_url, hostname),
        name="celery-heartbeat",
        daemon=True,
    )
    _heartbeat_thread.start()
    logger.info("Celery worker heartbeat started", extra={"hostname": hostname})


@worker_shutdown.connect
def _stop_heartbeat(**_: object) -> None:
    _heartbeat_stop_event.set()


celery_app = Celery("app", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    broker_connection_retry_on_startup=True,
    broker_pool_limit=1,
    worker_concurrency=4,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_enable_remote_control=True,
    broker_transport_options={
        "fanout_prefix": True,
        "fanout_patterns": True,
    },
)
celery_app.conf.broker_connection_retry_on_startup = True
logger.info("Task queue ready")

__all__ = [
    "CELERY_HEARTBEAT_INTERVAL_SECONDS",
    "CELERY_HEARTBEAT_KEY_PREFIX",
    "CELERY_HEARTBEAT_TTL_SECONDS",
    "celery_app",
]
