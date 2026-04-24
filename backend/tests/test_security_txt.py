"""Tests for /.well-known/security.txt (RFC 9116).

Lightweight: the file has a handful of well-defined fields and the
validator community's main gripes are "missing Expires" and "Expires
more than a year out", both of which we can pin in tests cheaply.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app import db as db_module
from app.db_models import Base


@pytest_asyncio.fixture
async def app_with_db(monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.db import install_sqlite_fk_pragma

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    install_sqlite_fk_pragma(engine)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "_engine", engine)
    monkeypatch.setattr(db_module, "_SessionLocal", SessionLocal)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client

    await engine.dispose()


def _parse_fields(body: str) -> dict[str, list[str]]:
    """RFC 9116 allows repeated fields. Return a dict of field → values."""
    out: dict[str, list[str]] = {}
    for line in body.splitlines():
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        name, _, value = line.partition(":")
        out.setdefault(name.strip(), []).append(value.strip())
    return out


@pytest.mark.asyncio
class TestSecurityTxt:
    async def test_served_at_well_known_path(self, app_with_db):
        r = await app_with_db.get("/.well-known/security.txt")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/plain")

    async def test_contact_field_required_by_rfc_is_present(self, app_with_db):
        r = await app_with_db.get("/.well-known/security.txt")
        fields = _parse_fields(r.text)
        assert fields.get("Contact"), "security.txt MUST carry a Contact: field (RFC 9116 §2.5.4)"
        assert fields["Contact"][0].startswith(("mailto:", "tel:", "https://"))

    async def test_expires_field_required_by_rfc_is_present(self, app_with_db):
        r = await app_with_db.get("/.well-known/security.txt")
        fields = _parse_fields(r.text)
        assert fields.get("Expires"), "security.txt MUST carry an Expires: field (RFC 9116 §2.5.5)"

    async def test_expires_default_is_at_most_one_year_out(self, app_with_db):
        # No env override → default is boot + 365d. Validators reject
        # an Expires value more than a year in the future; this is the
        # check that keeps us honest if someone later bumps the
        # fallback to "2099-01-01" and forgets why it mattered.
        r = await app_with_db.get("/.well-known/security.txt")
        fields = _parse_fields(r.text)
        expires_str = fields["Expires"][0]
        ts = datetime.fromisoformat(expires_str.replace("Z", "+00:00"))
        delta_days = (ts - datetime.now(timezone.utc)).days
        assert 0 < delta_days <= 366

    async def test_preferred_languages_present(self, app_with_db):
        # Not strictly required by the RFC but every linter checks for
        # it; cheap signal to researchers.
        r = await app_with_db.get("/.well-known/security.txt")
        fields = _parse_fields(r.text)
        assert fields.get("Preferred-Languages")

    async def test_configured_policy_url_is_included(self, app_with_db, monkeypatch):
        from app.config import settings as cfg
        monkeypatch.setattr(cfg, "security_policy_url", "https://example.com/security")

        r = await app_with_db.get("/.well-known/security.txt")
        fields = _parse_fields(r.text)
        assert fields.get("Policy") == ["https://example.com/security"]

    async def test_endpoint_is_public_no_auth_required(self, app_with_db):
        # Researchers must be able to fetch this without a login.
        r = await app_with_db.get("/.well-known/security.txt")
        assert r.status_code == 200

    async def test_configured_contact_email_is_used(self, app_with_db, monkeypatch):
        from app.config import settings as cfg
        monkeypatch.setattr(cfg, "security_contact_email", "security@gewobag.de")

        r = await app_with_db.get("/.well-known/security.txt")
        fields = _parse_fields(r.text)
        assert fields["Contact"] == ["mailto:security@gewobag.de"]

    async def test_canonical_included_when_base_url_set(self, app_with_db, monkeypatch):
        from app.config import settings as cfg
        monkeypatch.setattr(cfg, "app_base_url", "https://scanner.example.com")

        r = await app_with_db.get("/.well-known/security.txt")
        fields = _parse_fields(r.text)
        assert fields.get("Canonical") == [
            "https://scanner.example.com/.well-known/security.txt",
        ]
