"""System-admin endpoints (Phase 4).

All routes sit behind :func:`require_superuser`, so a signed-in but
non-admin user gets 403 — a meaningful signal, unlike the generic 404
the tenant-scoped endpoints use. Every successful write logs an audit
entry via :func:`app.audit.log_action`.

Surface intentionally small:

  - ``GET /admin/users``             — list all users
  - ``GET /admin/organizations``     — list all orgs (with member / scan counts)
  - ``GET /admin/audit``             — paginated audit log
  - ``POST /admin/users/{id}/reset-password`` — set a new password for a user
  - ``POST /admin/users/{id}/promote``        — grant superuser
  - ``POST /admin/users/{id}/demote``         — revoke superuser

No user-delete endpoint yet — it would need to handle the "last
owner of an organization" edge case, which is its own sub-project.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update

from app.audit import log_action
from app.auth import AuthedUser, hash_password, require_superuser
from app.billing.plans import PLANS
from app.billing.subscriptions import set_plan
from app.db import session_scope
from app.db_models import AuditLog, Membership, Organization, Scan, User


router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_superuser)],
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class AdminUser(BaseModel):
    id: str
    email: str
    display_name: str | None
    is_superuser: bool
    created_at: str


class AdminOrganization(BaseModel):
    id: str
    name: str
    slug: str
    created_at: str
    member_count: int
    scan_count: int


class ResetPasswordRequest(BaseModel):
    new_password: str = Field(min_length=10, max_length=200)


class SetPlanRequest(BaseModel):
    plan_code: str = Field(min_length=1, max_length=32)


class AdminAuditEntry(BaseModel):
    id: str
    created_at: str
    actor_user_id: str | None
    actor_email: str | None
    action: str
    target_type: str | None
    target_id: str | None
    details: dict | None
    ip: str | None
    user_agent: str | None


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

@router.get("/users", response_model=list[AdminUser])
async def list_users(
    limit: int = 100,
    _: AuthedUser = Depends(require_superuser),
) -> list[AdminUser]:
    limit = max(1, min(500, limit))
    async with session_scope() as session:
        rows = (await session.execute(
            select(User).order_by(User.created_at.desc()).limit(limit)
        )).scalars().all()
    return [
        AdminUser(
            id=u.id, email=u.email, display_name=u.display_name,
            is_superuser=bool(u.is_superuser), created_at=u.created_at,
        )
        for u in rows
    ]


@router.post("/users/{user_id}/reset-password")
async def reset_password(
    user_id: str,
    req: ResetPasswordRequest,
    request: Request,
    current: AuthedUser = Depends(require_superuser),
) -> dict:
    """Overwrite a user's password hash. No email notification yet —
    the admin is expected to deliver the new password out-of-band."""
    async with session_scope() as session:
        target = (await session.execute(
            select(User).where(User.id == user_id)
        )).scalar_one_or_none()
        if target is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
        await session.execute(
            update(User).where(User.id == user_id)
            .values(password_hash=hash_password(req.new_password))
        )
        target_email = target.email

    await log_action(
        action="user.reset_password",
        actor=current,
        target_type="user",
        target_id=user_id,
        details={"email": target_email},
        request=request,
    )
    return {"ok": True}


@router.post("/users/{user_id}/promote")
async def promote_user(
    user_id: str,
    request: Request,
    current: AuthedUser = Depends(require_superuser),
) -> dict:
    await _toggle_superuser(user_id, value=True, actor=current, request=request)
    return {"ok": True}


@router.post("/users/{user_id}/demote")
async def demote_user(
    user_id: str,
    request: Request,
    current: AuthedUser = Depends(require_superuser),
) -> dict:
    # Guard against self-demotion locking the system out entirely.
    if user_id == current.id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "refusing to demote yourself — use `python -m app.cli.promote --revoke` "
            "from the server if this is intentional",
        )
    await _toggle_superuser(user_id, value=False, actor=current, request=request)
    return {"ok": True}


async def _toggle_superuser(
    user_id: str, *, value: bool, actor: AuthedUser, request: Request,
) -> None:
    async with session_scope() as session:
        target = (await session.execute(
            select(User).where(User.id == user_id)
        )).scalar_one_or_none()
        if target is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
        if bool(target.is_superuser) == value:
            # Idempotent — no state change, no audit row either.
            return
        await session.execute(
            update(User).where(User.id == user_id).values(is_superuser=value)
        )
        target_email = target.email

    await log_action(
        action="user.promote" if value else "user.demote",
        actor=actor,
        target_type="user",
        target_id=user_id,
        details={"email": target_email},
        request=request,
    )


# ---------------------------------------------------------------------------
# Organizations
# ---------------------------------------------------------------------------

@router.get("/organizations", response_model=list[AdminOrganization])
async def list_organizations(
    limit: int = 100,
    _: AuthedUser = Depends(require_superuser),
) -> list[AdminOrganization]:
    limit = max(1, min(500, limit))
    async with session_scope() as session:
        # Raw counts via scalar subqueries — simpler than a window fn and
        # works identically on SQLite + Postgres.
        orgs = (await session.execute(
            select(Organization).order_by(Organization.created_at.desc()).limit(limit)
        )).scalars().all()

        member_counts: dict[str, int] = dict((await session.execute(
            select(Membership.organization_id, func.count())
            .group_by(Membership.organization_id)
        )).all())
        scan_counts: dict[str, int] = dict((await session.execute(
            select(Scan.organization_id, func.count())
            .where(Scan.organization_id.is_not(None))
            .group_by(Scan.organization_id)
        )).all())

    return [
        AdminOrganization(
            id=o.id, name=o.name, slug=o.slug, created_at=o.created_at,
            member_count=member_counts.get(o.id, 0),
            scan_count=scan_counts.get(o.id, 0),
        )
        for o in orgs
    ]


@router.post("/organizations/{organization_id}/set-plan")
async def set_organization_plan(
    organization_id: str,
    req: SetPlanRequest,
    request: Request,
    current: AuthedUser = Depends(require_superuser),
) -> dict:
    """Manual plan assignment for Phase 5a (before Mollie is wired).

    Idempotent: re-setting the same plan is a no-op (still logs the
    action for the audit trail since the admin's intent was to
    re-confirm). Verifies the org exists so a typo can't ghost-create a
    Subscription with a dangling FK.
    """
    if req.plan_code not in PLANS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"unknown plan_code; valid codes: {sorted(PLANS.keys())}",
        )

    async with session_scope() as session:
        org = (await session.execute(
            select(Organization).where(Organization.id == organization_id)
        )).scalar_one_or_none()
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "organization not found")

    sub = await set_plan(organization_id, req.plan_code)

    await log_action(
        action="organization.set_plan",
        actor=current,
        target_type="organization",
        target_id=organization_id,
        details={"plan_code": req.plan_code, "org_name": org.name},
        request=request,
    )
    return {
        "organization_id": organization_id,
        "plan_code": sub.plan_code,
        "status": sub.status,
    }


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

@router.get("/audit", response_model=list[AdminAuditEntry])
async def list_audit(
    limit: int = 100,
    action: str | None = None,
    actor_user_id: str | None = None,
    _: AuthedUser = Depends(require_superuser),
) -> list[AdminAuditEntry]:
    limit = max(1, min(500, limit))
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if actor_user_id:
        stmt = stmt.where(AuditLog.actor_user_id == actor_user_id)
    async with session_scope() as session:
        rows = (await session.execute(stmt)).scalars().all()
    return [
        AdminAuditEntry(
            id=r.id, created_at=r.created_at,
            actor_user_id=r.actor_user_id, actor_email=r.actor_email,
            action=r.action,
            target_type=r.target_type, target_id=r.target_id,
            details=json.loads(r.details) if r.details else None,
            ip=r.ip, user_agent=r.user_agent,
        )
        for r in rows
    ]
