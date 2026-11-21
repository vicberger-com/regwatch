"""OpenID Connect sign-in without a database (M1b; ADR-0007; CP-37): the state cookie, the
redirect target, the provider's URLs and every check on the ID token."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from joserfc.jwk import RSAKey

from regwatch.core.settings import Settings
from regwatch.identity import oidc
from tests.oidc_provider import CLIENT_ID, ISSUER, Provider, hs256_token, oidc_env


@pytest.fixture
def idp(valid_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> Iterator[Provider]:
    for key, value in oidc_env().items():
        monkeypatch.setenv(key, value)
    found = Provider()
    monkeypatch.setattr(oidc, "transport", found.transport())
    oidc._cache.clear()
    yield found
    oidc._cache.clear()


@pytest.fixture
def settings(idp: Provider) -> Settings:
    return Settings()


@pytest.mark.parametrize(("given", "expected"), [
    ("/items?x=1", "/items?x=1"), (None, "/"), ("", "/"), ("items", "/"),
    ("//evil.example", "/"), ("/\\evil.example", "/"), ("https://evil.example", "/"),
    ("/a\r\nSet-Cookie: x", "/"), ("/a\\b", "/"), ("/" + "a" * 600, "/"),
])  # fmt: skip
def test_safe_next_stays_on_this_site(given: str | None, expected: str) -> None:
    assert oidc.safe_next(given) == expected


def test_the_state_cookie_is_signed_and_expires(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = oidc._sign(settings, json.dumps({"state": "s", "at": time.time()}).encode())
    assert oidc._unsign(settings, value) == {"state": "s", "at": pytest.approx(time.time(), abs=5)}
    body, mac = value.split(".")
    forged = oidc._sign(Settings(secret_key="b" * 64), json.dumps({"state": "s", "at": time.time()}
                        ).encode())  # fmt: skip
    assert oidc._unsign(settings, forged) is None
    assert oidc._unsign(settings, body + "." + mac[:-2] + "AA") is None
    assert oidc._unsign(settings, "no dot") is None
    assert oidc._unsign(settings, "!!.!!") is None
    old = oidc._sign(settings, json.dumps({"state": "s", "at": time.time() - 601}).encode())
    assert oidc._unsign(settings, old) is None


def test_the_previous_key_still_opens_a_state_cookie(valid_env: dict[str, str]) -> None:
    old = Settings(secret_key="b" * 64)
    value = oidc._sign(old, json.dumps({"state": "s", "at": time.time()}).encode())
    rotated = Settings(secret_key="c" * 64, secret_key_previous="b" * 64)
    assert oidc._unsign(rotated, value) is not None
    assert oidc._unsign(Settings(secret_key="c" * 64), value) is None


async def test_the_token_answer_is_capped(idp: Provider, settings: Settings) -> None:
    url, cookie = await oidc.start(settings, None)
    back = idp.authorize(url)
    idp.token_override = "x" * (oidc.MAX_ANSWER + 10)
    with pytest.raises(oidc.SsoError) as caught:
        await oidc.finish(settings, cookie, back["state"], back["code"])
    assert caught.value.reason in {"refused", "provider"}


def test_provider_urls_must_be_https(settings: Settings) -> None:
    assert oidc._check_url("https://idp.example/x", settings)
    for bad in ("http://idp.example/x", "file:///etc/passwd", "https://u:p@idp.example/",
                "https:///nohost"):  # fmt: skip
        with pytest.raises(oidc.SsoError):
            oidc._check_url(bad, settings)
    plain = Settings(oidc_test_provider=True)
    assert oidc._check_url("http://keycloak:8080/x", plain)


def test_the_test_provider_is_refused_in_production(valid_env: dict[str, str]) -> None:
    with pytest.raises(ValueError, match="OIDC_TEST_PROVIDER"):
        Settings(env="production", oidc_test_provider=True, base_url="https://rw.example")


async def test_start_sends_pkce_state_and_nonce(idp: Provider, settings: Settings) -> None:
    url, cookie = await oidc.start(settings, "/items")
    parts = urlsplit(url)
    query = {k: v[0] for k, v in parse_qs(parts.query).items()}
    assert url.startswith(ISSUER + "/protocol/openid-connect/auth?")
    assert query["client_id"] == CLIENT_ID and query["response_type"] == "code"
    assert query["redirect_uri"] == "http://localhost/api/v1/auth/oidc/callback"
    assert query["scope"] == "openid email profile"
    assert query["code_challenge_method"] == "S256"
    held = oidc._unsign(settings, cookie)
    assert held is not None
    assert (held["state"], held["nonce"], held["next"]) == (query["state"], query["nonce"],
                                                            "/items")  # fmt: skip
    assert query["code_challenge"] != held["verifier"]  # S256, never the plain verifier
    assert "client_secret" not in url


async def test_the_discovery_must_name_the_configured_issuer(
    idp: Provider, settings: Settings
) -> None:
    idp.issuer_in_discovery = "https://other.example"
    with pytest.raises(oidc.SsoError) as caught:
        await oidc.start(settings, None)
    assert caught.value.reason == "provider"


async def test_discovery_is_cached(idp: Provider, settings: Settings) -> None:
    await oidc.start(settings, None)
    await oidc.start(settings, None)
    assert idp.calls.count("/realms/regwatch/.well-known/openid-configuration") == 1


async def test_a_large_answer_is_refused(
    idp: Provider, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(oidc, "transport", httpx.MockTransport(
        lambda _: httpx.Response(200, content=b" " * (oidc.MAX_ANSWER + 10))))  # fmt: skip
    with pytest.raises(oidc.SsoError, match="too large"):
        await oidc.start(settings, None)


async def _flow(
    idp: Provider, settings: Settings, next_path: str = "/"
) -> tuple[oidc.Identity, str]:
    url, cookie = await oidc.start(settings, next_path)
    back = idp.authorize(url)
    return await oidc.finish(settings, cookie, back["state"], back["code"])


async def test_finish_returns_the_identity(idp: Provider, settings: Settings) -> None:
    identity, next_path = await _flow(idp, settings, "/map")
    assert identity == oidc.Identity(ISSUER, "subject-1", "admin@example.org", True, "Admin")
    other = oidc.Identity("https://other.example", "subject-1", None, False, None)
    assert len(identity.key) == 64 and identity.key != other.key
    assert next_path == "/map"


async def test_finish_refuses_another_state_or_no_cookie(idp: Provider, settings: Settings
                                                         ) -> None:  # fmt: skip
    url, cookie = await oidc.start(settings, None)
    back = idp.authorize(url)
    for given_cookie, state in ((cookie, "other"), (None, back["state"]), (cookie, None)):
        with pytest.raises(oidc.SsoError) as caught:
            await oidc.finish(settings, given_cookie, state, back["code"])
        assert caught.value.reason == "state"


async def test_finish_refuses_a_wrong_verifier_or_a_replayed_code(
    idp: Provider, settings: Settings
) -> None:
    url, cookie = await oidc.start(settings, None)
    back = idp.authorize(url)
    _, other = await oidc.start(settings, None)
    held, other_held = oidc._unsign(settings, cookie), oidc._unsign(settings, other)
    assert held and other_held
    swapped = oidc._sign(settings, json.dumps({**held, "verifier": other_held["verifier"]}
                                              ).encode())  # fmt: skip
    with pytest.raises(oidc.SsoError) as caught:
        await oidc.finish(settings, swapped, back["state"], back["code"])
    assert caught.value.reason == "refused"
    back = idp.authorize(url, code="code-2")
    await oidc.finish(settings, cookie, back["state"], back["code"])
    with pytest.raises(oidc.SsoError):
        await oidc.finish(settings, cookie, back["state"], back["code"])  # the code is spent


@pytest.mark.parametrize(("changes", "why"), [
    ({"iss": "https://other.example"}, "issuer"),
    ({"aud": "another-client"}, "audience"),
    ({"exp": int(time.time()) - 3600}, "expired"),
    ({"iat": None}, "no iat"),
    ({"sub": None}, "no subject"),
    ({"nonce": "another"}, "nonce"),
    ({"aud": [CLIENT_ID, "another"], "azp": "another"}, "azp"),
    ({"aud": [CLIENT_ID, "another"]}, "several audiences, no azp"),
    ({"azp": "another"}, "an azp, present, must be ours"),
    ({"sub": "x" * 256}, "a subject too long"),
    ({"sub": 42}, "a subject not a string"),
])  # fmt: skip
async def test_finish_refuses_a_bad_id_token(
    idp: Provider, settings: Settings, changes: dict[str, object], why: str
) -> None:
    idp.claims = changes
    with pytest.raises(oidc.SsoError) as caught:
        await _flow(idp, settings)
    assert caught.value.reason == "token", why


async def test_several_audiences_with_our_azp_are_accepted(idp: Provider, settings: Settings
                                                           ) -> None:  # fmt: skip
    idp.claims = {"aud": [CLIENT_ID, "another"], "azp": CLIENT_ID}
    identity, _ = await _flow(idp, settings)
    assert identity.subject == "subject-1"


async def test_finish_refuses_unsigned_symmetric_and_foreign_tokens(
    idp: Provider, settings: Settings
) -> None:
    now = int(time.time())
    claims = {"iss": ISSUER, "aud": CLIENT_ID, "sub": "x", "iat": now, "exp": now + 60}
    foreign = RSAKey.generate_key(2048, {"kid": "k1"})
    import base64

    def b64(data: dict[str, object]) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    for token in (
        hs256_token(CLIENT_ID, claims),  # algorithm confusion
        b64({"alg": "none"}) + "." + b64(claims) + ".",  # unsigned
        Provider(key=foreign).id_token("n"),  # another key with the same kid
    ):
        idp.token_override = token
        with pytest.raises(oidc.SsoError) as caught:
            await _flow(idp, settings)
        assert caught.value.reason == "token"


async def test_a_rotated_key_is_fetched_once_more(idp: Provider, settings: Settings) -> None:
    await _flow(idp, settings)  # the key set is cached
    idp.key = RSAKey.generate_key(2048, {"kid": "k2"})
    identity, _ = await _flow(idp, settings)
    assert identity.subject == "subject-1"
    assert idp.calls.count("/realms/regwatch/protocol/openid-connect/certs") == 2


async def test_an_unverified_or_missing_email_is_reported_as_such(
    idp: Provider, settings: Settings
) -> None:
    idp.claims = {"email_verified": "true", "email": " Admin@Example.org "}
    identity, _ = await _flow(idp, settings)
    assert (identity.email, identity.email_verified) == ("admin@example.org", False)
    idp.claims = {"email": None, "email_verified": None}
    identity, _ = await _flow(idp, settings)
    assert (identity.email, identity.email_verified) == (None, False)
