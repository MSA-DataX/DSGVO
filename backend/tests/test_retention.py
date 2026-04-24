"""Tests for Phase 8 data-retention enforcement.

The retention helpers are the rare code path that mutates the audit
log. Their correctness determines whether our published retention
numbers are actually enforced — so the tests below pin:

  - cutoff arithmetic (months / years)
  - old rows removed, fresh rows preserved
  - orphan-scan sweep
  - return values (used by the Arq cron for logging)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from app import db as db_module
from app.db import session_scope
from app.db_models import AuditLog, Base, Organization, Scan
from app.retention import (
    purge_audit_older_than,
    purge_orphan_scans,
    purge_scans_older_than,
    run_retention_sweep,
)


@pytest_asyncio.fixture
async def db(monkeypatch):
    """Fresh in-memory DB per test — retention tests INSERT then
    DELETE, we don't want cross-test bleed."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.db import install_sqlite_fk_pragma

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    install_sqlite_fk_pragma(engine)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "_engine", engine)
    monkeypatch.setattr(db_module, "_SessionLocal", SessionLocal)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine
    await engine.dispose()


def _iso(when: datetime) -> str:
    return when.isoformat(timespec="seconds")


async def _make_org(name: str = "Acme") -> str:
    org_id = uuid.uuid4().hex[:12]
    async with session_scope() as session:
        session.add(Organization(
            id=org_id, name=name, slug=f"{name.lower()}-{org_id[:4]}",
            created_at=_iso(datetime.now(timezone.utc)),
        ))
    return org_id


async def _insert_scan(org_id: str | None, created_at: datetime) -> str:
    scan_id = uuid.uuid4().hex[:12]
    async with session_scope() as session:
        session.add(Scan(
            id=scan_id, organization_id=org_id,
            url="https://example.com/",
            status="done",
            score=80, rating="low",
            created_at=_iso(created_at), completed_at=_iso(created_at),
            payload="{}",
        ))
    return scan_id


async def _insert_audit(action: str, created_at: datetime) -> str:
    audit_id = uuid.uuid4().hex[:12]
    async with session_scope() as session:
        session.add(AuditLog(
            id=audit_id, created_at=_iso(created_at),
            actor_user_id=None, actor_email="test@example.com",
            action=action, target_type="user", target_id="u_123",
            details=None, ip=None, user_agent=None,
        ))
    return audit_id


# ---------------------------------------------------------------------------
# purge_scans_older_than
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestPurgeScans:
    async def test_old_scan_deleted_fresh_preserved(self, db):
        org_id = await _make_org()
        now = datetime.now(timezone.utc)
        old_id = await _insert_scan(org_id, now - timedelta(days=400))
        fresh_id = await _insert_scan(org_id, now - timedelta(days=30))

        n = await purge_scans_older_than(months=12)
        assert n == 1

        # The old one is gone, the fresh one stays.
        async with session_scope() as session:
            remaining = (await session.execute(
                Scan.__table__.select()
            )).fetchall()
        ids = {r.id for r in remaining}
        assert fresh_id in ids
        assert old_id not in ids

    async def test_boundary_cutoff_days(self, db):
        # 12 months × 30 days/month = 360 day cutoff.
        org_id = await _make_org()
        now = datetime.now(timezone.utc)
        # 359 days old: KEEP. 361 days old: DELETE.
        keep_id = await _insert_scan(org_id, now - timedelta(days=359))
        drop_id = await _insert_scan(org_id, now - timedelta(days=361))

        n = await purge_scans_older_than(months=12)
        assert n == 1

        async with session_scope() as session:
            rows = (await session.execute(Scan.__table__.select())).fetchall()
        ids = {r.id for r in rows}
        assert keep_id in ids
        assert drop_id not in ids

    async def test_empty_db_returns_zero(self, db):
        n = await purge_scans_older_than(months=12)
        assert n == 0

    async def test_custom_months_argument(self, db):
        org_id = await _make_org()
        now = datetime.now(timezone.utc)
        await _insert_scan(org_id, now - timedelta(days=100))
        await _insert_scan(org_id, now - timedelta(days=200))

        # Aggressive 3-month retention → both are gone.
        n = await purge_scans_older_than(months=3)
        assert n == 2


# ---------------------------------------------------------------------------
# purge_audit_older_than
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestPurgeAudit:
    async def test_old_audit_deleted_fresh_preserved(self, db):
        now = datetime.now(timezone.utc)
        old_id = await _insert_audit("user.promote", now - timedelta(days=400 * 3))
        fresh_id = await _insert_audit("user.promote", now - timedelta(days=100))

        n = await purge_audit_older_than(years=3)
        assert n == 1

        async with session_scope() as session:
            rows = (await session.execute(AuditLog.__table__.select())).fetchall()
        ids = {r.id for r in rows}
        assert fresh_id in ids
        assert old_id not in ids

    async def test_custom_years_argument(self, db):
        # 1-year retention on a 2-year-old row → drop.
        now = datetime.now(timezone.utc)
        await _insert_audit("x", now - timedelta(days=365 * 2))
        n = await purge_audit_older_than(years=1)
        assert n == 1


# ---------------------------------------------------------------------------
# purge_orphan_scans
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestPurgeOrphanScans:
    async def test_orphan_scan_deleted(self, db):
        now = datetime.now(timezone.utc)
        orphan_id = await _insert_scan(None, now)         # no org
        org_id = await _make_org()
        kept_id = await _insert_scan(org_id, now)         # owned

        n = await purge_orphan_scans()
        assert n == 1

        async with session_scope() as session:
            rows = (await session.execute(Scan.__table__.select())).fetchall()
        ids = {r.id for r in rows}
        assert kept_id in ids
        assert orphan_id not in ids

    async def test_no_orphans_returns_zero(self, db):
        org_id = await _make_org()
        now = datetime.now(timezone.utc)
        await _insert_scan(org_id, now)
        n = await purge_orphan_scans()
        assert n == 0


# ---------------------------------------------------------------------------
# run_retention_sweep combined
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestCombinedSweep:
    async def test_result_counts_are_accurate(self, db):
        org_id = await _make_org()
        now = datetime.now(timezone.utc)
        # Three targets for the sweep: 1 old scan + 2 old audit + 1 orphan.
        await _insert_scan(org_id, now - timedelta(days=400))
        await _insert_audit("a", now - timedelta(days=365 * 4))
        await _insert_audit("b", now - timedelta(days=365 * 5))
        await _insert_scan(None, now)

        # Plus fresh rows that must survive.
        await _insert_scan(org_id, now - timedelta(days=10))
        await _insert_audit("c", now - timedelta(days=10))

        result = await run_retention_sweep()
        assert result.scans_deleted == 1
        assert result.audit_deleted == 2
        assert result.orphan_scans_deleted == 1
        assert result.total == 4
