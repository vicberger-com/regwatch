"""Service layer; other modules call this module only through here (ADR-0001).

Sessions (#31): the application-wide gate is
:func:`regwatch.identity.permissions.authorize`; it uses :func:`resolve_session` from
here. Sessions live in the ``session`` table; the cookie holds a random token whose
sha256 is stored. Idle timeout is the user's preference bounded by
``sessions.idle_timeout_max_minutes``; absolute lifetime is
``sessions.absolute_lifetime_hours``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.admin.models import Setting
from regwatch.core import security
from regwatch.core.errors import ProblemError
from regwatch.core.services import audit
from regwatch.identity.models import Role, RolePermission, User, UserRole, UserSession
from regwatch.identity.schemas import Me, Preferences

TOUCH_INTERVAL = timedelta(seconds=60)

AUTH_DEFAULTS: dict[str, int] = {
    "auth.lockout_threshold": 10,
    "auth.lockout_minutes": 30,
    "auth.password_min_length": 12,
    "sessions.idle_timeout_max_minutes": 480,
    "sessions.absolute_lifetime_hours": 12,
}


def _now() -> datetime:
    return datetime.now(UTC)


def unauthenticated() -> ProblemError:
    return ProblemError(401, "unauthenticated", "Sign in to continue.")


async def auth_settings(db: AsyncSession) -> dict[str, int]:
    stmt = select(Setting.key, Setting.value).where(Setting.key.in_(AUTH_DEFAULTS))
    rows = await db.execute(stmt)
    values = dict(AUTH_DEFAULTS)
    for key, value in rows.all():
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            values[key] = value
    return values


@dataclass(frozen=True)
class Principal:
    user: User
    session_id: uuid.UUID
    roles: tuple[str, ...]
    permissions: frozenset[str]


async def roles_and_permissions(
    db: AsyncSession, user_id: uuid.UUID
) -> tuple[tuple[str, ...], frozenset[str]]:
    rows = await db.execute(
        select(Role.key, RolePermission.permission_key)
        .join(UserRole, UserRole.role_id == Role.id)
        .outerjoin(RolePermission, RolePermission.role_id == Role.id)
        .where(UserRole.user_id == user_id)
    )
    roles: set[str] = set()
    perms: set[str] = set()
    for role, perm in rows.all():
        roles.add(role)
        if perm:
            perms.add(perm)
    return tuple(sorted(roles)), frozenset(perms)


def to_me(user: User, roles: tuple[str, ...], perms: frozenset[str]) -> Me:
    return Me(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        status=user.status,
        roles=list(roles),
        must_change_password=user.must_change_password,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        permissions=sorted(perms),
        preferences=Preferences.model_validate(user.preferences or {}),
    )


def _idle_minutes(user: User, cfg: dict[str, int]) -> int:
    ceiling = cfg["sessions.idle_timeout_max_minutes"]
    wanted = (user.preferences or {}).get("session_idle_timeout_minutes")
    if isinstance(wanted, int) and not isinstance(wanted, bool) and wanted >= 15:
        return min(wanted, ceiling)
    return ceiling


async def resolve_session(db: AsyncSession, token: str) -> Principal | None:
    """The live session for a cookie value, or None; touches ``last_seen_at``."""
    found = (
        await db.execute(
            select(UserSession, User)
            .join(User, User.id == UserSession.user_id)
            .where(UserSession.token_hash == security.token_hash(token))
        )
    ).first()
    if found is None:
        return None
    sess, user = found
    now = _now()
    if sess.revoked_at is not None or sess.expires_at <= now or user.status != "active":
        return None
    cfg = await auth_settings(db)
    if sess.last_seen_at + timedelta(minutes=_idle_minutes(user, cfg)) <= now:
        sess.revoked_at = now
        await db.commit()
        return None
    if now - sess.last_seen_at >= TOUCH_INTERVAL:
        sess.last_seen_at = now
        await db.commit()
    roles, perms = await roles_and_permissions(db, user.id)
    return Principal(user=user, session_id=sess.id, roles=roles, permissions=perms)


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


async def create_user(
    db: AsyncSession,
    email: str,
    display_name: str,
    password: str,
    roles: list[str],
    *,
    must_change_password: bool,
    actor: uuid.UUID | None = None,
) -> User:
    """Create a local account with ``roles`` (keys); used by ``regwatch-admin`` and M1 admin."""
    found = await db.execute(select(Role.key, Role.id).where(Role.key.in_(roles)))
    role_ids: dict[str, uuid.UUID] = {key: rid for key, rid in found.all()}
    missing = sorted(set(roles) - set(role_ids))
    if missing:
        raise ValueError(f"unknown roles: {', '.join(missing)}")
    if await db.scalar(select(User.id).where(User.email == email.strip())) is not None:
        raise ValueError("a user with this email exists")
    user = User(
        email=email.strip(),
        display_name=display_name,
        password_hash=await security.hash_password_async(password),
        must_change_password=must_change_password,
        preferences={},
    )
    db.add(user)
    await db.flush()
    db.add_all(UserRole(user_id=user.id, role_id=role_ids[r]) for r in sorted(set(roles)))
    audit(db, "user.create", "user", user.id, actor=actor,
          after={"display_name": display_name, "roles": sorted(set(roles))})  # fmt: skip
    return user
