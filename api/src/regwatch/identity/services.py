"""Service layer; other modules call this module only through here (ADR-0001).

Authentication for every route (#31, ADR-0007):

- The application-wide gate is :func:`regwatch.identity.permissions.authorize`; it uses
  :func:`resolve_session` from here.
- :func:`login` applies the per-account and per-address limits on failed attempts (ADR-0007
  amendment 1), the lockout (threshold and
  duration from the ``auth.*`` settings, 15-minute failure window from the M1 spec, BL-50),
  and answers the same way for unknown, disabled and wrong-password accounts.
- Sessions live in the ``session`` table; the cookie holds a random token whose sha256 is
  stored. Idle timeout is the user's preference bounded by ``sessions.idle_timeout_max_minutes``;
  absolute lifetime is ``sessions.absolute_lifetime_hours``.
"""

from __future__ import annotations

import hashlib
import ipaddress
import time
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import cache
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
from regwatch.identity.models import (
    GroupMember,
    GroupRole,
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
    UserSession,
)
from regwatch.identity.schemas import (
    InterestFacet,
    InterestJurisdiction,
    InterestOption,
    InterestOptions,
    InterestRegion,
    Interests,
    Me,
    Preferences,
    SessionInfo,
)
from regwatch.identity.schemas import Permission as PermissionOut
from regwatch.identity.schemas import Role as RoleOut
from regwatch.identity.schemas import User as UserOut
from regwatch.identity.schemas import UserWithPassword as UserWithPasswordOut

LOCKOUT_WINDOW = timedelta(minutes=15)  # M1 spec; no settings key yet (BL-50)
# Failed attempts allowed per window (8.2; use testing U-M1-1, owner decision 2026-11-16). A
# successful sign-in or password change gives its attempt back, so only failures count.
LOGIN_RATE_ACCOUNT = (5, 60.0)  # per account: guessing one account's password
LOGIN_RATE_IP = (30, 60.0)  # per address: spraying many accounts, without blocking a shared office
LOGIN_RATE_IP_HOURLY = (100, 3600.0)  # per address, so spraying stays slow over a day (review 3)
PASSWORD_CHANGE_RATE = (5, 60.0)  # per signed-in user, separate from sign-in
# Every attempt, never given back: correct passwords still cost an Argon2 hash (review 2).
LOGIN_ALL_RATE = (20, 60.0)  # per account
PASSWORD_CHANGE_ALL_RATE = (10, 60.0)  # per signed-in user
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

    def __init__(self, window_s: float, evict_live: bool = True) -> None:
        self.window_s = window_s
        self._hits: dict[str, deque[float]] = {}
        self._last_sweep = float("-inf")
        # Whether live keys may be evicted at the cap; not for the unknown-account lockout
        # counter, whose entries must last as long as a real account's (re-verification 2, N4).
        self.evict_live = evict_live

    def _prune(self, key: str, now: float) -> deque[float]:
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= now - self.window_s:
            hits.popleft()
        return hits

    def count(self, key: str) -> int:
        """Events in the window; looking never creates an entry (re-verification N1)."""
        if key not in self._hits:
            return 0
        hits = self._prune(key, time.monotonic())
        if not hits:
            del self._hits[key]
        return len(hits)

    def _sweep(self, now: float) -> None:
        # At most once per window, so a flood of keys cannot make every request scan them all
        # (re-verification N1); if expiry alone is not enough, the oldest keys go first.
        if now - self._last_sweep < self.window_s:
            return
        self._last_sweep = now
        for k in [k for k, v in self._hits.items() if not v or v[-1] <= now - self.window_s]:
            del self._hits[k]
        if self.evict_live:  # least recently hit first: hit() moves a key to the end
            for k in list(self._hits)[: max(0, len(self._hits) - self.MAX_KEYS * 9 // 10)]:
                del self._hits[k]

    def hit(self, key: str) -> int:
        now = time.monotonic()
        if len(self._hits) > self.MAX_KEYS:
            self._sweep(now)
        hits = self._prune(key, now)
        hits.append(now)
        self._hits[key] = self._hits.pop(key)  # most recently hit last, for the eviction order
        return len(hits)

    def retry_after(self, key: str) -> int:
        if key not in self._hits:  # looking never creates an entry
            return 1
        hits = self._prune(key, time.monotonic())
        return max(1, int(hits[0] + self.window_s - time.monotonic()) + 1) if hits else 1

    def hit_at(self, key: str) -> float:
        """Count an event and return its time, so ``refund`` can remove exactly that event."""
        self.hit(key)
        return self._hits[key][-1]

    def refund(self, key: str, at: float) -> None:
        """Give back the event counted at ``at``, if it is still in the window (review 1)."""
        hits = self._hits.get(key)
        if hits:
            try:
                hits.remove(at)
            except ValueError:
                pass  # already outside the window

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)

    def clear(self) -> None:
        self._hits.clear()
        self._last_sweep = float("-inf")


class LockTable:
    """In-process lock end times for unknown accounts, mirroring ``user.locked_until``."""

    MAX_KEYS = 50_000

    def __init__(self) -> None:
        self._until: dict[str, float] = {}

    def lock(self, key: str, seconds: float) -> None:
        now = time.monotonic()
        if len(self._until) > self.MAX_KEYS:
            self._until = {k: t for k, t in self._until.items() if t > now}
        self._until[key] = now + seconds

    def locked(self, key: str) -> bool:
        until = self._until.get(key)
        if until is None:
            return False
        if until <= time.monotonic():
            del self._until[key]
            return False
        return True

    def clear(self) -> None:
        self._until.clear()


login_attempts = SlidingWindow(LOGIN_RATE_ACCOUNT[1])
password_changes = SlidingWindow(PASSWORD_CHANGE_RATE[1])
login_attempts_hourly = SlidingWindow(LOGIN_RATE_IP_HOURLY[1])
all_attempts = SlidingWindow(LOGIN_ALL_RATE[1])
unknown_failures = SlidingWindow(LOCKOUT_WINDOW.total_seconds(), evict_live=False)
unknown_locks = LockTable()


def _key(kind: str, value: str) -> str:
    return kind + ":" + hashlib.sha256(value.strip().lower().encode()).hexdigest()


def email_digest(email: str) -> str:
    """How an email appears in audit rows for unknown accounts (8.2: emails hashed)."""
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


def _too_many(window: SlidingWindow, key: str, kind: str = "sign-in") -> ProblemError:
    return ProblemError(
        429, "rate-limited", f"Too many {kind} attempts. {WAIT}",
        headers={"Retry-After": str(window.retry_after(key))},
    )  # fmt: skip


def address_key(ip: str) -> str:
    """The rate-limit key of a client address; IPv6 by its /64, which one client controls."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return _key("ip", ip)
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.ipv4_mapped is not None:
            return _key("ip", str(addr.ipv4_mapped))
        return _key("ip6", str(ipaddress.ip_network(f"{addr}/64", strict=False)))
    return _key("ip", str(addr))


RateTicket = list[tuple[SlidingWindow, str, float]]
# (window, key, limit, given back on success)
Limit = tuple[SlidingWindow, str, int, bool]

WAIT = "Wait and try again."


def _check(limits: list[Limit], kind: str) -> RateTicket:
    """Every limit is checked before anything is counted, so a rejected request leaves no
    trace and cannot keep a client over a cap (re-verification N1, N2); then all are counted
    in the same synchronous step, so a burst cannot slip under them."""
    for window, key, limit, _ in limits:
        if window.count(key) >= limit:
            raise _too_many(window, key, kind)
    stamps = [
        (window, key, window.hit_at(key), refundable) for window, key, _, refundable in limits
    ]
    return [(window, key, at) for window, key, at, refundable in stamps if refundable]


def check_login_rate(ip: str | None, email: str) -> RateTicket:
    """429 past a limit; otherwise count this attempt and return what ``forgive`` gives back.

    The attempt is counted before the password is checked, so a burst of parallel requests on
    one API process cannot all slip under a limit (BL-65: the counters are per process). While
    an attempt is in progress it counts, and at a limit even a correct password gets 429.
    """
    account = _key("acct", email)
    limits: list[Limit] = [
        (all_attempts, f"all:{account}", LOGIN_ALL_RATE[0], False),  # never given back
        (login_attempts, account, LOGIN_RATE_ACCOUNT[0], True),
    ]
    if ip:
        addr = address_key(ip)
        limits += [(login_attempts, addr, LOGIN_RATE_IP[0], True),
                   (login_attempts_hourly, addr, LOGIN_RATE_IP_HOURLY[0], True)]  # fmt: skip
    return _check(limits, "sign-in")


def check_password_change_rate(user_id: uuid.UUID) -> RateTicket:
    key = f"pwchg:{user_id}"
    limits: list[Limit] = [
        (all_attempts, f"all:{key}", PASSWORD_CHANGE_ALL_RATE[0], False),  # never given back
        (password_changes, key, PASSWORD_CHANGE_RATE[0], True),
    ]
    return _check(limits, "password-change")


def forgive(ticket: RateTicket) -> None:
    """Give back exactly the counts this attempt added, after it succeeded."""
    for window, key, at in ticket:
        window.refund(key, at)


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
    # The user's own roles, and those of every group they are in (CP-27).
    own = select(UserRole.role_id).where(UserRole.user_id == user_id)
    via_groups = (select(GroupRole.role_id)
                  .join(GroupMember, GroupMember.group_id == GroupRole.group_id)
                  .where(GroupMember.user_id == user_id))  # fmt: skip
    rows = await db.execute(
        select(Role.key, RolePermission.permission_key)
        .outerjoin(RolePermission, RolePermission.role_id == Role.id)
        .where(Role.id.in_(own.union(via_groups)))
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
        preferences=stored_preferences(user.preferences),
    )


def _idle_minutes(user: User, cfg: dict[str, int]) -> int:
    ceiling = cfg["sessions.idle_timeout_max_minutes"]
    wanted = (user.preferences or {}).get("session_idle_timeout_minutes")
    if isinstance(wanted, int) and not isinstance(wanted, bool) and wanted >= 15:
        return min(wanted, ceiling)
    return ceiling


async def resolve_session(db: AsyncSession, token: str, passive: bool = False) -> Principal | None:
    """The live session for a cookie value, or None; touches ``last_seen_at`` unless the
    request is ``passive`` (a page polling on its own, such as the live map): such a request
    is checked against the idle limit like any other but never renews it."""
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
    if not passive and now - sess.last_seen_at >= TOUCH_INTERVAL:
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


async def _count_failure(
    db: AsyncSession, user: User, ip: str | None, cfg: dict[str, int], now: datetime,
    reason: str,
) -> bool:  # fmt: skip
    """Record a wrong password for ``user`` (row locked by the caller); lock the account and
    end its sessions at the threshold. True when this failure locked it."""
    user.failed_logins += 1
    audit(db, "auth.login_failed", "user", user.id, ip=ip, after={"reason": reason})
    await db.flush()
    if await _failures_in_window(db, user, now) < cfg["auth.lockout_threshold"]:
        return False
    user.status = "locked"
    user.locked_until = now + timedelta(minutes=cfg["auth.lockout_minutes"])
    locked = {"status": "locked", "locked_until": user.locked_until.isoformat()}
    audit(db, "auth.locked", "user", user.id, ip=ip, before={"status": "active"}, after=locked)
    await _revoke_all(db, user.id)  # a locked account keeps no live session
    return True


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
    rate_ticket = check_login_rate(ip, email)
    cfg = await auth_settings(db)
    threshold = cfg["auth.lockout_threshold"]
    now = _now()
    # The row lock serialises concurrent attempts on one account, so every failure counts
    # (review finding 1); it is held for one Argon2 verify at most.
    user = await db.scalar(select(User).where(User.email == email.strip()).with_for_update())

    if user is None or user.password_hash is None or user.status == "disabled":
        key = _key("acct", email)
        await security.verify_password_async(None, password)
        if unknown_locks.locked(key):
            raise account_locked()
        reason = {"reason": "unknown_or_disabled", "email_sha256": email_digest(email)}
        audit(db, "auth.login_failed", "user", user.id if user else None, ip=ip, after=reason)
        await db.commit()
        # Unknown accounts lock like real ones, for as long, so 423 does not reveal which
        # emails exist (M1 acceptance 3, review finding 4).
        if unknown_failures.hit(key) >= threshold:
            unknown_locks.lock(key, cfg["auth.lockout_minutes"] * 60.0)
            unknown_failures.reset(key)  # like failed_logins, the count restarts after a lock
            raise account_locked()
        raise invalid_credentials()

    if user.status == "locked":
        if user.locked_until is None or user.locked_until > now:
            # Same Argon2 cost as every other answer, so timing does not tell accounts apart.
            await security.verify_password_async(None, password)
            raise account_locked()
        user.status, user.locked_until, user.failed_logins = "active", None, 0
        audit(db, "auth.unlocked", "user", user.id, ip=ip, after={"reason": "lock_expired"})

    if not await security.verify_password_async(user.password_hash, password):
        locked = await _count_failure(db, user, ip, cfg, now, "password")
        await db.commit()
        raise account_locked() if locked else invalid_credentials()

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
    forgive(rate_ticket)  # only failures count toward the failure limits
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
    rate_ticket = check_password_change_rate(principal.user.id)
    cfg = await auth_settings(db)
    user = await db.scalar(select(User).where(User.id == principal.user.id).with_for_update())
    if user is None:
        raise unauthenticated()
    if await security.verify_password_async(user.password_hash, current):
        forgive(rate_ticket)  # only a wrong current password counts toward the failure limit
    else:
        # A wrong current password counts toward the lockout like a failed login, so a stolen
        # session cannot be used to guess it (M1 re-review).
        await _count_failure(db, user, ip, cfg, _now(), "password_change")
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
    ip: str | None = None,
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
    audit(db, "user.create", "user", user.id, actor=actor, ip=ip,
          after={"display_name": display_name, "roles": sorted(set(roles))})  # fmt: skip
    return user


# --- Administration of users and roles (#32) -------------------------------------------

USER_MANAGER = "users.manage"
# Never granted through a group: who administers users and roles stays per user (CP-27).
GROUP_FORBIDDEN = frozenset({USER_MANAGER, "roles.manage"})


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


# Any value works as long as no other code takes the same transaction-level advisory lock.
ADMIN_CHANGE_LOCK = 0x7277_0001


async def _serialise_admin_changes(db: AsyncSession) -> None:
    """Run user and role changes one at a time, so the last-manager guard cannot be raced
    (review finding 9). Released at commit or rollback."""
    await db.execute(select(func.pg_advisory_xact_lock(ADMIN_CHANGE_LOCK)))


async def _perms_of_roles(db: AsyncSession, role_keys: list[str]) -> set[str]:
    rows = await db.scalars(
        select(RolePermission.permission_key)
        .join(Role, Role.id == RolePermission.role_id)
        .where(Role.key.in_(role_keys))
    )
    return set(rows.all())


def _require_held(actor: Principal, perms: set[str], what: str) -> None:
    """An administrator can only hand out, or act on holders of, permissions they hold
    themselves (review finding 2)."""
    missing = sorted(perms - actor.permissions)
    if missing:
        raise ProblemError(
            403, "forbidden",
            f"You cannot {what} permissions you do not hold: {', '.join(missing)}.",
        )  # fmt: skip


async def admin_create_user(
    db: AsyncSession, email: str, display_name: str, roles: list[str], actor: Principal,
    ip: str | None,
) -> UserWithPasswordOut:  # fmt: skip
    _require_held(actor, await _perms_of_roles(db, roles), "grant")
    temporary = security.new_temporary_password()
    try:
        user = await create_user(db, email, display_name, temporary, roles,
                                 must_change_password=True, actor=actor.user.id, ip=ip)  # fmt: skip
    except ValueError as exc:
        if "exists" in str(exc):
            raise ProblemError(409, "conflict", "A user with this email exists.") from exc
        raise validation("roles", str(exc)) from exc
    await db.commit()
    out = user_out(user, sorted(set(roles)))
    return UserWithPasswordOut(**out.model_dump(exclude_unset=True), temporary_password=temporary)


async def revoke_sessions(db: AsyncSession, user_id: uuid.UUID | None = None,
                          operator: str = "operator") -> int:  # fmt: skip
    """Revoke every live session, or one user's (``regwatch-admin revoke-sessions``; M10.6): the
    incident runbook's sign-everyone-out, since rotating secrets signs no one out. Audited."""
    where: list[Any] = [UserSession.revoked_at.is_(None)]
    if user_id is not None:
        where.append(UserSession.user_id == user_id)
    done = await db.execute(update(UserSession).where(*where).values(revoked_at=_now())
                            .returning(UserSession.id))  # fmt: skip
    count = len(done.scalars().all())
    audit(db, "session.revoke_all", "user" if user_id else "session",
          str(user_id) if user_id else None,
          after={"sessions": count, "by": operator})  # fmt: skip
    await db.commit()
    return count


async def _revoke_all(db: AsyncSession, user_id: uuid.UUID) -> None:
    await db.execute(
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=_now())
    )


async def update_user(
    db: AsyncSession, user_id: uuid.UUID, changes: dict[str, Any], actor: Principal,
    ip: str | None,
) -> UserOut:  # fmt: skip
    await _serialise_admin_changes(db)
    user = await _user_or_404(db, user_id)
    _require_held(actor, set((await roles_and_permissions(db, user.id))[1]), "manage holders of")
    before_roles = (await _role_keys_by_user(db, [user.id]))[user.id]
    before = {"display_name": user.display_name, "status": user.status, "roles": before_roles}
    if "display_name" in changes:
        name = (changes["display_name"] or "").strip()
        if not name or len(name) > 120:
            raise validation("display_name", "Give a display name of 1 to 120 characters.")
        user.display_name = name
    if "status" in changes:
        status = str(changes["status"])
        if user_id == actor.user.id and status != "active":
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
        _require_held(actor, await _perms_of_roles(db, wanted), "grant")
        await db.execute(delete(UserRole).where(UserRole.user_id == user.id))
        db.add_all(UserRole(user_id=user.id, role_id=ids[k]) for k in wanted)
    user.updated_at = _now()
    await _ensure_a_manager_remains(db)
    after_roles = (await _role_keys_by_user(db, [user.id]))[user.id]
    after = {"display_name": user.display_name, "status": user.status, "roles": after_roles}
    if after != before:
        audit(db, "user.update", "user", user.id, actor=actor.user.id, ip=ip,
              before=before, after=after)  # fmt: skip
    await db.commit()
    return user_out(user, after_roles)


async def reset_password(
    db: AsyncSession, user_id: uuid.UUID, actor: Principal, ip: str | None
) -> str:
    user = await _user_or_404(db, user_id)
    _require_held(actor, set((await roles_and_permissions(db, user.id))[1]), "manage holders of")
    temporary = security.new_temporary_password()
    user.password_hash = await security.hash_password_async(temporary)
    user.must_change_password = True
    user.failed_logins, user.locked_until = 0, None
    if user.status == "locked":
        user.status = "active"
    user.updated_at = _now()
    await _revoke_all(db, user.id)
    audit(db, "user.reset_password", "user", user.id, actor=actor.user.id, ip=ip)
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
    actor: Principal, ip: str | None,
) -> RoleOut:  # fmt: skip
    if not key:
        raise validation("key", "A role key is required.")
    if not label or not label.strip():
        raise validation("label", "A label is required.")
    if await db.scalar(select(Role.id).where(Role.key == key)) is not None:
        raise validation("key", "A role with this key exists.")
    perms = await _check_permissions(db, permissions or [])
    _require_held(actor, set(perms), "grant")
    role = Role(key=key, label=label.strip()[:120], system=False)
    db.add(role)
    await db.flush()
    db.add_all(RolePermission(role_id=role.id, permission_key=p) for p in perms)
    audit(db, "role.create", "role", role.id, actor=actor.user.id, ip=ip,
          after={"key": key, "label": role.label, "permissions": perms})  # fmt: skip
    await db.commit()
    return role_out(role, perms)


async def _role_or_404(db: AsyncSession, role_id: uuid.UUID) -> Role:
    role = await db.get(Role, role_id)
    if role is None:
        raise ProblemError(404, "not-found", "No such role.")
    return role


async def update_role(
    db: AsyncSession, role_id: uuid.UUID, changes: dict[str, Any], actor: Principal,
    ip: str | None,
) -> RoleOut:  # fmt: skip
    await _serialise_admin_changes(db)
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
        # Adding or removing a permission both need it held (re-review N2).
        _require_held(actor, set(perms) ^ set(perms_before), "change")
        if role.key == "admin" and role.system and perms != perms_before:
            raise validation("permissions", "The admin role always holds every permission.")
        if set(perms) & GROUP_FORBIDDEN and await db.scalar(
            select(GroupRole.group_id).where(GroupRole.role_id == role.id).limit(1)
        ):
            raise validation("permissions", "A role that groups hold cannot include "
                             f"{' or '.join(sorted(GROUP_FORBIDDEN))} (CP-27).")  # fmt: skip
        await db.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
        db.add_all(RolePermission(role_id=role.id, permission_key=p) for p in perms)
    role.updated_at = _now()
    await _ensure_a_manager_remains(db)
    after = {"key": role.key, "label": role.label, "permissions": perms}
    if after != before:
        audit(db, "role.update", "role", role.id, actor=actor.user.id, ip=ip,
              before=before, after=after)  # fmt: skip
    await db.commit()
    return role_out(role, perms)


async def delete_role(
    db: AsyncSession, role_id: uuid.UUID, actor: Principal, ip: str | None
) -> None:
    await _serialise_admin_changes(db)  # a group cannot take the role while it goes (review)
    role = await _role_or_404(db, role_id)
    if role.system:
        raise ProblemError(409, "conflict", "System roles cannot be deleted.")
    _require_held(actor, set((await _perms_by_role(db)).get(role.id, [])), "delete roles with")
    holders = await db.scalar(select(func.count()).select_from(UserRole)
                              .where(UserRole.role_id == role.id))  # fmt: skip
    if holders:
        raise ProblemError(409, "conflict", f"The role is assigned to {holders} user(s).")
    groups = await db.scalar(select(func.count()).select_from(GroupRole)
                             .where(GroupRole.role_id == role.id))  # fmt: skip
    if groups:
        raise ProblemError(409, "conflict", f"The role is held by {groups} group(s).")
    perms = (await _perms_by_role(db)).get(role.id, [])
    audit(db, "role.delete", "role", role.id, actor=actor.user.id, ip=ip,
          before={"key": role.key, "label": role.label, "permissions": perms})  # fmt: skip
    await db.delete(role)
    await db.commit()


async def list_permissions(db: AsyncSession) -> list[PermissionOut]:
    rows = await db.scalars(select(Permission).order_by(Permission.key))
    return [PermissionOut(key=p.key, description=p.description, module=p.module)
            for p in rows.all()]  # fmt: skip


# --- Preferences (M9) ---------------------------------------------------------------------

LOCALES = frozenset({"en"})  # UI strings shipped (M9 Q1: English; other locales are backlog E10)


def stored_preferences(raw: dict[str, Any] | None) -> Preferences:
    """The stored preferences, field by field: a value a later schema no longer accepts is
    dropped (back to its default), so it can never lock the user out (M9 review, info 1)."""
    kept: dict[str, Any] = {}
    for key, value in (raw or {}).items():
        if key not in Preferences.model_fields:
            continue
        try:
            Preferences.model_validate({key: value})
        except ValueError:
            continue
        kept[key] = value
    return Preferences.model_validate(kept)


@cache
def _timezones() -> frozenset[str]:
    from zoneinfo import available_timezones

    return frozenset(available_timezones())


def preferences_of(user: User, cfg: dict[str, int]) -> Preferences:
    """The stored preferences over the defaults, with the idle timeout actually in force."""
    stored = stored_preferences(user.preferences)
    # Every field set explicitly, so the answer carries the defaults too (unset fields are
    # left out of responses).
    fields = {name: getattr(stored, name) for name in Preferences.model_fields
              if name not in ("session_idle_timeout_minutes", "interests")}  # fmt: skip
    return Preferences(**fields, session_idle_timeout_minutes=_idle_minutes(user, cfg),
                       interests=stored.interests or Interests())  # fmt: skip


async def get_preferences(db: AsyncSession, principal: Principal) -> Preferences:
    prefs = preferences_of(principal.user, await auth_settings(db))
    return await _current(db, prefs)


async def _current(db: AsyncSession, prefs: Preferences) -> Preferences:
    """Interests that still exist: a facet, term or jurisdiction removed or deactivated since
    they were saved is dropped, so default filters never fail (M11.1 review)."""
    if prefs.interests is None:
        return prefs
    return prefs.model_copy(update={"interests": await live_interests(db, prefs.interests)})


async def live_interests(db: AsyncSession, interests: Interests,
                         offered: InterestOptions | None = None) -> Interests:  # fmt: skip
    """``interests`` without what has been removed or deactivated since it was saved."""
    offered = offered or await interest_options(db)
    codes = {j.code for j in offered.jurisdictions}
    regions_ = {r.key for r in offered.regions}
    facets = {f.key: {t.key for t in f.terms} for f in offered.facets}
    return Interests(
        jurisdictions=[c for c in interests.jurisdictions if c in codes],
        regions=[r for r in interests.regions if r in regions_],
        terms={f: kept for f, keys in interests.terms.items() if f in facets
               if (kept := [k for k in keys if k in facets[f]])},
    )  # fmt: skip


async def update_preferences(db: AsyncSession, principal: Principal,
                             body: Preferences) -> Preferences:  # fmt: skip
    """Merge the fields given into ``user.preferences`` (M9 acceptance 1: they follow the user
    to every device). Checked: the time zone is an IANA name, the locale is one the UI ships,
    the landing view is one the user can see, the idle timeout is within the admin's ceiling."""
    from regwatch.search.models import SavedView

    changes = body.model_dump(mode="json", exclude_unset=True)
    cfg = await auth_settings(db)
    errors: list[ProblemFieldError] = []
    if "timezone" in changes and changes["timezone"] not in _timezones():
        errors.append(
            ProblemFieldError(field="timezone", message="an IANA time zone, such as Europe/Berlin")
        )
    if "locale" in changes and changes["locale"] not in LOCALES:
        errors.append(
            ProblemFieldError(field="locale", message="one of: " + ", ".join(sorted(LOCALES)))
        )
    ceiling = cfg["sessions.idle_timeout_max_minutes"]
    minutes = changes.get("session_idle_timeout_minutes")
    if isinstance(minutes, int) and minutes > ceiling:
        limit = f"at most {ceiling} minutes (sessions.idle_timeout_max_minutes)"
        errors.append(ProblemFieldError(field="session_idle_timeout_minutes", message=limit))
    view = changes.get("landing_view_id")
    if view is not None:
        visible = await db.scalar(select(SavedView.id).where(
            SavedView.id == uuid.UUID(view),
            or_(SavedView.user_id == principal.user.id, SavedView.shared.is_(True))))  # fmt: skip
        if visible is None:
            errors.append(ProblemFieldError(field="landing_view_id", message="a view you can see"))
    if "interests" in changes:
        errors += await _interest_errors(db, body.interests)
        changes["interests"] = _normalised(body.interests)
    if errors:
        raise ProblemError(400, "validation", "Some preferences are not valid.", errors=errors)
    user = await db.get(User, principal.user.id, with_for_update=True)
    if user is None:  # deleted meanwhile; the session gate answers 401 next time
        raise ProblemError(401, "unauthenticated", "Sign in again.")
    user.preferences = {**(user.preferences or {}), **changes}
    await db.commit()
    return await _current(db, preferences_of(user, cfg))


# --- Interests (M11.1, ADR-0012) -----------------------------------------------------------


def _normalised(interests: Interests) -> dict[str, Any]:
    """Codes upper-cased, duplicates and empty term lists dropped, in a stable order."""
    return {
        "jurisdictions": sorted({c.upper() for c in interests.jurisdictions}),
        "regions": sorted(set(interests.regions)),
        "terms": {f: sorted(set(keys)) for f, keys in sorted(interests.terms.items()) if keys},
    }


async def interest_options(db: AsyncSession) -> InterestOptions:
    """Facets shown in filters with their active terms, active jurisdictions, and regions."""
    from regwatch.search.query import CONTINENTS
    from regwatch.taxonomy.models import Facet, Jurisdiction, Term
    from regwatch.taxonomy.services import M49_CONTINENTS, M49_REGIONS

    labels = {**M49_REGIONS, **M49_CONTINENTS}

    facets = (await db.scalars(select(Facet).where(Facet.show_in_filters)
                               .order_by(Facet.label))).all()  # fmt: skip
    terms = (await db.execute(
        select(Term.facet_id, Term.key, Term.label).where(
            Term.active.is_(True), Term.facet_id.in_([f.id for f in facets]))
        .order_by(Term.label))).tuples().all()  # fmt: skip
    by_facet: dict[uuid.UUID, list[InterestOption]] = {}
    for facet_id, key, label in terms:
        by_facet.setdefault(facet_id, []).append(InterestOption(key=key, label=label))
    places = (await db.execute(
        select(Jurisdiction.code, Jurisdiction.name, Jurisdiction.region_code)
        .where(Jurisdiction.active.is_(True))
        .order_by(Jurisdiction.name))).tuples().all()  # fmt: skip
    from regwatch.search.query import SUPRANATIONAL
    from regwatch.search.query import regions as covered

    used = {r for _, _, r in places if r} | set(CONTINENTS)
    regions = [
        InterestRegion(key=code, label=labels.get(code, code), members=sorted(
            {c for c, _, r in places if r in covered([code])} | SUPRANATIONAL.get(code, set())))
        # Continents first, then sub-regions, each by name.
        for code in sorted(used, key=lambda c: (c not in M49_CONTINENTS, labels.get(c, c)))
    ]  # fmt: skip
    return InterestOptions(
        facets=[InterestFacet(key=f.key, label=f.label, terms=by_facet.get(f.id, []))
                for f in facets],
        jurisdictions=[InterestJurisdiction(code=c, name=n, region_code=r) for c, n, r in places],
        regions=regions,
    )  # fmt: skip


async def _interest_errors(db: AsyncSession, interests: Interests) -> list[ProblemFieldError]:
    """Every code and key must be one the options offer (an unknown one is refused, so a stale
    or hostile value never becomes a filter)."""
    offered = await interest_options(db)
    errors: list[ProblemFieldError] = []
    codes = {j.code for j in offered.jurisdictions}
    if bad := [c for c in interests.jurisdictions if c.upper() not in codes]:
        unknown = f"unknown jurisdiction {bad[0][:16]!r}"
        errors.append(ProblemFieldError(field="interests.jurisdictions", message=unknown))
    region_keys = {r.key for r in offered.regions}
    if bad := [r for r in interests.regions if r not in region_keys]:
        errors.append(ProblemFieldError(field="interests.regions",
                                        message=f"unknown region {bad[0][:16]!r}"))  # fmt: skip
    facets = {f.key: {t.key for t in f.terms} for f in offered.facets}
    for facet, keys in interests.terms.items():
        if facet not in facets:
            errors.append(ProblemFieldError(field="interests.terms",
                                            message=f"unknown facet {facet[:64]!r}"))  # fmt: skip
        elif bad := [k for k in keys if k not in facets[facet]]:
            errors.append(ProblemFieldError(field="interests.terms",
                                            message=f"unknown term {bad[0][:64]!r}"))  # fmt: skip
    return errors
