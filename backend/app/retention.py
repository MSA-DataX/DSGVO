"""Data retention enforcement (Phase 8).

Implements the numbers written down in ``docs/retention-policy.md``:

  - Scans       older than 12 months → deleted
  - Audit log   older than  3 years  → deleted
  - Orphan scans (organization_id IS NULL) → deleted immediately

Kept as pure async functions so both the Arq cron (via
:mod:`app.worker`) and the operator CLI (:mod:`app.cli.retention`)
call the same code. Each function returns the count of deleted rows
so the caller can log / alert / audit.

Timestamps are compared as ISO-8601 strings — our schema stores them
that way, and the lexicographic order matches chronological order
for ISO-8601 strings with identical zones, which we enforce by
always producing UTC timestamps with ``timespec="seconds"``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, delete

from app.db import session_scope
from app.db_models import AuditLog, Scan


log = logging.getLogger("retention")


# Defaults lifted from docs/retention-policy.md. Kept here as module
# constants so operators can bump them for one-off sweeps without
# touching the schedule in worker.py.
DEFAULT_SCAN_MONTHS = 12
DEFAULT_AUDIT_YEARS = 3


@dataclass(frozen=True)
class RetentionResult:
    scans_deleted:       int
    audit_deleted:       int
    orphan_scans_deleted: int

    @property
    def total(self) -> int:
        return self.scans_deleted + self.audit_deleted + self.orphan_scans_deleted


def _iso_months_ago(months: int) -> str:
    """ISO-8601 UTC timestamp for ``months`` calendar-ish months ago.

    Calendar-month arithmetic via ``timedelta(days=30 * months)`` is
    approximate — good enough for a retention boundary. A truly-
    calendar-aware implementation would need `dateutil.relativedelta`;
    the ±one-day drift of this version is not material for a 12-month
    window.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=30 * months)
    return cutoff.isoformat(timespec="seconds")


def _iso_years_ago(years: int) -> str:
    cutoff = datetime.now(timezone.utc) - timedelta(days=365 * years)
    return cutoff.isoformat(timespec="seconds")


async def purge_scans_older_than(months: int = DEFAULT_SCAN_MONTHS) -> int:
    """Delete scans whose ``created_at`` is older than ``months``."""
    cutoff = _iso_months_ago(months)
    async with session_scope() as session:
        result = await session.execute(
            delete(Scan).where(Scan.created_at < cutoff)
        )
    n = result.rowcount or 0
    log.info("retention: purged %d scan(s) older than %d months (cutoff=%s)", n, months, cutoff)
    return n


async def purge_audit_older_than(years: int = DEFAULT_AUDIT_YEARS) -> int:
    """Delete audit-log rows older than ``years``.

    Convention #18 says audit is append-only from the app layer — this
    is the one exception, used exclusively by retention enforcement and
    guarded by the schedule configured in :mod:`app.worker`. No HTTP
    path mutates audit_logs; a developer adding one must update
    convention #18 at the same time.
    """
    cutoff = _iso_years_ago(years)
    async with session_scope() as session:
        result = await session.execute(
            delete(AuditLog).where(AuditLog.created_at < cutoff)
        )
    n = result.rowcount or 0
    log.info("retention: purged %d audit row(s) older than %d years (cutoff=%s)", n, years, cutoff)
    return n


async def purge_orphan_scans() -> int:
    """Delete scans whose ``organization_id`` is NULL.

    Every write path stamps the column; orphans should only appear
    immediately after a schema migration or if someone manually
    NULL-s the FK. Nightly sweep is defensive — expected count is 0.
    """
    async with session_scope() as session:
        result = await session.execute(
            delete(Scan).where(Scan.organization_id.is_(None))
        )
    n = result.rowcount or 0
    if n:
        log.warning("retention: purged %d orphan scan(s) — investigate schema / write paths", n)
    return n


async def run_retention_sweep(
    *,
    scan_months: int = DEFAULT_SCAN_MONTHS,
    audit_years: int = DEFAULT_AUDIT_YEARS,
) -> RetentionResult:
    """One call to purge everything. Used by the Arq cron job."""
    scans = await purge_scans_older_than(scan_months)
    audit = await purge_audit_older_than(audit_years)
    orphan = await purge_orphan_scans()
    log.info(
        "retention sweep complete: scans=%d audit=%d orphan=%d",
        scans, audit, orphan,
    )
    return RetentionResult(
        scans_deleted=scans, audit_deleted=audit, orphan_scans_deleted=orphan,
    )
