"""Tests for Phase 3b progress Pub/Sub + SSE.

No real Redis. A ``_FakePool`` records publishes and routes them to a
``_FakePubSub`` so subscribe_progress can read them back. That's enough
to exercise every behaviour the production code relies on:

  - channel name scoping (one scan per subscriber, no cross-talk)
  - the drainer publishes in the order the scanner emits
  - subscribe cleans up on generator close
  - the SSE endpoint handles the "already finished" snapshot path
  - terminal events (done / error) make the SSE stream close
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app import db as db_module
from app.db_models import Base
from app.jobs import set_pool_for_tests
from app.models import (
    ContactChannelsReport, CookieReport, CrawlResult, FormReport,
    NetworkResult, PrivacyAnalysis, RiskScore, ScanResponse,
    ThirdPartyWidgetsReport,
)
from app.progress import RedisProgressReporter
from app.progress_bus import (
    progress_channel,
    publish_progress,
    subscribe_progress,
)
from app.storage import (
    create_pending_scan,
    mark_done,
    mark_failed,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class _FakePubSub:
    """Behaves enough like ``redis.asyncio.client.PubSub`` for the
    subscribe_progress helper: subscribe / listen / unsubscribe."""

    def __init__(self, pool: "_FakePool"):
        self._pool = pool
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._channels: list[str] = []
        self._closed = False

    async def subscribe(self, channel: str) -> None:
        self._channels.append(channel)
        self._pool._subscribers.setdefault(channel, []).append(self._queue)
        # Mirror real behaviour: deliver a "subscribe" control message first.
        await self._queue.put({"type": "subscribe", "channel": channel})

    async def unsubscribe(self, channel: str) -> None:
        subs = self._pool._subscribers.get(channel, [])
        if self._queue in subs:
            subs.remove(self._queue)

    async def aclose(self) -> None:
        # Sentinel so any in-flight `listen()` can break out of its loop.
        self._closed = True
        await self._queue.put({"type": "__closed"})

    async def listen(self):
        while not self._closed:
            msg = await self._queue.get()
            if msg.get("type") == "__closed":
                return
            yield msg


class _FakePool:
    """In-memory stand-in for ``arq.connections.ArqRedis``. Supports the
    two methods the progress_bus actually calls: ``publish`` (fanout to
    all subscribers of the channel) and ``pubsub()`` (build a new
    subscription handle)."""

    def __init__(self):
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
        self.published: list[tuple[str, str]] = []  # (channel, data)

    async def publish(self, channel: str, message: Any) -> int:
        self.published.append((channel, message))
        queues = self._subscribers.get(channel, [])
        for q in queues:
            await q.put({"type": "message", "channel": channel, "data": message})
        return len(queues)

    def pubsub(self) -> _FakePubSub:
        return _FakePubSub(self)

    # Arq also needs `enqueue_job` on the pool; keep it here so tests
    # that reuse the fake for both paths (jobs + progress) don't break.
    async def enqueue_job(self, function: str, *args: Any, **kwargs: Any):
        return None


# ---------------------------------------------------------------------------
# Unit tests: publish_progress + subscribe_progress
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestProgressBus:
    async def test_publish_then_subscribe_roundtrips_event(self):
        pool = _FakePool()

        async def reader():
            got: list[dict] = []
            async for ev in subscribe_progress(pool, "scan-1"):
                got.append(ev)
                if len(got) == 2:
                    return got
            return got

        task = asyncio.create_task(reader())
        await asyncio.sleep(0)  # let the subscriber register

        await publish_progress(pool, "scan-1", {"stage": "crawling", "message": "start"})
        await publish_progress(pool, "scan-1", {"stage": "scoring",  "message": "done"})

        got = await asyncio.wait_for(task, timeout=2.0)
        assert got == [
            {"stage": "crawling", "message": "start"},
            {"stage": "scoring",  "message": "done"},
        ]

    async def test_subscriptions_are_scan_scoped(self):
        # Publishing to scan A must NOT reach scan B's subscriber.
        pool = _FakePool()

        async def reader(scan_id: str):
            async for ev in subscribe_progress(pool, scan_id):
                return ev
            return None

        task_b = asyncio.create_task(reader("B"))
        await asyncio.sleep(0)
        await publish_progress(pool, "A", {"stage": "crawling", "message": "hi"})
        # After a tick, B should still be waiting. Cancel to assert.
        await asyncio.sleep(0.05)
        assert not task_b.done()
        task_b.cancel()
        try:
            await task_b
        except asyncio.CancelledError:
            pass

    async def test_malformed_message_is_dropped(self):
        # A bad JSON blob must not abort the subscriber.
        pool = _FakePool()

        async def reader():
            async for ev in subscribe_progress(pool, "scan"):
                return ev
            return None

        task = asyncio.create_task(reader())
        await asyncio.sleep(0)

        # Inject malformed + good messages.
        for q in pool._subscribers[progress_channel("scan")]:
            await q.put({"type": "message", "channel": progress_channel("scan"),
                         "data": "not-json{{{"})
            await q.put({"type": "message", "channel": progress_channel("scan"),
                         "data": json.dumps({"stage": "scoring", "message": "ok"})})

        got = await asyncio.wait_for(task, timeout=2.0)
        assert got == {"stage": "scoring", "message": "ok"}

    async def test_channel_name_is_deterministic(self):
        assert progress_channel("abc123") == "scan:progress:abc123"


# ---------------------------------------------------------------------------
# RedisProgressReporter: drainer preserves emit order
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestRedisProgressReporter:
    async def test_drainer_publishes_in_emit_order(self):
        pool = _FakePool()
        reporter = RedisProgressReporter(pool, "scan-x")
        task = asyncio.create_task(reporter.run())

        reporter.emit("started",  "Starting scan")
        reporter.emit("crawling", "BFS crawl")
        reporter.emit("scoring",  "Computing risk")
        reporter.close()
        await asyncio.wait_for(task, timeout=2.0)

        # All three messages landed on the right channel, in order.
        assert [c for c, _ in pool.published] == [
            progress_channel("scan-x"),
            progress_channel("scan-x"),
            progress_channel("scan-x"),
        ]
        stages = [json.loads(data)["stage"] for _, data in pool.published]
        assert stages == ["started", "crawling", "scoring"]

    async def test_emit_after_close_is_noop(self):
        pool = _FakePool()
        reporter = RedisProgressReporter(pool, "scan-x")
        task = asyncio.create_task(reporter.run())
        reporter.close()
        await asyncio.wait_for(task, timeout=2.0)
        reporter.emit("crawling", "too late")
        assert pool.published == []


# ---------------------------------------------------------------------------
# SSE endpoint
# ---------------------------------------------------------------------------

def _fake_result() -> ScanResponse:
    return ScanResponse(
        target="https://example.com/",
        risk=RiskScore(score=80, rating="low", weighted_score=80,
                       sub_scores=[], applied_caps=[], recommendations=[]),
        crawl=CrawlResult(start_url="https://example.com/", pages=[],
                          privacy_policy_url=None, imprint_url=None),
        network=NetworkResult(requests=[], data_flow=[]),
        cookies=CookieReport(cookies=[], storage=[], summary={}),
        privacy_analysis=PrivacyAnalysis(
            provider="none", model=None, policy_url=None, summary="",
            issues=[], coverage=None, compliance_score=50,
            error="no_provider_configured",
        ),
        forms=FormReport(forms=[], summary={"total_forms": 0}),
        contact_channels=ContactChannelsReport(channels=[], summary={}),
        widgets=ThirdPartyWidgetsReport(widgets=[], summary={}),
    )


@pytest_asyncio.fixture
async def app_with_db(monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.security.rate_limit import auth_rate_limiter, scan_rate_limiter

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "_engine", engine)
    monkeypatch.setattr(db_module, "_SessionLocal", SessionLocal)
    scan_rate_limiter.reset()
    auth_rate_limiter.reset()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    pool = _FakePool()
    set_pool_for_tests(pool)
    # The jobs helper only opens a real pool if REDIS_URL is set AND
    # the singleton is empty; we pre-fill it with the fake so the
    # "no redis configured" branch doesn't fire in these tests.
    from app.config import settings as cfg
    monkeypatch.setattr(cfg, "redis_url", "redis://test")

    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, pool

    set_pool_for_tests(None)
    await engine.dispose()


async def _signup_and_org(client) -> tuple[str, str]:
    from sqlalchemy import select
    from app.db import session_scope
    from app.db_models import Membership

    r = await client.post("/auth/signup", json={
        "email": "alice@example.com", "password": "long-enough-password",
    })
    token = r.json()["access_token"]
    user_id = r.json()["user"]["id"]
    async with session_scope() as session:
        org_id = (await session.execute(
            select(Membership.organization_id).where(Membership.user_id == user_id)
        )).scalar_one()
    return token, org_id


def _parse_sse(raw: str) -> list[dict]:
    """Minimal SSE parser — enough for our fixed-format events."""
    out: list[dict] = []
    for frame in raw.split("\n\n"):
        frame = frame.strip()
        if not frame:
            continue
        data_lines = [line[5:].lstrip() for line in frame.split("\n")
                      if line.startswith("data:")]
        if data_lines:
            out.append(json.loads("\n".join(data_lines)))
    return out


@pytest.mark.asyncio
class TestSseEndpoint:
    async def test_already_done_scan_emits_snapshot_and_closes(self, app_with_db):
        client, _pool = app_with_db
        token, org_id = await _signup_and_org(client)

        scan_id, _ = await create_pending_scan(
            url="https://example.com/", organization_id=org_id,
        )
        await mark_done(scan_id, _fake_result())

        r = await client.get(
            f"/scan/jobs/{scan_id}/events",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        events = _parse_sse(r.text)
        assert len(events) == 1
        assert events[0]["stage"] == "done"

    async def test_already_failed_scan_emits_error_snapshot(self, app_with_db):
        client, _pool = app_with_db
        token, org_id = await _signup_and_org(client)

        scan_id, _ = await create_pending_scan(
            url="https://example.com/", organization_id=org_id,
        )
        await mark_failed(scan_id, "boom")

        r = await client.get(
            f"/scan/jobs/{scan_id}/events",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        events = _parse_sse(r.text)
        assert len(events) == 1
        assert events[0]["stage"] == "error"

    async def test_live_scan_streams_until_terminal(self, app_with_db):
        # Queued scan + publish progress events including a final done.
        # SSE stream must yield all progress events in order then close.
        client, pool = app_with_db
        token, org_id = await _signup_and_org(client)

        scan_id, _ = await create_pending_scan(
            url="https://example.com/", organization_id=org_id,
        )

        # Kick off the SSE request in the background; while it's
        # subscribing, publish events into the pool.
        async def publisher():
            # Yield enough for the subscribe to register.
            await asyncio.sleep(0.05)
            await publish_progress(pool, scan_id, {"stage": "crawling", "message": "1"})
            await publish_progress(pool, scan_id, {"stage": "scoring",  "message": "2"})
            await publish_progress(pool, scan_id, {"stage": "done",     "message": "3"})

        pub_task = asyncio.create_task(publisher())
        r = await client.get(
            f"/scan/jobs/{scan_id}/events",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5.0,
        )
        await pub_task
        assert r.status_code == 200
        events = _parse_sse(r.text)
        stages = [e["stage"] for e in events]
        assert stages == ["crawling", "scoring", "done"]

    async def test_events_requires_auth(self, app_with_db):
        client, _pool = app_with_db
        # Even a 404-style GET needs a bearer first.
        r = await client.get("/scan/jobs/anything/events")
        assert r.status_code == 401

    async def test_events_cross_tenant_is_404(self, app_with_db):
        client, _pool = app_with_db
        _token_a, org_a = await _signup_and_org(client)
        # Different user.
        rb = await client.post("/auth/signup", json={
            "email": "bob@example.com", "password": "long-enough-password",
        })
        token_b = rb.json()["access_token"]

        scan_id, _ = await create_pending_scan(
            url="https://example.com/", organization_id=org_a,
        )

        r = await client.get(
            f"/scan/jobs/{scan_id}/events",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert r.status_code == 404

    async def test_events_unknown_id_is_404(self, app_with_db):
        client, _pool = app_with_db
        token, _ = await _signup_and_org(client)
        r = await client.get(
            "/scan/jobs/does-not-exist/events",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 404

    async def test_events_without_redis_returns_503(self, app_with_db, monkeypatch):
        client, _pool = app_with_db
        token, org_id = await _signup_and_org(client)

        scan_id, _ = await create_pending_scan(
            url="https://example.com/", organization_id=org_id,
        )

        # Drop both the pool and the config so the helper refuses.
        set_pool_for_tests(None)
        from app.config import settings as cfg
        monkeypatch.setattr(cfg, "redis_url", None)

        r = await client.get(
            f"/scan/jobs/{scan_id}/events",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 503
