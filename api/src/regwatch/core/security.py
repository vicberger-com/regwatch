"""Password hashing, session tokens and the CSRF origin check (#31, ADR-0007).

Passwords use Argon2id through argon2-cffi with its RFC 9106 defaults. Session cookies carry
a 256-bit random token; only its sha256 is stored (``session.token_hash``), so a database
read does not yield usable cookies. Hashing is CPU-bound: async callers use the ``*_async``
variants, which run in a worker thread.
"""

from __future__ import annotations

import hashlib
import secrets
from functools import lru_cache
from urllib.parse import urlsplit

from anyio import to_thread
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# Longer input is refused before hashing, so a huge password cannot tie up a worker thread.
MAX_PASSWORD_LENGTH = 1024

_hasher = PasswordHasher()


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    """A hash to verify against when there is no account, so timing does not reveal it."""
    return _hasher.hash(secrets.token_hex(16))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str | None, password: str) -> bool:
    """True when ``password`` matches; with no hash, burn the same time and return False."""
    if len(password) > MAX_PASSWORD_LENGTH:
        return False
    try:
        return _hasher.verify(stored_hash or _dummy_hash(), password) and stored_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    return _hasher.check_needs_rehash(stored_hash)


async def hash_password_async(password: str) -> str:
    return await to_thread.run_sync(hash_password, password)


async def verify_password_async(stored_hash: str | None, password: str) -> bool:
    return await to_thread.run_sync(verify_password, stored_hash, password)


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_temporary_password() -> str:
    """A random password for admin-created accounts and resets (about 120 bits)."""
    return secrets.token_urlsafe(15)


def origin_of(url: str) -> str:
    """``scheme://host[:port]`` in lower case, with the scheme's default port dropped."""
    parts = urlsplit(url.strip())
    scheme, host = parts.scheme.lower(), (parts.hostname or "").lower()
    if not scheme or not host:
        return ""
    if ":" in host:
        host = f"[{host}]"
    try:
        port = parts.port
    except ValueError:
        return ""
    default = {"http": 80, "https": 443}.get(scheme)
    return f"{scheme}://{host}" + (f":{port}" if port and port != default else "")


def origin_allowed(method: str, origin: str | None, site_url: str) -> bool:
    """CSRF check: a mutating request must carry an ``Origin`` equal to the site's origin."""
    if method.upper() not in UNSAFE_METHODS:
        return True
    expected = origin_of(site_url)
    return bool(origin) and bool(expected) and origin_of(origin or "") == expected
