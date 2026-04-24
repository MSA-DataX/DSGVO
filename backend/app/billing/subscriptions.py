"""Subscription + quota helpers.

Keeps the Plan + DB row + usage-count concerns together so scan
endpoints only have to call :func:`check_scan_quota` (for enforcement)
or :func:`get_subscription_summary` (for the read API).

Usage period semantics: Phase 5a resets quotas on the first of each
calendar month (UTC). No pro-rata, no trial periods, no rollover.
Phase 5b will replace this with Mollie's own period boundaries once
subscriptions are real.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select

from app.billing.plans import Plan, get_plan
from app.db import session_scope
from app.db_models import Scan, Subscription


@dataclass(frozen=True)
class SubscriptionSummary:
    """Snapshot returned by GET /billing/subscription.

    ``scans_used`` and ``scans_quota`` speak the same language (both
    are per-calendar-month counts). ``quota_remaining`` is negative
    when a customer is past their allowance — surface that in the UI
    rather than silently clamping to zero so the user knows where they
    stand.
    """
    plan: Plan
    status: str                        # active | canceled | past_due | no_subscription
    current_period_start: str          # ISO-8601; first of month for Phase 5a
    scans_used: int
    scans_quota: int                   # 0 => unlimited (mirrors Plan.monthly_scan_quota)
    quota_remaining: int               # negative once past the allowance


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _month_start_iso() -> str:
    """First-of-current-month at 00:00 UTC. Quota counter bound."""
    now = datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start.isoformat(timespec="seconds")


async def _load_subscription(organization_id: str) -> Subscription | None:
    async with session_scope() as session:
        return (await session.execute(
            select(Subscription).where(Subscription.organization_id == organization_id)
        )).scalar_one_or_none()


async def _count_scans_since(organization_id: str, since_iso: str) -> int:
    async with session_scope() as session:
        count = (await session.execute(
            select(func.count()).select_from(Scan).where(and_(
                Scan.organization_id == organization_id,
                Scan.created_at >= since_iso,
            ))
        )).scalar_one()
    return int(count or 0)


async def get_subscription_summary(organization_id: str) -> SubscriptionSummary:
    """Compose the billing view of one org — the single source of
    truth used by both the enforcement path and the read API."""
    sub = await _load_subscription(organization_id)
    if sub is None:
        plan = get_plan(None)          # free tier
        sub_status = "no_subscription"
        period_start = _month_start_iso()
    else:
        plan = get_plan(sub.plan_code)
        sub_status = sub.status
        # If Phase 5b has filled in a real billing period, honour it.
        # Otherwise use the first-of-month fallback.
        period_start = sub.current_period_start or _month_start_iso()

    used = await _count_scans_since(organization_id, period_start)
    quota = plan.monthly_scan_quota
    remaining = -1 if plan.is_unlimited else (quota - used)

    return SubscriptionSummary(
        plan=plan,
        status=sub_status,
        current_period_start=period_start,
        scans_used=used,
        scans_quota=quota,
        quota_remaining=remaining,
    )


async def check_scan_quota(organization_id: str) -> None:
    """Raise 402 Payment Required when the caller has used up their
    month's allowance. Called inside /scan, /scan/stream, /scan/jobs
    handlers — after SSRF + rate-limit so those failures don't burn
    budget and 402 stays a genuinely "you used your allocation" signal.
    """
    summary = await get_subscription_summary(organization_id)
    if summary.plan.is_unlimited:
        return
    if summary.scans_used >= summary.plan.monthly_scan_quota:
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "message": (
                    f"Monthly scan quota exceeded ({summary.scans_used}/"
                    f"{summary.plan.monthly_scan_quota} on plan '{summary.plan.code}'). "
                    "Upgrade at /billing/plans or wait until the next calendar month."
                ),
                "plan": summary.plan.code,
                "scans_used": summary.scans_used,
                "scans_quota": summary.plan.monthly_scan_quota,
            },
        )


async def set_plan(organization_id: str, plan_code: str) -> Subscription:
    """Idempotent plan upsert. Raises ValueError on unknown plan code.

    Phase 5a only — invoked from the admin endpoint for manual
    assignment. Phase 5b calls this from the Mollie webhook handler
    after a successful payment.
    """
    if plan_code not in {"free", "pro", "business"}:
        # Guard against typos reaching the DB. The plans module is the
        # source of truth; a `get_plan` lookup would silently fall
        # back to free which is a footgun for an admin tool.
        from app.billing.plans import PLANS
        if plan_code not in PLANS:
            raise ValueError(f"unknown plan_code: {plan_code!r}")

    now = _now_iso()
    async with session_scope() as session:
        existing = (await session.execute(
            select(Subscription).where(Subscription.organization_id == organization_id)
        )).scalar_one_or_none()

        if existing is None:
            sub = Subscription(
                organization_id=organization_id,
                plan_code=plan_code,
                status="active",
                created_at=now, updated_at=now,
            )
            session.add(sub)
        else:
            existing.plan_code = plan_code
            existing.status = "active"
            existing.updated_at = now
            sub = existing

    # Reload outside the `session_scope` so the returned object is
    # detached and safe to serialise.
    refreshed = await _load_subscription(organization_id)
    assert refreshed is not None
    return refreshed
