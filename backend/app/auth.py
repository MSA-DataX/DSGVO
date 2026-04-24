"""Authentication primitives.

Pure functions (hash/verify password, encode/decode JWT) plus a single
FastAPI dependency ``get_current_user`` that protected routes can declare.

The JWT carries: ``sub`` (user id), ``email``, ``exp``. No org membership
in the token — orgs are looked up server-side via the user's memberships
so revoking access is one DB write, not "wait for token to expire".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from app.config import settings
from app.db import session_scope
from app.db_models import Membership, User


# Optional bearer — we want our own 401 message, not FastAPI's default.
_bearer = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------

def hash_password(plain: str) -> str:
    """Bcrypt hash with cost 12 (~250ms on a modern CPU)."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        # Malformed hash — treat as failed auth, never raise to caller.
        return False


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------

def create_access_token(*, user_id: str, email: str) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": user_id,
        "email": email,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.jwt_ttl_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """Returns the decoded payload or raises HTTPException(401)."""
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token expired") from e
    except jwt.InvalidTokenError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from e


# ---------------------------------------------------------------------------
# Current-user dependency
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AuthedUser:
    id: str
    email: str
    display_name: str | None
    # Phase 1.3: every authed request also carries the organization it
    # should operate on. For now this is the user's oldest membership
    # (created at signup). Multi-org users will later pick one via an
    # explicit header; keeping the resolution here means callers always
    # get a non-None value.
    organization_id: str
    # Phase 4: system-wide admin flag. Checked by `require_superuser`
    # for /admin endpoints. Normal endpoints ignore it — this is a
    # separate privilege dimension from the organization role.
    is_superuser: bool = False


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthedUser:
    """Decode the bearer token and resolve the user from the DB.

    Hitting the DB on every request is intentional — it lets the operator
    revoke a session by deleting/disabling the user without waiting for
    the JWT TTL to elapse. Also resolves the primary organization so
    downstream handlers don't have to care about the join.
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    payload = decode_access_token(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token claims")
    async with session_scope() as session:
        user = (await session.execute(
            select(User).where(User.id == user_id)
        )).scalar_one_or_none()
        if user is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User no longer exists")
        org_id = (await session.execute(
            select(Membership.organization_id)
            .where(Membership.user_id == user.id)
            .order_by(Membership.created_at.asc())
            .limit(1)
        )).scalar_one_or_none()
    if org_id is None:
        # Should be unreachable: signup always creates a membership. Hit
        # this only if a future migration / admin action orphaned a user.
        raise HTTPException(status.HTTP_403_FORBIDDEN, "User has no organization")
    return AuthedUser(
        id=user.id, email=user.email,
        display_name=user.display_name, organization_id=org_id,
        is_superuser=bool(user.is_superuser),
    )


async def require_superuser(
    current: AuthedUser = Depends(get_current_user),
) -> AuthedUser:
    """Dependency for /admin/* endpoints.

    Returns 403 (not 401) when the caller is authenticated but not a
    superuser — the distinction matters for logs: 401 means "who are
    you?", 403 means "I know who you are and you can't do this". Both
    help an attacker learn less than a generic 500 would, but the
    semantic distinction is valuable for the operator reviewing logs.
    """
    if not current.is_superuser:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Superuser privilege required")
    return current
