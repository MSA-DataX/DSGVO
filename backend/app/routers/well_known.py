"""/.well-known/* routes — RFC-registered paths that aren't tied to
the product's feature set.

Currently:

  GET /.well-known/security.txt    RFC 9116

The security.txt file tells a researcher who to contact when they
find a vulnerability in the service and how long the declaration is
valid. Shipping it is a baseline SOC2 + ISO 27001 expectation — an
audit checks for it early.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from app.config import settings


router = APIRouter(tags=["well-known"])


def _expires_value() -> str:
    """Return the ``Expires:`` line value.

    RFC 9116 requires this field and demands it be no more than one
    year out. If the operator didn't configure an explicit date we
    default to 365 days from boot — gives them a year to either
    set one or update the deploy.
    """
    if settings.security_txt_expires:
        return settings.security_txt_expires
    return (datetime.now(timezone.utc) + timedelta(days=365)).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")


@router.get("/.well-known/security.txt", include_in_schema=False)
async def security_txt() -> PlainTextResponse:
    """RFC 9116 security.txt — how to responsibly report vulnerabilities."""
    # Build the file as a list of ``Field: value`` lines. Order doesn't
    # matter per the RFC, but ``Contact`` first is convention.
    lines: list[str] = [
        f"Contact: mailto:{settings.security_contact_email}",
        f"Expires: {_expires_value()}",
        "Preferred-Languages: en, de",
    ]
    if settings.security_policy_url:
        lines.append(f"Policy: {settings.security_policy_url}")
    if settings.security_acknowledgments_url:
        lines.append(f"Acknowledgments: {settings.security_acknowledgments_url}")
    # Canonical line: where the file lives. Robust even if the
    # operator also serves it as a static file from Caddy.
    if settings.app_base_url:
        base = settings.app_base_url.rstrip("/")
        lines.append(f"Canonical: {base}/.well-known/security.txt")

    body = "\n".join(lines) + "\n"
    return PlainTextResponse(body, media_type="text/plain; charset=utf-8")
