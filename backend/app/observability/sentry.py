"""Sentry bootstrap (Phase 7).

Opt-in via ``SENTRY_DSN``. Without it the SDK is never imported at
runtime — zero overhead on dev + self-hosted deploys that don't want
third-party error telemetry.

What we send:
  - unhandled exceptions from HTTP handlers and background jobs
  - 5xx responses
  - 4xx are NOT sent: they're usually caller errors (bad input, auth)
    and would bury real signal

What we DON'T send:
  - scan payloads, passwords, JWTs, cookie values — the ``before_send``
    hook strips anything that looks like a secret and replaces request
    bodies with their size.
"""

from __future__ import annotations

import logging
from typing import Any


log = logging.getLogger("sentry-init")


def init_sentry_if_configured() -> None:
    """Initialise Sentry exactly once at process start. No-op when
    ``SENTRY_DSN`` is unset. Safe to call multiple times (the SDK
    itself is idempotent)."""
    from app.config import settings

    if not settings.sentry_dsn:
        log.info("sentry: SENTRY_DSN not set; telemetry disabled")
        return

    # Local import so production dev boxes without the package
    # installed still boot. (sentry_sdk is in requirements.txt, but
    # keeping the import lazy is a cheap safety net.)
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
    except ImportError:
        log.warning("sentry: sentry-sdk not installed; skipping initialisation")
        return

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        release=settings.app_version,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        send_default_pii=False,          # don't ship IPs / cookies / users by default
        before_send=_scrub_event,
        integrations=[
            # failed_request_status_codes empty → only 5xx go to Sentry.
            # 4xx are user errors, not application bugs.
            StarletteIntegration(failed_request_status_codes=set()),
            FastApiIntegration(failed_request_status_codes=set()),
        ],
    )
    log.info("sentry: initialised (release=%s)", settings.app_version)


def _scrub_event(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    """Drop likely-secret fields before events leave the process.

    Sentry's default PII scrubber is decent, but scan payloads contain
    URL fragments + cookie-value snippets we don't want forwarded
    anywhere even by accident. Strip broadly.
    """
    # 1. Request body — replace with a length marker. Even a SCAN response
    #    can include hostnames we don't want on another vendor's infra.
    req = event.get("request") or {}
    if "data" in req:
        data = req["data"]
        size = len(data) if isinstance(data, (str, bytes, list, dict)) else "?"
        req["data"] = f"<scrubbed, size={size}>"

    # 2. Headers — drop authorization + cookie unconditionally.
    headers = req.get("headers") or {}
    if isinstance(headers, dict):
        for name in list(headers.keys()):
            if name.lower() in {"authorization", "cookie", "x-forwarded-for"}:
                headers[name] = "<redacted>"

    # 3. Common secret-like extra fields.
    extra = event.get("extra") or {}
    if isinstance(extra, dict):
        for name in list(extra.keys()):
            if any(tok in name.lower() for tok in ("password", "token", "secret", "api_key")):
                extra[name] = "<redacted>"

    return event
