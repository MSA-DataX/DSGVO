"""Read-only billing endpoints (Phase 5a).

GET /billing/plans         — public, lists plan catalogue for pricing pages
GET /billing/subscription  — authed, returns the caller's plan + usage meter

Write paths (checkout, cancel, webhook) land in Phase 5b once Mollie is
wired up. For now admins can swap an org's plan via
POST /admin/organizations/{id}/set-plan.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.auth import AuthedUser, get_current_user
from app.billing.checkout import (
    cancel_org_subscription,
    handle_webhook_payment,
    resolve_organization_name,
    start_checkout,
)
from app.billing.mollie import MollieError
from app.billing.plans import PLANS, list_plans
from app.billing.subscriptions import get_subscription_summary
from app.config import settings


log = logging.getLogger("billing.router")


router = APIRouter(prefix="/billing", tags=["billing"])


class PlanView(BaseModel):
    code: str
    name: str
    price_eur_cents: int
    monthly_scan_quota: int
    description: str
    is_free: bool
    is_unlimited: bool


class SubscriptionView(BaseModel):
    plan: PlanView
    status: str                 # active | canceled | past_due | no_subscription
    current_period_start: str
    scans_used: int
    scans_quota: int            # 0 == unlimited (mirrors Plan.monthly_scan_quota)
    quota_remaining: int        # negative once past the allowance


def _to_plan_view(p) -> PlanView:
    return PlanView(
        code=p.code, name=p.name,
        price_eur_cents=p.price_eur_cents,
        monthly_scan_quota=p.monthly_scan_quota,
        description=p.description,
        is_free=p.is_free, is_unlimited=p.is_unlimited,
    )


@router.get("/plans", response_model=list[PlanView])
async def get_plans() -> list[PlanView]:
    # Public: pricing pages / marketing site hit this before login.
    return [_to_plan_view(p) for p in list_plans()]


@router.get("/subscription", response_model=SubscriptionView)
async def get_my_subscription(
    current: AuthedUser = Depends(get_current_user),
) -> SubscriptionView:
    summary = await get_subscription_summary(current.organization_id)
    return SubscriptionView(
        plan=_to_plan_view(summary.plan),
        status=summary.status,
        current_period_start=summary.current_period_start,
        scans_used=summary.scans_used,
        scans_quota=summary.scans_quota,
        quota_remaining=summary.quota_remaining,
    )


# ---------------------------------------------------------------------------
# Phase 5b — Mollie checkout / webhook / cancel
# ---------------------------------------------------------------------------

class CheckoutRequest(BaseModel):
    plan_code: str = Field(min_length=1, max_length=32)


class CheckoutResponse(BaseModel):
    checkout_url: str


def _require_mollie_configured() -> None:
    """All three env vars must be set or we can't safely operate the
    checkout / cancel / webhook paths. Surface as 503 so the UI can
    show a "billing temporarily unavailable" message instead of
    stamping a half-committed Subscription row."""
    if not (settings.mollie_api_key and settings.app_base_url and settings.mollie_webhook_token):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Mollie billing is not configured on this server. "
            "Admins can still assign plans via /admin/organizations/{id}/set-plan.",
        )


@router.post("/checkout", response_model=CheckoutResponse)
async def checkout(
    req: CheckoutRequest,
    current: AuthedUser = Depends(get_current_user),
) -> CheckoutResponse:
    _require_mollie_configured()
    if req.plan_code not in PLANS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unknown plan_code: {req.plan_code!r}")
    if req.plan_code == "free":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "cannot checkout the free plan — use /admin/organizations/{id}/set-plan "
            "to downgrade an existing subscription",
        )

    org_name = await resolve_organization_name(current.organization_id)
    try:
        url = await start_checkout(
            organization_id=current.organization_id,
            organization_name=org_name,
            buyer_email=current.email,
            plan_code=req.plan_code,
        )
    except MollieError as e:
        log.exception("Mollie checkout failed for org %s", current.organization_id)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"payment provider error: {e}") from e
    return CheckoutResponse(checkout_url=url)


@router.post("/cancel")
async def cancel(
    current: AuthedUser = Depends(get_current_user),
) -> dict:
    _require_mollie_configured()
    try:
        return await cancel_org_subscription(current.organization_id)
    except MollieError as e:
        log.exception("Mollie cancel failed for org %s", current.organization_id)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"payment provider error: {e}") from e


@router.post("/webhook/{token}")
async def mollie_webhook(token: str, request: Request) -> dict:
    """Mollie POSTs `id=tr_xxx` (form-encoded) here every time a
    payment changes state. We authenticate by comparing the URL
    path token against `MOLLIE_WEBHOOK_TOKEN`, then re-fetch the
    payment from Mollie before touching any DB row. Handler is
    idempotent: Mollie retries on non-2xx and occasionally
    double-delivers on flaky networks."""
    _require_mollie_configured()
    expected = settings.mollie_webhook_token or ""
    # Constant-time compare so token length / prefix can't be probed.
    import hmac
    if not hmac.compare_digest(token, expected):
        # 404 (not 403) so probers can't distinguish "no such endpoint"
        # from "wrong token".
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")

    form = await request.form()
    payment_id = form.get("id")
    if not isinstance(payment_id, str) or not payment_id:
        # Return 2xx: a malformed delivery shouldn't cause Mollie to
        # retry forever. Log loudly so operators notice.
        log.warning("mollie webhook received without payment id: form=%r", dict(form))
        return {"status": "ignored"}

    await handle_webhook_payment(payment_id)
    return {"status": "ok"}
