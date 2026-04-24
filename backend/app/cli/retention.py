"""Manual retention sweeps.

    python -m app.cli.retention                 # use policy defaults
    python -m app.cli.retention --dry-run       # count rows, delete nothing
    python -m app.cli.retention --scan-months 6 --audit-years 1

The Arq cron in app.worker runs this every night. The CLI exists for
two cases:

  1. An operator doing a one-off sweep after changing the policy
     (don't wait 24h for the next cron).
  2. Dry-run inspections before tightening a window — "how many rows
     would a 6-month scan retention delete right now?"

Requires the same DATABASE_URL as the rest of the app. No Redis / no
worker process needed.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.db import session_scope
from app.db_models import AuditLog, Scan
from app.retention import (
    DEFAULT_AUDIT_YEARS,
    DEFAULT_SCAN_MONTHS,
    run_retention_sweep,
)


log = logging.getLogger("cli.retention")


async def _dry_run(scan_months: int, audit_years: int) -> None:
    scan_cutoff = (
        datetime.now(timezone.utc) - timedelta(days=30 * scan_months)
    ).isoformat(timespec="seconds")
    audit_cutoff = (
        datetime.now(timezone.utc) - timedelta(days=365 * audit_years)
    ).isoformat(timespec="seconds")

    async with session_scope() as session:
        scan_count = (await session.execute(
            select(func.count()).select_from(Scan).where(Scan.created_at < scan_cutoff)
        )).scalar_one()
        audit_count = (await session.execute(
            select(func.count()).select_from(AuditLog)
            .where(AuditLog.created_at < audit_cutoff)
        )).scalar_one()
        orphan_count = (await session.execute(
            select(func.count()).select_from(Scan)
            .where(Scan.organization_id.is_(None))
        )).scalar_one()

    print(f"Dry run — nothing deleted.")
    print(f"  scans older than {scan_months} months: {scan_count}  (cutoff {scan_cutoff})")
    print(f"  audit older than {audit_years} years:  {audit_count}  (cutoff {audit_cutoff})")
    print(f"  orphan scans (null org_id):           {orphan_count}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.retention",
        description="Run retention-policy enforcement manually.",
    )
    parser.add_argument(
        "--scan-months", type=int, default=DEFAULT_SCAN_MONTHS,
        help=f"delete scans older than N months (default: {DEFAULT_SCAN_MONTHS})",
    )
    parser.add_argument(
        "--audit-years", type=int, default=DEFAULT_AUDIT_YEARS,
        help=f"delete audit rows older than N years (default: {DEFAULT_AUDIT_YEARS})",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="count rows that would be deleted; don't actually delete anything",
    )
    args = parser.parse_args(argv)

    if args.dry_run:
        asyncio.run(_dry_run(args.scan_months, args.audit_years))
        return 0

    result = asyncio.run(run_retention_sweep(
        scan_months=args.scan_months, audit_years=args.audit_years,
    ))
    print(f"deleted scans={result.scans_deleted} "
          f"audit={result.audit_deleted} "
          f"orphan_scans={result.orphan_scans_deleted}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
