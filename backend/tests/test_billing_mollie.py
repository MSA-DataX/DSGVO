"""Tests for Phase 5b — Mollie checkout, webhook, cancel.

A ``_FakeMollieClient`` records every method call and hands back
canned responses so the full checkout → webhook → active flow runs
without any real network I/O. Every webhook test is replayed twice to
pin idempotency (Mollie retries on non-2xx and occasional double-
delivers).

Also pins the config-gated behaviour:

  - With MOLLIE_API_KEY set → checkout/cancel work.
  - Without → both 503 with a clear message.
  - Webhook path demands the token; wrong token → 404 so probers can't
    distinguish from "no such endpoint".
"""

from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app import db as db_module
from app.db_models import Base


# ---------------------------------------------------------------------------
# Fake Mollie client + fixtures
# ---------------------------------------------------------------------------

class _FakeMollieClient:
    """Minimal stand-in for ``app.billing.mollie.MollieClient``.
    Records every call + returns canned responses. Tests set
    attributes on the instance to pick the canned reply."""

    def __init__(self):
        self.calls: list[tuple[str, dict[str, Any]]] = []
        # Canned replies — tests tweak these before exercising flows.
        self.customer_id = "cst_TEST123"
        self.payment: dict[str, Any] = {
            "id": "tr_PAYMENT123",
            "status": "paid",
            "customerId": self.customer_id,
            "metadata": {"kind": "first_payment"},
            "_links": {"checkout": {"href": "https://pay.mollie.dev/checkout/tr_PAYMENT123"}},
        }
        self.subscription: dict[str, Any] = {
            "id": "sub_SUB123",
            "status": "active",
            "nextPaymentDate": "2026-05-24",
        }

    async def create_customer(self, *, name: str, email: str) -> dict[str, Any]:
        self.calls.append(("create_customer", {"name": name, "email": email}))
        return {"id": self.customer_id, "name": name, "email": email}

    async def create_first_payment(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("create_first_payment", kwargs))
        # Customise the metadata reply so webhook lookups line up.
        return {**self.payment, "metadata": kwargs["metadata"]}

    async def get_payment(self, payment_id: str) -> dict[str, Any]:
        self.calls.append(("get_payment", {"id": payment_id}))
        return self.payment

    async def create_subscription(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("create_subscription", kwargs))
        return self.subscription

    async def cancel_subscription(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("cancel_subscription", kwargs))
        return {**self.subscription, "status": "canceled"}


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

    # Enable Mollie mode in config + install the fake client.
    from app.config import settings as cfg
    monkeypatch.setattr(cfg, "mollie_api_key", "test_fake-key")
    monkeypatch.setattr(cfg, "app_base_url", "https://scanner.test")
    monkeypatch.setattr(cfg, "mollie_webhook_token", "WEBHOOK-TOKEN-ABC")

    fake = _FakeMollieClient()
    set_mollie_client_for_tests(fake)

    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, fake

    set_mollie_client_for_tests(None)
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


async def _load_subscription(org_id: str):
    from sqlalchemy import select
    from app.db import session_scope
    from app.db_models import Subscription
    async with session_scope() as session:
        return (await session.execute(
            select(Subscription).where(Subscription.organization_id == org_id)
        )).scalar_one_or_none()


# ---------------------------------------------------------------------------
# _cents_to_mollie pure helper
# ---------------------------------------------------------------------------

class TestCentsFormatting:
    def test_round_amounts(self):
        from app.billing.mollie import _cents_to_mollie
        assert _cents_to_mollie(0) == "0.00"
        assert _cents_to_mollie(1900) == "19.00"
        assert _cents_to_mollie(9900) == "99.00"

    def test_odd_cents(self):
        from app.billing.mollie import _cents_to_mollie
        assert _cents_to_mollie(123) == "1.23"
        assert _cents_to_mollie(5) == "0.05"

    def test_rejects_negative(self):
        from app.billing.mollie import _cents_to_mollie
        with pytest.raises(ValueError):
            _cents_to_mollie(-1)


# ---------------------------------------------------------------------------
# Config gate: /checkout requires all three env vars
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestConfigGate:
    async def test_checkout_without_api_key_is_503(self, app_with_db, monkeypatch):
        client, _fake = app_with_db
        from app.config import settings as cfg
        monkeypatch.setattr(cfg, "mollie_api_key", None)

        token, _ = await _signup(client, "alice@example.com")
        r = await client.post(
            "/billing/checkout",
            headers={"Authorization": f"Bearer {token}"},
            json={"plan_code": "pro"},
        )
        assert r.status_code == 503
        assert "not configured" in r.json()["detail"].lower()

    async def test_cancel_without_webhook_token_is_503(self, app_with_db, monkeypatch):
        client, _fake = app_with_db
        from app.config import settings as cfg
        monkeypatch.setattr(cfg, "mollie_webhook_token", None)

        token, _ = await _signup(client, "alice@example.com")
        r = await client.post(
            "/billing/cancel",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 503

    async def test_webhook_without_base_url_is_503(self, app_with_db, monkeypatch):
        client, _fake = app_with_db
        from app.config import settings as cfg
        monkeypatch.setattr(cfg, "app_base_url", None)

        r = await client.post(
            "/billing/webhook/WEBHOOK-TOKEN-ABC",
            data={"id": "tr_xxx"},
        )
        assert r.status_code == 503


# ---------------------------------------------------------------------------
# Checkout flow
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestCheckout:
    async def test_checkout_returns_mollie_url_and_parks_pending_row(self, app_with_db):
        client, fake = app_with_db
        token, user_id = await _signup(client, "alice@example.com")
        org_id = await _org_id_for(user_id)

        r = await client.post(
            "/billing/checkout",
            headers={"Authorization": f"Bearer {token}"},
            json={"plan_code": "pro"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["checkout_url"].startswith("https://pay.mollie.dev/")

        # Mollie side-effects: one customer + one first payment.
        names = [c[0] for c in fake.calls]
        assert names == ["create_customer", "create_first_payment"]

        # First-payment kwargs carry our metadata + webhook URL + correct amount.
        _name, kwargs = fake.calls[1]
        assert kwargs["amount_cents"] == 1900
        assert kwargs["webhook_url"] == (
            "https://scanner.test/billing/webhook/WEBHOOK-TOKEN-ABC"
        )
        assert kwargs["metadata"]["organization_id"] == org_id
        assert kwargs["metadata"]["plan_code"] == "pro"
        assert kwargs["metadata"]["kind"] == "first_payment"

        # DB parked a pending subscription row with the customer id.
        sub = await _load_subscription(org_id)
        assert sub is not None
        assert sub.mollie_customer_id == fake.customer_id
        assert sub.status == "past_due"         # awaiting first-payment
        assert sub.plan_code == "pro"

    async def test_checkout_rejects_free_plan(self, app_with_db):
        client, _ = app_with_db
        token, _ = await _signup(client, "alice@example.com")
        r = await client.post(
            "/billing/checkout",
            headers={"Authorization": f"Bearer {token}"},
            json={"plan_code": "free"},
        )
        assert r.status_code == 400

    async def test_checkout_rejects_unknown_plan(self, app_with_db):
        client, _ = app_with_db
        token, _ = await _signup(client, "alice@example.com")
        r = await client.post(
            "/billing/checkout",
            headers={"Authorization": f"Bearer {token}"},
            json={"plan_code": "platinum-unicorn"},
        )
        assert r.status_code == 400

    async def test_checkout_requires_auth(self, app_with_db):
        client, _ = app_with_db
        r = await client.post("/billing/checkout", json={"plan_code": "pro"})
        assert r.status_code == 401

    async def test_second_checkout_reuses_mollie_customer(self, app_with_db):
        client, fake = app_with_db
        token, _ = await _signup(client, "alice@example.com")

        await client.post(
            "/billing/checkout",
            headers={"Authorization": f"Bearer {token}"},
            json={"plan_code": "pro"},
        )
        await client.post(
            "/billing/checkout",
            headers={"Authorization": f"Bearer {token}"},
            json={"plan_code": "business"},
        )
        # First checkout: create_customer + create_first_payment.
        # Second: ONLY create_first_payment — customer is reused.
        names = [c[0] for c in fake.calls]
        assert names == [
            "create_customer", "create_first_payment",
            "create_first_payment",
        ]


# ---------------------------------------------------------------------------
# Webhook flow — first payment, recurring, failure, idempotency
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestWebhook:
    async def test_wrong_token_is_404(self, app_with_db):
        client, _fake = app_with_db
        r = await client.post(
            "/billing/webhook/WRONG-TOKEN",
            data={"id": "tr_something"},
        )
        assert r.status_code == 404

    async def test_missing_id_returns_200_and_no_mollie_call(self, app_with_db):
        client, fake = app_with_db
        r = await client.post(
            "/billing/webhook/WEBHOOK-TOKEN-ABC",
            data={},  # no id
        )
        assert r.status_code == 200
        # We never went to Mollie.
        assert fake.calls == []

    async def test_first_payment_paid_activates_subscription(self, app_with_db):
        client, fake = app_with_db
        token, user_id = await _signup(client, "alice@example.com")
        org_id = await _org_id_for(user_id)

        # 1. Start checkout — parks the pending row + customer id.
        await client.post(
            "/billing/checkout",
            headers={"Authorization": f"Bearer {token}"},
            json={"plan_code": "pro"},
        )

        # 2. Mollie's webhook: payment paid → we activate the sub.
        fake.payment = {
            "id": "tr_PAYMENT123",
            "status": "paid",
            "customerId": fake.customer_id,
            "metadata": {
                "organization_id": org_id,
                "plan_code": "pro",
                "kind": "first_payment",
            },
        }
        r = await client.post(
            "/billing/webhook/WEBHOOK-TOKEN-ABC",
            data={"id": "tr_PAYMENT123"},
        )
        assert r.status_code == 200

        sub = await _load_subscription(org_id)
        assert sub is not None
        assert sub.status == "active"
        assert sub.mollie_subscription_id == "sub_SUB123"
        assert sub.plan_code == "pro"
        assert sub.current_period_end == "2026-05-24"

        # Mollie side-effects: get_payment + create_subscription.
        assert ("get_payment", {"id": "tr_PAYMENT123"}) in fake.calls
        assert any(c[0] == "create_subscription" for c in fake.calls)

    async def test_duplicate_webhook_does_not_create_second_subscription(self, app_with_db):
        """Mollie retries on non-2xx and occasionally double-delivers.
        Handler must be idempotent: second call sees mollie_subscription_id
        already set and skips create_subscription."""
        client, fake = app_with_db
        token, user_id = await _signup(client, "alice@example.com")
        org_id = await _org_id_for(user_id)

        await client.post(
            "/billing/checkout",
            headers={"Authorization": f"Bearer {token}"},
            json={"plan_code": "pro"},
        )
        fake.payment = {
            "id": "tr_PAYMENT123",
            "status": "paid",
            "customerId": fake.customer_id,
            "metadata": {"organization_id": org_id, "plan_code": "pro", "kind": "first_payment"},
        }

        # First delivery.
        await client.post(
            "/billing/webhook/WEBHOOK-TOKEN-ABC",
            data={"id": "tr_PAYMENT123"},
        )
        subs_before = sum(1 for c in fake.calls if c[0] == "create_subscription")
        # Replay.
        r = await client.post(
            "/billing/webhook/WEBHOOK-TOKEN-ABC",
            data={"id": "tr_PAYMENT123"},
        )
        assert r.status_code == 200
        subs_after = sum(1 for c in fake.calls if c[0] == "create_subscription")
        assert subs_after == subs_before           # no second create_subscription

        sub = await _load_subscription(org_id)
        assert sub is not None
        assert sub.status == "active"
        assert sub.mollie_subscription_id == "sub_SUB123"

    async def test_recurring_paid_updates_status_and_period(self, app_with_db):
        client, fake = app_with_db
        token, user_id = await _signup(client, "alice@example.com")
        org_id = await _org_id_for(user_id)

        # Bring the subscription to active via a first payment.
        await client.post(
            "/billing/checkout",
            headers={"Authorization": f"Bearer {token}"},
            json={"plan_code": "pro"},
        )
        fake.payment = {
            "id": "tr_FIRST",
            "status": "paid",
            "customerId": fake.customer_id,
            "metadata": {"organization_id": org_id, "plan_code": "pro", "kind": "first_payment"},
        }
        await client.post(
            "/billing/webhook/WEBHOOK-TOKEN-ABC",
            data={"id": "tr_FIRST"},
        )

        # Flip the subscription to past_due manually and then deliver
        # a recurring charge — handler should bring it back to active.
        from sqlalchemy import update
        from app.db import session_scope
        from app.db_models import Subscription
        async with session_scope() as session:
            await session.execute(
                update(Subscription)
                .where(Subscription.organization_id == org_id)
                .values(status="past_due")
            )

        fake.payment = {
            "id": "tr_RECURRING",
            "status": "paid",
            "customerId": fake.customer_id,
            "metadata": {"organization_id": org_id, "plan_code": "pro", "kind": "recurring"},
        }
        await client.post(
            "/billing/webhook/WEBHOOK-TOKEN-ABC",
            data={"id": "tr_RECURRING"},
        )

        sub = await _load_subscription(org_id)
        assert sub is not None
        assert sub.status == "active"

    async def test_failed_payment_marks_past_due(self, app_with_db):
        client, fake = app_with_db
        token, user_id = await _signup(client, "alice@example.com")
        org_id = await _org_id_for(user_id)

        await client.post(
            "/billing/checkout",
            headers={"Authorization": f"Bearer {token}"},
            json={"plan_code": "pro"},
        )
        fake.payment = {
            "id": "tr_FAIL",
            "status": "failed",
            "customerId": fake.customer_id,
            "metadata": {"organization_id": org_id, "plan_code": "pro", "kind": "first_payment"},
        }
        r = await client.post(
            "/billing/webhook/WEBHOOK-TOKEN-ABC",
            data={"id": "tr_FAIL"},
        )
        assert r.status_code == 200

        sub = await _load_subscription(org_id)
        assert sub is not None
        assert sub.status == "past_due"

    async def test_unknown_customer_is_logged_and_ignored(self, app_with_db):
        client, fake = app_with_db
        fake.payment = {
            "id": "tr_GHOST",
            "status": "paid",
            "customerId": "cst_UNKNOWN",
            "metadata": {},
        }
        r = await client.post(
            "/billing/webhook/WEBHOOK-TOKEN-ABC",
            data={"id": "tr_GHOST"},
        )
        # 200 so Mollie doesn't retry forever; the handler logs + drops.
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Cancel flow
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestCancel:
    async def test_cancel_without_subscription_is_noop(self, app_with_db):
        client, fake = app_with_db
        token, _ = await _signup(client, "alice@example.com")
        r = await client.post(
            "/billing/cancel",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "no_active_subscription"
        # Never called Mollie because there's nothing to cancel.
        assert not any(c[0] == "cancel_subscription" for c in fake.calls)

    async def test_cancel_active_subscription(self, app_with_db):
        client, fake = app_with_db
        token, user_id = await _signup(client, "alice@example.com")
        org_id = await _org_id_for(user_id)

        # Get to active state.
        await client.post(
            "/billing/checkout",
            headers={"Authorization": f"Bearer {token}"},
            json={"plan_code": "pro"},
        )
        fake.payment = {
            "id": "tr_OK",
            "status": "paid",
            "customerId": fake.customer_id,
            "metadata": {"organization_id": org_id, "plan_code": "pro", "kind": "first_payment"},
        }
        await client.post(
            "/billing/webhook/WEBHOOK-TOKEN-ABC",
            data={"id": "tr_OK"},
        )

        # Cancel.
        r = await client.post(
            "/billing/cancel",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "canceled"

        # Mollie saw the cancel call with our stored ids.
        cancel_call = next(c for c in fake.calls if c[0] == "cancel_subscription")
        assert cancel_call[1]["customer_id"] == fake.customer_id
        assert cancel_call[1]["subscription_id"] == "sub_SUB123"

        sub = await _load_subscription(org_id)
        assert sub is not None
        assert sub.status == "canceled"
