"""Service layer; other modules call this module only through here (ADR-0001).

Local accounts (#31): :func:`create_user` makes an account with Argon2id hashing; it is
used by ``regwatch-admin create-user``. Defaults for the ``auth.*`` and ``sessions.*``
settings come from registries.yaml and are read by :func:`auth_settings`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.admin.models import Setting
from regwatch.core import security
from regwatch.core.services import audit
from regwatch.identity.models import Role, User, UserRole

AUTH_DEFAULTS: dict[str, int] = {
    "auth.lockout_threshold": 10,
    "auth.lockout_minutes": 30,
    "auth.password_min_length": 12,
    "sessions.idle_timeout_max_minutes": 480,
    "sessions.absolute_lifetime_hours": 12,
}


def _now() -> datetime:
    return datetime.now(UTC)


async def auth_settings(db: AsyncSession) -> dict[str, int]:
    stmt = select(Setting.key, Setting.value).where(Setting.key.in_(AUTH_DEFAULTS))
    rows = await db.execute(stmt)
    values = dict(AUTH_DEFAULTS)
    for key, value in rows.all():
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            values[key] = value
    return values


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
