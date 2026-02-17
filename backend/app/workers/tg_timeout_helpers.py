"""Async timeout helpers for Pyrogram I/O operations.

Celery solo pool + asyncio.run() means SoftTimeLimitExceeded cannot
interrupt a blocked event loop.  Every Pyrogram coroutine and async
generator must have an explicit timeout so the event loop stays
responsive and Celery's hard time_limit can eventually kill the task.
"""

import asyncio
import logging
from typing import List, TypeVar

T = TypeVar("T")
logger = logging.getLogger(__name__)


async def collect_async_gen(
    gen,
    *,
    timeout: float = 120,
    max_items: int = 50_000,
) -> List:
    """Consume an async generator with an overall timeout and item cap.

    Returns whatever items were collected before the timeout or cap was
    reached.  On timeout the partial list is returned (no exception).
    """
    items: list = []
    try:
        async with asyncio.timeout(timeout):
            async for item in gen:
                items.append(item)
                if len(items) >= max_items:
                    break
    except TimeoutError:
        logger.warning(
            "collect_async_gen timed out after %.0fs, collected %d items",
            timeout,
            len(items),
        )
    return items


async def safe_call(coro, *, timeout: float = 30, default=None):
    """Await a coroutine with a timeout; return *default* on timeout."""
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning("safe_call timed out after %.0fs", timeout)
        return default
