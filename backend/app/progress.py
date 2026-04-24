"""Progress reporter for long-running scans.

A tiny pub/sub: the scanner calls ``reporter.emit(stage, message, data)`` as
it passes through pipeline stages; the HTTP handler ``async for event in
reporter`` consumes them and pushes them over SSE.

Why not just log? Logs go to the server console — users staring at a
scanning spinner don't see them. This forwards the same events to a queue
that ends up in the browser as Server-Sent Events.

Why not BackgroundTasks / Celery? Overkill for an in-process dev server. If
we ever outgrow one worker, this module is the single seam to replace.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, AsyncIterator, Literal


Stage = Literal[
    "started",
    "crawling",
    "cookie_analysis",
    "policy_extraction",
    "ai_analysis",
    "form_analysis",
    "scoring",
    "done",
    "error",
]


class ProgressEvent:
    __slots__ = ("stage", "message", "data", "ts")

    def __init__(self, stage: Stage, message: str, data: dict[str, Any] | None = None):
        self.stage = stage
        self.message = message
        self.data = data or {}
        self.ts = time.time()

    def to_sse(self) -> str:
        """Format as a single Server-Sent Event frame."""
        payload = json.dumps({
            "stage": self.stage,
            "message": self.message,
            "data": self.data,
            "ts": self.ts,
        })
        return f"event: progress\ndata: {payload}\n\n"


class ProgressReporter:
    """Fan-in queue for progress events.

    Usage:

        reporter = ProgressReporter()
        asyncio.create_task(scanner.run_scan(req, progress=reporter))
        async for event in reporter:
            yield event.to_sse()
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue[ProgressEvent | None] = asyncio.Queue()
        self._closed = False

    def emit(self, stage: Stage, message: str, data: dict[str, Any] | None = None) -> None:
        if self._closed:
            return
        self._queue.put_nowait(ProgressEvent(stage, message, data))

    def close(self) -> None:
        """Signal end of stream. Safe to call multiple times."""
        if self._closed:
            return
        self._closed = True
        # None is the sentinel that makes __aiter__ stop.
        self._queue.put_nowait(None)

    async def __aiter__(self) -> AsyncIterator[ProgressEvent]:
        while True:
            event = await self._queue.get()
            if event is None:
                return
            yield event


class NoopReporter(ProgressReporter):
    """Used by the batch /scan endpoint where nobody listens."""

    def emit(self, stage: Stage, message: str, data: dict[str, Any] | None = None) -> None:
        return


class RedisProgressReporter(ProgressReporter):
    """Progress reporter for the Phase-3 worker path.

    The scanner keeps calling ``emit`` synchronously from anywhere in
    the pipeline (that's the contract — not every call site is an
    async function). We enqueue locally, then a background drainer
    task pulls events off the queue and ``publish_progress`` forwards
    each one to Redis.

    Why the queue + drainer instead of fire-and-forget
    ``create_task(publish())`` on every emit: ordering. The HTTP
    subscriber relies on events arriving in the sequence the scanner
    produced them; two concurrent tasks don't promise that.
    """

    def __init__(self, pool: Any, scan_id: str) -> None:
        super().__init__()
        self._pool = pool
        self._scan_id = scan_id

    async def run(self) -> None:
        """Drain the in-memory queue and republish to Redis until
        :meth:`close` is called. Called once per reporter, typically
        scheduled as an :func:`asyncio.create_task` and awaited at the
        end of the scan."""
        # Imported lazily to keep a plain ProgressReporter dep-free.
        from app.progress_bus import publish_progress

        async for event in self:
            await publish_progress(self._pool, self._scan_id, {
                "stage":   event.stage,
                "message": event.message,
                "data":    event.data,
                "ts":      event.ts,
            })
