"""Tests for the auth flow.

Covers signup → login → /me + protection of /scans, plus password
hashing and JWT round-trip primitives. Uses an in-memory SQLite DB so
the suite stays hermetic and parallel-safe; the real app uses the same
SQLAlchemy code path against the file-backed dev DB or Postgres.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app import db as db_module
from app.auth import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.db_models import Base


# ---------------------------------------------------------------------------
# Test DB fixture: per-function in-memory SQLite, isolated from dev/prod.
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def app_with_db(monkeypatch):
    """Swap the module-level engine + session factory to an in-memory DB,
    create the schema, hand back a configured TestClient, then tear down.
    Also resets the module-level scan rate limiter so cases don't
    cross-contaminate via a shared per-minute budget.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.security.rate_limit import auth_rate_limiter, scan_rate_limiter

    # File-less SQLite per test → no leakage between tests, no on-disk
    # artefacts. `uri=true` + `cache=shared` lets multiple connections see
    # the same in-memory DB within one engine.
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    monkeypatch.setattr(db_module, "_engine", engine)
    monkeypatch.setattr(db_module, "_SessionLocal", SessionLocal)

    scan_rate_limiter.reset()
    auth_rate_limiter.reset()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Import lazily so the monkeypatch above takes effect before main.py's
    # module-level code resolves the engine.
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client

    await engine.dispose()


# ---------------------------------------------------------------------------
# Pure-function primitives
# ---------------------------------------------------------------------------

class TestPasswordHashing:
    def test_hash_then_verify_roundtrip(self):
        h = hash_password("correct horse battery staple")
        assert verify_password("correct horse battery staple", h) is True

    def test_verify_rejects_wrong_password(self):
        h = hash_password("right one")
        assert verify_password("wrong one", h) is False

    def test_hash_is_not_reversible(self):
        h = hash_password("plaintext-secret")
        assert "plaintext-secret" not in h

    def test_verify_handles_malformed_hash_safely(self):
        # Malformed hashes must NOT raise — they're treated as "no match".
        assert verify_password("anything", "not-a-real-hash") is False


class TestJwt:
    def test_roundtrip(self):
        token = create_access_token(user_id="u-123", email="x@example.com")
        decoded = decode_access_token(token)
        assert decoded["sub"] == "u-123"
        assert decoded["email"] == "x@example.com"
        assert "exp" in decoded and "iat" in decoded

    def test_tampered_token_raises_401(self):
        from fastapi import HTTPException
        token = create_access_token(user_id="u-123", email="x@example.com")
        # Mutate the signature segment
        bad = token[:-4] + "AAAA"
        with pytest.raises(HTTPException) as exc:
            decode_access_token(bad)
        assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# HTTP flow
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestSignupLoginMe:
    async def test_signup_creates_user_and_returns_token(self, app_with_db):
        r = await app_with_db.post("/auth/signup", json={
            "email": "alice@example.com",
            "password": "long-enough-password",
            "display_name": "Alice",
        })
        assert r.status_code == 201
        body = r.json()
        assert body["access_token"]
        assert body["user"]["email"] == "alice@example.com"
        assert body["user"]["display_name"] == "Alice"

    async def test_signup_rejects_short_password(self, app_with_db):
        r = await app_with_db.post("/auth/signup", json={
            "email": "shorty@example.com",
            "password": "tiny",  # < 10 chars
        })
        assert r.status_code == 422

    async def test_signup_rejects_invalid_email(self, app_with_db):
        r = await app_with_db.post("/auth/signup", json={
            "email": "not-an-email",
            "password": "long-enough-password",
        })
        assert r.status_code == 422

    async def test_signup_duplicate_email_returns_409(self, app_with_db):
        payload = {"email": "dup@example.com", "password": "long-enough-pw1"}
        r1 = await app_with_db.post("/auth/signup", json=payload)
        assert r1.status_code == 201
        r2 = await app_with_db.post("/auth/signup", json=payload)
        assert r2.status_code == 409

    async def test_login_with_correct_password_returns_token(self, app_with_db):
        await app_with_db.post("/auth/signup", json={
            "email": "bob@example.com", "password": "long-enough-password",
        })
        r = await app_with_db.post("/auth/login", json={
            "email": "bob@example.com", "password": "long-enough-password",
        })
        assert r.status_code == 200
        assert r.json()["access_token"]

    async def test_login_with_wrong_password_returns_401(self, app_with_db):
        await app_with_db.post("/auth/signup", json={
            "email": "carol@example.com", "password": "long-enough-password",
        })
        r = await app_with_db.post("/auth/login", json={
            "email": "carol@example.com", "password": "wrong-pwd-but-long",
        })
        assert r.status_code == 401

    async def test_login_unknown_email_returns_same_401(self, app_with_db):
        # Account-enumeration defence: same status + message regardless of
        # whether the email exists.
        r = await app_with_db.post("/auth/login", json={
            "email": "nobody@example.com", "password": "anything-here-pls",
        })
        assert r.status_code == 401

    async def test_me_with_valid_token_returns_user(self, app_with_db):
        signup = await app_with_db.post("/auth/signup", json={
            "email": "dave@example.com", "password": "long-enough-password",
        })
        token = signup.json()["access_token"]
        r = await app_with_db.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json()["email"] == "dave@example.com"

    async def test_me_without_token_returns_401(self, app_with_db):
        r = await app_with_db.get("/auth/me")
        assert r.status_code == 401

    async def test_me_with_garbage_token_returns_401(self, app_with_db):
        r = await app_with_db.get("/auth/me",
                                  headers={"Authorization": "Bearer not-a-real-jwt"})
        assert r.status_code == 401


@pytest.mark.asyncio
class TestProtectedEndpoints:
    async def test_scan_requires_auth(self, app_with_db):
        r = await app_with_db.post("/scan", json={"url": "https://example.com"})
        assert r.status_code == 401

    async def test_scans_list_requires_auth(self, app_with_db):
        r = await app_with_db.get("/scans")
        assert r.status_code == 401

    async def test_scans_get_requires_auth(self, app_with_db):
        r = await app_with_db.get("/scans/some-id")
        assert r.status_code == 401

    async def test_scans_delete_requires_auth(self, app_with_db):
        r = await app_with_db.delete("/scans/some-id")
        assert r.status_code == 401

    async def test_scans_list_with_token_returns_empty_array(self, app_with_db):
        signup = await app_with_db.post("/auth/signup", json={
            "email": "eve@example.com", "password": "long-enough-password",
        })
        token = signup.json()["access_token"]
        r = await app_with_db.get("/scans", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json() == []

    async def test_health_does_not_require_auth(self, app_with_db):
        # Sanity: monitoring tools shouldn't need a token to ping liveness.
        r = await app_with_db.get("/health")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Cross-tenant isolation (Phase 1.3)
# ---------------------------------------------------------------------------

async def _signup(client, email: str) -> tuple[str, dict]:
    """Sign up a user and return (token, user_dict)."""
    r = await client.post("/auth/signup", json={
        "email": email, "password": "long-enough-password",
        "display_name": email.split("@")[0],
    })
    assert r.status_code == 201, r.text
    body = r.json()
    return body["access_token"], body["user"]


async def _insert_scan_for(client, token: str) -> str:
    """Use the direct storage API to insert a scan owned by ``token``'s org
    without driving Playwright. Returns the new scan id.
    """
    # Resolve the org_id by reading /auth/me... actually /me doesn't return
    # org. Use the authed user's membership via direct DB call. We reach
    # into storage here because that's the only place that sees org_id.
    from sqlalchemy import select
    from app.db import session_scope
    from app.db_models import Membership
    from app.models import (
        ContactChannelsReport, CookieReport, CrawlResult, FormReport,
        NetworkResult, PrivacyAnalysis, RiskScore, ScanResponse,
        ThirdPartyWidgetsReport,
    )
    from app.storage import save_scan

    # Figure out whose token we're holding.
    r = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    user_id = r.json()["id"]

    async with session_scope() as session:
        org_id = (await session.execute(
            select(Membership.organization_id).where(Membership.user_id == user_id)
        )).scalar_one()

    scan = ScanResponse(
        target="https://example.com/",
        risk=RiskScore(score=80, rating="low", weighted_score=80,
                       sub_scores=[], applied_caps=[], recommendations=[]),
        crawl=CrawlResult(start_url="https://example.com/", pages=[],
                          privacy_policy_url=None, imprint_url=None),
        network=NetworkResult(requests=[], data_flow=[]),
        cookies=CookieReport(cookies=[], storage=[], summary={}),
        privacy_analysis=PrivacyAnalysis(
            provider="none", model=None, policy_url=None, summary="",
            issues=[], coverage=None, compliance_score=50,
            error="no_provider_configured",
        ),
        forms=FormReport(forms=[], summary={"total_forms": 0}),
        contact_channels=ContactChannelsReport(channels=[], summary={}),
        widgets=ThirdPartyWidgetsReport(widgets=[], summary={}),
    )
    scan_id, _ = await save_scan(scan, organization_id=org_id)
    return scan_id


@pytest.mark.asyncio
class TestTenantIsolation:
    async def test_list_scans_returns_only_own_tenants_scans(self, app_with_db):
        token_a, _ = await _signup(app_with_db, "alice@example.com")
        token_b, _ = await _signup(app_with_db, "bob@example.com")

        await _insert_scan_for(app_with_db, token_a)
        await _insert_scan_for(app_with_db, token_a)

        r_a = await app_with_db.get("/scans", headers={"Authorization": f"Bearer {token_a}"})
        assert r_a.status_code == 200
        assert len(r_a.json()) == 2

        r_b = await app_with_db.get("/scans", headers={"Authorization": f"Bearer {token_b}"})
        assert r_b.status_code == 200
        assert r_b.json() == []

    async def test_get_scan_by_id_across_tenants_is_404(self, app_with_db):
        token_a, _ = await _signup(app_with_db, "alice2@example.com")
        token_b, _ = await _signup(app_with_db, "bob2@example.com")

        scan_id = await _insert_scan_for(app_with_db, token_a)

        # Owner sees it.
        r_a = await app_with_db.get(
            f"/scans/{scan_id}",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert r_a.status_code == 200

        # Other tenant gets a plain 404 — same response as a nonexistent ID,
        # so existence of A's scan isn't leaked to B.
        r_b = await app_with_db.get(
            f"/scans/{scan_id}",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert r_b.status_code == 404

    async def test_delete_scan_across_tenants_is_404(self, app_with_db):
        token_a, _ = await _signup(app_with_db, "alice3@example.com")
        token_b, _ = await _signup(app_with_db, "bob3@example.com")

        scan_id = await _insert_scan_for(app_with_db, token_a)

        # B tries to delete A's scan → 404 + the row still exists for A.
        r_del = await app_with_db.delete(
            f"/scans/{scan_id}",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert r_del.status_code == 404

        r_a = await app_with_db.get(
            f"/scans/{scan_id}",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert r_a.status_code == 200  # still there

    async def test_delete_scan_by_owner_works(self, app_with_db):
        token_a, _ = await _signup(app_with_db, "alice4@example.com")
        scan_id = await _insert_scan_for(app_with_db, token_a)

        r_del = await app_with_db.delete(
            f"/scans/{scan_id}",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert r_del.status_code == 200
        assert r_del.json() == {"deleted": scan_id}

        # Second delete should 404.
        r_del2 = await app_with_db.delete(
            f"/scans/{scan_id}",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert r_del2.status_code == 404

    async def test_authed_user_has_organization_id(self, app_with_db):
        # Guard against regressions to the auth dependency that would drop
        # the resolved org_id. Unrelated to the fixture but kept in the
        # same class for scope — the existence of this contract is what
        # makes all the other tenant-isolation tests meaningful.
        from app.auth import AuthedUser

        await _signup(app_with_db, "alice5@example.com")
        fields = {f.name for f in AuthedUser.__dataclass_fields__.values()}
        assert "organization_id" in fields


# ---------------------------------------------------------------------------
# /scan boundary guards — SSRF + rate limit (Phase 2)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestScanBoundaryGuards:
    async def test_scan_with_private_ip_is_400(self, app_with_db):
        token, _ = await _signup(app_with_db, "alice6@example.com")
        r = await app_with_db.post(
            "/scan",
            headers={"Authorization": f"Bearer {token}"},
            json={"url": "http://127.0.0.1/"},
        )
        assert r.status_code == 400
        # Message should mention the block reason (loopback/private/etc).
        body = r.json()
        assert "loopback" in body["detail"].lower() or "private" in body["detail"].lower()

    async def test_scan_with_aws_metadata_is_400(self, app_with_db):
        token, _ = await _signup(app_with_db, "alice7@example.com")
        r = await app_with_db.post(
            "/scan",
            headers={"Authorization": f"Bearer {token}"},
            json={"url": "http://169.254.169.254/latest/meta-data/"},
        )
        assert r.status_code == 400

    async def test_scan_with_file_scheme_is_400(self, app_with_db):
        token, _ = await _signup(app_with_db, "alice8@example.com")
        r = await app_with_db.post(
            "/scan",
            headers={"Authorization": f"Bearer {token}"},
            json={"url": "file:///etc/passwd"},
        )
        # pydantic's `HttpUrl` may already reject this at the schema layer
        # (422) — either way, the request MUST NOT reach Playwright.
        assert r.status_code in (400, 422)

    async def test_scan_exceeds_rate_limit_returns_429(self, app_with_db, monkeypatch):
        # Drop the limit to 1/min and stub run_scan so Playwright never
        # launches — the test cares about boundary behaviour, not a real scan.
        from app.security.rate_limit import scan_rate_limiter
        monkeypatch.setattr(scan_rate_limiter, "per_minute", 1)

        async def _fake_run_scan(*_a, **_kw):
            raise RuntimeError("stubbed — Playwright not invoked in tests")

        monkeypatch.setattr("app.main.run_scan", _fake_run_scan)

        token, _ = await _signup(app_with_db, "alice9@example.com")
        payload = {"url": "http://93.184.216.34/"}  # public IP, SSRF passes
        headers = {"Authorization": f"Bearer {token}"}

        # 1st call passes SSRF + rate-limit; stubbed scanner raises → 500.
        r1 = await app_with_db.post("/scan", headers=headers, json=payload)
        assert r1.status_code == 500

        # 2nd call: same caller within 60s → rate-limited before scan runs.
        r2 = await app_with_db.post("/scan", headers=headers, json=payload)
        assert r2.status_code == 429
        assert "Retry-After" in r2.headers

    async def test_signup_rate_limit_blocks_flood_from_same_ip(self, app_with_db, monkeypatch):
        # Tighten the limit so we can trip it quickly. The TestClient
        # doesn't set X-Forwarded-For, so all requests share the fallback
        # client host ("testclient") — same IP for rate-limit purposes.
        from app.security.rate_limit import auth_rate_limiter
        monkeypatch.setattr(auth_rate_limiter, "per_minute", 3)

        # Three legitimate signups — all accepted.
        for i in range(3):
            r = await app_with_db.post("/auth/signup", json={
                "email": f"user{i}@example.com",
                "password": "long-enough-password",
            })
            assert r.status_code == 201, r.text

        # Fourth signup from the same IP within 60s → 429 + Retry-After.
        r = await app_with_db.post("/auth/signup", json={
            "email": "flood@example.com",
            "password": "long-enough-password",
        })
        assert r.status_code == 429
        assert "Retry-After" in r.headers

    async def test_signup_and_login_share_the_same_ip_bucket(self, app_with_db, monkeypatch):
        # Rotating between endpoints must NOT let an attacker double their
        # budget. Both use the same "auth:<ip>" key.
        from app.security.rate_limit import auth_rate_limiter
        monkeypatch.setattr(auth_rate_limiter, "per_minute", 2)

        # Signup #1 — consumes the first slot.
        r1 = await app_with_db.post("/auth/signup", json={
            "email": "first@example.com", "password": "long-enough-password",
        })
        assert r1.status_code == 201

        # Login attempt #1 — consumes the second slot.
        r2 = await app_with_db.post("/auth/login", json={
            "email": "first@example.com", "password": "long-enough-password",
        })
        assert r2.status_code == 200

        # Either endpoint from the same IP is now rate-limited.
        r3 = await app_with_db.post("/auth/login", json={
            "email": "first@example.com", "password": "wrong-password-xxx",
        })
        assert r3.status_code == 429

        r4 = await app_with_db.post("/auth/signup", json={
            "email": "second@example.com", "password": "long-enough-password",
        })
        assert r4.status_code == 429

    async def test_rate_limit_is_per_tenant_not_global(self, app_with_db, monkeypatch):
        from app.security.rate_limit import scan_rate_limiter
        monkeypatch.setattr(scan_rate_limiter, "per_minute", 1)

        async def _fake_run_scan(*_a, **_kw):
            raise RuntimeError("stubbed")

        monkeypatch.setattr("app.main.run_scan", _fake_run_scan)

        token_a, _ = await _signup(app_with_db, "alice10@example.com")
        token_b, _ = await _signup(app_with_db, "bob10@example.com")

        payload = {"url": "http://93.184.216.34/"}

        # A uses its single budget.
        r_a1 = await app_with_db.post(
            "/scan", headers={"Authorization": f"Bearer {token_a}"}, json=payload,
        )
        assert r_a1.status_code == 500  # stub raised

        # A is now over quota.
        r_a2 = await app_with_db.post(
            "/scan", headers={"Authorization": f"Bearer {token_a}"}, json=payload,
        )
        assert r_a2.status_code == 429

        # B still has a full budget — proves the key is per-tenant.
        r_b = await app_with_db.post(
            "/scan", headers={"Authorization": f"Bearer {token_b}"}, json=payload,
        )
        assert r_b.status_code == 500  # stub raised (SSRF + rate-limit passed)
