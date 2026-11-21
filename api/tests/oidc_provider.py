"""A mock OpenID Connect provider for the M1b tests, served through ``oidc.transport``: no
network. It signs ID tokens with its own RSA key and checks the client's secret and the PKCE
verifier like a real provider."""

from __future__ import annotations

import base64
import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
from joserfc import jwt
from joserfc.jwk import KeySet, OctKey, RSAKey

ISSUER = "https://idp.example.test/realms/regwatch"
CLIENT_ID = "regwatch"
CLIENT_SECRET = "client secret for the tests"  # noqa: S105 - a test value


def oidc_env() -> dict[str, str]:
    return {"REGWATCH_OIDC_ISSUER": ISSUER, "REGWATCH_OIDC_CLIENT_ID": CLIENT_ID,
            "REGWATCH_OIDC_CLIENT_SECRET": CLIENT_SECRET}  # fmt: skip


@dataclass
class Provider:
    key: RSAKey = field(default_factory=lambda: RSAKey.generate_key(2048, {"kid": "k1"}))
    claims: dict[str, Any] = field(default_factory=dict)
    codes: dict[str, tuple[str, str]] = field(default_factory=dict)  # code: (challenge, nonce)
    issuer_in_discovery: str = ISSUER
    calls: list[str] = field(default_factory=list)
    token_override: str | None = None
    jwks_override: dict[str, Any] | None = None

    def jwks(self) -> dict[str, Any]:
        if self.jwks_override is not None:
            return self.jwks_override
        return KeySet([self.key]).as_dict(private=False)

    def id_token(self, nonce: str, **changes: Any) -> str:  # noqa: ANN401
        now = int(time.time())
        claims = {"iss": ISSUER, "aud": CLIENT_ID, "sub": "subject-1", "iat": now,
                  "exp": now + 300, "nonce": nonce, "email": "admin@example.org",
                  "email_verified": True, "name": "Admin"}  # fmt: skip
        claims.update(self.claims)
        claims.update(changes)
        for k in [k for k, v in claims.items() if v is None]:
            del claims[k]
        return jwt.encode({"alg": "RS256", "kid": self.key.kid}, claims, self.key)

    def authorize(self, url: str, code: str = "code-1") -> dict[str, str]:
        """What the browser brings back: the ``state``, and a code the token endpoint knows."""
        query = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        assert query["code_challenge_method"] == "S256"
        self.codes[code] = (query["code_challenge"], query["nonce"])
        return {"code": code, "state": query["state"]}

    def _token(self, request: httpx.Request) -> httpx.Response:
        expected = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
        if request.headers.get("authorization") != f"Basic {expected}":
            return httpx.Response(401, json={"error": "invalid_client"})
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        held = self.codes.pop(form.get("code", ""), None)
        if held is None or form.get("grant_type") != "authorization_code":
            return httpx.Response(400, json={"error": "invalid_grant"})
        digest = hashlib.sha256(form.get("code_verifier", "").encode()).digest()
        if base64.urlsafe_b64encode(digest).decode().rstrip("=") != held[0]:
            return httpx.Response(400, json={"error": "invalid_grant"})
        token = self.token_override or self.id_token(held[1])
        return httpx.Response(200, json={"access_token": "at", "token_type": "Bearer",
                                         "expires_in": 300, "id_token": token})  # fmt: skip

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append(path)
        if path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(200, json={
                "issuer": self.issuer_in_discovery,
                "authorization_endpoint": ISSUER + "/protocol/openid-connect/auth",
                "token_endpoint": ISSUER + "/protocol/openid-connect/token",
                "jwks_uri": ISSUER + "/protocol/openid-connect/certs"})  # fmt: skip
        if path.endswith("/certs"):
            return httpx.Response(200, content=json.dumps(self.jwks()).encode())
        if path.endswith("/token"):
            return self._token(request)
        return httpx.Response(404)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)


def hs256_token(secret: str, claims: dict[str, Any]) -> str:
    """A token signed with a shared secret: the algorithm-confusion attempt."""
    return jwt.encode({"alg": "HS256"}, claims, OctKey.import_key(secret.encode() * 4))
