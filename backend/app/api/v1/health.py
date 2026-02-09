import asyncio
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi import status as http_status
from fastapi.responses import JSONResponse
from redis import Redis
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.cache import ping as cache_ping
from app.core.database import get_db
from app.core.settings import get_settings
from app.core.version import APP_VERSION
from app.workers import CELERY_HEARTBEAT_KEY_PREFIX, CELERY_HEARTBEAT_TTL_SECONDS

router = APIRouter()
settings = get_settings()


def _derive_status(checks: dict[str, dict[str, object]]) -> str:
    statuses = [check["status"] for check in checks.values()]
    if "fail" in statuses:
        return "fail"
    if "warn" in statuses:
        return "warn"
    return "ok"


async def _run_with_timeout(func, timeout_seconds: float, *args, **kwargs):
    return await asyncio.wait_for(asyncio.to_thread(func, *args, **kwargs), timeout=timeout_seconds)


def _read_worker_heartbeat(redis_client: Redis) -> tuple[str | None, bytes | None]:
    heartbeat_key = next(
        redis_client.scan_iter(match=f"{CELERY_HEARTBEAT_KEY_PREFIX}:*"),
        None,
    )
    if not heartbeat_key:
        return None, None
    value = redis_client.get(heartbeat_key)
    key_str = heartbeat_key.decode() if isinstance(heartbeat_key, bytes) else str(heartbeat_key)
    return key_str, value


@router.get("/health")
async def health_check(db: Session = Depends(get_db)) -> JSONResponse:
    checks: dict[str, dict[str, object]] = {}
    timeout_seconds = settings.health_check_timeout_seconds

    db_started = time.monotonic()
    try:
        await _run_with_timeout(db.execute, timeout_seconds, text("SELECT 1"))
        db_latency_ms = int((time.monotonic() - db_started) * 1000)
        db_status = "ok" if db_latency_ms <= timeout_seconds * 1000 else "warn"
        checks["database"] = {"status": db_status, "latency_ms": db_latency_ms}
    except asyncio.TimeoutError:
        checks["database"] = {"status": "fail", "error": "timeout"}
    except Exception as exc:  # noqa: BLE001
        checks["database"] = {"status": "fail", "error": str(exc)}

    if settings.redis_url:
        try:
            redis_started = time.monotonic()
            redis_ok = await asyncio.wait_for(cache_ping(), timeout=timeout_seconds)
            redis_latency_ms = int((time.monotonic() - redis_started) * 1000)
            checks["redis"] = {
                "status": "ok" if redis_ok else "fail",
                "latency_ms": redis_latency_ms,
            }
        except asyncio.TimeoutError:
            checks["redis"] = {"status": "fail", "error": "timeout"}
        except Exception as exc:  # noqa: BLE001
            checks["redis"] = {"status": "fail", "error": str(exc)}
    else:
        checks["redis"] = {"status": "warn", "detail": "disabled"}

    if settings.redis_url:
        try:
            redis_client = await _run_with_timeout(Redis.from_url, timeout_seconds, settings.redis_url)
            queue_length = await _run_with_timeout(redis_client.llen, timeout_seconds, "celery")
            queue_status = "ok"
            if queue_length >= settings.health_queue_warn_threshold:
                queue_status = "warn"
            checks["celery_queue"] = {"status": queue_status, "queue_length": queue_length}
        except asyncio.TimeoutError:
            checks["celery_queue"] = {"status": "fail", "error": "timeout"}
        except Exception as exc:  # noqa: BLE001
            checks["celery_queue"] = {"status": "fail", "error": str(exc)}
    else:
        checks["celery_queue"] = {"status": "warn", "detail": "disabled"}

    if settings.redis_url:
        try:
            redis_client = await _run_with_timeout(Redis.from_url, timeout_seconds, settings.redis_url)
            heartbeat_key, heartbeat_value = await _run_with_timeout(
                _read_worker_heartbeat,
                timeout_seconds,
                redis_client,
            )
            if not heartbeat_key or not heartbeat_value:
                checks["celery_worker"] = {"status": "warn", "error": "missing_heartbeat"}
            else:
                try:
                    heartbeat_ts = float(heartbeat_value)
                    age_seconds = max(0.0, time.time() - heartbeat_ts)
                    worker_status = (
                        "ok" if age_seconds <= CELERY_HEARTBEAT_TTL_SECONDS else "warn"
                    )
                    checks["celery_worker"] = {
                        "status": worker_status,
                        "heartbeat_key": heartbeat_key,
                        "age_seconds": int(age_seconds),
                    }
                except (TypeError, ValueError):
                    checks["celery_worker"] = {
                        "status": "warn",
                        "error": "invalid_heartbeat",
                        "heartbeat_key": heartbeat_key,
                    }
        except asyncio.TimeoutError:
            checks["celery_worker"] = {"status": "warn", "error": "timeout"}
        except Exception as exc:  # noqa: BLE001
            checks["celery_worker"] = {"status": "warn", "error": str(exc)}
    else:
        checks["celery_worker"] = {"status": "warn", "detail": "disabled"}

    status_str = _derive_status(checks)
    response_payload = {
        "status": status_str,
        "checks": checks,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": APP_VERSION,
    }
    http_status_code = (
        http_status.HTTP_503_SERVICE_UNAVAILABLE
        if status_str == "fail"
        else http_status.HTTP_200_OK
    )
    return JSONResponse(content=response_payload, status_code=http_status_code)
