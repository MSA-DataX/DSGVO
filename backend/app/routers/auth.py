"""Auth endpoints: signup, login, /me.

POST /auth/signup creates the user AND a personal organization in one
shot — every account ships with a default tenant so they can scan
immediately. POST /auth/login returns a bearer JWT. GET /auth/me echoes
the resolved user (used by the frontend to confirm a stored token is
still valid after a reload).
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select

from app.auth import (
    AuthedUser,
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.db import session_scope
from app.db_models import Membership, Organization, User
from app.observability import metrics as obs_metrics
from app.security.rate_limit import auth_rate_limiter, client_ip


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
