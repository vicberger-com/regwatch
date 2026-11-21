"""The TOTP flows (BL-148; CP-38): enrolment on the User tab, the second step of a password
sign-in, and an administrator's reset. See ``identity/mfa.py``."""

from __future__ import annotations

import uuid

from fastapi import Request, Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.core.errors import ProblemError
from regwatch.core.services import audit
from regwatch.core.settings import Settings
from regwatch.identity import mfa
from regwatch.identity.models import User, UserMfa
from regwatch.identity.schemas import Me
from regwatch.identity.services import (
    Principal,
    _count_failure,
    _now,
    _require_held,
    _revoke_all,
    _user_or_404,
    account_locked,
    auth_settings,
    check_login_rate,
    check_password_change_rate,
    client_ip,
    forgive,
    roles_and_permissions,  # fmt: skip
    start_session,
    unauthenticated,
)


def wrong_code() -> ProblemError:
    return ProblemError(401, "mfa-invalid", "The code is not valid. Enter a new one.")


async def _locked_user(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await db.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None:
        raise unauthenticated()
    return user


async def _password_or_fail(db: AsyncSession, user: User, password: str, ip: str | None) -> None:
    """The password again for a change to the authenticator; a wrong one counts toward the
    lockout, as for a password change."""
    ticket = check_password_change_rate(user.id)
    if await mfa.check_password(user, password):
        forgive(ticket)
        return
    await _count_failure(db, user, ip, await auth_settings(db), _now(), "mfa_change")
    await db.commit()
    raise ProblemError(400, "password-incorrect", "The password is incorrect.")


async def setup(db: AsyncSession, settings: Settings, principal: Principal, request: Request,
                password: str) -> tuple[str, str, list[str]]:  # fmt: skip
    user = await _locked_user(db, principal.user.id)
    await _password_or_fail(db, user, password, client_ip(request))
    found = await mfa.start_setup(db, settings, user, mfa.site_name(settings))
    await db.commit()
    return found


async def confirm(db: AsyncSession, settings: Settings, principal: Principal, request: Request,
                  code: str) -> list[str]:  # fmt: skip
    user = await _locked_user(db, principal.user.id)
    ticket = check_password_change_rate(user.id)
    codes = await mfa.finish_setup(db, settings, user, code)
    if codes is None:
        await db.rollback()
        raise wrong_code()
    forgive(ticket)
    # Other sessions end: whoever else held one must now pass the second step too.
    await _revoke_all(db, user.id, keep=principal.session_id)
    audit(db, "auth.mfa_enabled", "user", user.id, actor=user.id, ip=client_ip(request))
    await db.commit()
    return codes


async def _password_and_code(db: AsyncSession, settings: Settings, user: User, request: Request,
                             password: str, code: str) -> UserMfa:  # fmt: skip
    row = await mfa.confirmed(db, user.id, lock=True)
    if row is None:
        raise ProblemError(409, "mfa-off", "Two-factor sign-in is off.")
    await _password_or_fail(db, user, password, client_ip(request))
    ticket = check_password_change_rate(user.id)
    if await mfa.verify(db, settings, row, code) is None:
        await db.commit()
        raise wrong_code()
    forgive(ticket)
    return row


async def disable(db: AsyncSession, settings: Settings, principal: Principal, request: Request,
                  password: str, code: str) -> None:  # fmt: skip
    user = await _locked_user(db, principal.user.id)
    await _password_and_code(db, settings, user, request, password, code)
    await db.execute(delete(UserMfa).where(UserMfa.user_id == user.id))
    audit(db, "auth.mfa_disabled", "user", user.id, actor=user.id, ip=client_ip(request))
    await db.commit()


async def new_recovery_codes(db: AsyncSession, settings: Settings, principal: Principal,
                             request: Request, password: str, code: str) -> list[str]:  # fmt: skip
    user = await _locked_user(db, principal.user.id)
    row = await _password_and_code(db, settings, user, request, password, code)
    codes = mfa.new_recovery_codes()
    row.recovery_hashes = [mfa.recovery_digest(settings, c) for c in codes]
    audit(db, "auth.mfa_recovery_renewed", "user", user.id, actor=user.id, ip=client_ip(request))
    await db.commit()
    return codes


async def complete_sign_in(db: AsyncSession, request: Request, response: Response,
                           settings: Settings, code: str) -> Me:  # fmt: skip
    """The second step of a password sign-in (``POST /auth/mfa``)."""
    held = mfa.read_pending(settings, request.cookies.get(mfa.PENDING_COOKIE))
    if held is None:
        raise ProblemError(401, "mfa-expired", "The sign-in took too long. Start again.")
    try:
        user_id = uuid.UUID(str(held["uid"]))
    except ValueError:
        raise unauthenticated() from None
    user = await _locked_user(db, user_id)
    ip = client_ip(request)
    ticket = check_login_rate(ip, user.email)
    now = _now()
    if not mfa.pending_matches(held, user) or user.status == "disabled":
        raise ProblemError(401, "mfa-expired", "The sign-in took too long. Start again.")
    if user.status == "locked" and (user.locked_until is None or user.locked_until > now):
        raise account_locked()
    row = await mfa.confirmed(db, user.id, lock=True)
    if row is None:  # reset by an administrator meanwhile
        raise ProblemError(401, "mfa-expired", "The sign-in took too long. Start again.")
    used = await mfa.verify(db, settings, row, code)
    cfg = await auth_settings(db)
    if used is None:
        locked = await _count_failure(db, user, ip, cfg, now, "mfa")
        await db.commit()
        raise account_locked() if locked else wrong_code()
    if used == "recovery":
        audit(db, "auth.mfa_recovery_used", "user", user.id, actor=user.id, ip=ip,
              after={"left": len(row.recovery_hashes)})  # fmt: skip
    if user.status == "locked":
        user.status, user.locked_until = "active", None
    me = await start_session(db, request, response, settings, user, cfg, ip,
                             bool(held.get("remember")), "password+" + used)  # fmt: skip
    mfa.clear_pending(response)
    forgive(ticket)
    return me


async def operator_reset(db: AsyncSession, user_id: uuid.UUID, operator: str) -> bool:
    """``regwatch-admin reset-mfa``: the recovery path from a shell on the host, for an
    administrator with no other administrator, phone or recovery code. Audited by who ran it."""
    gone = await db.execute(delete(UserMfa).where(UserMfa.user_id == user_id))
    if not gone.rowcount:  # type: ignore[attr-defined]
        return False
    await _revoke_all(db, user_id)
    audit(db, "auth.mfa_reset", "user", user_id, after={"by": operator})
    await db.commit()
    return True


async def reset(db: AsyncSession, user_id: uuid.UUID, actor: Principal, ip: str | None) -> None:
    """An administrator removes a user's authenticator (a lost phone); their sessions end."""
    if user_id == actor.user.id:
        # A stolen session must not strip its own account's second factor (review Low 2): one's
        # own goes through /me/mfa/disable, with the password and a code.
        raise ProblemError(
            403, "forbidden", "Turn your own two-factor sign-in off on the User tab."
        )
    user = await _user_or_404(db, user_id)
    _require_held(actor, set((await roles_and_permissions(db, user.id))[1]), "manage holders of")
    gone = await db.execute(delete(UserMfa).where(UserMfa.user_id == user.id))
    if not gone.rowcount:  # type: ignore[attr-defined]
        raise ProblemError(404, "not-found", "This user has no authenticator.")
    await _revoke_all(db, user.id)
    audit(db, "auth.mfa_reset", "user", user.id, actor=actor.user.id, ip=ip)
    await db.commit()
