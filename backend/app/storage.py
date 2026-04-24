"""Scan persistence.

SQLAlchemy 2.0 async over SQLite (dev) or Postgres (prod) — driver is
chosen by the ``DATABASE_URL`` env var. Same code path either way.

Phase 1.3: every read/write is scoped by ``organization_id``. The
caller MUST pass it; there is no "global" access path. A scan owned by
org A is completely invisible to org B — queries return ``None`` / an
empty list / ``False`` rather than raising, so HTTP callers surface a
plain 404 and don't leak the fact that the ID exists elsewhere.

The full ``ScanResponse`` JSON is the source of truth in ``payload``;
``url`` / ``score`` / ``rating`` / ``created_at`` are denormalised so the
list endpoint can render without deserialising every blob.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from dataclasses import dataclass

from sqlalchemy import and_, delete, select, update

from app.db import session_scope, get_engine
from app.db_models import Base, Scan
from app.models import ScanListItem, ScanResponse


log = logging.getLogger("storage")


async def init_db() -> None:
    """Create tables if they don't exist.

    Used at app boot for local dev. Production should drive schema via
    Alembic migrations (`alembic upgrade head`); this call is idempotent
    and safe to leave in either way.
    """
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    log.info("scan db ready (%s)", engine.url.render_as_string(hide_password=True))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


async def save_scan(scan: ScanResponse, organization_id: str) -> tuple[str, str]:
    """Persist a completed scan (sync /scan path) and return (id, created_at).

    Stamps ``status="done"`` and ``completed_at`` so rows written through
    this path look identical to rows finalised by the Arq worker —
    ``list_scans`` and ``get_scan_status`` don't have to special-case
    legacy sync rows.
    """
    scan_id = uuid.uuid4().hex[:12]
    now = _now_iso()
    payload = scan.model_dump_json()
    async with session_scope() as session:
        session.add(Scan(
            id=scan_id, organization_id=organization_id,
            url=scan.target,
            status="done",
            score=scan.risk.score, rating=scan.risk.rating,
            created_at=now, completed_at=now, payload=payload,
        ))
    return scan_id, now


async def list_scans(organization_id: str, limit: int = 50) -> list[ScanListItem]:
    limit = max(1, min(200, limit))
    # Only surface finished scans — a `queued` / `running` row carries
    # placeholder score=0 rating="critical", which would be actively
    # misleading in a history UI. Clients that want to track in-flight
    # jobs poll /scan/jobs/{id} directly.
    stmt = (
        select(Scan.id, Scan.url, Scan.score, Scan.rating, Scan.created_at)
        .where(and_(
            Scan.organization_id == organization_id,
            Scan.status == "done",
        ))
        .order_by(Scan.created_at.desc())
        .limit(limit)
    )
    async with session_scope() as session:
        rows = (await session.execute(stmt)).all()
    return [
        ScanListItem(
            id=r.id, url=r.url, score=r.score,
            rating=r.rating, created_at=r.created_at,
        )
        for r in rows
    ]


async def get_scan(scan_id: str, organization_id: str) -> ScanResponse | None:
    """Return the scan iff it belongs to ``organization_id``.

    Cross-tenant hits return ``None`` — same outcome as "not found" — so
    callers can always map the absence to a plain 404 without leaking
    existence of a scan that belongs to someone else.
    """
    async with session_scope() as session:
        row = (await session.execute(
            select(Scan.payload).where(and_(
                Scan.id == scan_id,
                Scan.organization_id == organization_id,
            ))
        )).scalar_one_or_none()
    if row is None:
        return None
    return ScanResponse.model_validate(json.loads(row))


async def delete_scan(scan_id: str, organization_id: str) -> bool:
    async with session_scope() as session:
        result = await session.execute(
            delete(Scan).where(and_(
                Scan.id == scan_id,
                Scan.organization_id == organization_id,
            ))
        )
    return result.rowcount > 0


# ---------------------------------------------------------------------------
# Phase 3: async scan job lifecycle
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ScanJobStatus:
    """Snapshot of a background scan's progress, returned by the status
    endpoint. ``result`` is the parsed :class:`ScanResponse` when the job
    has finished successfully, otherwise ``None``."""
    id: str
    status: str                # queued | running | done | failed
    url: str
    created_at: str
    started_at: str | None
    completed_at: str | None
    error: str | None
    result: ScanResponse | None


async def create_pending_scan(
    *,
    url: str,
    organization_id: str,
) -> tuple[str, str]:
    """Insert a row in ``queued`` state and return (scan_id, created_at).

    Called by the HTTP handler when enqueueing a scan. The worker will
    later call :func:`mark_running` and :func:`mark_done` (or
    :func:`mark_failed`) on the same id.
    """
    scan_id = uuid.uuid4().hex[:12]
    created_at = _now_iso()
    async with session_scope() as session:
        session.add(Scan(
            id=scan_id, organization_id=organization_id,
            url=url,
            status="queued",
            score=0, rating="critical",   # placeholders until completion
            created_at=created_at, payload="",
        ))
    return scan_id, created_at


async def mark_running(scan_id: str) -> None:
    """Transition queued → running. No-op if the row is gone or already
    finished — the worker shouldn't fail on a cancelled job."""
    async with session_scope() as session:
        await session.execute(
            update(Scan)
            .where(and_(Scan.id == scan_id, Scan.status == "queued"))
            .values(status="running", started_at=_now_iso())
        )


async def mark_done(scan_id: str, scan: ScanResponse) -> None:
    """Finalise a successful scan. Writes the full ``ScanResponse`` payload
    and stamps score / rating so the list endpoint can render the row."""
    async with session_scope() as session:
        await session.execute(
            update(Scan)
            .where(Scan.id == scan_id)
            .values(
                status="done",
                score=scan.risk.score,
                rating=scan.risk.rating,
                completed_at=_now_iso(),
                payload=scan.model_dump_json(),
                error=None,
            )
        )


async def mark_failed(scan_id: str, error: str) -> None:
    async with session_scope() as session:
        await session.execute(
            update(Scan)
            .where(Scan.id == scan_id)
            .values(
                status="failed",
                completed_at=_now_iso(),
                error=(error or "unknown error")[:2000],  # cap for DB sanity
            )
        )


async def get_scan_status(
    scan_id: str,
    organization_id: str,
) -> ScanJobStatus | None:
    """Tenant-scoped status lookup. Returns ``None`` if the id is missing
    or belongs to a different org — same 404-on-cross-tenant behaviour as
    :func:`get_scan`."""
    async with session_scope() as session:
        row = (await session.execute(
            select(Scan).where(and_(
                Scan.id == scan_id,
                Scan.organization_id == organization_id,
            ))
        )).scalar_one_or_none()
    if row is None:
        return None
    result: ScanResponse | None = None
    if row.status == "done" and row.payload:
        result = ScanResponse.model_validate(json.loads(row.payload))
    return ScanJobStatus(
        id=row.id,
        status=row.status,
        url=row.url,
        created_at=row.created_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
        error=row.error,
        result=result,
    )
