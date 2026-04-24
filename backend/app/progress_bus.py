"""Redis pub/sub wrapper for background-scan progress events.

Phase 3 put the scanner into an Arq worker — which took progress
reporting offline: the old ``/scan/stream`` SSE reads an in-process
``asyncio.Queue`` and has no way to see events that happen in a
different process. This module bridges the two by publishing every
event to a per-scan Redis channel so the HTTP side can subscribe.

Kept tiny and protocol-shaped so tests can inject a fake pool without
pulling in fakeredis. The production call sites are all one-liners.
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Protocol


log = logging.getLogger("progress_bus")


def progress_channel(scan_id: str) -> str:
    """Canonical channel name. Scoped per-scan so subscribers only see
    events for the scan they're watching."""
    return f"scan:progress:{scan_id}"


class _Publisher(Protocol):
    async def publish(self, channel: str, message: Any) -> Any: ...


class _Subscribable(Protocol):
    def pubsub(self) -> Any: ...


async def publish_progress(
    pool: _Publisher,
    scan_id: str,
    event: dict[str, Any],
) -> None:
    """Serialise ``event`` and push it to the scan's progress channel."""
    await pool.publish(progress_channel(scan_id), json.dumps(event))


async def subscribe_progress(
    pool: _Subscribable,
    scan_id: str,
) -> AsyncIterator[dict[str, Any]]:
    """Async iterator over published events for ``scan_id``.

    Yields every message until the caller breaks out (typically on a
    terminal ``stage in {"done","error"}`` event). Handles subscribe /
    unsubscribe lifecycle so callers can just ``async for`` over it.
    """
    channel = progress_channel(scan_id)
    pubsub = pool.pubsub()
    await pubsub.subscribe(channel)
    try:
        async for message in pubsub.listen():
            # redis-py delivers a "subscribe" confirmation first; skip it.
            if message.get("type") != "message":
                continue
            raw = message.get("data")
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            if not raw:
                continue
            try:
                yield json.loads(raw)
            except json.JSONDecodeError:
                log.warning("dropped malformed progress message: %r", raw)
                continue
    finally:
        try:
            await pubsub.unsubscribe(channel)
        finally:
            # `aclose` is the modern API; `close` is the legacy fallback.
            closer = getattr(pubsub, "aclose", None) or getattr(pubsub, "close", None)
            if closer is not None:
                result = closer()
                if hasattr(result, "__await__"):
                    await result
