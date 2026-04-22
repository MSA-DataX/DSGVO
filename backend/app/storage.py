"""Scan persistence.

SQLite via aiosqlite. One table, two columns that matter (``id`` +
``payload``), everything else is denormalized from ``payload`` for cheap
list queries. The full ``ScanResponse`` JSON is the source of truth.

Why SQLite: zero-config for a single-node SaaS; swap to Postgres later by
changing the connection string. Why denormalize: the list endpoint needs
url + score + rating + timestamp without deserializing every JSON blob.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone

import aiosqlite

from app.models import ScanListItem, ScanResponse


log = logging.getLogger("storage")

_DB_PATH = os.environ.get("SCAN_DB_PATH", "scans.db")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    id          TEXT PRIMARY KEY,
    url         TEXT NOT NULL,
    score       INTEGER NOT NULL,
    rating      TEXT NOT NULL,
    created_at  TEXT NOT NULL,      -- ISO-8601 UTC
    payload     TEXT NOT NULL       -- full ScanResponse as JSON
);
CREATE INDEX IF NOT EXISTS scans_created_at_idx ON scans(created_at DESC);
CREATE INDEX IF NOT EXISTS scans_url_idx        ON scans(url);
"""


async def init_db() -> None:
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.executescript(_SCHEMA)
        await db.commit()
    log.info("scan db ready at %s", _DB_PATH)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


async def save_scan(scan: ScanResponse) -> tuple[str, str]:
    """Persist a scan and return (id, created_at)."""
    scan_id = uuid.uuid4().hex[:12]
    created_at = _now_iso()
    payload = scan.model_dump_json()
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute(
            "INSERT INTO scans(id, url, score, rating, created_at, payload) "
            "VALUES(?, ?, ?, ?, ?, ?)",
            (scan_id, scan.target, scan.risk.score, scan.risk.rating, created_at, payload),
        )
        await db.commit()
    return scan_id, created_at


async def list_scans(limit: int = 50) -> list[ScanListItem]:
    limit = max(1, min(200, limit))
    async with aiosqlite.connect(_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await db.execute_fetchall(
            "SELECT id, url, score, rating, created_at FROM scans "
            "ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
    return [
        ScanListItem(
            id=r["id"], url=r["url"], score=r["score"],
            rating=r["rating"], created_at=r["created_at"],
        )
        for r in rows
    ]


async def get_scan(scan_id: str) -> ScanResponse | None:
    async with aiosqlite.connect(_DB_PATH) as db:
        async with db.execute(
            "SELECT payload FROM scans WHERE id = ?", (scan_id,)
        ) as cur:
            row = await cur.fetchone()
    if row is None:
        return None
    return ScanResponse.model_validate(json.loads(row[0]))


async def delete_scan(scan_id: str) -> bool:
    async with aiosqlite.connect(_DB_PATH) as db:
        cur = await db.execute("DELETE FROM scans WHERE id = ?", (scan_id,))
        await db.commit()
        return cur.rowcount > 0
