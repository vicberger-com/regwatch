"""Integration: logo upload and the public logo route (BL-68, CP-07, M1 acceptance 6)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from regwatch.api.app import API_PREFIX, create_app
from regwatch.core.settings import Settings, get_settings
from tests.integration.test_admin import _as_new_user
from tests.integration.test_auth import ADMIN_PW, ORIGIN, _login, clear_limits, db_url
from tests.unit.test_logo_check import png, svg

pytestmark = pytest.mark.integration
__all__ = ["clear_limits", "db_url"]

LOGO = API_PREFIX + "/admin/branding/logo"
PUBLIC = API_PREFIX + "/branding/logo"


@pytest.fixture
async def client(
    db_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    monkeypatch.setenv("REGWATCH_OBJECT_STORE_PATH", str(tmp_path))
    get_settings.cache_clear()
    transport = httpx.ASGITransport(app=create_app(Settings()))
    async with httpx.AsyncClient(transport=transport, base_url="https://localhost",
                                 headers=ORIGIN) as c:  # fmt: skip
        yield c


async def _admin(c: httpx.AsyncClient) -> None:
    assert (await _login(c, "admin@example.org", ADMIN_PW)).status_code == 200


async def test_png_upload_is_served_publicly_with_strict_headers(
    client: httpx.AsyncClient, tmp_path: Path
) -> None:
    assert (await client.get(PUBLIC)).status_code == 404
    await _admin(client)
    data = png()
    resp = await client.post(LOGO, files={"file": ("x.svg", data, "image/svg+xml")})
    assert resp.status_code == 200, resp.text
    url = resp.json()["logo_url"]
    assert url.startswith(PUBLIC + "?v=") and len(url.rsplit("=", 1)[1]) == 12
    assert (await client.get(API_PREFIX + "/branding")).json()["logo_url"] == url
    stored = list((tmp_path / "branding").iterdir())
    assert [p.read_bytes() for p in stored] == [data]

    async with httpx.AsyncClient(transport=client._transport, base_url="https://localhost") as anon:
        got = await anon.get(url)
        assert got.status_code == 200 and got.content == data
        assert got.headers["content-type"] == "image/png"  # from the content, not the client
        assert "sandbox" in got.headers["content-security-policy"]
        assert got.headers["x-content-type-options"] == "nosniff"
        again = await anon.get(PUBLIC, headers={"If-None-Match": got.headers["etag"]})
        assert again.status_code == 304 and again.content == b""


async def test_svg_logo_replaces_png_and_is_audited(client: httpx.AsyncClient) -> None:
    await _admin(client)
    await client.post(LOGO, files={"file": ("a.png", png(), "image/png")})
    first = (await client.get(API_PREFIX + "/branding")).json()["logo_url"]
    image = svg('<rect width="10" height="10" fill="#123"/>')
    resp = await client.post(LOGO, files={"file": ("b.svg", image, "image/svg+xml")})
    assert resp.status_code == 200 and resp.json()["logo_url"] != first
    got = await client.get(PUBLIC)
    assert got.headers["content-type"].startswith("image/svg+xml") and got.content == image
    audit = await client.get(API_PREFIX + "/admin/audit", params={"action": "branding.logo"})
    assert audit.json()["total"] >= 2


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (svg("<script>alert(1)</script>"), "<script>"),
        (svg("", 'onload="alert(1)"'), "onload"),
        (b"GIF89a", "PNG or SVG"),
    ],
)
async def test_unsafe_or_other_files_are_refused(
    client: httpx.AsyncClient, data: bytes, reason: str
) -> None:
    await _admin(client)
    before = (await client.get(API_PREFIX + "/branding")).json().get("logo_url")
    resp = await client.post(LOGO, files={"file": ("logo.svg", data, "image/svg+xml")})
    assert resp.status_code == 415 and reason in resp.json()["detail"]
    assert (await client.get(API_PREFIX + "/branding")).json().get("logo_url") == before


async def test_upload_needs_a_file_part_and_settings_manage(client: httpx.AsyncClient) -> None:
    assert (
        await client.post(LOGO, files={"file": ("a.png", png(), "image/png")})
    ).status_code == 401
    await _admin(client)
    assert (await client.post(LOGO, data={"file": "not a file"})).status_code == 415
    two = [("file", ("a.png", png(), "image/png")), ("file", ("b.png", png(), "image/png"))]
    assert (await client.post(LOGO, files=two)).status_code >= 400


async def test_upload_needs_the_permission_and_the_site_origin(client: httpx.AsyncClient) -> None:
    """BL-68 review finding 8: a signed-in user without settings.manage, and a foreign Origin."""
    await _admin(client)
    viewer = await _as_new_user(client, "logo-viewer@example.org", ["viewer"])
    try:
        refused = await viewer.post(LOGO, files={"file": ("a.png", png(), "image/png")})
        assert refused.status_code == 403
    finally:
        await viewer.aclose()
    foreign = await client.post(LOGO, files={"file": ("a.png", png(), "image/png")},
                                headers={"Origin": "https://evil.example"})  # fmt: skip
    assert foreign.status_code == 403
    assert (await client.get(PUBLIC)).status_code == 404  # nothing was stored
