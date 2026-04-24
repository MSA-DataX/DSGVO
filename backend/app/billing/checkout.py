"""Checkout + webhook orchestration for Phase 5b.

Sits between the FastAPI handlers (:mod:`app.routers.billing`) and the
thin Mollie client (:mod:`app.billing.mollie`). Does the bookkeeping
nobody else cares about:

  - reuses a Mollie customer per organization (one-to-one)
  - stashes the customer id on the Subscription row so later webhook
    messages can look the org up by id
  - translates Mollie payment / subscription states into our
    ``active`` / ``past_due`` / ``canceled`` vocabulary
  - ensures the webhook handler is idempotent — Mollie retries on
    non-2xx, so duplicate deliveries are the norm, not the exception
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.billing.mollie import MollieClient, MollieError, get_mollie_client
from app.billing.plans import Plan, get_plan
from app.billing.subscriptions import set_plan
from app.config import settings
from app.db import session_scope
from app.db_models import Organization, Subscription


log = logging.getLogger("billing.checkout")


# Plain-text description the user sees on their Mollie bank statement.
# Keep short — some banks truncate at ~25 chars.
def _subscription_description(plan: Plan) -> str:
    return f"MSA DataX {plan.name} Plan"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _webhook_url() -> str:
    """Mollie needs a publicly-reachable URL to POST into. Built from
    APP_BASE_URL + the random webhook-token path segment."""
    base = (settings.app_base_url or "").rstrip("/")
    token = settings.mollie_webhook_token or ""
    if not base or not token:
        raise RuntimeError(
            "APP_BASE_URL and MOLLIE_WEBHOOK_TOKEN must both be set to "
            "accept Mollie webhooks.",
        )
    return f"{base}/billing/webhook/{token}"


def _redirect_url() -> str:
    """Where Mollie sends the user back after the checkout page.
    Frontend route handles the "thanks!" landing."""
    base = (settings.app_base_url or "").rstrip("/")
    return f"{base}/billing?status=return"


# ---------------------------------------------------------------------------
# Checkout (POST /billing/checkout)
# ---------------------------------------------------------------------------

async def start_checkout(
    *,
    organization_id: str,
    organization_name: str,
    buyer_email: str,
    plan_code: str,
) -> str:
    """Drive the first-payment flow for ``plan_code`` and return the
    Mollie checkout URL the caller should redirect to.

    The flow is:

      1. Resolve (or create) our Mollie customer for this org.
      2. Create a first-payment for the plan's monthly price. This
         doubles as mandate authorisation — Mollie stores the
         payment method so subsequent subscription charges succeed.
      3. Stash the customer id + a `pending` subscription row so the
         webhook handler has somewhere to write when payment settles.

    On success the frontend redirects the browser to the returned URL.
    """
    plan = get_plan(plan_code)
    if plan.is_free:
        raise ValueError("cannot checkout the free plan; use admin set-plan to downgrade")

    client = get_mollie_client()
    customer_id = await _ensure_customer(
        client, organization_id=organization_id,
        name=organization_name, email=buyer_email,
    )

    payment = await client.create_first_payment(
        customer_id=customer_id,
        amount_cents=plan.price_eur_cents,
        description=_subscription_description(plan),
        redirect_url=_redirect_url(),
        webhook_url=_webhook_url(),
        metadata={
            "organization_id": organization_id,
            "plan_code": plan.code,
            "kind": "first_payment",
        },
    )

    # Park a pending row so the webhook can find us by customer id
    # even before the payment settles. `set_plan` doesn't run yet —
    # we only flip to the paid plan once Mollie confirms the money.
    await _upsert_pending(
        organization_id=organization_id,
        customer_id=customer_id,
        plan_code=plan.code,
    )

    url = payment.get("_links", {}).get("checkout", {}).get("href")
    if not url:
        raise MollieError(502, f"Mollie first-payment response missing checkout url: {payment!r}")
    return url


async def _ensure_customer(
    client: MollieClient, *, organization_id: str, name: str, email: str,
) -> str:
    """Return the Mollie customer id for ``organization_id`` — create
    one on first use. Idempotent on retries: once the row has
    `mollie_customer_id` set we reuse it indefinitely."""
    async with session_scope() as session:
        sub = (await session.execute(
            select(Subscription).where(Subscription.organization_id == organization_id)
        )).scalar_one_or_none()
        if sub is not None and sub.mollie_customer_id:
            return sub.mollie_customer_id

    created = await client.create_customer(name=name, email=email)
    customer_id = created.get("id")
    if not customer_id:
        raise MollieError(502, f"Mollie create_customer response missing id: {created!r}")
    return customer_id


async def _upsert_pending(
    *, organization_id: str, customer_id: str, plan_code: str,
) -> None:
    """Store the customer id + intended plan in a row with
    ``status='past_due'`` — our equivalent of "awaiting first payment".
    Webhook handler flips it to ``active`` once the payment settles."""
    now = _now_iso()
    async with session_scope() as session:
        existing = (await session.execute(
            select(Subscription).where(Subscription.organization_id == organization_id)
        )).scalar_one_or_none()
        if existing is None:
            session.add(Subscription(
                organization_id=organization_id,
                plan_code=plan_code,
                status="past_due",
                mollie_customer_id=customer_id,
                created_at=now, updated_at=now,
            ))
        else:
            existing.plan_code = plan_code
            existing.status = "past_due"
            existing.mollie_customer_id = customer_id
            existing.updated_at = now


# ---------------------------------------------------------------------------
# Webhook (POST /billing/webhook/{token})
# ---------------------------------------------------------------------------

async def handle_webhook_payment(payment_id: str) -> None:
    """Process one payment webhook event from Mollie.

    Mollie sends `id=tr_xxx` — we refetch the payment to verify and
    to avoid trusting the delivery-time state. Four outcomes:

      - First payment paid → create real subscription + set_plan.
      - Recurring payment paid → bump current_period_end, leave
        status=`active`.
      - Payment failed/expired on first attempt → mark past_due but
        keep the customer id so the user can retry.
      - Anything else → idempotent no-op + WARN log (Mollie may
        retry).

    Idempotency is critical: Mollie retries on non-2xx and sometimes
    double-delivers on flaky networks. Every branch below must be
    safe to run twice.
    """
    client = get_mollie_client()
    try:
        payment = await client.get_payment(payment_id)
    except MollieError as e:
        log.warning("webhook: refusing to process unknown payment %s: %s", payment_id, e)
        return  # don't crash — Mollie will retry if this was transient

    customer_id = payment.get("customerId")
    status_mollie = payment.get("status")
    metadata = payment.get("metadata") or {}
    kind = metadata.get("kind")
    plan_code_from_meta = metadata.get("plan_code")
    organization_id_from_meta = metadata.get("organization_id")

    if not customer_id:
        log.warning("webhook: payment %s has no customerId, skipping", payment_id)
        return

    # Look up our subscription row by customer id.
    async with session_scope() as session:
        sub = (await session.execute(
            select(Subscription).where(Subscription.mollie_customer_id == customer_id)
        )).scalar_one_or_none()

    if sub is None:
        # Race: the webhook fired before our upsert committed (or we
        # lost the row somehow). Try metadata fallback so a freshly-
        # completed checkout isn't stranded.
        if organization_id_from_meta:
            log.warning(
                "webhook: no subscription row for customer %s, recovering via metadata org %s",
                customer_id, organization_id_from_meta,
            )
            await _upsert_pending(
                organization_id=organization_id_from_meta,
                customer_id=customer_id,
                plan_code=plan_code_from_meta or "free",
            )
            async with session_scope() as session:
                sub = (await session.execute(
                    select(Subscription).where(
                        Subscription.organization_id == organization_id_from_meta
                    )
                )).scalar_one_or_none()
        if sub is None:
            log.warning("webhook: abandoning payment %s — no subscription row", payment_id)
            return

    organization_id = sub.organization_id
    intended_plan = plan_code_from_meta or sub.plan_code

    if status_mollie == "paid":
        if kind == "first_payment" and not sub.mollie_subscription_id:
            # First payment cleared → spin up the recurring subscription.
            await _activate_subscription(
                client, sub=sub,
                organization_id=organization_id,
                plan_code=intended_plan,
            )
        else:
            # Recurring charge (or a rerun of a handled first payment):
            # just refresh the billing window.
            await _mark_active_period(organization_id)
    elif status_mollie in ("failed", "canceled", "expired"):
        log.info("webhook: payment %s %s for org %s", payment_id, status_mollie, organization_id)
        await _mark_past_due(organization_id)
    else:
        # 'open' / 'pending' / 'authorized' — nothing to do yet. Mollie
        # will hit the webhook again once the final status is known.
        log.debug("webhook: payment %s in state %s; waiting", payment_id, status_mollie)


async def _activate_subscription(
    client: MollieClient, *, sub: Subscription,
    organization_id: str, plan_code: str,
) -> None:
    """Create the Mollie subscription AFTER a first-payment settles,
    then flip our DB row to ``active`` + the paid ``plan_code``."""
    plan = get_plan(plan_code)
    sub_resp = await client.create_subscription(
        customer_id=sub.mollie_customer_id or "",
        amount_cents=plan.price_eur_cents,
        interval="1 month",
        description=_subscription_description(plan),
        webhook_url=_webhook_url(),
        metadata={
            "organization_id": organization_id,
            "plan_code": plan.code,
            "kind": "recurring",
        },
    )
    mollie_sub_id = sub_resp.get("id")
    next_payment = sub_resp.get("nextPaymentDate")   # YYYY-MM-DD

    # `set_plan` handles the upsert and stamps `status="active"` —
    # we just have to fold the Mollie-specific fields in.
    await set_plan(organization_id, plan.code)
    now = _now_iso()
    async with session_scope() as session:
        row = (await session.execute(
            select(Subscription).where(Subscription.organization_id == organization_id)
        )).scalar_one_or_none()
        if row is not None:
            row.mollie_subscription_id = mollie_sub_id
            row.current_period_start = now
            row.current_period_end = next_payment
            row.updated_at = now


async def _mark_active_period(organization_id: str) -> None:
    """Refresh the billing window after a recurring charge cleared."""
    now = _now_iso()
    async with session_scope() as session:
        row = (await session.execute(
            select(Subscription).where(Subscription.organization_id == organization_id)
        )).scalar_one_or_none()
        if row is not None:
            row.status = "active"
            row.current_period_start = now
            row.updated_at = now


async def _mark_past_due(organization_id: str) -> None:
    now = _now_iso()
    async with session_scope() as session:
        row = (await session.execute(
            select(Subscription).where(Subscription.organization_id == organization_id)
        )).scalar_one_or_none()
        if row is not None:
            row.status = "past_due"
            row.updated_at = now


# ---------------------------------------------------------------------------
# Cancel (POST /billing/cancel)
# ---------------------------------------------------------------------------

async def cancel_org_subscription(organization_id: str) -> dict[str, Any]:
    """Tell Mollie to stop future charges and mark our row ``canceled``.

    We keep ``plan_code`` at whatever it was until the current billing
    period ends — the user paid for this month; they keep the quota.
    A cron could flip to free at ``current_period_end`` (future work).
    """
    async with session_scope() as session:
        sub = (await session.execute(
            select(Subscription).where(Subscription.organization_id == organization_id)
        )).scalar_one_or_none()
    if sub is None or not sub.mollie_subscription_id:
        return {"status": "no_active_subscription"}

    client = get_mollie_client()
    await client.cancel_subscription(
        customer_id=sub.mollie_customer_id or "",
        subscription_id=sub.mollie_subscription_id,
    )

    now = _now_iso()
    async with session_scope() as session:
        row = (await session.execute(
            select(Subscription).where(Subscription.organization_id == organization_id)
        )).scalar_one_or_none()
        if row is not None:
            row.status = "canceled"
            row.updated_at = now
    return {"status": "canceled"}


# ---------------------------------------------------------------------------
# Organisation helper
# ---------------------------------------------------------------------------

async def resolve_organization_name(organization_id: str) -> str:
    """Used to seed the Mollie customer record. Falls back gracefully
    if the org row is gone — we don't want a billing call to 500 just
    because a rename is in flight."""
    async with session_scope() as session:
        org = (await session.execute(
            select(Organization).where(Organization.id == organization_id)
        )).scalar_one_or_none()
    return org.name if org is not None else "unknown organization"
