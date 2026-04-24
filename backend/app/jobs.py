"""Job enqueueing helpers — the HTTP side of the Phase 3 async path.

Abstracted here so the FastAPI handlers stay thin and so tests can
swap the pool for a fake without monkeypatching Arq internals.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.config import settings


log = logging.getLogger("jobs")


class _PoolLike(Protocol):
    """The subset of :class:`arq.connections.ArqRedis` we actually call.

    Tests inject fakes that implement just this surface — no real Redis
    required for the enqueue round-trip.
    """
    async def enqueue_job(self, function: str, *args: Any, **kwargs: Any) -> Any: ...


# Module-level singleton so we don't open a new Redis connection per
# request. Lazily initialised on first use.
_pool: _PoolLike | None = None


async def get_pool() -> _PoolLike:
    global _pool
    if _pool is None:
        if not settings.redis_url:
            raise RuntimeError(
                "REDIS_URL is not configured. Async scans are disabled; "
                "use /scan for sync mode or set REDIS_URL in .env.",
            )
        _pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    return _pool


async def close_pool() -> None:
    """Release the shared pool. Called from the FastAPI lifespan so the
    app shuts down cleanly; tests also call it between cases."""
    global _pool
    if _pool is not None and isinstance(_pool, ArqRedis):
        await _pool.aclose()
    _pool = None


def set_pool_for_tests(pool: _PoolLike | None) -> None:
    """Install a fake pool — test-only. Avoids reaching into the module
    internals from each test."""
    global _pool
    _pool = pool


async def enqueue_scan(scan_id: str, request_payload: dict) -> None:
    """Push a scan job onto the worker queue. The scan row must already
    exist in ``queued`` status (see :func:`storage.create_pending_scan`).

    Uses ``_job_id=scan_id`` so a retry of the same scan doesn't spawn
    duplicates — Arq dedupes by job id.
    """
    pool = await get_pool()
    await pool.enqueue_job("run_scan_task", scan_id, request_payload, _job_id=scan_id)
    log.info("enqueued scan %s", scan_id)
