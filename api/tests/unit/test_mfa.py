"""TOTP helpers without a database (BL-148; CP-38): codes, replay, recovery codes, the secret at
rest and the pending sign-in cookie."""

from __future__ import annotations

import json
import time
import uuid

import pyotp
import pytest

from regwatch.core.errors import ProblemError
from regwatch.core.settings import Settings
from regwatch.identity import mfa
from regwatch.identity.models import User

SECRET = pyotp.random_base32(32)
NOW = 1_800_000_000.0


def _code(step: int) -> str:
    return pyotp.TOTP(SECRET).generate_otp(step)


def test_a_code_from_this_step_or_either_side_is_accepted() -> None:
    step = int(NOW // 30)
    for offset in (-1, 0, 1):
        assert mfa.check_code(SECRET, _code(step + offset), 0, NOW) == step + offset
    assert mfa.check_code(SECRET, _code(step + 2), 0, NOW) is None
    assert mfa.check_code(SECRET, _code(step - 2), 0, NOW) is None


def test_a_code_is_never_accepted_twice() -> None:
    step = int(NOW // 30)
    assert mfa.check_code(SECRET, _code(step), step, NOW) is None
    assert mfa.check_code(SECRET, _code(step - 1), step, NOW) is None  # nor an older one
    assert mfa.check_code(SECRET, _code(step + 1), step, NOW) == step + 1


@pytest.mark.parametrize("given", ["", "12345", "1234567", "abcdef", "١٢٣٤٥٦", "12 34 5"])
def test_malformed_codes_are_refused(given: str) -> None:
    assert mfa.check_code(SECRET, given, 0, NOW) is None


def test_spaces_inside_a_code_are_ignored() -> None:
    code = _code(int(NOW // 30))
    assert mfa.check_code(SECRET, code[:3] + " " + code[3:], 0, NOW) is not None


def test_recovery_codes_are_random_keyed_and_match_however_typed(
    valid_env: dict[str, str],
) -> None:
    settings = Settings()
    codes = mfa.new_recovery_codes()
    assert len(codes) == 10 and len(set(codes)) == 10
    assert all(len(c) == 11 and c[5] == "-" for c in codes)
    first = codes[0]
    digest = mfa.recovery_digest(settings, first)
    assert digest == mfa.recovery_digest(settings, " " + first.upper().replace("-", ""))
    assert digest != mfa.recovery_digest(settings, codes[1])
    assert digest != mfa.recovery_digest(Settings(secret_key="b" * 64), first)  # keyed
    rotated = Settings(secret_key="b" * 64, secret_key_previous=settings.secret_key)
    assert digest in mfa.recovery_digests(rotated, first)


def test_the_secret_is_encrypted_and_survives_a_key_rotation(valid_env: dict[str, str]) -> None:
    old = Settings(secret_key="b" * 64)
    token = mfa.encrypt(old, SECRET)
    assert SECRET not in token
    assert mfa.decrypt(old, token) == SECRET
    rotated = Settings(secret_key="c" * 64, secret_key_previous="b" * 64)
    assert mfa.decrypt(rotated, token) == SECRET
    with pytest.raises(ProblemError) as caught:
        mfa.decrypt(Settings(secret_key="c" * 64), token)
    assert caught.value.slug == "mfa-unreadable"


def test_provisioning_gives_an_otpauth_uri_and_a_square_qr(valid_env: dict[str, str]) -> None:
    uri, qr = mfa.provisioning(SECRET, "ana@example.org", mfa.site_name(Settings()))
    assert uri.startswith("otpauth://totp/") and f"secret={SECRET}" in uri
    assert "issuer=regwatch%20%28localhost%29" in uri
    assert len(qr) == len(qr[0]) and set("".join(qr)) == {"0", "1"}


def _user(password_hash: str = "$argon2id$x") -> User:  # noqa: S107 - not a password
    return User(id=uuid.uuid4(), email="ana@example.org", display_name="Ana",
                password_hash=password_hash)  # fmt: skip


def test_the_pending_cookie_is_signed_short_lived_and_tied_to_the_password(
    valid_env: dict[str, str],
) -> None:
    settings = Settings()
    user = _user()
    value = mfa.pending_cookie(settings, user, True)
    held = mfa.read_pending(settings, value)
    assert held is not None and held["remember"] is True and mfa.pending_matches(held, user)
    assert not mfa.pending_matches(held, _user("$argon2id$changed"))  # the password changed
    assert mfa.read_pending(Settings(secret_key="d" * 64), value) is None
    assert mfa.read_pending(settings, value[:-3] + "AAA") is None
    assert mfa.read_pending(settings, None) is None
    assert mfa.read_pending(settings, "a.b.c") is None
    body = json.dumps({"uid": str(user.id), "pw": "x", "remember": False,
                       "at": time.time() - 301}).encode()  # fmt: skip
    import base64

    stale = (base64.urlsafe_b64encode(body).decode().rstrip("=") + "."
             + base64.urlsafe_b64encode(mfa._mac(settings, settings.secret_key, body))
             .decode().rstrip("="))  # fmt: skip
    assert mfa.read_pending(settings, stale) is None


def test_the_pending_cookie_is_strict_and_scoped(valid_env: dict[str, str]) -> None:
    header = mfa.pending_header("v")
    assert "Path=/api/v1/auth/mfa" in header and "HttpOnly" in header
    assert "SameSite=strict" in header and "Secure" in header and "Max-Age=300" in header
