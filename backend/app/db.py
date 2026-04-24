"""SQLAlchemy 2.0 async engine + session factory.

Single async engine for the whole process; sessions are short-lived and
created per request (or per storage call) via ``session_scope``. The same
code path runs against:

  - SQLite via aiosqlite (local dev / tests / zero-config)
  - Postgres via asyncpg (production / multi-tenant)

Switching between them is a single env-var (``DATABASE_URL``) change —
Phase 1.1 of the SaaS migration delivers this.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    """Declarative base shared by all ORM models."""


def install_sqlite_fk_pragma(engine: AsyncEngine) -> None:
    """Force FK enforcement on every SQLite connection.

    SQLite ships with ``foreign_keys=OFF`` per connection — silently.
    That means ``ON DELETE CASCADE`` / ``SET NULL`` declared in the
    ORM are no-ops on dev and test DBs, while Postgres in production
    enforces them. Without this fix, a developer writes code that
    relies on cascade, the SQLite tests pass, Postgres accepts them,
    and the bug hides until an Art. 17 erasure request comes in.

    Listener is attached to the sync sub-engine inside the async
    wrapper (SQLAlchemy 2.0 surfaces this via ``engine.sync_engine``).
    """
    @event.listens_for(engine.sync_engine, "connect")
    def _fk_on(dbapi_connection, _connection_record) -> None:  # type: ignore[misc]
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()


_engine: AsyncEngine = create_async_engine(
    settings.database_url,
    # `future` is the default in 2.0; explicit echo for the dev-noise dial.
    echo=False,
    # SQLite cannot use a real connection pool; everything else benefits.
    pool_pre_ping=not settings.database_url.startswith("sqlite"),
)

if settings.database_url.startswith("sqlite"):
    install_sqlite_fk_pragma(_engine)

_SessionLocal = async_sessionmaker(_engine, expire_on_commit=False)


def get_engine() -> AsyncEngine:
    return _engine


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """One session per logical operation; commit on success, rollback on
    exception. Storage callers should use this rather than instantiating
    ``_SessionLocal`` directly."""
    session = _SessionLocal()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
