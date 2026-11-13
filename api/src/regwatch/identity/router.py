"""Auth, users, roles and ``/me`` routes; mounted under /api/v1 by regwatch.api.app.

Login, logout and ``/auth/me`` are implemented (#31); the other stubs answer 501 until
#31 and #32 land.
"""

from __future__ import annotations

from typing import Annotated, NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from regwatch.core.db import DbSession
from regwatch.core.routing import Paging, Tags, not_implemented, spec
from regwatch.core.schemas import Page
from regwatch.core.settings import Settings, get_settings
from regwatch.identity import services
from regwatch.identity.permissions import CurrentPrincipal
from regwatch.identity.schemas import (
    Login,
    Me,
    PasswordChange,
    Permission,
    Preferences,
    Role,
    RoleWrite,
    SessionInfo,
    TemporaryPassword,
    User,
    UserCreate,
    UserStatus,
    UserUpdate,
    UserWithPassword,
)

router = APIRouter()
AUTH: Tags = ["auth"]
ADMIN: Tags = ["admin"]
ME: Tags = ["me"]
USERS, ROLES = "users.manage", "roles.manage"
SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.post(
    "/auth/login", tags=AUTH,
    **spec(Me, desc="Session cookie set", public=True, errors=(401, 423, 429),
           error_desc={423: "Account locked"}, stub=False),
)  # fmt: skip
async def login(
    body: Login, request: Request, response: Response, db: DbSession, settings: SettingsDep
) -> Me:
    return await services.login(
        db, request, response, settings, body.email, body.password, body.remember_me
    )


@router.post(
    "/auth/logout", tags=AUTH, **spec(status=204, desc="Session revoked", stub=False)
)  # fmt: skip
async def logout(
    principal: CurrentPrincipal, request: Request, db: DbSession, settings: SettingsDep
) -> Response:
    await services.logout(db, principal, request)
    response = Response(status_code=204)
    services.clear_session_cookie(response, settings)
    return response


@router.get("/auth/me", tags=AUTH, **spec(Me, desc="Current user", stub=False))
async def auth_me(principal: CurrentPrincipal) -> Me:
    return services.to_me(principal.user, principal.roles, principal.permissions)


@router.post("/auth/password", tags=AUTH, **spec(status=204, desc="Changed", errors=(400,)))
async def change_password(body: PasswordChange) -> NoReturn:
    not_implemented()


@router.get("/admin/users", tags=ADMIN, **spec(Page[User], desc="Users", perm=USERS))
async def list_users(
    paging: Paging, q: str | None = None, status: UserStatus | None = None
) -> NoReturn:
    not_implemented()


@router.post(
    "/admin/users", tags=ADMIN,
    **spec(UserWithPassword, status=201, desc="Created; temporary password returned once",
           perm=USERS, errors=(409,)),
)  # fmt: skip
async def create_user(body: UserCreate) -> NoReturn:
    not_implemented()


@router.get("/admin/users/{id}", tags=ADMIN, **spec(User, desc="User", perm=USERS, errors=(404,)))
async def get_user(id: UUID) -> NoReturn:
    not_implemented()


@router.patch("/admin/users/{id}", tags=ADMIN, **spec(User, desc="Updated", perm=USERS))
async def update_user(id: UUID, body: UserUpdate) -> NoReturn:
    not_implemented()


@router.post(
    "/admin/users/{id}/reset-password", tags=ADMIN,
    **spec(TemporaryPassword, desc="One-time temporary password", perm=USERS),
)  # fmt: skip
async def reset_password(id: UUID) -> NoReturn:
    not_implemented()


@router.get("/admin/roles", tags=ADMIN, **spec(list[Role], desc="Roles", perm=ROLES))
async def list_roles() -> NoReturn:
    not_implemented()


@router.post("/admin/roles", tags=ADMIN, **spec(Role, status=201, desc="Created", perm=ROLES))
async def create_role(body: RoleWrite) -> NoReturn:
    not_implemented()


@router.patch("/admin/roles/{id}", tags=ADMIN, **spec(Role, desc="Updated", perm=ROLES))
async def update_role(id: UUID, body: RoleWrite) -> NoReturn:
    not_implemented()


@router.delete(
    "/admin/roles/{id}", tags=ADMIN, **spec(status=204, desc="Deleted", perm=ROLES, errors=(409,))
)
async def delete_role(id: UUID) -> NoReturn:
    not_implemented()


@router.get(
    "/admin/permissions", tags=ADMIN,
    **spec(list[Permission], desc="Permission catalogue from registries.yaml", perm=ROLES),
)  # fmt: skip
async def list_permissions() -> NoReturn:
    not_implemented()


@router.get("/me/preferences", tags=ME, **spec(Preferences, desc="Preferences"))
async def get_preferences() -> NoReturn:
    not_implemented()


@router.patch("/me/preferences", tags=ME, **spec(Preferences, desc="Updated", errors=(400,)))
async def update_preferences(body: Preferences) -> NoReturn:
    not_implemented()


@router.get("/me/sessions", tags=ME, **spec(list[SessionInfo], desc="Active sessions"))
async def list_sessions() -> NoReturn:
    not_implemented()


@router.delete("/me/sessions/{id}", tags=ME, **spec(status=204, desc="Revoked"))
async def revoke_session(id: UUID) -> NoReturn:
    not_implemented()
