"""Tests for DELETE /auth/me (GDPR Art. 17 right to erasure).

The behavioural invariants are:

  1. A user with NO owned orgs: just the user row + their memberships
     disappear. Co-owned orgs stay intact.
  2. A user who is the SOLE owner of an org: that org disappears with
     all its scans + subscription. Mollie subscription (if any) is
     cancelled first.
  3. A user who is ONE OF several owners: their membership goes, the
     org continues, other owners unaffected.
  4. Audit rows survive via ``ON DELETE SET NULL`` on actor_user_id —
     the denormalised ``actor_email`` keeps the trail readable.
  5. Mollie cancel failure must not block deletion (user's right
     trumps billing-API availability).
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app import db as db_module
from app.db_models import (
    AuditLog,
    Base,
    Membership,
    Organization,
    Scan,
    Subscription,
    User,
)


@pytest_asyncio.fixture
async def app_with_db(monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.billing.mollie import set_mollie_client_for_tests
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

    # Default to Mollie being OFF — so cancel_org_subscription raises
    # RuntimeError, which the handler treats as "nothing to cancel".
    set_mollie_client_for_tests(None)

    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client

    set_mollie_client_for_tests(None)
    await engine.dispose()


async def _signup(client, email: str) -> tuple[str, str]:
    r = await client.post("/auth/signup", json={
        "email": email, "password": "long-enough-password",
        "display_name": email.split("@")[0],
    })
    assert r.status_code == 201, r.text
    body = r.json()
    return body["access_token"], body["user"]["id"]


async def _org_id_of(user_id: str) -> str:
    from sqlalchemy import select
    from app.db import session_scope
    async with session_scope() as session:
        return (await session.execute(
            select(Membership.organization_id).where(Membership.user_id == user_id)
        )).scalar_one()


async def _count(model) -> int:
    from sqlalchemy import func, select
    from app.db import session_scope
    async with session_scope() as session:
        return (await session.execute(
            select(func.count()).select_from(model)
        )).scalar_one()


async def _row_exists(model, id_column, id_value: str) -> bool:
    from sqlalchemy import select
    from app.db import session_scope
    async with session_scope() as session:
        return (await session.execute(
            select(id_column).where(id_column == id_value)
        )).scalar_one_or_none() is not None


# ---------------------------------------------------------------------------
# Sole-owner path — the default signup shape
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestSoleOwnerDelete:
    async def test_returns_deleted_status_and_org_id(self, app_with_db):
        token, user_id = await _signup(app_with_db, "alice@example.com")
        org_id = await _org_id_of(user_id)

        r = await app_with_db.delete(
            "/auth/me", headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "deleted"
        assert body["deleted_user_id"] == user_id
        assert body["deleted_organization_ids"] == [org_id]
        assert body["mollie_subscriptions_canceled"] == 0   # no Mollie sub

    async def test_user_row_is_gone(self, app_with_db):
        token, user_id = await _signup(app_with_db, "alice@example.com")
        await app_with_db.delete(
            "/auth/me", headers={"Authorization": f"Bearer {token}"},
        )
        assert await _row_exists(User, User.id, user_id) is False

    async def test_org_and_membership_are_gone(self, app_with_db):
        token, user_id = await _signup(app_with_db, "alice@example.com")
        org_id = await _org_id_of(user_id)
        await app_with_db.delete(
            "/auth/me", headers={"Authorization": f"Bearer {token}"},
        )
        assert await _row_exists(Organization, Organization.id, org_id) is False
        assert await _count(Membership) == 0

    async def test_scans_cascade_away(self, app_with_db):
        token, user_id = await _signup(app_with_db, "alice@example.com")
        org_id = await _org_id_of(user_id)

        # Persist a scan owned by the org so we can prove the cascade.
        from app.models import (
            ContactChannelsReport, CookieReport, CrawlResult, FormReport,
            NetworkResult, PrivacyAnalysis, RiskScore, ScanResponse,
            ThirdPartyWidgetsReport,
        )
        from app.storage import save_scan

        fake = ScanResponse(
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
        await save_scan(fake, organization_id=org_id)
        assert await _count(Scan) == 1

        await app_with_db.delete(
            "/auth/me", headers={"Authorization": f"Bearer {token}"},
        )
        assert await _count(Scan) == 0

    async def test_subscription_cascades_away(self, app_with_db):
        from app.billing.subscriptions import set_plan

        token, user_id = await _signup(app_with_db, "alice@example.com")
        org_id = await _org_id_of(user_id)
        await set_plan(org_id, "pro")
        assert await _count(Subscription) == 1

        await app_with_db.delete(
            "/auth/me", headers={"Authorization": f"Bearer {token}"},
        )
        assert await _count(Subscription) == 0

    async def test_subsequent_auth_requests_are_401(self, app_with_db):
        token, _ = await _signup(app_with_db, "alice@example.com")
        r1 = await app_with_db.delete(
            "/auth/me", headers={"Authorization": f"Bearer {token}"},
        )
        assert r1.status_code == 200
        # The JWT is still cryptographically valid until its TTL, but
        # the user row is gone — get_current_user returns 401.
        r2 = await app_with_db.get(
            "/auth/me", headers={"Authorization": f"Bearer {token}"},
        )
        assert r2.status_code == 401


# ---------------------------------------------------------------------------
# Co-owner path — org survives
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestCoOwnerDelete:
    async def test_co_owner_leaves_org_intact(self, app_with_db):
        # Alice signs up → her org.
        alice_token, alice_id = await _signup(app_with_db, "alice@example.com")
        alice_org_id = await _org_id_of(alice_id)

        # Bob signs up → his own org (every signup spawns one). But
        # then we promote Bob to a co-owner of Alice's org directly
        # in the DB.
        _, bob_id = await _signup(app_with_db, "bob@example.com")
        import uuid
        from datetime import datetime, timezone
        from app.db import session_scope
        async with session_scope() as session:
            session.add(Membership(
                id=uuid.uuid4().hex[:12],
                user_id=bob_id, organization_id=alice_org_id,
                role="owner",
                created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ))

        # Alice deletes herself — she's no longer the SOLE owner, so
        # the org must survive.
        r = await app_with_db.delete(
            "/auth/me", headers={"Authorization": f"Bearer {alice_token}"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["deleted_organization_ids"] == []   # none deleted

        # Org + Bob's membership on it both still exist.
        assert await _row_exists(Organization, Organization.id, alice_org_id) is True
        from sqlalchemy import select
        async with session_scope() as session:
            remaining = (await session.execute(
                select(Membership).where(Membership.organization_id == alice_org_id)
            )).scalars().all()
        assert [m.user_id for m in remaining] == [bob_id]


# ---------------------------------------------------------------------------
# Audit preservation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestAuditPreservation:
    async def test_audit_rows_survive_with_null_actor_and_kept_email(self, app_with_db):
        # Alice promotes herself to superuser (direct DB, the CLI
        # flow is tested elsewhere). Then performs an admin action
        # that leaves an audit row attributed to her, then self-deletes.
        from sqlalchemy import select, update
        from app.db import session_scope
        from app.db_models import User as UserModel

        alice_token, alice_id = await _signup(app_with_db, "alice@example.com")
        async with session_scope() as session:
            await session.execute(
                update(UserModel).where(UserModel.id == alice_id).values(is_superuser=True)
            )

        _, bob_id = await _signup(app_with_db, "bob@example.com")
        r = await app_with_db.post(
            f"/admin/users/{bob_id}/promote",
            headers={"Authorization": f"Bearer {alice_token}"},
        )
        assert r.status_code == 200

        # Alice self-deletes. The "user.promote" row above AND the
        # "user.self_delete" row generated by the delete endpoint
        # must both survive.
        await app_with_db.delete(
            "/auth/me", headers={"Authorization": f"Bearer {alice_token}"},
        )

        async with session_scope() as session:
            rows = (await session.execute(
                select(AuditLog).where(AuditLog.actor_email == "alice@example.com")
            )).scalars().all()
        assert any(r.action == "user.promote" for r in rows)
        assert any(r.action == "user.self_delete" for r in rows)
        # actor_user_id is nulled out (ON DELETE SET NULL) but email survives.
        for r in rows:
            assert r.actor_user_id is None
            assert r.actor_email == "alice@example.com"


# ---------------------------------------------------------------------------
# Mollie integration edge cases
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestMollieCancellation:
    async def test_mollie_cancel_called_for_active_subscription(self, app_with_db, monkeypatch):
        # Set up Mollie, pretend we have an active sub.
        from app.billing.mollie import set_mollie_client_for_tests
        from app.billing.subscriptions import set_plan
        from app.config import settings as cfg
        monkeypatch.setattr(cfg, "mollie_api_key", "test_fake-key")
        monkeypatch.setattr(cfg, "app_base_url", "https://scanner.test")
        monkeypatch.setattr(cfg, "mollie_webhook_token", "T")

        cancellations: list[dict] = []

        class _FakeClient:
            async def cancel_subscription(self, **kwargs):
                cancellations.append(kwargs)
                return {"status": "canceled"}

        set_mollie_client_for_tests(_FakeClient())

        token, user_id = await _signup(app_with_db, "alice@example.com")
        org_id = await _org_id_of(user_id)
        sub = await set_plan(org_id, "pro")

        # Stamp Mollie ids directly — signup path doesn't do this.
        from sqlalchemy import update
        from app.db import session_scope
        async with session_scope() as session:
            await session.execute(update(Subscription)
                                  .where(Subscription.organization_id == org_id)
                                  .values(
                                      mollie_customer_id="cst_X",
                                      mollie_subscription_id="sub_Y",
                                  ))
        del sub

        r = await app_with_db.delete(
            "/auth/me", headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        assert r.json()["mollie_subscriptions_canceled"] == 1
        assert len(cancellations) == 1
        assert cancellations[0]["customer_id"] == "cst_X"
        assert cancellations[0]["subscription_id"] == "sub_Y"

    async def test_mollie_failure_does_not_block_deletion(self, app_with_db, monkeypatch):
        # The user's GDPR right to erasure must not be held hostage by
        # a third-party API outage. If cancel_subscription raises, we
        # log and continue deleting.
        from app.billing.mollie import MollieError, set_mollie_client_for_tests
        from app.billing.subscriptions import set_plan
        from app.config import settings as cfg
        monkeypatch.setattr(cfg, "mollie_api_key", "test_fake-key")
        monkeypatch.setattr(cfg, "app_base_url", "https://scanner.test")
        monkeypatch.setattr(cfg, "mollie_webhook_token", "T")

        class _BrokenClient:
            async def cancel_subscription(self, **_kw):
                raise MollieError(500, "Mollie is on fire")

        set_mollie_client_for_tests(_BrokenClient())

        token, user_id = await _signup(app_with_db, "alice@example.com")
        org_id = await _org_id_of(user_id)
        await set_plan(org_id, "pro")
        from sqlalchemy import update
        from app.db import session_scope
        async with session_scope() as session:
            await session.execute(update(Subscription)
                                  .where(Subscription.organization_id == org_id)
                                  .values(
                                      mollie_customer_id="cst_X",
                                      mollie_subscription_id="sub_Y",
                                  ))

        r = await app_with_db.delete(
            "/auth/me", headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        # Org + user still gone — deletion proceeded in spite of Mollie.
        assert await _row_exists(User, User.id, user_id) is False
        assert await _row_exists(Organization, Organization.id, org_id) is False
        # Cancel count reflects SUCCESSFUL cancellations only.
        assert r.json()["mollie_subscriptions_canceled"] == 0


# ---------------------------------------------------------------------------
# Auth gate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestAuthGate:
    async def test_delete_me_requires_auth(self, app_with_db):
        r = await app_with_db.delete("/auth/me")
        assert r.status_code == 401
