"""Auth, users, roles and ``/me`` routes; mounted under /api/v1 by regwatch.api.app.

Auth and ``/me/sessions`` (#31) and user and role administration (#32) are implemented;
``/me/preferences`` reads and merges the user's preferences (M9).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import RedirectResponse

from regwatch.core.db import DbSession
from regwatch.core.routing import Paging, Tags, spec
from regwatch.core.schemas import Page
from regwatch.core.settings import Settings, get_settings
from regwatch.identity import groups, oidc, services
from regwatch.identity.permissions import CurrentPrincipal
from regwatch.identity.schemas import (
    Group,
    GroupWrite,
    InterestOptions,
    Login,
    Me,
    MyGroup,
    PasswordChange,
    Permission,
    Preferences,
    Role,
    RoleWrite,
    SessionInfo,
    SsoStatus,
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


@router.get("/auth/sso", tags=AUTH,
            **spec(SsoStatus, desc="Whether sign-in with the organisation's account is on (CP-37)",
                   public=True, stub=False))  # fmt: skip
async def sso_status(db: DbSession, settings: SettingsDep) -> SsoStatus:
    return SsoStatus(enabled=await services.sso_enabled(db, settings))


@router.get(
    "/auth/oidc/login", tags=AUTH,
    **spec(status=302, desc="To the identity provider (CP-37; M1b)", public=True, errors=(404,),
           stub=False),
)  # fmt: skip
async def oidc_login(
    db: DbSession, settings: SettingsDep, next: Annotated[str | None, Query(max_length=500)] = None
) -> Response:  # noqa: A002
    if not await services.sso_enabled(db, settings):
        raise oidc.unavailable()
    try:
        url, cookie = await oidc.start(settings, next)
    except oidc.SsoError as exc:
        return RedirectResponse(f"/login?sso={exc.reason}", status_code=302)
    response = RedirectResponse(url, status_code=302)
    response.set_cookie(oidc.STATE_COOKIE, cookie, max_age=oidc.STATE_MAX_AGE_S,
                        path="/api/v1/auth/oidc", secure=True, httponly=True,
                        samesite="lax")  # fmt: skip
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get(
    "/auth/oidc/callback", tags=AUTH,
    **spec(status=302, desc="Back from the identity provider: signed in, or to the login page "
           "with the reason (CP-37)", public=True, stub=False),
)  # fmt: skip
async def oidc_callback(
    request: Request, db: DbSession, settings: SettingsDep,
    code: Annotated[str | None, Query(max_length=2048)] = None,
    state: Annotated[str | None, Query(max_length=256)] = None,
    error: Annotated[str | None, Query(max_length=256)] = None,
) -> Response:  # fmt: skip
    if not await services.sso_enabled(db, settings):
        raise oidc.unavailable()
    target = "/login?sso=refused"
    response = RedirectResponse(target, status_code=302)
    try:
        if error:
            raise oidc.SsoError("refused", "the provider refused the sign-in")
        identity, next_path = await oidc.finish(
            settings, request.cookies.get(oidc.STATE_COOKIE), state, code)  # fmt: skip
        response = RedirectResponse(next_path, status_code=302)
        await services.sso_sign_in(db, request, response, settings, identity)
    except oidc.SsoError as exc:
        response = RedirectResponse(f"/login?sso={exc.reason}", status_code=302)
    response.delete_cookie(oidc.STATE_COOKIE, path="/api/v1/auth/oidc", secure=True,
                           httponly=True, samesite="lax")  # fmt: skip
    response.headers["Cache-Control"] = "no-store"
    return response


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
    "/me/interest-options", tags=ME,
    **spec(InterestOptions, desc="What a user may pick as interests", perm="items.read",
           stub=False),
)  # fmt: skip
async def get_interest_options(principal: CurrentPrincipal, db: DbSession) -> InterestOptions:
    return await services.interest_options(db)


@router.get(
    "/me/groups", tags=ME,
    **spec(list[MyGroup], desc="Your groups and their interests", stub=False),
)  # fmt: skip
async def get_my_groups(principal: CurrentPrincipal, db: DbSession) -> list[MyGroup]:
    return await groups.my_groups(db, principal.user.id)


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


# Groups (CP-27): members get the group's roles alongside their own.
@router.get("/admin/groups", tags=ADMIN, **spec(list[Group], desc="Groups", perm=USERS, stub=False))
async def list_groups(db: DbSession) -> list[Group]:
    return await groups.list_groups(db)


@router.post(
    "/admin/groups", tags=ADMIN, **spec(Group, status=201, desc="Created", perm=USERS, stub=False)
)  # fmt: skip
async def create_group(
    body: GroupWrite, principal: CurrentPrincipal, request: Request, db: DbSession
) -> Group:
    changes = body.model_dump(exclude_unset=True)
    return await groups.create_group(db, changes, principal, services.client_ip(request))


@router.patch(
    "/admin/groups/{id}", tags=ADMIN, **spec(Group, desc="Updated", perm=USERS, stub=False)
)  # fmt: skip
async def update_group(
    id: UUID, body: GroupWrite, principal: CurrentPrincipal, request: Request, db: DbSession
) -> Group:
    changes = body.model_dump(exclude_unset=True)
    return await groups.update_group(db, id, changes, principal, services.client_ip(request))


@router.delete(
    "/admin/groups/{id}", tags=ADMIN, **spec(status=204, desc="Deleted", perm=USERS, stub=False)
)  # fmt: skip
async def delete_group(
    id: UUID, principal: CurrentPrincipal, request: Request, db: DbSession
) -> Response:
    await groups.delete_group(db, id, principal, services.client_ip(request))
    return Response(status_code=204)


@router.put(
    "/admin/groups/{id}/members/{user_id}", tags=ADMIN,
    **spec(status=204, desc="Member", perm=USERS, stub=False),
)  # fmt: skip
async def add_member(
    id: UUID, user_id: UUID, principal: CurrentPrincipal, request: Request, db: DbSession
) -> Response:
    await groups.set_member(db, id, user_id, True, principal, services.client_ip(request))
    return Response(status_code=204)


@router.delete(
    "/admin/groups/{id}/members/{user_id}", tags=ADMIN,
    **spec(status=204, desc="Not a member", perm=USERS, stub=False),
)  # fmt: skip
async def remove_member(
    id: UUID, user_id: UUID, principal: CurrentPrincipal, request: Request, db: DbSession
) -> Response:
    await groups.set_member(db, id, user_id, False, principal, services.client_ip(request))
    return Response(status_code=204)
