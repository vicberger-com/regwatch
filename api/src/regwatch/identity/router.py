"""Auth, users, roles and ``/me`` routes; mounted under /api/v1 by regwatch.api.app.

Auth and ``/me/sessions`` (#31) and user and role administration (#32) are implemented;
``/me/preferences`` reads and merges the user's preferences (M9).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from regwatch.core.db import DbSession
from regwatch.core.routing import Paging, Tags, spec
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


@router.post(
    "/auth/password", tags=AUTH, **spec(status=204, desc="Changed", errors=(400,), stub=False)
)  # fmt: skip
async def change_password(
    body: PasswordChange,
    principal: CurrentPrincipal,
    request: Request,
    db: DbSession,
    settings: SettingsDep,
) -> Response:
    response = Response(status_code=204)
    await services.change_password(
        db, principal, request, response, settings, body.current_password, body.new_password
    )
    return response


@router.get(
    "/admin/users", tags=ADMIN, **spec(Page[User], desc="Users", perm=USERS, stub=False)
)  # fmt: skip
async def list_users(
    paging: Paging, db: DbSession, q: str | None = None, status: UserStatus | None = None
) -> Page[User]:
    return await services.list_users(db, paging.page, paging.page_size, q, status)


@router.post(
    "/admin/users", tags=ADMIN,
    **spec(UserWithPassword, status=201, desc="Created; temporary password returned once",
           perm=USERS, errors=(409,), stub=False),
)  # fmt: skip
async def create_user(
    body: UserCreate, principal: CurrentPrincipal, request: Request, response: Response,
    db: DbSession,
) -> UserWithPassword:  # fmt: skip
    response.headers["Cache-Control"] = "no-store"  # carries a credential (finding 11)
    out = await services.admin_create_user(
        db, body.email, body.display_name, body.roles, principal, services.client_ip(request)
    )
    return out


@router.get(
    "/admin/users/{id}", tags=ADMIN,
    **spec(User, desc="User", perm=USERS, errors=(404,), stub=False),
)  # fmt: skip
async def get_user(id: UUID, db: DbSession) -> User:
    return await services.get_user(db, id)


@router.patch("/admin/users/{id}", tags=ADMIN, **spec(User, desc="Updated", perm=USERS, stub=False))
async def update_user(
    id: UUID, body: UserUpdate, principal: CurrentPrincipal, request: Request, db: DbSession
) -> User:
    return await services.update_user(
        db, id, body.model_dump(exclude_unset=True), principal,
        services.client_ip(request),
    )  # fmt: skip


@router.post(
    "/admin/users/{id}/reset-password", tags=ADMIN,
    **spec(TemporaryPassword, desc="One-time temporary password", perm=USERS, stub=False),
)  # fmt: skip
async def reset_password(
    id: UUID, principal: CurrentPrincipal, request: Request, response: Response, db: DbSession
) -> TemporaryPassword:
    response.headers["Cache-Control"] = "no-store"  # carries a credential (finding 11)
    temporary = await services.reset_password(db, id, principal, services.client_ip(request))
    return TemporaryPassword(temporary_password=temporary)


@router.get(
    "/admin/roles", tags=ADMIN, **spec(list[Role], desc="Roles", perm=ROLES, stub=False)
)  # fmt: skip
async def list_roles(db: DbSession) -> list[Role]:
    return await services.list_roles(db)


@router.post(
    "/admin/roles", tags=ADMIN,
    **spec(Role, status=201, desc="Created", perm=ROLES, stub=False),
)  # fmt: skip
async def create_role(
    body: RoleWrite, principal: CurrentPrincipal, request: Request, db: DbSession
) -> Role:
    return await services.create_role(
        db, body.key, body.label, body.permissions, principal,
        services.client_ip(request),
    )  # fmt: skip


@router.patch(
    "/admin/roles/{id}", tags=ADMIN, **spec(Role, desc="Updated", perm=ROLES, stub=False)
)  # fmt: skip
async def update_role(
    id: UUID, body: RoleWrite, principal: CurrentPrincipal, request: Request, db: DbSession
) -> Role:
    return await services.update_role(
        db, id, body.model_dump(exclude_unset=True), principal,
        services.client_ip(request),
    )  # fmt: skip


@router.delete(
    "/admin/roles/{id}", tags=ADMIN,
    **spec(status=204, desc="Deleted", perm=ROLES, errors=(409,), stub=False),
)  # fmt: skip
async def delete_role(
    id: UUID, principal: CurrentPrincipal, request: Request, db: DbSession
) -> Response:
    await services.delete_role(db, id, principal, services.client_ip(request))
    return Response(status_code=204)


@router.get(
    "/admin/permissions", tags=ADMIN,
    **spec(list[Permission], desc="Permission catalogue from registries.yaml", perm=ROLES,
           stub=False),
)  # fmt: skip
async def list_permissions(db: DbSession) -> list[Permission]:
    return await services.list_permissions(db)


@router.get("/me/preferences", tags=ME, **spec(Preferences, desc="Preferences", stub=False))
async def get_preferences(principal: CurrentPrincipal, db: DbSession) -> Preferences:
    return await services.get_preferences(db, principal)


@router.patch(
    "/me/preferences", tags=ME,
    **spec(Preferences, desc="Updated", errors=(400,), stub=False),
)  # fmt: skip
async def update_preferences(body: Preferences, principal: CurrentPrincipal,
                             db: DbSession) -> Preferences:  # fmt: skip
    return await services.update_preferences(db, principal, body)


@router.get(
    "/me/sessions", tags=ME, **spec(list[SessionInfo], desc="Active sessions", stub=False)
)  # fmt: skip
async def list_sessions(principal: CurrentPrincipal, db: DbSession) -> list[SessionInfo]:
    return await services.list_sessions(db, principal)


@router.delete("/me/sessions/{id}", tags=ME, **spec(status=204, desc="Revoked", stub=False))
async def revoke_session(
    id: UUID, principal: CurrentPrincipal, request: Request, db: DbSession
) -> Response:
    await services.revoke_own_session(db, principal, id, request)
    return Response(status_code=204)
