"""Tests for Phase 3 async scan jobs.

Covers:
  - Storage transitions (create_pending / mark_running / mark_done /
    mark_failed) and the status snapshot they produce.
  - Worker task: driving a scan through the task function with a stub
    scanner so Playwright never launches.
  - Enqueue helper: proves the pool's enqueue_job is called with the
    correct args + job id, using a fake pool.
  - HTTP flow: POST /scan/jobs → 202 + scan_id; GET /scan/jobs/{id}
    reflects the stored state; cross-tenant GET returns 404.

Nothing here talks to Redis. The Arq pool is always replaced with a
recording fake via :func:`app.jobs.set_pool_for_tests`.
"""

from __future__ import annotations

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
from app.storage import (
    create_pending_scan,
    get_scan_status,
    mark_done,
    mark_failed,
    mark_running,
    save_scan,
)


def _fake_result(url: str = "https://example.com/", score: int = 80) -> ScanResponse:
    return ScanResponse(
        target=url,
        risk=RiskScore(score=score, rating="low", weighted_score=score,
                       sub_scores=[], applied_caps=[], recommendations=[]),
        crawl=CrawlResult(start_url=url, pages=[], privacy_policy_url=None, imprint_url=None),
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


# ---------------------------------------------------------------------------
# In-memory DB fixture + fake Arq pool
# ---------------------------------------------------------------------------

class _FakePool:
    """Records every enqueue_job call so assertions can inspect them."""
    def __init__(self):
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    async def enqueue_job(self, function: str, *args: Any, **kwargs: Any):
        self.calls.append((function, args, kwargs))
        return None  # real arq returns a Job; callers ignore it


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

    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, pool

    set_pool_for_tests(None)
    await engine.dispose()


async def _signup_and_get_org(client) -> tuple[str, str]:
    """Sign up a user, return (token, org_id). Mirrors the helper in
    test_auth but kept local so these tests don't depend on that file's
    module-level imports."""
    from sqlalchemy import select
    from app.db import session_scope
    from app.db_models import Membership

    r = await client.post("/auth/signup", json={
        "email": "alice@example.com",
        "password": "long-enough-password",
    })
    assert r.status_code == 201, r.text
    token = r.json()["access_token"]
    user_id = r.json()["user"]["id"]
    async with session_scope() as session:
        org_id = (await session.execute(
            select(Membership.organization_id).where(Membership.user_id == user_id)
        )).scalar_one()
    return token, org_id


# ---------------------------------------------------------------------------
# Storage transitions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestStorageLifecycle:
    async def test_create_pending_yields_queued_snapshot(self, app_with_db):
        _, _ = app_with_db  # use the fixture purely to set up the DB
        client, _pool = app_with_db
        _token, org_id = await _signup_and_get_org(client)

        scan_id, created_at = await create_pending_scan(
            url="https://example.com/", organization_id=org_id,
        )
        assert scan_id and len(scan_id) == 12
        assert created_at

        status = await get_scan_status(scan_id, organization_id=org_id)
        assert status is not None
        assert status.status == "queued"
        assert status.url == "https://example.com/"
        assert status.started_at is None
        assert status.completed_at is None
        assert status.error is None
        assert status.result is None

    async def test_mark_running_transitions_state(self, app_with_db):
        client, _ = app_with_db
        _token, org_id = await _signup_and_get_org(client)
        scan_id, _ = await create_pending_scan(url="https://a.com/", organization_id=org_id)

        await mark_running(scan_id)
        status = await get_scan_status(scan_id, organization_id=org_id)
        assert status is not None
        assert status.status == "running"
        assert status.started_at is not None

    async def test_mark_done_populates_result(self, app_with_db):
        client, _ = app_with_db
        _token, org_id = await _signup_and_get_org(client)
        scan_id, _ = await create_pending_scan(url="https://a.com/", organization_id=org_id)
        await mark_running(scan_id)
        await mark_done(scan_id, _fake_result(url="https://a.com/", score=72))

        status = await get_scan_status(scan_id, organization_id=org_id)
        assert status is not None
        assert status.status == "done"
        assert status.completed_at is not None
        assert status.error is None
        assert status.result is not None
        assert status.result.risk.score == 72

    async def test_mark_failed_records_error(self, app_with_db):
        client, _ = app_with_db
        _token, org_id = await _signup_and_get_org(client)
        scan_id, _ = await create_pending_scan(url="https://a.com/", organization_id=org_id)

        await mark_failed(scan_id, "boom: Playwright died")
        status = await get_scan_status(scan_id, organization_id=org_id)
        assert status is not None
        assert status.status == "failed"
        assert status.error == "boom: Playwright died"
        assert status.result is None

    async def test_mark_failed_truncates_huge_errors(self, app_with_db):
        client, _ = app_with_db
        _token, org_id = await _signup_and_get_org(client)
        scan_id, _ = await create_pending_scan(url="https://a.com/", organization_id=org_id)

        huge = "x" * 10_000
        await mark_failed(scan_id, huge)
        status = await get_scan_status(scan_id, organization_id=org_id)
        assert status is not None
        assert status.error is not None
        assert len(status.error) <= 2000

    async def test_mark_running_on_finished_is_noop(self, app_with_db):
        # Guards against a worker accidentally re-transitioning a completed
        # scan back to "running" on a retry.
        client, _ = app_with_db
        _token, org_id = await _signup_and_get_org(client)
        scan_id, _ = await create_pending_scan(url="https://a.com/", organization_id=org_id)
        await mark_running(scan_id)
        await mark_done(scan_id, _fake_result())

        await mark_running(scan_id)  # should not revert
        status = await get_scan_status(scan_id, organization_id=org_id)
        assert status is not None
        assert status.status == "done"

    async def test_list_scans_excludes_in_flight_rows(self, app_with_db):
        # Placeholder score=0 rating=critical must NEVER surface in the
        # history UI — only completed rows count.
        from app.storage import list_scans
        client, _ = app_with_db
        _token, org_id = await _signup_and_get_org(client)

        # One queued + one done.
        await create_pending_scan(url="https://pending.com/", organization_id=org_id)
        await save_scan(_fake_result(url="https://done.com/"), organization_id=org_id)

        items = await list_scans(organization_id=org_id, limit=50)
        assert len(items) == 1
        assert items[0].url == "https://done.com/"


# ---------------------------------------------------------------------------
# Worker task
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestWorkerTask:
    async def test_task_drives_scan_to_done(self, app_with_db, monkeypatch):
        client, _ = app_with_db
        _token, org_id = await _signup_and_get_org(client)

        scan_id, _ = await create_pending_scan(
            url="https://example.com/", organization_id=org_id,
        )

        async def _fake_run_scan(req):
            assert str(req.url) == "https://example.com/"
            return _fake_result(url="https://example.com/", score=66)

        monkeypatch.setattr("app.worker.run_scan", _fake_run_scan)

        from app.worker import run_scan_task
        await run_scan_task({}, scan_id, {"url": "https://example.com/"})

        status = await get_scan_status(scan_id, organization_id=org_id)
        assert status is not None
        assert status.status == "done"
        assert status.result is not None
        assert status.result.risk.score == 66

    async def test_task_marks_failed_on_scanner_exception(self, app_with_db, monkeypatch):
        client, _ = app_with_db
        _token, org_id = await _signup_and_get_org(client)

        scan_id, _ = await create_pending_scan(
            url="https://example.com/", organization_id=org_id,
        )

        async def _boom(req):
            raise RuntimeError("chromium exploded")

        monkeypatch.setattr("app.worker.run_scan", _boom)

        from app.worker import run_scan_task
        await run_scan_task({}, scan_id, {"url": "https://example.com/"})

        status = await get_scan_status(scan_id, organization_id=org_id)
        assert status is not None
        assert status.status == "failed"
        assert status.error is not None
        assert "chromium exploded" in status.error


# ---------------------------------------------------------------------------
# HTTP flow — POST /scan/jobs + GET /scan/jobs/{id}
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestScanJobEndpoints:
    async def test_post_returns_202_and_enqueues(self, app_with_db):
        client, pool = app_with_db
        token, _ = await _signup_and_get_org(client)

        r = await client.post(
            "/scan/jobs",
            headers={"Authorization": f"Bearer {token}"},
            json={"url": "https://example.com/"},
        )
        assert r.status_code == 202
        body = r.json()
        assert body["status"] == "queued"
        assert body["id"]

        # The pool saw exactly one enqueue_job with our scan_id.
        assert len(pool.calls) == 1
        fn, args, kwargs = pool.calls[0]
        assert fn == "run_scan_task"
        assert args[0] == body["id"]
        assert kwargs.get("_job_id") == body["id"]
        assert args[1]["url"] == "https://example.com/"

    async def test_post_rejects_ssrf_target(self, app_with_db):
        client, pool = app_with_db
        token, _ = await _signup_and_get_org(client)
        r = await client.post(
            "/scan/jobs",
            headers={"Authorization": f"Bearer {token}"},
            json={"url": "http://127.0.0.1/"},
        )
        assert r.status_code == 400
        # Guard was hit BEFORE enqueue — nothing went on the queue.
        assert pool.calls == []

    async def test_post_requires_auth(self, app_with_db):
        client, _ = app_with_db
        r = await client.post("/scan/jobs", json={"url": "https://example.com/"})
        assert r.status_code == 401

    async def test_get_queued_status(self, app_with_db):
        client, _ = app_with_db
        token, _ = await _signup_and_get_org(client)

        posted = await client.post(
            "/scan/jobs",
            headers={"Authorization": f"Bearer {token}"},
            json={"url": "https://example.com/"},
        )
        scan_id = posted.json()["id"]

        r = await client.get(
            f"/scan/jobs/{scan_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == scan_id
        assert body["status"] == "queued"
        assert body["result"] is None

    async def test_get_done_status_returns_result(self, app_with_db):
        client, _ = app_with_db
        token, org_id = await _signup_and_get_org(client)

        scan_id, _ = await create_pending_scan(
            url="https://example.com/", organization_id=org_id,
        )
        await mark_running(scan_id)
        await mark_done(scan_id, _fake_result(score=88))

        r = await client.get(
            f"/scan/jobs/{scan_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "done"
        assert body["result"] is not None
        assert body["result"]["risk"]["score"] == 88

    async def test_get_failed_status_returns_error(self, app_with_db):
        client, _ = app_with_db
        token, org_id = await _signup_and_get_org(client)

        scan_id, _ = await create_pending_scan(
            url="https://example.com/", organization_id=org_id,
        )
        await mark_failed(scan_id, "boom: playwright died")

        r = await client.get(
            f"/scan/jobs/{scan_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "failed"
        assert body["error"] == "boom: playwright died"
        assert body["result"] is None

    async def test_get_cross_tenant_is_404(self, app_with_db):
        # Same invariant as /scans/{id} — other tenants must see a plain
        # 404, not 403, to avoid leaking existence.
        client, _ = app_with_db
        token_a, org_a = await _signup_and_get_org(client)

        # Sign up a second user + org directly (can't re-use the helper
        # because we're already past its first signup).
        r = await client.post("/auth/signup", json={
            "email": "bob@example.com", "password": "long-enough-password",
        })
        token_b = r.json()["access_token"]

        scan_id, _ = await create_pending_scan(
            url="https://example.com/", organization_id=org_a,
        )

        r_b = await client.get(
            f"/scan/jobs/{scan_id}",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert r_b.status_code == 404

    async def test_get_unknown_id_is_404(self, app_with_db):
        client, _ = app_with_db
        token, _ = await _signup_and_get_org(client)
        r = await client.get(
            "/scan/jobs/does-not-exist",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 404

    async def test_post_without_redis_returns_503(self, app_with_db, monkeypatch):
        # If the operator forgot to set REDIS_URL, the handler must fail
        # loud rather than leave scans stuck in "queued" forever.
        client, _ = app_with_db
        token, _ = await _signup_and_get_org(client)

        # Pretend the pool isn't initialised AND REDIS_URL is missing.
        set_pool_for_tests(None)
        from app.config import settings as cfg
        monkeypatch.setattr(cfg, "redis_url", None)

        r = await client.post(
            "/scan/jobs",
            headers={"Authorization": f"Bearer {token}"},
            json={"url": "https://example.com/"},
        )
        assert r.status_code == 503
        assert "REDIS_URL" in r.json()["detail"]
