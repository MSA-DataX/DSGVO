"""Per-tenant rate limiting.

In-memory sliding window — good enough for a single-node deployment.
When the app moves to multiple workers / nodes (Phase 3), swap the
storage for Redis and leave the public interface identical.

Why sliding-window + a deque (not a token bucket): the dominant UX
signal is "how many scans have I run in the last minute / hour / day"
and the deque lets us answer all three from one structure with no
drift. Token buckets are cheaper per hit but the user-visible limit
phrasing ("50 per day") is awkward to express.
"""

from __future__ import annotations

from collections import defaultdict, deque
from time import monotonic
from typing import Deque

from fastapi import HTTPException, Request, status


# The default limits are intentionally conservative for a single-tenant
# dev deploy; tenants on paid plans will bump these via per-plan
# overrides once billing exists (Phase 4).
_DEFAULT_PER_MINUTE = 3
_DEFAULT_PER_DAY = 50

_WINDOW_MINUTE = 60.0
_WINDOW_DAY = 60.0 * 60.0 * 24.0


class RateLimiter:
    """Single bucket class — one instance per distinct policy/endpoint.

    Keys are arbitrary strings; callers typically pass ``f"{endpoint}:{org_id}"``.
    """

    def __init__(self, *, per_minute: int = _DEFAULT_PER_MINUTE, per_day: int = _DEFAULT_PER_DAY):
        self.per_minute = per_minute
        self.per_day = per_day
        self._hits: dict[str, Deque[float]] = defaultdict(deque)

    def reset(self) -> None:
        """Clear all tracked hits. Used by test fixtures to isolate cases."""
        self._hits.clear()

    def check(self, key: str, *, now: float | None = None) -> None:
        """Record a hit on ``key`` or raise HTTPException(429).

        Accepts an injected ``now`` so tests can advance the clock without
        sleeping. In production always call with no argument.
        """
        t = monotonic() if now is None else now
        dq = self._hits[key]

        # Drop timestamps outside the 24h window. O(k) where k = expiring
        # entries; amortised O(1) per hit.
        while dq and dq[0] < t - _WINDOW_DAY:
            dq.popleft()

        count_day = len(dq)
        count_minute = sum(1 for ts in dq if ts > t - _WINDOW_MINUTE)

        if count_minute >= self.per_minute:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded: {self.per_minute} scans/minute. "
                       f"Try again in a moment.",
                headers={"Retry-After": "60"},
            )
        if count_day >= self.per_day:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Daily rate limit exceeded: {self.per_day} scans in 24 hours. "
                       f"Contact sales for a higher limit.",
                headers={"Retry-After": str(int(_WINDOW_DAY))},
            )

        dq.append(t)


# Module-level singleton used by /scan and /scan/stream. Tests monkey-
# patch `.reset()` in a fixture to keep cases isolated.
scan_rate_limiter = RateLimiter(per_minute=_DEFAULT_PER_MINUTE, per_day=_DEFAULT_PER_DAY)


# Separate bucket for /auth/signup + /auth/login. Keyed by client IP
# rather than org_id (the user has no org_id yet / an attacker uses
# many disposable signups, so per-tenant keys would be useless). Both
# endpoints share the same bucket so an attacker can't rotate between
# signup and login to double their budget.
#
# Budget sized for humans-with-typos (5 attempts per minute) but tight
# enough that a credential-stuffing bot hits the ceiling fast. Day limit
# is loose — we only want to drain unusually aggressive sources.
auth_rate_limiter = RateLimiter(per_minute=5, per_day=50)


def client_ip(request: Request) -> str:
    """Best-effort client IP, honouring a single X-Forwarded-For hop.

    Only trust ``X-Forwarded-For`` when running behind a reverse proxy
    we control (dev: localhost; prod: nginx/caddy/ingress). Taking the
    left-most value is the common convention — that's the original
    client before any intermediate proxies added themselves.
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"
