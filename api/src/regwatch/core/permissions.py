"""Permission checks: the single seam between route ``x-permission`` keys and identity (M1).

Every implemented route depends on :func:`require` for the key in its ``x-permission``
(``spec(..., stub=False)`` wires it). :func:`current_principal` is the part M1 (#31, #32)
replaces: it will resolve the ``rw_session`` cookie to a user and the union of their role
permissions. Until then no sign-in exists, so outside production every request acts as a
principal holding ``*``; production refuses with 401. Tests override ``current_principal``
with an explicit principal, so neither handlers nor tests change when M1 lands.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends

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


async def current_principal(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Principal:
    """Pre-M1 placeholder; M1 replaces this body and keeps the signature's return type."""
    if settings.env == "production":
        raise ProblemError(401, "unauthenticated", "Sign-in is not available yet.")
    return Principal(user_id=None, permissions=frozenset({ALL}))


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]


def require(permission: str) -> Callable[[Principal], Awaitable[Principal]]:
    """Dependency that answers 403 unless the principal holds ``permission``."""

    async def check(principal: CurrentPrincipal) -> Principal:
        if not principal.has(permission):
            raise ProblemError(403, "forbidden", f"This action needs the {permission} permission.")
        return principal

    return check
