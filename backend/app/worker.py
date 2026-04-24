"""Arq worker — runs scan jobs outside the HTTP request path.

Start with:

    arq app.worker.WorkerSettings

REDIS_URL must be set (see .env.example). The worker process is fully
independent from the FastAPI process: you can run many workers against
the same Redis and they'll cooperatively consume the queue.

The task (:func:`run_scan_task`) is deliberately thin — it transitions
the DB row, delegates to the existing :func:`app.scanner.run_scan`,
then marks the row ``done`` / ``failed``. All domain logic stays in
``scanner.py``; this module just translates between Arq's ctx model and
our storage.

Phase 3b: the task now wires a :class:`RedisProgressReporter` into the
scanner so live progress events are published to a per-scan Redis
channel. The HTTP ``GET /scan/jobs/{id}/events`` endpoint subscribes
there.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time

from arq.connections import RedisSettings
from arq.cron import cron

from app.config import settings
from app.models import ScanRequest
from app.progress import RedisProgressReporter
from app.progress_bus import publish_progress
from app.retention import run_retention_sweep
from app.scanner import run_scan
from app.storage import mark_done, mark_failed, mark_running


log = logging.getLogger("worker")


# Windows + Playwright needs the Proactor event loop (see run_dev.py for
# the FastAPI side). The arq CLI imports this module *before* creating
# the loop, so we pin the policy here for symmetry.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


def _redis_settings() -> RedisSettings:
    """Parse ``redis_url`` into an :class:`arq.connections.RedisSettings`.

    Arq defaults to localhost:6379. A ``None`` / empty setting means the
    operator didn't enable async mode; we still return defaults so that
    starting the worker without config fails loudly with a Redis
    connection error rather than a cryptic import-time crash.
    """
    url = settings.redis_url or "redis://localhost:6379"
    return RedisSettings.from_dsn(url)


async def retention_sweep_task(ctx: dict) -> dict:
    """Daily cron — enforces docs/retention-policy.md. Returns a dict
    so the Arq result log has useful counts if you go look."""
    result = await run_retention_sweep()
    return {
        "scans_deleted":        result.scans_deleted,
        "audit_deleted":        result.audit_deleted,
        "orphan_scans_deleted": result.orphan_scans_deleted,
    }


async def run_scan_task(ctx: dict, scan_id: str, request_payload: dict) -> None:
    """Background scan execution. ``scan_id`` was pre-allocated by the
    HTTP handler via :func:`create_pending_scan`."""
    pool = ctx.get("redis")
    reporter = RedisProgressReporter(pool, scan_id) if pool is not None else None
    drainer = asyncio.create_task(reporter.run()) if reporter is not None else None

    await mark_running(scan_id)
    try:
        req = ScanRequest.model_validate(request_payload)
        result = await run_scan(req, progress=reporter) if reporter else await run_scan(req)
        await mark_done(scan_id, result)
        log.info("scan %s completed score=%d", scan_id, result.risk.score)
        if pool is not None:
            # Terminal event so the SSE subscriber knows to close even
            # if the scanner didn't emit its own "done" event. Sent
            # directly (bypassing the drainer) so close() below doesn't
            # race it.
            await publish_progress(pool, scan_id, {
                "stage":   "done",
                "message": "Scan complete",
                "data":    {"score": result.risk.score, "scan_id": scan_id},
                "ts":      time.time(),
            })
    except Exception as e:   # noqa: BLE001 — we want anything the scanner raises
        log.exception("scan %s failed", scan_id)
        err = f"{type(e).__name__}: {e}"
        await mark_failed(scan_id, err)
        if pool is not None:
            await publish_progress(pool, scan_id, {
                "stage":   "error",
                "message": f"Scan failed: {err}",
                "data":    {"error": err},
                "ts":      time.time(),
            })
    finally:
        if reporter is not None:
            reporter.close()
        if drainer is not None:
            await drainer


class WorkerSettings:
    """Arq entry point — `arq app.worker.WorkerSettings`."""
    functions = [run_scan_task, retention_sweep_task]
    redis_settings = _redis_settings()
    # A scan can easily hit 60-90s with Playwright + AI; add headroom.
    job_timeout = 180
    # Keep the result in Redis long enough that a late poll can still
    # see completion before falling back to the DB.
    keep_result = 600
    # One browser at a time per worker — Chromium is heavy and two
    # concurrent launches on a small VM will OOM. Scale horizontally by
    # running more worker processes, not by raising this.
    max_jobs = 1
    # Daily retention sweep at 03:30 UTC. That's a low-traffic window
    # globally and gives customer-visible cron noise a predictable
    # boundary. Arq distributes cron across multiple worker processes:
    # only ONE worker actually runs a given cron firing, even if you
    # scale horizontally.
    cron_jobs = [
        cron(
            retention_sweep_task,
            name="retention-sweep",
            hour={3}, minute={30},
            run_at_startup=False,
        ),
    ]
