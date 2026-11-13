"""``regwatch-admin``: operator commands run inside the api container (#31).

``create-user`` makes the first administrator (or any local account) without the web UI.
The password is read from the terminal without echo, or from standard input with
``--password-stdin``; it is never taken as an argument, so it stays out of shell history
and process listings.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from collections.abc import Sequence

from regwatch.core.db import create_engine, session_factory
from regwatch.core.schemas import check_email
from regwatch.core.security import MAX_PASSWORD_LENGTH
from regwatch.identity import services


def _read_password(from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    first = getpass.getpass("Password: ")
    if getpass.getpass("Repeat password: ") != first:
        raise ValueError("passwords do not match")
    return first


async def _create(url: str, email: str, name: str, password: str, roles: list[str],
                  temporary: bool) -> str:  # fmt: skip
    engine = create_engine(url, poolclass_null=True)
    try:
        async with session_factory(engine)() as db:
            email = check_email(email)
            minimum = max(12, (await services.auth_settings(db))["auth.password_min_length"])
            if not minimum <= len(password) <= MAX_PASSWORD_LENGTH:
                raise ValueError(
                    f"password must have {minimum} to {MAX_PASSWORD_LENGTH} characters"
                )
            user = await services.create_user(
                db, email, name, password, roles, must_change_password=temporary
            )
            await db.commit()
            return str(user.id)
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="regwatch-admin", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-user", help="create a local account")
    create.add_argument("--email", required=True)
    create.add_argument("--name", required=True, help="display name")
    create.add_argument("--role", action="append", dest="roles", default=None,
                        help="role key; repeat for several (default: admin)")  # fmt: skip
    create.add_argument("--password-stdin", action="store_true",
                        help="read the password from standard input")  # fmt: skip
    create.add_argument("--temporary", action="store_true",
                        help="require a password change at first login")  # fmt: skip
    args = parser.parse_args(argv)
    from regwatch.core.settings import get_settings

    url = get_settings().database_url.get_secret_value()
    try:
        password = _read_password(args.password_stdin)
        user_id = asyncio.run(
            _create(url, args.email, args.name, password, args.roles or ["admin"], args.temporary)
        )
    except ValueError as exc:
        print(f"regwatch-admin: {exc}", file=sys.stderr)
        return 1
    print(f"regwatch-admin: created user {user_id}")
    return 0
