"""Privileged-action audit log (Phase 4).

Single public helper — :func:`log_action` — called by every admin
endpoint after the guarded operation completed successfully. The
record is append-only from the app layer (no update / delete code
path exists); operators who need retention control should handle it
at the database level.

Design notes:

- ``actor`` is ``None`` for CLI / migration actions. The first
  promotion bootstrapping the system has nobody to attribute it to,
  and we still want the event recorded.
- ``details`` is a free-form dict, serialised as JSON. Keep it small
  and PII-free: field names like "new_display_name" are fine; the
  *old* password hash or the plaintext of a user's scan payload are
  not. Convention #18 spells this out.
- Writes use their own ``session_scope`` so a failure in the audit
  path never rolls back the privileged operation the caller already
  committed. (Trading strict transactional consistency for the
  ability to finish the user-visible action.)
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import Request

from app.auth import AuthedUser
from app.db import session_scope
from app.db_models import AuditLog


log = logging.getLogger("audit")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _client_ip(request: Request | None) -> str | None:
    if request is None:
        return None
    xff = request.headers.get("x-forwarded-for")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else None


def _user_agent(request: Request | None) -> str | None:
    if request is None:
        return None
    ua = request.headers.get("user-agent")
    if ua and len(ua) > 512:
        return ua[:512]
    return ua


async def log_action(
    *,
    action: str,
    actor: AuthedUser | None = None,
    actor_email: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    details: dict[str, Any] | None = None,
    request: Request | None = None,
) -> None:
    """Append one entry to the audit log.

    ``actor`` takes precedence for id + email; if absent (system
    action), ``actor_email`` alone is acceptable. Either way the
    action must be a short dotted-namespace string like
    ``"user.promote"`` — ad-hoc strings scatter across queries.
    """
    serialised = json.dumps(details, ensure_ascii=False) if details else None
    try:
        async with session_scope() as session:
            session.add(AuditLog(
                id=uuid.uuid4().hex[:12],
                created_at=_now_iso(),
                actor_user_id=actor.id if actor else None,
                actor_email=(actor.email if actor else actor_email),
                action=action,
                target_type=target_type,
                target_id=target_id,
                details=serialised,
                ip=_client_ip(request),
                user_agent=_user_agent(request),
            ))
    except Exception:
        # An audit write must never crash the privileged operation we
        # just performed. Log locally and move on — operators can
        # grep server logs to catch blind spots.
        log.exception("audit log insert failed: action=%s target=%s", action, target_id)
