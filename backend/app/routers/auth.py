"""Auth endpoints: signup, login, /me.

POST /auth/signup creates the user AND a personal organization in one
shot — every account ships with a default tenant so they can scan
immediately. POST /auth/login returns a bearer JWT. GET /auth/me echoes
the resolved user (used by the frontend to confirm a stored token is
still valid after a reload).
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import and_, delete, func, select

from app.audit import log_action
from app.auth import (
    AuthedUser,
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.billing.checkout import cancel_org_subscription
from app.billing.mollie import MollieError
from app.db import session_scope
from app.db_models import Membership, Organization, User
from app.observability import metrics as obs_metrics
from app.security.rate_limit import auth_rate_limiter, client_ip


log = logging.getLogger("auth.router")


router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)
    display_name: str | None = Field(default=None, max_length=120)
    organization_name: str | None = Field(default=None, max_length=120)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "MeResponse"


class MeResponse(BaseModel):
    id: str
    email: str
    display_name: str | None
    # Phase 4: lets the frontend decide whether to render the /admin
    # entry point. Every endpoint still re-checks the flag server-side.
    is_superuser: bool = False


TokenResponse.model_rebuild()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _slug_from_name(name: str) -> str:
    # Lowercase, ASCII letters/digits/dash only; collapse runs of dashes;
    # append a short random suffix to avoid collisions across orgs that
    # picked the same name.
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "org"
    suffix = uuid.uuid4().hex[:6]
    return f"{base[:60]}-{suffix}"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def signup(req: SignupRequest, request: Request) -> TokenResponse:
    # Per-IP rate limit BEFORE any bcrypt work — a flood of signup
    # attempts would otherwise burn CPU hashing garbage passwords.
    auth_rate_limiter.check(f"auth:{client_ip(request)}")

    user_id = uuid.uuid4().hex[:12]
    org_id = uuid.uuid4().hex[:12]
    membership_id = uuid.uuid4().hex[:12]
    now = _now_iso()
    org_name = req.organization_name or (req.display_name or req.email.split("@")[0]) + "'s workspace"

    async with session_scope() as session:
        # Reject duplicate email up front — UNIQUE constraint also catches
        # this but a clean 409 is friendlier than a generic 500.
        existing = (await session.execute(
            select(User.id).where(User.email == req.email)
        )).scalar_one_or_none()
        if existing is not None:
            obs_metrics.auth_attempts_total.labels("signup", "duplicate_email").inc()
            raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")

        session.add(User(
            id=user_id, email=req.email, password_hash=hash_password(req.password),
            display_name=req.display_name, created_at=now,
        ))
        session.add(Organization(
            id=org_id, name=org_name, slug=_slug_from_name(org_name), created_at=now,
        ))
        # Flush so the FKs referenced below resolve to existing rows.
        # Without declared relationships(), SA's unit-of-work can't
        # topo-sort these — so we sort by hand.
        await session.flush()
        session.add(Membership(
            id=membership_id, user_id=user_id, organization_id=org_id,
            role="owner", created_at=now,
        ))

    obs_metrics.auth_attempts_total.labels("signup", "ok").inc()
    return TokenResponse(
        access_token=create_access_token(user_id=user_id, email=req.email),
        user=MeResponse(id=user_id, email=req.email, display_name=req.display_name),
    )


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, request: Request) -> TokenResponse:
    # Same bucket as signup — an attacker can't rotate endpoints to
    # double their budget. bcrypt verification is the expensive step;
    # bouncing before it matters even more than on signup.
    auth_rate_limiter.check(f"auth:{client_ip(request)}")

    async with session_scope() as session:
        user = (await session.execute(
            select(User).where(User.email == req.email)
        )).scalar_one_or_none()
    # Same generic message regardless of whether the email exists — denies
    # an attacker the ability to enumerate accounts.
    if user is None or not verify_password(req.password, user.password_hash):
        obs_metrics.auth_attempts_total.labels("login", "bad_credentials").inc()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    obs_metrics.auth_attempts_total.labels("login", "ok").inc()
    return TokenResponse(
        access_token=create_access_token(user_id=user.id, email=user.email),
        user=MeResponse(
            id=user.id, email=user.email, display_name=user.display_name,
            is_superuser=bool(user.is_superuser),
        ),
    )


@router.get("/me", response_model=MeResponse)
async def me(current: AuthedUser = Depends(get_current_user)) -> MeResponse:
    return MeResponse(
        id=current.id, email=current.email,
        display_name=current.display_name, is_superuser=current.is_superuser,
    )


# ---------------------------------------------------------------------------
# DELETE /auth/me — Phase 8, GDPR Art. 17 right to erasure
# ---------------------------------------------------------------------------

class AccountDeletionResponse(BaseModel):
    """Response shape for a successful self-deletion so the frontend
    can tell the user what else we took down with them."""
    status: str                          # "deleted"
    deleted_user_id: str
    deleted_organization_ids: list[str]
    mollie_subscriptions_canceled: int


async def _find_sole_owner_org_ids(user_id: str) -> list[str]:
    """Return org ids where ``user_id`` is the sole ``role="owner"``.

    Orgs with co-owners stay intact — the user's membership row is
    removed on cascade, but the org (scans, subscription, other
    members) is not their data to erase.
    """
    async with session_scope() as session:
        # Subquery: orgs the user owns.
        my_owner_orgs = (await session.execute(
            select(Membership.organization_id).where(and_(
                Membership.user_id == user_id,
                Membership.role == "owner",
            ))
        )).scalars().all()

        sole: list[str] = []
        for org_id in my_owner_orgs:
            owner_count = (await session.execute(
                select(func.count()).select_from(Membership).where(and_(
                    Membership.organization_id == org_id,
                    Membership.role == "owner",
                ))
            )).scalar_one()
            if owner_count == 1:
                sole.append(org_id)
        return sole


@router.delete("/me", response_model=AccountDeletionResponse)
async def delete_my_account(
    request: Request,
    current: AuthedUser = Depends(get_current_user),
) -> AccountDeletionResponse:
    """GDPR Art. 17 — right to erasure.

    Deletion cascade:

      1. For every organization the user is the SOLE owner of:
           a. cancel the Mollie subscription if one exists
              (best-effort — failure is logged, deletion proceeds so
              the user's right can't be blocked by a billing API
              outage);
           b. delete the organization row → SQLAlchemy cascades drop
              its memberships, scans, and subscription.
      2. For every other organization the user is a member of: their
         membership row is deleted, the org continues.
      3. The user row itself is deleted. ``audit_logs.actor_user_id``
         has ``ON DELETE SET NULL`` — audit rows survive with the
         denormalised ``actor_email`` intact, which is what both GDPR
         traceability and SOC 2 require.
      4. One final audit entry ``user.self_delete`` is written so the
         deletion event itself is traceable.

    The caller's JWT stays cryptographically valid until its TTL
    expires — the frontend is expected to call ``/api/auth/logout``
    immediately after this endpoint returns so the browser stops
    sending the now-orphaned token. ``get_current_user`` will return
    401 on any subsequent request anyway because the user row is gone.
    """
    user_id = current.id
    user_email = current.email

    sole_owner_org_ids = await _find_sole_owner_org_ids(user_id)

    # --- Cancel Mollie subscriptions for orgs that are about to vanish --
    canceled = 0
    for org_id in sole_owner_org_ids:
        try:
            await cancel_org_subscription(org_id)
            canceled += 1
        except (RuntimeError, MollieError) as e:
            # RuntimeError: MOLLIE_API_KEY not configured → billing was
            # in admin-assigned-plans mode; nothing to cancel.
            # MollieError: API call failed → log, proceed. Billing
            # support can refund manually.
            log.warning(
                "mollie cancel failed for org %s during self-delete: %s", org_id, e,
            )

    # --- Write the audit entry BEFORE the delete so session scope order
    #     is predictable (audit + user rows in the same visibility window).
    await log_action(
        action="user.self_delete",
        actor=current,
        target_type="user",
        target_id=user_id,
        details={
            "email": user_email,
            "sole_owner_org_ids": sole_owner_org_ids,
            "mollie_cancellations_attempted": len(sole_owner_org_ids),
            "mollie_cancellations_successful": canceled,
        },
        request=request,
    )

    # --- Delete cascade -----------------------------------------------
    async with session_scope() as session:
        # Orgs first — their cascade handles memberships + scans + subscription.
        for org_id in sole_owner_org_ids:
            await session.execute(
                delete(Organization).where(Organization.id == org_id)
            )
        # Then the user — FK cascade removes remaining memberships.
        await session.execute(delete(User).where(User.id == user_id))

    log.info(
        "self-delete complete: user=%s orgs_removed=%d mollie_canceled=%d",
        user_id, len(sole_owner_org_ids), canceled,
    )
    return AccountDeletionResponse(
        status="deleted",
        deleted_user_id=user_id,
        deleted_organization_ids=sole_owner_org_ids,
        mollie_subscriptions_canceled=canceled,
    )
