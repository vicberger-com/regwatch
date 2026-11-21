"""OpenID Connect sign-in (M1b; ADR-0007; CP-37), behind the ``auth.oidc`` flag.

The authorization-code flow with PKCE (S256), through Authlib (BSD-3) and joserfc (BSD-3):
- ``start``: the provider's discovery document gives its endpoints. A random ``state``, ``nonce``
  and PKCE verifier are kept in a short-lived cookie signed with the secret key, and the
  browser goes to the provider.
- ``finish``: the callback's ``state`` must match the cookie's. The code is exchanged with the
  verifier. The ID token must be signed by a key from the provider's JWKS (asymmetric
  algorithms only), issued by the configured issuer, for this client, unexpired, and carry the
  cookie's ``nonce``.
- Users are matched by ``external_subject``, a digest of the issuer and the subject. On a first
  sign-in, an existing account is linked only by an ``email_verified`` email from this provider,
  audited (G0 Q1), and never an administrator's: those an administrator links. There is no
  self-registration: an unknown person is refused. Roles stay in the application (Q3). The
  issuer must be single-tenant: anyone it vouches for with a verified email can be linked.
- With OIDC on, password sign-in stays for administrators only, as a recovery path (Q2).
Every call to the provider has a timeout, follows no redirect, reads at most ``MAX_ANSWER``, and
must be https (plain http only for the `oidc-test` provider, never in production).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx
import structlog
from authlib.integrations.httpx_client import AsyncOAuth2Client  # type: ignore[import-untyped]
from authlib.oauth2.rfc7636 import create_s256_code_challenge  # type: ignore[import-untyped]
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet

from regwatch.core.errors import ProblemError
from regwatch.core.settings import Settings

FLAG = "auth.oidc"
STATE_COOKIE = "rw_oidc"
STATE_MAX_AGE_S = 600
TIMEOUT_S = 10.0
MAX_ANSWER = 512 * 1024
ALGORITHMS = ["RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512"]
CACHE_S = 3600.0
_log = structlog.get_logger("regwatch.oidc")


class SsoError(Exception):
    """Why a sign-in through the provider did not complete; ``reason`` goes to the login page."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(detail or reason)
        self.reason = reason


@dataclass(frozen=True)
class Provider:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str


@dataclass(frozen=True)
class Identity:
    issuer: str
    subject: str
    email: str | None
    email_verified: bool
    name: str | None

    @property
    def key(self) -> str:
        """What ``external_subject`` holds: a subject is unique only within its issuer."""
        return hashlib.sha256(f"{self.issuer}\0{self.subject}".encode()).hexdigest()


def configured(settings: Settings) -> bool:
    return bool(settings.oidc_issuer and settings.oidc_client_id and settings.oidc_client_secret)


def redirect_uri(settings: Settings) -> str:
    return str(settings.base_url).rstrip("/") + "/api/v1/auth/oidc/callback"


def _check_url(url: str, settings: Settings) -> str:
    parts = urlsplit(url)
    plain_ok = settings.oidc_test_provider and settings.env != "production"
    if parts.scheme != "https" and not (plain_ok and parts.scheme == "http"):
        raise SsoError("provider", f"the provider's URL must be https: {url[:80]}")
    if not parts.hostname or parts.username or parts.password:
        raise SsoError("provider", "the provider's URL has no host, or holds credentials")
    return url


_cache: dict[str, tuple[float, Any]] = {}


async def _get_json(client: httpx.AsyncClient, url: str) -> Any:  # noqa: ANN401 - JSON
    async with client.stream("GET", url) as response:
        if response.status_code != 200:
            raise SsoError("provider", f"the provider answered {response.status_code}")
        body = b""
        async for chunk in response.aiter_bytes():
            body += chunk
            if len(body) > MAX_ANSWER:
                raise SsoError("provider", "the provider's answer is too large")
    return json.loads(body)


# Tests serve a mock provider through this transport; it stays ``None`` in the application.
transport: httpx.AsyncBaseTransport | None = None


class _Capped(httpx.AsyncBaseTransport):
    """Reads no more than ``MAX_ANSWER`` of any answer, the token endpoint's included, which
    Authlib reads whole (M1b review Low 2)."""

    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self.inner = inner

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self.inner.handle_async_request(request)
        body = bytearray()
        try:
            async for chunk in response.stream:  # type: ignore[union-attr]
                body += chunk
                if len(body) > MAX_ANSWER:
                    raise SsoError("provider", "the provider's answer is too large")
        finally:
            await response.aclose()
        return httpx.Response(response.status_code, headers=response.headers,
                              content=bytes(body), request=request)  # fmt: skip

    async def aclose(self) -> None:
        await self.inner.aclose()


def _transport() -> httpx.AsyncBaseTransport:
    return _Capped(transport or httpx.AsyncHTTPTransport(retries=0))


def http_client() -> httpx.AsyncClient:
    """The client for the provider's discovery and keys."""
    return httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=False, transport=_transport())


async def provider(settings: Settings) -> Provider:
    """The discovery document, kept for an hour; its issuer must be the configured one."""
    issuer = str(settings.oidc_issuer).rstrip("/")
    hit = _cache.get("provider:" + issuer)
    if hit and time.monotonic() - hit[0] < CACHE_S:
        return hit[1]  # type: ignore[no-any-return]
    url = _check_url(issuer + "/.well-known/openid-configuration", settings)
    async with http_client() as client:
        doc = await _get_json(client, url)
    if str(doc.get("issuer", "")).rstrip("/") != issuer:
        raise SsoError("provider", "the discovery document names another issuer")
    found = Provider(
        issuer=str(doc["issuer"]),
        authorization_endpoint=_check_url(str(doc["authorization_endpoint"]), settings),
        token_endpoint=_check_url(str(doc["token_endpoint"]), settings),
        jwks_uri=_check_url(str(doc["jwks_uri"]), settings),
    )
    _cache["provider:" + issuer] = (time.monotonic(), found)
    return found


async def keys(found: Provider, settings: Settings, refresh: bool = False) -> KeySet:
    hit = _cache.get("jwks:" + found.jwks_uri)
    if hit and not refresh and time.monotonic() - hit[0] < CACHE_S:
        return hit[1]  # type: ignore[no-any-return]
    async with http_client() as client:
        doc = await _get_json(client, found.jwks_uri)
    keyset = KeySet.import_key_set(doc)
    _cache["jwks:" + found.jwks_uri] = (time.monotonic(), keyset)
    return keyset


# --- the state cookie --------------------------------------------------------------------


def _sign(settings: Settings, payload: bytes) -> str:
    key = settings.secret_key.get_secret_value().encode()
    mac = hmac.new(key, b"oidc-state:" + payload, hashlib.sha256).digest()
    return (base64.urlsafe_b64encode(payload).decode().rstrip("=") + "."
            + base64.urlsafe_b64encode(mac).decode().rstrip("="))  # fmt: skip


def _unsign(settings: Settings, value: str) -> dict[str, Any] | None:
    try:
        body, mac = value.split(".", 1)
        payload = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
        given = base64.urlsafe_b64decode(mac + "=" * (-len(mac) % 4))
    except (ValueError, TypeError):
        return None
    keys = [k for k in (settings.secret_key, settings.secret_key_previous) if k is not None]
    if not any(
        hmac.compare_digest(
            given,
            hmac.new(
                k.get_secret_value().encode(), b"oidc-state:" + payload, hashlib.sha256
            ).digest(),
        )  # fmt: skip
        for k in keys
    ):  # the previous key too, so a rotation does not break sign-ins under way
        return None
    data = json.loads(payload)
    if not isinstance(data, dict) or time.time() - float(data.get("at", 0)) > STATE_MAX_AGE_S:
        return None
    return data


def safe_next(value: str | None) -> str:
    """A path on this site only: never another origin (``//host``, ``/\\host``, schemes)."""
    if (
        not value
        or not value.startswith("/")
        or value.startswith(("//", "/\\"))
        or len(value) > 500
    ):
        return "/"
    return value if all(c.isprintable() and c not in "\\\r\n" for c in value) else "/"


async def start(settings: Settings, next_path: str | None) -> tuple[str, str]:
    """The provider's URL to send the browser to, and the signed state cookie's value."""
    found = await provider(settings)
    state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    client = AsyncOAuth2Client(client_id=settings.oidc_client_id, scope="openid email profile",
                               redirect_uri=redirect_uri(settings))  # fmt: skip
    challenge = create_s256_code_challenge(verifier)
    url, _ = client.create_authorization_url(
        found.authorization_endpoint, state=state, nonce=nonce,
        code_challenge=challenge, code_challenge_method="S256")  # fmt: skip
    cookie = _sign(settings, json.dumps({"state": state, "nonce": nonce, "verifier": verifier,
                                         "next": safe_next(next_path),
                                         "at": time.time()}).encode())  # fmt: skip
    return url, cookie


async def finish(settings: Settings, cookie: str | None, state: str | None,
                 code: str | None) -> tuple[Identity, str]:  # fmt: skip
    """The signed-in person, and where to go next; an ``SsoError`` otherwise."""
    held = _unsign(settings, cookie or "")
    if held is None or not state or not hmac.compare_digest(str(held["state"]), state):
        raise SsoError("state", "the sign-in was not started here, or took too long")
    if not code:
        raise SsoError("refused", "the provider gave no code")
    found = await provider(settings)
    secret = settings.oidc_client_secret
    client = AsyncOAuth2Client(
        client_id=settings.oidc_client_id,
        client_secret=secret.get_secret_value() if secret else None,
        redirect_uri=redirect_uri(settings), timeout=TIMEOUT_S, follow_redirects=False,
        transport=_transport(), token_endpoint_auth_method="client_secret_basic")  # noqa: S106  # fmt: skip
    try:
        async with client:
            token = await client.fetch_token(found.token_endpoint, code=code,
                                             code_verifier=held["verifier"])  # fmt: skip
    except Exception as exc:  # noqa: BLE001 - any failure of the exchange is a refusal
        _log.warning("oidc_token_failed", error=type(exc).__name__)
        raise SsoError("refused", "the provider did not accept the sign-in") from None
    id_token = token.get("id_token")
    if not isinstance(id_token, str):
        raise SsoError("token", "the provider sent no ID token")
    return await _identity(settings, found, id_token, str(held["nonce"])), str(held["next"])


async def _identity(settings: Settings, found: Provider, id_token: str, nonce: str) -> Identity:
    for refresh in (False, True):  # a key the provider has rotated in: fetch the keys once more
        try:
            decoded = jwt.decode(id_token, await keys(found, settings, refresh),
                                 algorithms=ALGORITHMS)  # fmt: skip
            break
        except JoseError as exc:
            if refresh:
                raise SsoError("token", f"the ID token is not valid ({type(exc).__name__})") \
                    from None  # fmt: skip
    claims = decoded.claims
    registry = jwt.JWTClaimsRegistry(
        iss={"essential": True, "value": found.issuer},
        aud={"essential": True, "value": str(settings.oidc_client_id)},
        sub={"essential": True}, exp={"essential": True}, iat={"essential": True},
        nonce={"essential": True, "value": nonce}, leeway=60)  # fmt: skip
    try:
        registry.validate(claims)
    except JoseError as exc:
        raise SsoError("token", f"the ID token's claims are not valid ({type(exc).__name__})") \
            from None  # fmt: skip
    audience = claims.get("aud")
    several = isinstance(audience, list) and len(audience) > 1
    if (several or "azp" in claims) and claims.get("azp") != settings.oidc_client_id:
        raise SsoError("token", "the ID token was issued to another client")  # OIDC Core 3.1.3.7
    subject = claims["sub"]
    if not isinstance(subject, str) or not subject or len(subject) > 255:
        raise SsoError("token", "the ID token's subject is not valid")
    email = claims.get("email")
    return Identity(issuer=found.issuer, subject=subject,
                    email=str(email).strip().lower()[:254] if isinstance(email, str) else None,
                    email_verified=claims.get("email_verified") is True,
                    name=str(claims["name"])[:200]
                    if isinstance(claims.get("name"), str) else None)  # fmt: skip


def unavailable() -> ProblemError:
    return ProblemError(404, "not-found", "Sign-in with the organisation's account is off.")
