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


celery_pool = os.getenv("CELERY_POOL", "solo")
if celery_pool == "solo":
    celery_concurrency = int(os.getenv("CELERY_CONCURRENCY", "1"))
else:
    celery_concurrency = int(os.getenv("CELERY_CONCURRENCY", "4"))

celery_app = Celery(
    "app",
    broker=settings.redis_url,
    backend=settings.redis_url,
    # Explicit list of every module that contains @celery_app.task definitions.
    # autodiscover_tasks only finds modules named "tasks.py" by default,
    # so non-standard names like tg_auth_tasks.py were silently skipped.
    include=[
        "app.workers.tasks",
        "app.workers.tg_auth_unified_tasks",
        "app.workers.tg_auth_password_tasks",
        "app.workers.tg_auth_verify_tasks",
        "app.workers.tg_warming_tasks",
        "app.workers.warming_throttle",
        "app.workers.tg_campaign_tasks",
        "app.workers.tg_sync_tasks",
        "app.workers.tg_invite_tasks",
        "app.workers.health_tasks",
    ],
)
celery_app.conf.update(
    broker_connection_retry_on_startup=True,
    broker_pool_limit=10,
    broker_connection_timeout=10,
    worker_concurrency=celery_concurrency,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_enable_remote_control=True,
    broker_transport_options={
        "fanout_prefix": True,
        "fanout_patterns": True,
        "socket_connect_timeout": 5,
        "socket_timeout": 5,
        "retry_on_timeout": False,
    },
    beat_schedule={
        "check-tg-cooldowns-every-2-min": {
            "task": "app.workers.tg_warming_tasks.check_tg_cooldowns",
            "schedule": 120.0,
        },
        "resume-tg-warming-every-5-min": {
            "task": "app.workers.tg_warming_tasks.resume_tg_warming",
            "schedule": 300.0,
        },
        "update-warming-throttle-every-5-min": {
            "task": "app.workers.warming_throttle.update_warming_throttle",
            "schedule": 300.0,
        },
        "check-system-health-every-5-min": {
            "task": "app.workers.health_tasks.check_system_health",
            "schedule": 300.0,
        },
    },
)
logger.info("Task queue ready")

__all__ = [
    "CELERY_HEARTBEAT_INTERVAL_SECONDS",
    "CELERY_HEARTBEAT_KEY_PREFIX",
    "CELERY_HEARTBEAT_TTL_SECONDS",
    "celery_app",
]
