"""Tests for the per-tenant rate limiter.

The limiter takes an injectable ``now`` so we can exercise the sliding
window without sleeping. Real deploys always pass ``None`` and use
``monotonic()``; tests feed explicit timestamps.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.security.rate_limit import RateLimiter


class TestPerMinuteBucket:
    def test_allows_up_to_limit(self):
        rl = RateLimiter(per_minute=3, per_day=1000)
        for _ in range(3):
            rl.check("org:A", now=0.0)

    def test_rejects_over_minute_limit(self):
        rl = RateLimiter(per_minute=3, per_day=1000)
        for _ in range(3):
            rl.check("org:A", now=0.0)
        with pytest.raises(HTTPException) as exc:
            rl.check("org:A", now=0.5)
        assert exc.value.status_code == 429
        assert "per minute" in exc.value.detail.lower() or "minute" in exc.value.detail.lower()

    def test_permits_again_after_minute_window(self):
        rl = RateLimiter(per_minute=2, per_day=1000)
        rl.check("org:A", now=0.0)
        rl.check("org:A", now=0.1)
        with pytest.raises(HTTPException):
            rl.check("org:A", now=0.2)
        # Advance 61s — the two old hits slide out of the minute window.
        rl.check("org:A", now=61.0)
        rl.check("org:A", now=61.1)

    def test_429_includes_retry_after_header(self):
        rl = RateLimiter(per_minute=1, per_day=1000)
        rl.check("org:A", now=0.0)
        with pytest.raises(HTTPException) as exc:
            rl.check("org:A", now=0.1)
        assert exc.value.headers is not None
        assert "Retry-After" in exc.value.headers


class TestPerDayBucket:
    def test_rejects_over_day_limit(self):
        rl = RateLimiter(per_minute=1000, per_day=5)
        # 5 hits spread across the day so we never hit the per-minute cap.
        for i in range(5):
            rl.check("org:A", now=i * 120.0)  # 2 minutes apart
        with pytest.raises(HTTPException) as exc:
            rl.check("org:A", now=5 * 120.0)
        assert exc.value.status_code == 429
        assert "day" in exc.value.detail.lower() or "daily" in exc.value.detail.lower()

    def test_permits_again_after_day_window(self):
        rl = RateLimiter(per_minute=1000, per_day=2)
        rl.check("org:A", now=0.0)
        rl.check("org:A", now=10.0)
        with pytest.raises(HTTPException):
            rl.check("org:A", now=20.0)
        # > 24h later, both hits are expired.
        rl.check("org:A", now=86_500.0)


class TestIsolationBetweenKeys:
    def test_different_keys_do_not_share_budget(self):
        rl = RateLimiter(per_minute=2, per_day=1000)
        rl.check("org:A", now=0.0)
        rl.check("org:A", now=0.1)
        # org B should be unaffected by org A's exhaustion.
        rl.check("org:B", now=0.2)
        rl.check("org:B", now=0.3)
        with pytest.raises(HTTPException):
            rl.check("org:A", now=0.4)
        with pytest.raises(HTTPException):
            rl.check("org:B", now=0.5)


class TestReset:
    def test_reset_clears_all_buckets(self):
        rl = RateLimiter(per_minute=1, per_day=1000)
        rl.check("org:A", now=0.0)
        with pytest.raises(HTTPException):
            rl.check("org:A", now=0.1)
        rl.reset()
        # Post-reset should accept again — useful between test cases.
        rl.check("org:A", now=0.2)
