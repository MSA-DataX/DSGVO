"""Tests for Phase 4 admin + audit.

Covers:
  - require_superuser: 401 unauth, 403 authed-but-not-admin, 200 admin
  - /admin/users and /admin/organizations (list + counts)
  - /admin/users/{id}/promote + demote + idempotency
  - /admin/users/{id}/reset-password: password actually rotates,
    audit entry written
  - self-demote guarded (400)
  - /admin/audit surfaces entries, filterable by action
  - CLI promote script grants/revokes the flag + writes an audit row
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app import db as db_module
from app.db_models import Base


@pytest_asyncio.fixture
async def app_with_db(monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.db import install_sqlite_fk_pragma
    from app.security.rate_limit import auth_rate_limiter, scan_rate_limiter

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    install_sqlite_fk_pragma(engine)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "_engine", engine)
    monkeypatch.setattr(db_module, "_SessionLocal", SessionLocal)
    scan_rate_limiter.reset()
    auth_rate_limiter.reset()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client

    await engine.dispose()


async def _signup(client, email: str) -> tuple[str, str]:
    """Sign up a user and return (token, user_id)."""
    r = await client.post("/auth/signup", json={
        "email": email, "password": "long-enough-password",
        "display_name": email.split("@")[0],
    })
    assert r.status_code == 201, r.text
    body = r.json()
    return body["access_token"], body["user"]["id"]


async def _promote_in_db(user_id: str) -> None:
    """Flip the is_superuser flag directly — simulates the CLI path
    without spinning up a subprocess. Used to bootstrap the first admin
    in each test case."""
    from sqlalchemy import update
    from app.db import session_scope
    from app.db_models import User
    async with session_scope() as session:
        await session.execute(
            update(User).where(User.id == user_id).values(is_superuser=True)
        )


# ---------------------------------------------------------------------------
# require_superuser gate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestRequireSuperuser:
    async def test_admin_routes_401_without_token(self, app_with_db):
        for path in ("/admin/users", "/admin/organizations", "/admin/audit"):
            r = await app_with_db.get(path)
            assert r.status_code == 401, path

    async def test_admin_routes_403_for_non_admin(self, app_with_db):
        token, _ = await _signup(app_with_db, "regular@example.com")
        r = await app_with_db.get(
            "/admin/users", headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403
        assert "superuser" in r.json()["detail"].lower()

    async def test_admin_routes_200_for_admin(self, app_with_db):
        token, user_id = await _signup(app_with_db, "admin@example.com")
        await _promote_in_db(user_id)
        r = await app_with_db.get(
            "/admin/users", headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200

    async def test_auth_me_surfaces_is_superuser(self, app_with_db):
        token, user_id = await _signup(app_with_db, "me@example.com")
        await _promote_in_db(user_id)
        r = await app_with_db.get(
            "/auth/me", headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        assert r.json()["is_superuser"] is True


# ---------------------------------------------------------------------------
# List users + orgs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestAdminLists:
    async def test_users_list_returns_every_account(self, app_with_db):
        token, admin_id = await _signup(app_with_db, "admin@example.com")
        await _promote_in_db(admin_id)
        await _signup(app_with_db, "alice@example.com")
        await _signup(app_with_db, "bob@example.com")

        r = await app_with_db.get(
            "/admin/users", headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        emails = {u["email"] for u in r.json()}
        assert {"admin@example.com", "alice@example.com", "bob@example.com"} <= emails

    async def test_organizations_list_includes_counts(self, app_with_db):
        token, admin_id = await _signup(app_with_db, "admin@example.com")
        await _promote_in_db(admin_id)

        # Each signup auto-creates an org with one member + zero scans.
        await _signup(app_with_db, "a@example.com")
        await _signup(app_with_db, "b@example.com")

        r = await app_with_db.get(
            "/admin/organizations", headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        orgs = r.json()
        assert len(orgs) >= 3   # admin's + alice's + bob's
        for o in orgs:
            assert o["member_count"] == 1
            assert o["scan_count"] == 0


# ---------------------------------------------------------------------------
# Promote / demote
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestPromoteDemote:
    async def test_promote_then_demote_flips_flag(self, app_with_db):
        admin_token, admin_id = await _signup(app_with_db, "admin@example.com")
        await _promote_in_db(admin_id)
        _alice_token, alice_id = await _signup(app_with_db, "alice@example.com")

        # Promote
        r = await app_with_db.post(
            f"/admin/users/{alice_id}/promote",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert r.status_code == 200
        # verify via the list
        users = (await app_with_db.get(
            "/admin/users", headers={"Authorization": f"Bearer {admin_token}"},
        )).json()
        alice = next(u for u in users if u["id"] == alice_id)
        assert alice["is_superuser"] is True

        # Demote
        r = await app_with_db.post(
            f"/admin/users/{alice_id}/demote",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert r.status_code == 200
        users = (await app_with_db.get(
            "/admin/users", headers={"Authorization": f"Bearer {admin_token}"},
        )).json()
        alice = next(u for u in users if u["id"] == alice_id)
        assert alice["is_superuser"] is False

    async def test_self_demote_is_400(self, app_with_db):
        admin_token, admin_id = await _signup(app_with_db, "admin@example.com")
        await _promote_in_db(admin_id)

        r = await app_with_db.post(
            f"/admin/users/{admin_id}/demote",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert r.status_code == 400
        assert "yourself" in r.json()["detail"].lower()

    async def test_promote_unknown_user_is_404(self, app_with_db):
        admin_token, admin_id = await _signup(app_with_db, "admin@example.com")
        await _promote_in_db(admin_id)

        r = await app_with_db.post(
            "/admin/users/does-not-exist/promote",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert r.status_code == 404

    async def test_promote_is_idempotent(self, app_with_db):
        admin_token, admin_id = await _signup(app_with_db, "admin@example.com")
        await _promote_in_db(admin_id)
        _alice_token, alice_id = await _signup(app_with_db, "alice@example.com")

        r1 = await app_with_db.post(
            f"/admin/users/{alice_id}/promote",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        r2 = await app_with_db.post(
            f"/admin/users/{alice_id}/promote",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert r1.status_code == 200
        assert r2.status_code == 200

        # Second call must NOT create a second audit row — the op was
        # already in the desired state.
        audit = (await app_with_db.get(
            "/admin/audit?action=user.promote",
            headers={"Authorization": f"Bearer {admin_token}"},
        )).json()
        promotions_of_alice = [
            e for e in audit if e["target_id"] == alice_id
        ]
        assert len(promotions_of_alice) == 1


# ---------------------------------------------------------------------------
# Reset password
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestResetPassword:
    async def test_reset_password_changes_hash_and_logs(self, app_with_db):
        admin_token, admin_id = await _signup(app_with_db, "admin@example.com")
        await _promote_in_db(admin_id)
        _, alice_id = await _signup(app_with_db, "alice@example.com")

        r = await app_with_db.post(
            f"/admin/users/{alice_id}/reset-password",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"new_password": "admin-forced-new-pw"},
        )
        assert r.status_code == 200

        # Old password should no longer work.
        r_old = await app_with_db.post("/auth/login", json={
            "email": "alice@example.com", "password": "long-enough-password",
        })
        assert r_old.status_code == 401

        # New password does.
        r_new = await app_with_db.post("/auth/login", json={
            "email": "alice@example.com", "password": "admin-forced-new-pw",
        })
        assert r_new.status_code == 200

        # Audit entry exists.
        audit = (await app_with_db.get(
            "/admin/audit?action=user.reset_password",
            headers={"Authorization": f"Bearer {admin_token}"},
        )).json()
        assert any(
            e["target_id"] == alice_id and e["actor_email"] == "admin@example.com"
            for e in audit
        )

    async def test_reset_password_too_short_is_422(self, app_with_db):
        admin_token, admin_id = await _signup(app_with_db, "admin@example.com")
        await _promote_in_db(admin_id)
        _, alice_id = await _signup(app_with_db, "alice@example.com")

        r = await app_with_db.post(
            f"/admin/users/{alice_id}/reset-password",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"new_password": "too-short"},
        )
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# Audit log listing + filters
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestAuditListing:
    async def test_audit_captures_actor_details(self, app_with_db):
        admin_token, admin_id = await _signup(app_with_db, "admin@example.com")
        await _promote_in_db(admin_id)
        _, alice_id = await _signup(app_with_db, "alice@example.com")

        await app_with_db.post(
            f"/admin/users/{alice_id}/promote",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        r = await app_with_db.get(
            "/admin/audit", headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert r.status_code == 200
        rows = r.json()
        hit = next(e for e in rows if e["action"] == "user.promote")
        assert hit["actor_user_id"] == admin_id
        assert hit["actor_email"] == "admin@example.com"
        assert hit["target_type"] == "user"
        assert hit["target_id"] == alice_id
        assert hit["details"]["email"] == "alice@example.com"

    async def test_audit_filter_by_action(self, app_with_db):
        admin_token, admin_id = await _signup(app_with_db, "admin@example.com")
        await _promote_in_db(admin_id)
        _, alice_id = await _signup(app_with_db, "alice@example.com")

        await app_with_db.post(
            f"/admin/users/{alice_id}/promote",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        await app_with_db.post(
            f"/admin/users/{alice_id}/reset-password",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"new_password": "a-new-strong-password"},
        )

        only_promotes = (await app_with_db.get(
            "/admin/audit?action=user.promote",
            headers={"Authorization": f"Bearer {admin_token}"},
        )).json()
        assert only_promotes
        assert all(e["action"] == "user.promote" for e in only_promotes)

        only_resets = (await app_with_db.get(
            "/admin/audit?action=user.reset_password",
            headers={"Authorization": f"Bearer {admin_token}"},
        )).json()
        assert only_resets
        assert all(e["action"] == "user.reset_password" for e in only_resets)


# ---------------------------------------------------------------------------
# CLI promote
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestCliPromote:
    async def test_cli_grants_and_revokes(self, app_with_db, capsys):
        from app.cli.promote import _set_superuser
        await _signup(app_with_db, "target@example.com")

        # Grant
        code = await _set_superuser("target@example.com", True)
        assert code == 0

        # Re-grant is a no-op (idempotent)
        code2 = await _set_superuser("target@example.com", True)
        assert code2 == 0
        out = capsys.readouterr().out
        assert "no change" in out

        # Revoke
        code3 = await _set_superuser("target@example.com", False)
        assert code3 == 0

    async def test_cli_unknown_email_returns_nonzero(self, app_with_db):
        from app.cli.promote import _set_superuser
        code = await _set_superuser("nobody@example.com", True)
        assert code == 1

    async def test_cli_writes_audit_row_with_null_actor(self, app_with_db):
        from sqlalchemy import select
        from app.cli.promote import _set_superuser
        from app.db import session_scope
        from app.db_models import AuditLog

        _, user_id = await _signup(app_with_db, "target@example.com")
        await _set_superuser("target@example.com", True)

        async with session_scope() as session:
            rows = (await session.execute(
                select(AuditLog).where(AuditLog.target_id == user_id)
            )).scalars().all()
        assert rows, "CLI promote should leave an audit trail"
        row = rows[0]
        assert row.action == "user.promote"
        assert row.actor_user_id is None         # system action
        assert row.actor_email == "cli:promote.py"
