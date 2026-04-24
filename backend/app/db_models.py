"""SQLAlchemy ORM models — the persistence schema.

Phase 1.1 added ``Scan``. Phase 1.2 adds the multi-tenant identity
trio: ``User`` (a real human), ``Organization`` (a billing/scope unit),
and ``Membership`` (the user→org link with a role). Every scan is now
owned by an organization via ``Scan.organization_id``.

Why "organization" not "tenant": the word that ends up in URL paths and
billing flows. Internally we still use the term *tenant* for the request-
scoped guard middleware (Phase 1.3).
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


# NOTE: `Mapped[str | None]` would be ideal but SQLAlchemy `eval()`s the
# annotation at class-construction time, and Python 3.9 doesn't support
# the PEP 604 union operator at runtime even with `from __future__ import
# annotations`. Stick to `Optional[str]` until the project drops 3.9.


class User(Base):
    __tablename__ = "users"

    id:            Mapped[str] = mapped_column(String(32), primary_key=True)
    email:         Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name:  Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    created_at:    Mapped[str] = mapped_column(String(32), nullable=False)
    # Phase 4: system-wide super-admin flag. Distinct from Membership.role
    # (which is per-organization). Set via `python -m app.cli.promote
    # <email>`; never set from a normal HTTP endpoint. Auditable.
    is_superuser:  Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Organization(Base):
    __tablename__ = "organizations"

    id:         Mapped[str] = mapped_column(String(32), primary_key=True)
    name:       Mapped[str] = mapped_column(String(120), nullable=False)
    # URL-safe identifier (lowercase, dash-separated). Unique across the system.
    slug:       Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)


class Membership(Base):
    """Join table between users and organizations.

    Roles are intentionally simple for Phase 1.2 — ``owner`` (full
    control + billing) and ``member`` (can run scans + view history).
    Phase 1.3 layers RBAC checks on top.
    """
    __tablename__ = "memberships"

    id:              Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id:         Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    organization_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False,
    )
    role:            Mapped[str] = mapped_column(String(16), nullable=False, default="member")
    created_at:      Mapped[str] = mapped_column(String(32), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "organization_id", name="memberships_user_org_uq"),
        Index("memberships_user_idx", "user_id"),
        Index("memberships_org_idx", "organization_id"),
    )


class Scan(Base):
    __tablename__ = "scans"

    id:              Mapped[str] = mapped_column(String(32), primary_key=True)
    # Phase 1.2 added the column (nullable); Phase 1.3 stamps it on every
    # write via storage.save_scan(..., organization_id=...). TODO: once
    # pre-1.3 dev rows are backfilled or purged, tighten this to
    # nullable=False in a follow-up migration. The app layer already
    # treats a missing org_id as "orphaned row, invisible to everyone".
    organization_id: Mapped[Optional[str]] = mapped_column(
        String(32),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
    )
    url:             Mapped[str] = mapped_column(Text, nullable=False)
    # Phase 3: job lifecycle. Sync scans (legacy /scan) set status="done"
    # and score/rating at creation time, so old rows that predate Phase 3
    # need a backfill of status="done" for `score` / `rating` to keep
    # meaning. The migration does this.
    status:          Mapped[str] = mapped_column(String(16), nullable=False, default="done")
    # Score + rating are populated only when status == "done". For
    # queued/running jobs they hold placeholder 0 / "critical" so the
    # columns stay NOT NULL and old list queries keep working.
    score:           Mapped[int] = mapped_column(Integer, nullable=False)
    rating:          Mapped[str] = mapped_column(String(16), nullable=False)
    created_at:      Mapped[str] = mapped_column(String(32), nullable=False)
    started_at:      Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    completed_at:    Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    # Error message if status == "failed"; None otherwise.
    error:           Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # The full ScanResponse JSON when done; empty string while queued /
    # running. Nullable would be cleaner but Phase 1.1 declared it NOT NULL
    # and we don't want to rewrite old rows.
    payload:         Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        Index("scans_created_at_idx", "created_at"),
        Index("scans_url_idx", "url"),
        Index("scans_org_idx", "organization_id"),
        Index("scans_status_idx", "status"),
    )


class Subscription(Base):
    """One row per paying-or-free organization (Phase 5).

    Absence of a row is equivalent to the free tier — we only insert a
    row when someone upgrades or an admin assigns a plan manually. That
    way existing deployments are backward-compatible: every org that
    existed before Phase 5 simply gets the free tier by default.

    The ``mollie_*`` columns are reserved for Phase 5b. They stay
    nullable here so the schema is stable across the upgrade window.
    """
    __tablename__ = "subscriptions"

    # organization_id IS the primary key: exactly one subscription per
    # org. No join table, no version history — upgrades overwrite.
    organization_id:        Mapped[str] = mapped_column(
        String(32),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    plan_code:              Mapped[str] = mapped_column(String(32), nullable=False)
    # active | canceled | past_due — mirror Mollie's states so 5b
    # doesn't need to translate.
    status:                 Mapped[str] = mapped_column(
        String(16), nullable=False, default="active",
    )
    created_at:             Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at:             Mapped[str] = mapped_column(String(32), nullable=False)
    # Mollie hooks (Phase 5b); null until a real payment flow runs.
    mollie_customer_id:     Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    mollie_subscription_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # When did the most recent billing period start? Used to derive the
    # usage meter bounds when we move off calendar-month resets.
    current_period_start:   Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    current_period_end:     Mapped[Optional[str]] = mapped_column(String(32), nullable=True)


class AuditLog(Base):
    """Append-only log of privileged actions (Phase 4).

    Written by :func:`app.audit.log_action` on every admin-endpoint
    success. Kept intentionally append-only — no update / delete paths
    exist in the codebase so rows can't be rewritten after the fact.

    ``actor_user_id`` is nullable so system actions (CLI bootstrap,
    migrations) can log too. ``actor_email`` is denormalised so a
    deleted / renamed user still reads as the original email in the
    audit view — critical for DSGVO traceability.
    """
    __tablename__ = "audit_logs"

    id:             Mapped[str] = mapped_column(String(32), primary_key=True)
    created_at:     Mapped[str] = mapped_column(String(32), nullable=False)
    # Who did it. Null == system / CLI action (no HTTP caller).
    actor_user_id:  Mapped[Optional[str]] = mapped_column(
        String(32),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_email:    Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    # What happened. Dotted namespace keeps the string queryable —
    # e.g. "user.promote", "user.reset_password", "admin.login".
    action:         Mapped[str] = mapped_column(String(64), nullable=False)
    # Optional target reference. target_type is "user" / "organization"
    # / "scan" / None; target_id is the row id in that domain.
    target_type:    Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    target_id:      Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # Free-form JSON context (new email, old plan name, IP of the
    # victim, …). Stored as text so SQLite doesn't need a JSON column.
    details:        Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ip:             Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    user_agent:     Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    __table_args__ = (
        Index("audit_logs_created_at_idx", "created_at"),
        Index("audit_logs_actor_idx", "actor_user_id"),
        Index("audit_logs_action_idx", "action"),
    )
