"""Tests for Phase 5a billing + quota.

Covers:
  - Free tier defaults for orgs without a Subscription row
  - set_plan() upserts + is idempotent on replay
  - GET /billing/plans (public) + GET /billing/subscription (authed)
  - Quota enforcement on /scan/jobs (402 when over limit) — stubs
    run_scan so Playwright never launches
  - Admin POST /admin/organizations/{id}/set-plan: auth gate + audit row
  - Tenant isolation: one org's scan budget doesn't affect another's
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app import db as db_module
from app.db_models import Base


@pytest_asyncio.fixture
async def app_with_db(monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.db import install_sqlite_fk_pragma
    from app.security.rate_limit import auth_rate_limiter, scan_rate_limiter

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    install_sqlite_fk_pragma(engine)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "_engine", engine)
    monkeypatch.setattr(db_module, "_SessionLocal", SessionLocal)
    scan_rate_limiter.reset()
    auth_rate_limiter.reset()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client

    await engine.dispose()


async def _signup(client, email: str) -> tuple[str, str]:
    r = await client.post("/auth/signup", json={
        "email": email, "password": "long-enough-password",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    return body["access_token"], body["user"]["id"]


async def _org_id_for(user_id: str) -> str:
    from sqlalchemy import select
    from app.db import session_scope
    from app.db_models import Membership
    async with session_scope() as session:
        return (await session.execute(
            select(Membership.organization_id).where(Membership.user_id == user_id)
        )).scalar_one()


async def _promote_in_db(user_id: str) -> None:
    from sqlalchemy import update
    from app.db import session_scope
    from app.db_models import User
    async with session_scope() as session:
        await session.execute(
            update(User).where(User.id == user_id).values(is_superuser=True)
        )


# ---------------------------------------------------------------------------
# Plans / subscription read endpoints
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestBillingReads:
    async def test_plans_public(self, app_with_db):
        # No auth header — endpoint is intentionally anonymous so a
        # pricing page can hit it without a session.
        r = await app_with_db.get("/billing/plans")
        assert r.status_code == 200
        plans = r.json()
        codes = {p["code"] for p in plans}
        assert {"free", "pro", "business"} <= codes

    async def test_subscription_defaults_to_free(self, app_with_db):
        token, _ = await _signup(app_with_db, "alice@example.com")
        r = await app_with_db.get(
            "/billing/subscription",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["plan"]["code"] == "free"
        assert body["status"] == "no_subscription"
        assert body["scans_used"] == 0
        assert body["scans_quota"] == 5

    async def test_subscription_requires_auth(self, app_with_db):
        r = await app_with_db.get("/billing/subscription")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# set_plan upsert semantics
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestSetPlanHelper:
    async def test_upsert_creates_row_on_first_call(self, app_with_db):
        from app.billing.subscriptions import set_plan
        _, user_id = await _signup(app_with_db, "alice@example.com")
        org_id = await _org_id_for(user_id)

        sub = await set_plan(org_id, "pro")
        assert sub.organization_id == org_id
        assert sub.plan_code == "pro"
        assert sub.status == "active"

    async def test_upsert_updates_existing_row(self, app_with_db):
        from app.billing.subscriptions import set_plan
        _, user_id = await _signup(app_with_db, "alice@example.com")
        org_id = await _org_id_for(user_id)

        await set_plan(org_id, "pro")
        sub = await set_plan(org_id, "business")
        assert sub.plan_code == "business"

        # Only one row per org.
        from sqlalchemy import func, select
        from app.db import session_scope
        from app.db_models import Subscription
        async with session_scope() as session:
            n = (await session.execute(
                select(func.count()).select_from(Subscription)
                .where(Subscription.organization_id == org_id)
            )).scalar_one()
        assert n == 1

    async def test_unknown_plan_raises(self, app_with_db):
        from app.billing.subscriptions import set_plan
        _, user_id = await _signup(app_with_db, "alice@example.com")
        org_id = await _org_id_for(user_id)

        with pytest.raises(ValueError):
            await set_plan(org_id, "enterprise-unlimited-platinum")


# ---------------------------------------------------------------------------
# Quota enforcement on scan endpoints
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestQuotaEnforcement:
    async def test_free_tier_blocks_after_five_scans(self, app_with_db, monkeypatch):
        from app.security.rate_limit import scan_rate_limiter
        # Raise rate limit out of the way — we're testing the quota dimension.
        monkeypatch.setattr(scan_rate_limiter, "per_minute", 100)
        monkeypatch.setattr(scan_rate_limiter, "per_day", 10000)

        token, _ = await _signup(app_with_db, "alice@example.com")
        org_id = await _org_id_for(_to_user_id(token))

        # Directly insert 5 completed scans so we don't need to run
        # Playwright. mark_done carries organization_id via save_scan.
        from app.models import (
            ContactChannelsReport, CookieReport, CrawlResult, FormReport,
            NetworkResult, PrivacyAnalysis, RiskScore, ScanResponse,
            ThirdPartyWidgetsReport,
        )
        from app.storage import save_scan

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

        for _ in range(5):
            await save_scan(_fake_result(), organization_id=org_id)

        # 6th scan via /scan/jobs — quota should trip. Stub enqueue so
        # no Redis is required; the quota check runs BEFORE enqueue.
        from app.jobs import set_pool_for_tests

        class _FakePool:
            async def enqueue_job(self, *_a, **_kw):
                return None

        set_pool_for_tests(_FakePool())
        from app.config import settings as cfg
        monkeypatch.setattr(cfg, "redis_url", "redis://test")

        r = await app_with_db.post(
            "/scan/jobs",
            headers={"Authorization": f"Bearer {token}"},
            json={"url": "https://example.com/"},
        )
        assert r.status_code == 402
        body = r.json()
        detail = body["detail"]
        assert detail["plan"] == "free"
        assert detail["scans_used"] == 5
        assert detail["scans_quota"] == 5

        set_pool_for_tests(None)

    async def test_pro_plan_raises_ceiling(self, app_with_db, monkeypatch):
        from app.billing.subscriptions import set_plan
        from app.security.rate_limit import scan_rate_limiter
        monkeypatch.setattr(scan_rate_limiter, "per_minute", 100)
        monkeypatch.setattr(scan_rate_limiter, "per_day", 10000)

        token, user_id = await _signup(app_with_db, "alice@example.com")
        org_id = await _org_id_for(user_id)
        await set_plan(org_id, "pro")   # 100 scans / month

        # 5 scans used; Pro still has ~95 remaining.
        from tests.test_billing import _seed_done_scans  # noqa
        await _seed_done_scans(org_id, 5)

        r = await app_with_db.get(
            "/billing/subscription",
            headers={"Authorization": f"Bearer {token}"},
        )
        body = r.json()
        assert body["plan"]["code"] == "pro"
        assert body["scans_quota"] == 100
        assert body["scans_used"] == 5
        assert body["quota_remaining"] == 95

    async def test_quota_isolation_across_orgs(self, app_with_db):
        # Saturating A's budget must leave B untouched.
        token_a, user_a = await _signup(app_with_db, "alice@example.com")
        org_a = await _org_id_for(user_a)
        token_b, user_b = await _signup(app_with_db, "bob@example.com")
        org_b = await _org_id_for(user_b)

        await _seed_done_scans(org_a, 5)   # A is at the free-tier ceiling

        ra = await app_with_db.get(
            "/billing/subscription",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert ra.json()["scans_used"] == 5
        assert ra.json()["quota_remaining"] == 0

        rb = await app_with_db.get(
            "/billing/subscription",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert rb.json()["scans_used"] == 0


# ---------------------------------------------------------------------------
# Admin set-plan endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestAdminSetPlan:
    async def test_non_admin_gets_403(self, app_with_db):
        token, user_id = await _signup(app_with_db, "alice@example.com")
        org_id = await _org_id_for(user_id)
        r = await app_with_db.post(
            f"/admin/organizations/{org_id}/set-plan",
            headers={"Authorization": f"Bearer {token}"},
            json={"plan_code": "pro"},
        )
        assert r.status_code == 403

    async def test_admin_assigns_plan_and_logs_audit(self, app_with_db):
        admin_token, admin_id = await _signup(app_with_db, "admin@example.com")
        await _promote_in_db(admin_id)
        _, alice_id = await _signup(app_with_db, "alice@example.com")
        alice_org = await _org_id_for(alice_id)

        r = await app_with_db.post(
            f"/admin/organizations/{alice_org}/set-plan",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"plan_code": "business"},
        )
        assert r.status_code == 200
        assert r.json() == {
            "organization_id": alice_org,
            "plan_code": "business",
            "status": "active",
        }

        # Alice's subscription endpoint now reflects it.
        alice_token_r = await app_with_db.post("/auth/login", json={
            "email": "alice@example.com", "password": "long-enough-password",
        })
        alice_token = alice_token_r.json()["access_token"]
        sub = await app_with_db.get(
            "/billing/subscription",
            headers={"Authorization": f"Bearer {alice_token}"},
        )
        assert sub.json()["plan"]["code"] == "business"
        assert sub.json()["scans_quota"] == 1000

        # Audit entry exists with the right shape.
        audit = (await app_with_db.get(
            "/admin/audit?action=organization.set_plan",
            headers={"Authorization": f"Bearer {admin_token}"},
        )).json()
        hit = next(
            e for e in audit
            if e["target_id"] == alice_org and e["action"] == "organization.set_plan"
        )
        assert hit["details"]["plan_code"] == "business"
        assert hit["actor_email"] == "admin@example.com"

    async def test_unknown_plan_code_is_400(self, app_with_db):
        admin_token, admin_id = await _signup(app_with_db, "admin@example.com")
        await _promote_in_db(admin_id)
        _, alice_id = await _signup(app_with_db, "alice@example.com")
        alice_org = await _org_id_for(alice_id)

        r = await app_with_db.post(
            f"/admin/organizations/{alice_org}/set-plan",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"plan_code": "free-plus-unicorn"},
        )
        assert r.status_code == 400

    async def test_unknown_org_is_404(self, app_with_db):
        admin_token, admin_id = await _signup(app_with_db, "admin@example.com")
        await _promote_in_db(admin_id)

        r = await app_with_db.post(
            "/admin/organizations/does-not-exist/set-plan",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"plan_code": "pro"},
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Helpers (private — kept at the bottom so they don't clutter the suite)
# ---------------------------------------------------------------------------

def _to_user_id(token: str) -> str:
    """Extract sub from the JWT payload without hitting the DB. The
    quota test already has the token; this saves an /auth/me round-trip."""
    import base64
    import json
    payload_b64 = token.split(".")[1]
    # Pad for base64url decoding.
    padded = payload_b64 + "=" * (-len(payload_b64) % 4)
    payload = json.loads(base64.urlsafe_b64decode(padded))
    return payload["sub"]


async def _seed_done_scans(organization_id: str, n: int) -> None:
    """Insert ``n`` completed scans for the given org. Skips the
    scanner entirely — we only need the `scans` rows for the quota
    count to tick up."""
    from app.models import (
        ContactChannelsReport, CookieReport, CrawlResult, FormReport,
        NetworkResult, PrivacyAnalysis, RiskScore, ScanResponse,
        ThirdPartyWidgetsReport,
    )
    from app.storage import save_scan

    def _fake() -> ScanResponse:
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

    for _ in range(n):
        await save_scan(_fake(), organization_id=organization_id)
