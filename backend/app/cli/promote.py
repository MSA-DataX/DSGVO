"""Bootstrap / revoke super-admin privilege from the command line.

    python -m app.cli.promote <email>            # grant
    python -m app.cli.promote --revoke <email>   # revoke

Exists because HTTP endpoints can't grant the first superuser — there
is no superuser yet to call `POST /admin/users/{id}/promote`. Running
this from the server's shell is a deliberate out-of-band operation and
writes an audit log entry with a null actor so the system action is
traceable.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import select, update

from app.audit import log_action
from app.db import session_scope
from app.db_models import User


async def _set_superuser(email: str, value: bool) -> int:
    email = email.strip().lower()
    async with session_scope() as session:
        user = (await session.execute(
            select(User).where(User.email == email)
        )).scalar_one_or_none()
        if user is None:
            print(f"error: no user with email {email!r}", file=sys.stderr)
            return 1
        if bool(user.is_superuser) == value:
            print(f"no change: {email} is_superuser already {value}")
            return 0
        await session.execute(
            update(User).where(User.id == user.id).values(is_superuser=value)
        )
        target_id = user.id
        target_email = user.email

    await log_action(
        action="user.promote" if value else "user.demote",
        actor=None,                      # CLI / system action
        actor_email="cli:promote.py",
        target_type="user",
        target_id=target_id,
        details={"email": target_email, "is_superuser": value, "source": "cli"},
    )
    verb = "promoted" if value else "demoted"
    print(f"{verb} {target_email} (is_superuser={value})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.promote",
        description="Grant or revoke the system-wide superuser flag.",
    )
    parser.add_argument("email", help="user email to promote / demote")
    parser.add_argument(
        "--revoke", action="store_true",
        help="revoke is_superuser instead of granting it",
    )
    args = parser.parse_args(argv)
    return asyncio.run(_set_superuser(args.email, value=not args.revoke))


if __name__ == "__main__":
    sys.exit(main())
