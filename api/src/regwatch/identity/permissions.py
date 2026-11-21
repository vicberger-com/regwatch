"""Permission keys this module registers, and the gate that enforces every key (#31).

Keys come from docs/contracts/registries.yaml (seeded in #28). :func:`authorize` is an
application-wide dependency (``regwatch.api.app``), so every route passes it:

1. A mutating request must carry an ``Origin`` equal to ``REGWATCH_BASE_URL`` (CSRF), public
   routes included, so a foreign page cannot sign a browser in either.
2. Routes whose spec is ``public=True`` (``security: []``) need nothing more.
3. Every other route needs a live session cookie (401 otherwise). Deny by default: a new
   route is protected unless its spec marks it public.
4. While a temporary password is in force, only ``PASSWORD_CHANGE_ROUTES`` answer (403);
   while ``auth.mfa_required`` covers an account with no authenticator, only
   ``MFA_SETUP_ROUTES`` (BL-148, CP-40).
5. The route's ``x-permission`` key must be among the user's permissions (403).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, Request
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from regwatch.core import security
from regwatch.core.errors import ProblemError
from regwatch.core.settings import Settings, get_settings
from regwatch.identity import services
from regwatch.identity.services import Principal

PASSIVE_HEADER = "x-regwatch-passive"  # polling that must not renew the session (M6 live map)

PERMISSIONS: tuple[str, ...] = ()

# M1 acceptance 2: with a temporary password the user can only see who they are, change it,
# or leave.
PASSWORD_CHANGE_ROUTES = frozenset({"auth_me", "logout", "change_password"})
# BL-148 (CP-40): an account auth.mfa_required covers can only see who it is, set up an
# authenticator, or leave.
MFA_SETUP_ROUTES = frozenset({"auth_me", "logout", "mfa_status", "mfa_setup", "mfa_confirm"})
MAX_COOKIE_LENGTH = 128

SettingsDep = Annotated[Settings, Depends(get_settings)]


async def authorize(request: Request, settings: SettingsDep) -> None:
    """The application-wide gate; see the module docstring."""
    if not security.origin_allowed(
        request.method, request.headers.get("origin"), str(settings.base_url)
    ):
        raise ProblemError(403, "origin-mismatch", "The request origin is not allowed.")
    route = request.scope.get("route")
    extra: dict[str, Any] = (route.openapi_extra or {}) if isinstance(route, APIRoute) else {}
    if extra.get("security") == []:
        return
    token = request.cookies.get(settings.session_cookie_name)
    if not token or len(token) > MAX_COOKIE_LENGTH:
        raise services.unauthenticated()
    factory: async_sessionmaker[AsyncSession] = request.app.state.db
    async with factory() as db:
        # A client marks its own polling as passive, so it never keeps an idle session alive;
        # the header can only make a session end sooner, never later.
        passive = request.headers.get(PASSIVE_HEADER) == "1"
        principal = await services.resolve_session(db, token, passive=passive)
    if principal is None:
        raise services.unauthenticated()
    name = route.name if isinstance(route, APIRoute) else ""
    # The two forced steps are exclusive (review finding 1): while a temporary password is in
    # force only its gate applies; the authenticator comes after it.
    if principal.user.must_change_password:
        if name not in PASSWORD_CHANGE_ROUTES:
            raise ProblemError(
                403, "password-change-required", "Change the temporary password to continue."
            )
    elif principal.mfa_setup_required and name not in MFA_SETUP_ROUTES:
        raise ProblemError(403, "mfa-setup-required", "Set up two-factor sign-in to continue.")
    needed = extra.get("x-permission")
    if needed and needed not in principal.permissions:
        raise ProblemError(403, "forbidden", "You do not have permission for this action.")
    request.state.principal = principal


def current_principal(request: Request) -> Principal:
    """The principal :func:`authorize` stored; 401 if the gate did not run."""
    principal = getattr(request.state, "principal", None)
    if not isinstance(principal, Principal):
        raise services.unauthenticated()
    return principal


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]
