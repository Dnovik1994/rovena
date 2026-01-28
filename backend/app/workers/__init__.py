from celery import Celery

from app.core.settings import get_settings

settings = get_settings()

celery_app = Celery("app", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    broker_connection_retry_on_startup=True,
    broker_pool_limit=1,
    worker_concurrency=4,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)

__all__ = ["celery_app"]
