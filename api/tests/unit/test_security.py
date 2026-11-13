"""Password hashing, session tokens and the origin check (#31, REQ-14, REQ-16)."""

from __future__ import annotations

import pytest

from regwatch.core import security


def test_argon2id_round_trip() -> None:
    hashed = security.hash_password("correct horse battery")
    assert hashed.startswith("$argon2id$")
    assert security.verify_password(hashed, "correct horse battery")
    assert not security.verify_password(hashed, "correct horse batterY")
    assert not security.needs_rehash(hashed)


def test_verify_without_hash_or_with_junk_is_false() -> None:
    assert not security.verify_password(None, "anything at all")
    assert not security.verify_password("not-a-hash", "anything at all")


def test_overlong_password_is_refused_before_hashing() -> None:
    hashed = security.hash_password("x" * 20)
    assert not security.verify_password(hashed, "x" * (security.MAX_PASSWORD_LENGTH + 1))


async def test_async_variants() -> None:
    hashed = await security.hash_password_async("a long enough secret")
    assert await security.verify_password_async(hashed, "a long enough secret")


def test_tokens_are_random_and_stored_hashed() -> None:
    a, b = security.new_session_token(), security.new_session_token()
    assert a != b and len(a) >= 43
    assert security.token_hash(a) != a and len(security.token_hash(a)) == 64
    assert len(security.new_temporary_password()) >= 20


@pytest.mark.parametrize(
    ("url", "origin"),
    [
        ("https://Example.org/path?q", "https://example.org"),
        ("https://example.org:443", "https://example.org"),
        ("http://localhost:80/", "http://localhost"),
        ("http://localhost:8080", "http://localhost:8080"),
        ("http://[::1]:5173", "http://[::1]:5173"),
        ("example.org", ""),
        ("http://host:99999", ""),
        ("null", ""),
    ],
)
def test_origin_of(url: str, origin: str) -> None:
    assert security.origin_of(url) == origin


@pytest.mark.parametrize(
    ("method", "origin", "allowed"),
    [
        ("GET", None, True),
        ("HEAD", "https://evil.example", True),
        ("POST", None, False),
        ("POST", "null", False),
        ("POST", "https://evil.example", False),
        ("PATCH", "http://localhost.evil.example", False),
        ("DELETE", "https://localhost", False),  # scheme differs
        ("PUT", "http://localhost", True),
        ("post", "http://LOCALHOST:80", True),
    ],
)
def test_origin_allowed(method: str, origin: str | None, allowed: bool) -> None:
    assert security.origin_allowed(method, origin, "http://localhost/") is allowed
