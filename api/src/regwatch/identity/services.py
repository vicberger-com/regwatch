"""Service layer; other modules call this module only through here (ADR-0001).

Authentication for every route (#31, ADR-0007):

- The application-wide gate is :func:`regwatch.identity.permissions.authorize`; it uses
  :func:`resolve_session` from here.
- :func:`login` applies the per-IP and per-account rate limits, the lockout (threshold and
  duration from the ``auth.*`` settings, 15-minute failure window from the M1 spec, BL-50),
  and answers the same way for unknown, disabled and wrong-password accounts.
- Sessions live in the ``session`` table; the cookie holds a random token whose sha256 is
  stored. Idle timeout is the user's preference bounded by ``sessions.idle_timeout_max_minutes``;
  absolute lifetime is ``sessions.absolute_lifetime_hours``.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Request, Response
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.admin.models import Setting
from regwatch.core import security
from regwatch.core.errors import ProblemError, ProblemFieldError
from regwatch.core.models import AuditLog
from regwatch.core.schemas import Page
from regwatch.core.services import audit
from regwatch.core.settings import Settings
from regwatch.identity.models import Permission, Role, RolePermission, User, UserRole, UserSession
from regwatch.identity.schemas import Me, Preferences, SessionInfo
from regwatch.identity.schemas import Permission as PermissionOut
from regwatch.identity.schemas import Role as RoleOut
from regwatch.identity.schemas import User as UserOut
from regwatch.identity.schemas import UserWithPassword as UserWithPasswordOut

LOCKOUT_WINDOW = timedelta(minutes=15)  # M1 spec; no settings key yet (BL-50)
LOGIN_RATE = (5, 60.0)  # attempts per seconds, per IP and per account (8.2)
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


def invalid_credentials() -> ProblemError:
    return ProblemError(401, "invalid-credentials", "The email or password is incorrect.")


def account_locked() -> ProblemError:
    return ProblemError(
        423, "locked", "The account is locked. Try again later or ask an administrator.",
        title="Locked",
    )  # fmt: skip


class SlidingWindow:
    """In-process counter of events per key within a time window.

    State is per API process: with several workers each enforces its own limit, which still
    bounds the total. Keys are hashed by callers so emails are not held in memory in clear.
    """

    MAX_KEYS = 50_000

    def __init__(self, window_s: float) -> None:
        self.window_s = window_s
        self._hits: dict[str, deque[float]] = {}

    def _prune(self, key: str, now: float) -> deque[float]:
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= now - self.window_s:
            hits.popleft()
        return hits

    def count(self, key: str) -> int:
        return len(self._prune(key, time.monotonic()))

    def hit(self, key: str) -> int:
        now = time.monotonic()
        if len(self._hits) > self.MAX_KEYS:
            for k in [k for k, v in self._hits.items() if not v or v[-1] <= now - self.window_s]:
                del self._hits[k]
        hits = self._prune(key, now)
        hits.append(now)
        return len(hits)

    def retry_after(self, key: str) -> int:
        hits = self._prune(key, time.monotonic())
        return max(1, int(hits[0] + self.window_s - time.monotonic()) + 1) if hits else 1

    def clear(self) -> None:
        self._hits.clear()


login_attempts = SlidingWindow(LOGIN_RATE[1])
unknown_failures = SlidingWindow(LOCKOUT_WINDOW.total_seconds())


def _key(kind: str, value: str) -> str:
    return kind + ":" + hashlib.sha256(value.strip().lower().encode()).hexdigest()


def email_digest(email: str) -> str:
    """How an email appears in audit rows for unknown accounts (8.2: emails hashed)."""
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


def check_login_rate(ip: str | None, email: str) -> None:
    keys = [_key("acct", email)] + ([_key("ip", ip)] if ip else [])
    for key in keys:
        if login_attempts.count(key) >= LOGIN_RATE[0]:
            raise ProblemError(
                429, "rate-limited", "Too many sign-in attempts. Wait a minute and try again.",
                headers={"Retry-After": str(login_attempts.retry_after(key))},
            )  # fmt: skip
    for key in keys:
        login_attempts.hit(key)


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


async def _failures_in_window(db: AsyncSession, user: User, now: datetime) -> int:
    recent = await db.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(
            AuditLog.action == "auth.login_failed",
            AuditLog.entity_type == "user",
            AuditLog.entity_id == str(user.id),
            AuditLog.occurred_at > now - LOCKOUT_WINDOW,
        )
    )
    # failed_logins resets on success and on unlock, so earlier failures stop counting.
    return min(int(recent or 0), user.failed_logins)


async def create_session(
    db: AsyncSession, user: User, request: Request, cfg: dict[str, int]
) -> tuple[str, UserSession]:
    token = security.new_session_token()
    now = _now()
    sess = UserSession(
        user_id=user.id,
        token_hash=security.token_hash(token),
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(hours=cfg["sessions.absolute_lifetime_hours"]),
        ip=client_ip(request),
        user_agent=(request.headers.get("user-agent") or "")[:512] or None,
    )
    db.add(sess)
    await db.flush()
    return token, sess


def set_session_cookie(
    response: Response, settings: Settings, token: str, max_age: int | None
) -> None:
    response.set_cookie(
        settings.session_cookie_name, token, max_age=max_age, path="/",
        secure=True, httponly=True, samesite="lax",
    )  # fmt: skip


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        settings.session_cookie_name, path="/", secure=True, httponly=True, samesite="lax"
    )


async def revoke_token(db: AsyncSession, token: str | None) -> None:
    if token and len(token) <= 128:
        await db.execute(
            update(UserSession)
            .where(UserSession.token_hash == security.token_hash(token))
            .where(UserSession.revoked_at.is_(None))
            .values(revoked_at=_now())
        )


async def login(
    db: AsyncSession,
    request: Request,
    response: Response,
    settings: Settings,
    email: str,
    password: str,
    remember_me: bool,
) -> Me:
    ip = client_ip(request)
    check_login_rate(ip, email)
    cfg = await auth_settings(db)
    threshold = cfg["auth.lockout_threshold"]
    now = _now()
    user = await db.scalar(select(User).where(User.email == email.strip()))

    if user is None or user.password_hash is None or user.status == "disabled":
        await security.verify_password_async(None, password)
        reason = {"reason": "unknown_or_disabled", "email_sha256": email_digest(email)}
        audit(db, "auth.login_failed", "user", user.id if user else None, ip=ip, after=reason)
        await db.commit()
        # Unknown accounts lock like real ones, so 423 does not reveal which emails exist.
        if unknown_failures.hit(_key("acct", email)) >= threshold:
            raise account_locked()
        raise invalid_credentials()

    if user.status == "locked":
        if user.locked_until is None or user.locked_until > now:
            raise account_locked()
        user.status, user.locked_until, user.failed_logins = "active", None, 0
        audit(db, "auth.unlocked", "user", user.id, ip=ip, after={"reason": "lock_expired"})

    if not await security.verify_password_async(user.password_hash, password):
        user.failed_logins += 1
        audit(db, "auth.login_failed", "user", user.id, ip=ip, after={"reason": "password"})
        await db.flush()
        if await _failures_in_window(db, user, now) >= threshold:
            user.status = "locked"
            user.locked_until = now + timedelta(minutes=cfg["auth.lockout_minutes"])
            locked = {"status": "locked", "locked_until": user.locked_until.isoformat()}
            audit(db, "auth.locked", "user", user.id, ip=ip,
                  before={"status": "active"}, after=locked)  # fmt: skip
            await db.commit()
            raise account_locked()
        await db.commit()
        raise invalid_credentials()

    if security.needs_rehash(user.password_hash):
        user.password_hash = await security.hash_password_async(password)
    user.failed_logins = 0
    user.last_login_at = now
    # Rotation on login: a session cookie the browser already holds is revoked (fixation).
    await revoke_token(db, request.cookies.get(settings.session_cookie_name))
    token, sess = await create_session(db, user, request, cfg)
    audit(db, "auth.login", "session", sess.id, actor=user.id, ip=ip)
    await db.commit()
    lifetime = cfg["sessions.absolute_lifetime_hours"] * 3600
    set_session_cookie(response, settings, token, lifetime if remember_me else None)
    roles, perms = await roles_and_permissions(db, user.id)
    return to_me(user, roles, perms)


async def logout(db: AsyncSession, principal: Principal, request: Request) -> None:
    await db.execute(
        update(UserSession).where(UserSession.id == principal.session_id).values(revoked_at=_now())
    )
    audit(db, "auth.logout", "session", principal.session_id, actor=principal.user.id,
          ip=client_ip(request))  # fmt: skip
    await db.commit()


def password_problem(message: str) -> ProblemError:
    return ProblemError(400, "password-policy", message)


async def change_password(
    db: AsyncSession,
    principal: Principal,
    request: Request,
    response: Response,
    settings: Settings,
    current: str,
    new: str,
) -> None:
    ip = client_ip(request)
    check_login_rate(ip, principal.user.email)
    cfg = await auth_settings(db)
    user = await db.get(User, principal.user.id)
    if user is None:
        raise unauthenticated()
    if not await security.verify_password_async(user.password_hash, current):
        audit(db, "auth.password_change_failed", "user", user.id, actor=user.id, ip=ip)
        await db.commit()
        raise password_problem("The current password is incorrect.")
    minimum = max(12, cfg["auth.password_min_length"])
    if len(new) < minimum:
        raise password_problem(f"The new password must have at least {minimum} characters.")
    if len(new) > security.MAX_PASSWORD_LENGTH:
        raise password_problem(
            f"The new password must have at most {security.MAX_PASSWORD_LENGTH} characters."
        )
    if new == current:
        raise password_problem("The new password must differ from the current one.")
    user.password_hash = await security.hash_password_async(new)
    was_temporary = user.must_change_password
    user.must_change_password = False
    user.updated_at = _now()
    # Every session of the user ends, including this one, which is replaced by a new one.
    await db.execute(
        update(UserSession)
        .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
        .values(revoked_at=_now())
    )
    token, sess = await create_session(db, user, request, cfg)
    audit(db, "auth.password_change", "user", user.id, actor=user.id, ip=ip,
          after={"was_temporary": was_temporary, "session_id": str(sess.id)})  # fmt: skip
    await db.commit()
    set_session_cookie(response, settings, token, None)


async def list_sessions(db: AsyncSession, principal: Principal) -> list[SessionInfo]:
    now = _now()
    rows = await db.scalars(
        select(UserSession)
        .where(
            UserSession.user_id == principal.user.id,
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > now,
        )
        .order_by(UserSession.last_seen_at.desc())
    )
    return [
        SessionInfo(
            id=s.id,
            created_at=s.created_at,
            last_seen_at=s.last_seen_at,
            expires_at=s.expires_at,
            ip=str(s.ip) if s.ip else None,
            user_agent=s.user_agent,
            current=s.id == principal.session_id,
        )  # fmt: skip
        for s in rows.all()
    ]


async def revoke_own_session(
    db: AsyncSession, principal: Principal, session_id: uuid.UUID, request: Request
) -> None:
    result = await db.execute(
        update(UserSession)
        .where(
            UserSession.id == session_id,
            UserSession.user_id == principal.user.id,
            UserSession.revoked_at.is_(None),
        )
        .values(revoked_at=_now())
        .returning(UserSession.id)
    )
    if result.first() is None:
        raise ProblemError(404, "not-found", "No such session.")
    audit(db, "session.revoke", "session", session_id, actor=principal.user.id,
          ip=client_ip(request))  # fmt: skip
    await db.commit()


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


# --- Administration of users and roles (#32) -------------------------------------------

USER_MANAGER = "users.manage"


def validation(field: str, message: str) -> ProblemError:
    return ProblemError(422, "validation", message,
                        errors=[ProblemFieldError(field=field, message=message)])  # fmt: skip


async def _role_keys_by_user(
    db: AsyncSession, user_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[str]]:
    out: dict[uuid.UUID, list[str]] = {uid: [] for uid in user_ids}
    rows = await db.execute(
        select(UserRole.user_id, Role.key)
        .join(Role, Role.id == UserRole.role_id)
        .where(UserRole.user_id.in_(user_ids))
        .order_by(Role.key)
    )
    for uid, key in rows.tuples().all():
        out[uid].append(key)
    return out


def user_out(user: User, roles: list[str]) -> UserOut:
    return UserOut(
        id=user.id, email=user.email, display_name=user.display_name, status=user.status,
        roles=roles, must_change_password=user.must_change_password,
        last_login_at=user.last_login_at, created_at=user.created_at,
    )  # fmt: skip


async def list_users(
    db: AsyncSession, page: int, page_size: int, q: str | None, status: str | None
) -> Page[UserOut]:
    conds: list[Any] = []
    if q:
        like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        conds.append(or_(User.email.ilike(like, escape="\\"),
                         User.display_name.ilike(like, escape="\\")))  # fmt: skip
    if status:
        conds.append(User.status == status)
    total = await db.scalar(select(func.count()).select_from(User).where(*conds)) or 0
    users = (await db.scalars(
        select(User).where(*conds).order_by(User.email).limit(page_size)
        .offset((page - 1) * page_size)
    )).all()  # fmt: skip
    roles = await _role_keys_by_user(db, [u.id for u in users])
    return Page[UserOut](items=[user_out(u, roles[u.id]) for u in users], total=total,
                         page=page, page_size=page_size)  # fmt: skip


async def _user_or_404(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise ProblemError(404, "not-found", "No such user.")
    return user


async def get_user(db: AsyncSession, user_id: uuid.UUID) -> UserOut:
    user = await _user_or_404(db, user_id)
    return user_out(user, (await _role_keys_by_user(db, [user.id]))[user.id])


async def _ensure_a_manager_remains(db: AsyncSession) -> None:
    """Refuse a change that would leave no active user able to manage users."""
    await db.flush()
    count = await db.scalar(
        select(func.count(func.distinct(User.id)))
        .join(UserRole, UserRole.user_id == User.id)
        .join(RolePermission, RolePermission.role_id == UserRole.role_id)
        .where(User.status == "active", RolePermission.permission_key == USER_MANAGER)
    )
    if not count:
        await db.rollback()
        raise validation("roles", "At least one active user must keep the users.manage permission.")


async def admin_create_user(
    db: AsyncSession, email: str, display_name: str, roles: list[str], actor: uuid.UUID
) -> UserWithPasswordOut:
    temporary = security.new_temporary_password()
    try:
        user = await create_user(db, email, display_name, temporary, roles,
                                 must_change_password=True, actor=actor)  # fmt: skip
    except ValueError as exc:
        if "exists" in str(exc):
            raise ProblemError(409, "conflict", "A user with this email exists.") from exc
        raise validation("roles", str(exc)) from exc
    await db.commit()
    out = user_out(user, sorted(set(roles)))
    return UserWithPasswordOut(**out.model_dump(exclude_unset=True), temporary_password=temporary)


async def _revoke_all(db: AsyncSession, user_id: uuid.UUID) -> None:
    await db.execute(
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=_now())
    )


async def update_user(
    db: AsyncSession, user_id: uuid.UUID, changes: dict[str, Any], actor: uuid.UUID,
    ip: str | None,
) -> UserOut:  # fmt: skip
    user = await _user_or_404(db, user_id)
    before_roles = (await _role_keys_by_user(db, [user.id]))[user.id]
    before = {"display_name": user.display_name, "status": user.status, "roles": before_roles}
    if "display_name" in changes:
        name = (changes["display_name"] or "").strip()
        if not name or len(name) > 120:
            raise validation("display_name", "Give a display name of 1 to 120 characters.")
        user.display_name = name
    if "status" in changes:
        status = str(changes["status"])
        if user_id == actor and status != "active":
            raise validation("status", "You cannot disable or lock your own account.")
        if status != user.status:
            if status == "active":  # unlock by admin (M1 design notes)
                user.failed_logins, user.locked_until = 0, None
            else:
                user.locked_until = None  # an admin lock has no end
                await _revoke_all(db, user.id)
            user.status = status
    if "roles" in changes:
        wanted = sorted(set(changes["roles"] or []))
        found = await db.execute(select(Role.key, Role.id).where(Role.key.in_(wanted)))
        ids: dict[str, uuid.UUID] = {key: rid for key, rid in found.tuples().all()}
        missing = sorted(set(wanted) - set(ids))
        if missing:
            raise validation("roles", f"unknown roles: {', '.join(missing)}")
        await db.execute(delete(UserRole).where(UserRole.user_id == user.id))
        db.add_all(UserRole(user_id=user.id, role_id=ids[k]) for k in wanted)
    user.updated_at = _now()
    await _ensure_a_manager_remains(db)
    after_roles = (await _role_keys_by_user(db, [user.id]))[user.id]
    after = {"display_name": user.display_name, "status": user.status, "roles": after_roles}
    if after != before:
        audit(db, "user.update", "user", user.id, actor=actor, ip=ip, before=before, after=after)
    await db.commit()
    return user_out(user, after_roles)


async def reset_password(
    db: AsyncSession, user_id: uuid.UUID, actor: uuid.UUID, ip: str | None
) -> str:
    user = await _user_or_404(db, user_id)
    temporary = security.new_temporary_password()
    user.password_hash = await security.hash_password_async(temporary)
    user.must_change_password = True
    user.failed_logins, user.locked_until = 0, None
    if user.status == "locked":
        user.status = "active"
    user.updated_at = _now()
    await _revoke_all(db, user.id)
    audit(db, "user.reset_password", "user", user.id, actor=actor, ip=ip)
    await db.commit()
    return temporary


async def _perms_by_role(db: AsyncSession) -> dict[uuid.UUID, list[str]]:
    out: dict[uuid.UUID, list[str]] = {}
    rows = await db.execute(
        select(RolePermission.role_id, RolePermission.permission_key).order_by(
            RolePermission.permission_key
        )
    )
    for rid, key in rows.tuples().all():
        out.setdefault(rid, []).append(key)
    return out


def role_out(role: Role, perms: list[str]) -> RoleOut:
    return RoleOut(id=role.id, key=role.key, label=role.label, permissions=perms,
                   system=role.system)  # fmt: skip


async def list_roles(db: AsyncSession) -> list[RoleOut]:
    perms = await _perms_by_role(db)
    roles = (await db.scalars(select(Role).order_by(Role.key))).all()
    return [role_out(r, perms.get(r.id, [])) for r in roles]


async def _check_permissions(db: AsyncSession, keys: list[str]) -> list[str]:
    wanted = sorted(set(keys))
    known = set((await db.scalars(select(Permission.key).where(Permission.key.in_(wanted)))).all())
    missing = sorted(set(wanted) - known)
    if missing:
        raise validation("permissions", f"unknown permissions: {', '.join(missing)}")
    return wanted


async def create_role(
    db: AsyncSession, key: str | None, label: str | None, permissions: list[str] | None,
    actor: uuid.UUID, ip: str | None,
) -> RoleOut:  # fmt: skip
    if not key:
        raise validation("key", "A role key is required.")
    if not label or not label.strip():
        raise validation("label", "A label is required.")
    if await db.scalar(select(Role.id).where(Role.key == key)) is not None:
        raise validation("key", "A role with this key exists.")
    perms = await _check_permissions(db, permissions or [])
    role = Role(key=key, label=label.strip()[:120], system=False)
    db.add(role)
    await db.flush()
    db.add_all(RolePermission(role_id=role.id, permission_key=p) for p in perms)
    audit(db, "role.create", "role", role.id, actor=actor, ip=ip,
          after={"key": key, "label": role.label, "permissions": perms})  # fmt: skip
    await db.commit()
    return role_out(role, perms)


async def _role_or_404(db: AsyncSession, role_id: uuid.UUID) -> Role:
    role = await db.get(Role, role_id)
    if role is None:
        raise ProblemError(404, "not-found", "No such role.")
    return role


async def update_role(
    db: AsyncSession, role_id: uuid.UUID, changes: dict[str, Any], actor: uuid.UUID,
    ip: str | None,
) -> RoleOut:  # fmt: skip
    role = await _role_or_404(db, role_id)
    perms_before = (await _perms_by_role(db)).get(role.id, [])
    before = {"key": role.key, "label": role.label, "permissions": perms_before}
    if "key" in changes and changes["key"] != role.key:
        if role.system:
            raise validation("key", "A system role keeps its key.")
        if await db.scalar(select(Role.id).where(Role.key == changes["key"])) is not None:
            raise validation("key", "A role with this key exists.")
        role.key = changes["key"]
    if "label" in changes:
        label = (changes["label"] or "").strip()
        if not label:
            raise validation("label", "A label is required.")
        role.label = label[:120]
    perms = perms_before
    if "permissions" in changes:
        perms = await _check_permissions(db, changes["permissions"] or [])
        if role.key == "admin" and role.system and perms != perms_before:
            raise validation("permissions", "The admin role always holds every permission.")
        await db.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
        db.add_all(RolePermission(role_id=role.id, permission_key=p) for p in perms)
    role.updated_at = _now()
    await _ensure_a_manager_remains(db)
    after = {"key": role.key, "label": role.label, "permissions": perms}
    if after != before:
        audit(db, "role.update", "role", role.id, actor=actor, ip=ip, before=before, after=after)
    await db.commit()
    return role_out(role, perms)


async def delete_role(
    db: AsyncSession, role_id: uuid.UUID, actor: uuid.UUID, ip: str | None
) -> None:
    role = await _role_or_404(db, role_id)
    if role.system:
        raise ProblemError(409, "conflict", "System roles cannot be deleted.")
    holders = await db.scalar(select(func.count()).select_from(UserRole)
                              .where(UserRole.role_id == role.id))  # fmt: skip
    if holders:
        raise ProblemError(409, "conflict", f"The role is assigned to {holders} user(s).")
    perms = (await _perms_by_role(db)).get(role.id, [])
    audit(db, "role.delete", "role", role.id, actor=actor, ip=ip,
          before={"key": role.key, "label": role.label, "permissions": perms})  # fmt: skip
    await db.delete(role)
    await db.commit()


async def list_permissions(db: AsyncSession) -> list[PermissionOut]:
    rows = await db.scalars(select(Permission).order_by(Permission.key))
    return [PermissionOut(key=p.key, description=p.description, module=p.module)
            for p in rows.all()]  # fmt: skip
