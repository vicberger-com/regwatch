"""Two-factor sign-in with TOTP for local accounts (BL-148; ADR-0007 G0 Q4; CP-38).

- **Enrolment** (``/me/mfa``): the user confirms their password and gets a new secret, as a QR
  code and as text. The authenticator is on once a first code from it is entered, which also
  gives 10 one-time recovery codes. Turning it off needs the password and a code.
- **Sign-in**: after a correct password, an account with an authenticator gets
  ``401 mfa-required`` and a signed, 5-minute ``rw_mfa`` cookie instead of a session.
  ``POST /auth/mfa`` with a code from the app, or a recovery code, then starts the session.
  Wrong codes count toward the account lockout like wrong passwords, and a code is never
  accepted twice (``last_step``).
- **Storage**: the secret is encrypted with a key derived from the secret key (Fernet), and
  the previous secret key still decrypts during a rotation. Recovery codes are kept as SHA-256
  digests keyed with the secret key: they are random, 50 bits each, and single-use.
- An administrator with ``users.manage`` resets a user's authenticator when a phone is lost,
  audited, and the user's sessions end.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import pyotp
import segno
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from fastapi import Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.core import security
from regwatch.core.errors import ProblemError
from regwatch.core.settings import Settings
from regwatch.identity.models import User, UserMfa

STEP_S = 30
DIGITS = 6
PENDING_COOKIE = "rw_mfa"
PENDING_PATH = "/api/v1/auth/mfa"
PENDING_MAX_AGE_S = 300
RECOVERY_COUNT = 10
_RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no 0/o, 1/l/i
_clock = time.time  # the TOTP clock; tests move it forward


# --- the secret at rest ----------------------------------------------------------------


def _fernet(settings: Settings) -> MultiFernet:
    keys = [k for k in (settings.secret_key, settings.secret_key_previous) if k is not None]
    return MultiFernet([
        Fernet(base64.urlsafe_b64encode(
            hmac.new(k.get_secret_value().encode(), b"regwatch-mfa-v1", hashlib.sha256).digest()))
        for k in keys
    ])  # fmt: skip


def encrypt(settings: Settings, secret: str) -> str:
    return _fernet(settings).encrypt(secret.encode()).decode()


def decrypt(settings: Settings, token: str) -> str:
    try:
        return _fernet(settings).decrypt(token.encode()).decode()
    except InvalidToken:
        # Neither the current nor the previous secret key: the authenticator must be reset.
        raise ProblemError(409, "mfa-unreadable", "The authenticator cannot be read after a key "
                           "change; ask an administrator to reset it.") from None  # fmt: skip


async def rotate_all(db: AsyncSession, settings: Settings) -> tuple[int, int]:
    """Re-encrypt every stored secret with the current secret key, during a key rotation before
    ``REGWATCH_SECRET_KEY_PREVIOUS`` is removed (``regwatch-admin rotate-mfa-secrets``).
    Returns how many were re-encrypted, and how many neither key opens (to reset)."""
    fernet = _fernet(settings)
    done = unreadable = 0
    for row in (await db.scalars(select(UserMfa).with_for_update())).all():
        try:
            row.secret_enc = fernet.rotate(row.secret_enc.encode()).decode()
            done += 1
        except InvalidToken:
            unreadable += 1
        # Recovery codes cannot be re-keyed (only their digests are kept): those made under the
        # previous key keep working while it is set, so the users get new ones meanwhile.
    await db.commit()
    return done, unreadable


# --- codes -------------------------------------------------------------------------------


def _digits(code: str) -> str | None:
    clean = code.replace(" ", "")
    return clean if len(clean) == DIGITS and clean.isascii() and clean.isdigit() else None


def check_code(secret: str, code: str, last_step: int, now: float | None = None) -> int | None:
    """The time step of a valid code from the authenticator, one step either side, never one
    at or before ``last_step``; None otherwise."""
    given = _digits(code)
    if given is None:
        return None
    totp = pyotp.TOTP(secret, digits=DIGITS, interval=STEP_S)
    step = int((_clock() if now is None else now) // STEP_S)
    for candidate in (step - 1, step, step + 1):
        if candidate > last_step and hmac.compare_digest(totp.generate_otp(candidate), given):
            return candidate
    return None


def new_recovery_codes() -> list[str]:
    def one() -> str:
        raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(10))
        return raw[:5] + "-" + raw[5:]

    return [one() for _ in range(RECOVERY_COUNT)]


def recovery_digests(settings: Settings, code: str) -> list[str]:
    """The keyed digests of a recovery code, under the current key and the previous one: a
    database dump alone cannot be searched for codes (review Low 1). The first is the one
    to store."""
    clean = code.strip().lower().replace("-", "").replace(" ", "").encode()
    keys = [k for k in (settings.secret_key, settings.secret_key_previous) if k is not None]
    return [hmac.new(hmac.new(k.get_secret_value().encode(), b"regwatch-recovery-v1",
                              hashlib.sha256).digest(), clean, hashlib.sha256).hexdigest()
            for k in keys]  # fmt: skip


def recovery_digest(settings: Settings, code: str) -> str:
    return recovery_digests(settings, code)[0]


def provisioning(secret: str, email: str, site: str) -> tuple[str, list[str]]:
    """The ``otpauth://`` URI, and its QR code as rows of 0 and 1 (drawn by the web app, so no
    image or inline style is needed)."""
    uri = pyotp.TOTP(secret, digits=DIGITS, interval=STEP_S).provisioning_uri(
        name=email, issuer_name=site)  # fmt: skip
    matrix = segno.make(uri, error="m").matrix
    return uri, ["".join("1" if cell else "0" for cell in row) for row in matrix]


# --- the pending sign-in -----------------------------------------------------------------


def _mac(settings: Settings, key: Any, payload: bytes) -> bytes:  # noqa: ANN401 - SecretStr
    return hmac.new(key.get_secret_value().encode(), b"mfa-pending:" + payload,
                    hashlib.sha256).digest()  # fmt: skip


def _password_tag(user: User) -> str:
    """Ties a pending sign-in to the password it was started with."""
    return hashlib.sha256((user.password_hash or "").encode()).hexdigest()[:16]


def pending_cookie(settings: Settings, user: User, remember_me: bool) -> str:
    payload = json.dumps({"uid": str(user.id), "pw": _password_tag(user), "remember": remember_me,
                          "at": time.time()}).encode()  # fmt: skip
    b64 = base64.urlsafe_b64encode
    return (b64(payload).decode().rstrip("=") + "."
            + b64(_mac(settings, settings.secret_key, payload)).decode().rstrip("="))  # fmt: skip


def read_pending(settings: Settings, value: str | None) -> dict[str, Any] | None:
    try:
        body, mac = (value or "").split(".", 1)
        payload = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
        given = base64.urlsafe_b64decode(mac + "=" * (-len(mac) % 4))
        data = json.loads(payload)
    except ValueError:
        return None
    keys = [k for k in (settings.secret_key, settings.secret_key_previous) if k is not None]
    if not any(hmac.compare_digest(given, _mac(settings, k, payload)) for k in keys):
        return None
    if not isinstance(data, dict) or time.time() - float(data.get("at", 0)) > PENDING_MAX_AGE_S:
        return None
    return data


def pending_matches(data: dict[str, Any], user: User) -> bool:
    return str(user.id) == data.get("uid") and hmac.compare_digest(
        _password_tag(user), str(data.get("pw", "")))  # fmt: skip


def set_pending(response: Response, value: str) -> None:
    response.set_cookie(PENDING_COOKIE, value, max_age=PENDING_MAX_AGE_S, path=PENDING_PATH,
                        secure=True, httponly=True, samesite="strict")  # fmt: skip


def clear_pending(response: Response) -> None:
    response.delete_cookie(PENDING_COOKIE, path=PENDING_PATH, secure=True, httponly=True,
                           samesite="strict")  # fmt: skip


def pending_header(value: str) -> str:
    """The ``Set-Cookie`` value for a problem answer, which has no response object."""
    probe = Response()
    set_pending(probe, value)
    return probe.headers["set-cookie"]


# --- the stored authenticator ------------------------------------------------------------


@dataclass(frozen=True)
class Status:
    enabled: bool
    confirmed_at: datetime | None
    recovery_codes_left: int


async def confirmed(db: AsyncSession, user_id: uuid.UUID, lock: bool = False) -> UserMfa | None:
    stmt = select(UserMfa).where(UserMfa.user_id == user_id, UserMfa.confirmed_at.is_not(None))
    found: UserMfa | None = await db.scalar(stmt.with_for_update() if lock else stmt)
    return found


async def status(db: AsyncSession, user_id: uuid.UUID) -> Status:
    row = await confirmed(db, user_id)
    return Status(row is not None, row.confirmed_at if row else None,
                  len(row.recovery_hashes) if row else 0)  # fmt: skip


async def verify(db: AsyncSession, settings: Settings, row: UserMfa, code: str) -> str | None:
    """``"totp"`` or ``"recovery"`` when ``code`` is accepted (and spent), None otherwise."""
    step = check_code(decrypt(settings, row.secret_enc), code, row.last_step)
    if step is not None:
        row.last_step = step
        return "totp"
    digests = recovery_digests(settings, code)
    for kept in row.recovery_hashes:
        if any(hmac.compare_digest(kept, d) for d in digests):
            row.recovery_hashes = [h for h in row.recovery_hashes if h != kept]
            return "recovery"
    return None


async def start_setup(db: AsyncSession, settings: Settings, user: User, site: str
                      ) -> tuple[str, str, list[str]]:  # fmt: skip
    """A new, unconfirmed secret; an earlier unconfirmed one is replaced."""
    if await confirmed(db, user.id) is not None:
        raise ProblemError(409, "mfa-enabled", "Two-factor sign-in is already on.")
    secret = pyotp.random_base32(32)
    await db.execute(delete(UserMfa).where(UserMfa.user_id == user.id))
    db.add(UserMfa(user_id=user.id, secret_enc=encrypt(settings, secret)))
    uri, qr = provisioning(secret, user.email, site)
    return secret, uri, qr


async def finish_setup(db: AsyncSession, settings: Settings, user: User, code: str
                       ) -> list[str] | None:  # fmt: skip
    """The recovery codes once ``code`` proves the authenticator works; None for a wrong code."""
    row = await db.scalar(select(UserMfa).where(UserMfa.user_id == user.id).with_for_update())
    if row is None or row.confirmed_at is not None:
        raise ProblemError(409, "mfa-not-started", "Start the set-up first.")
    step = check_code(decrypt(settings, row.secret_enc), code, row.last_step)
    if step is None:
        return None
    codes = new_recovery_codes()
    row.confirmed_at, row.last_step = datetime.now(UTC), step
    row.recovery_hashes = [recovery_digest(settings, c) for c in codes]
    return codes


async def check_password(user: User, password: str) -> bool:
    return await security.verify_password_async(user.password_hash, password)


def site_name(settings: Settings) -> str:
    """The name the authenticator app shows: regwatch and this installation's host."""
    return f"regwatch ({urlsplit(str(settings.base_url)).hostname or 'local'})"
