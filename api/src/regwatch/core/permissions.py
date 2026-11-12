"""Permission checks: the single seam between route ``x-permission`` keys and identity (M1).

Every implemented route depends on :func:`require` for the key in its ``x-permission``
(``spec(..., stub=False)`` wires it). :func:`current_principal` is the part M1 (#31, #32)
replaces: it will resolve the ``rw_session`` cookie to a user and the union of their role
permissions. Until then no sign-in exists: outside production, a session cookie equal to
:func:`dev_session_token` (derived from the secret key) acts as a principal holding ``*``;
any other request, and every request in production, gets 401. Unit tests override
``current_principal`` with an explicit principal, so handlers and tests survive M1.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request

from regwatch.core.errors import ProblemError
from regwatch.core.settings import Settings, get_settings

PERMISSIONS: tuple[str, ...] = ()
ALL = "*"


@dataclass(frozen=True)
class Principal:
    """Who is acting: ``user_id`` is ``None`` for the pre-M1 development principal."""

    user_id: UUID | None
    permissions: frozenset[str]

    def has(self, permission: str) -> bool:
        return ALL in self.permissions or permission in self.permissions


def dev_session_token(settings: Settings) -> str:
    """The pre-M1 development session value; never accepted in production."""
    key = settings.secret_key.get_secret_value().encode()
    return hmac.new(key, b"regwatch pre-M1 development session", hashlib.sha256).hexdigest()


async def current_principal(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> Principal:
    """Pre-M1 placeholder; M1 replaces this body and keeps the signature's return type."""
    cookie = request.cookies.get(settings.session_cookie_name, "")
    if settings.env != "production" and hmac.compare_digest(
        cookie.encode(), dev_session_token(settings).encode()
    ):
        return Principal(user_id=None, permissions=frozenset({ALL}))
    raise ProblemError(401, "unauthenticated", "A valid session is required.")


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]


def require(permission: str) -> Callable[[Principal], Awaitable[Principal]]:
    """Dependency that answers 403 unless the principal holds ``permission``."""

    async def check(principal: CurrentPrincipal) -> Principal:
        if not principal.has(permission):
            raise ProblemError(403, "forbidden", f"This action needs the {permission} permission.")
        return principal

    return check
