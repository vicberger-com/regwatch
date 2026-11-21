"""Integration: server-rendered report preview (M7.2; acceptance 1; the M7.1 review's guards)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.processing.pipeline import process_manifest
from regwatch.reports import render
from tests.integration.test_admin import _api, _as_new_user, admin
from tests.integration.test_auth import clear_limits, db_url
from tests.integration.test_capture_runs import db
from tests.integration.test_processing_pipeline import BSI, loader, made_source, manifest
from tests.integration.test_sources import fixed_dns

pytestmark = pytest.mark.integration
__all__ = ["admin", "clear_limits", "db", "db_url", "fixed_dns"]  # shared fixtures

TAG = uuid.uuid4().hex[:8]


@pytest.fixture(autouse=True)
def clear_rates() -> Iterator[None]:
    from regwatch.search import services

    services.searches._hits.clear()
    render.renders.clear()
    yield
    render.renders.clear()


async def corpus(admin: httpx.AsyncClient, db: AsyncSession) -> None:
    sid = await made_source(admin)
    rows = [
        {"url": f"https://example.org/{TAG}/a", "text": "Eins. " + BSI,
         "title": f"{TAG} A < B & \"C\" > D guidance", "summary": "First."},
        {"url": f"https://example.org/{TAG}/b", "text": "Zwei. " + BSI,
         "title": f"{TAG} NIS2 scope", "summary": "Second."},
    ]  # fmt: skip
    key, objects = manifest(sid, uuid.uuid4(), rows)
    await process_manifest(db, key, loader(objects))


def body(*content: dict[str, object], **extra: object) -> dict[str, object]:
    return {"name": "Preview", "data_source": {"query": {"q": TAG}, "limit": 10},
            "layout": {"root": {"props": {"title": "Weekly <b>digest</b>"}},
                       "content": list(content)}, **extra}  # fmt: skip


TABLE = {"type": "ItemsTable", "props": {"id": "t", "columns": ["item.title", "item.url",
                                                                 "source.credibility"],
                                         "sort": "item.title", "direction": "asc"}}  # fmt: skip


async def test_the_preview_shows_the_rows_escaped(
    admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    """Acceptance 1 (the rows of the query), with hostile text escaped and a strict CSP."""
    await corpus(admin, db)
    footer = {"type": "HeaderFooter", "props": {"id": "f", "footer_text": 'x"; } * { color: red'}}
    note = {
        "type": "Paragraph",
        "props": {"id": "p", "text": "Line one\n<img src=x onerror=alert(1)>"},
    }
    made = await admin.post(_api("/reports/layouts"), json=body(note, TABLE, footer))
    assert made.status_code == 201, made.text
    got = await admin.post(_api(f"/reports/layouts/{made.json()['id']}/preview"))
    assert got.status_code == 200, got.text
    assert got.headers["content-type"].startswith("text/html")
    csp = got.headers["content-security-policy"]
    assert "default-src 'none'" in csp and "sandbox" in csp and "script-src" not in csp
    html = got.text
    # Captured text arrives tag-free from M4 but may hold markup characters: escaped here.
    assert f"{TAG} A &lt; B &amp; &#34;C&#34; &gt; D guidance" in html
    assert "<img" not in html and "&lt;img src=x onerror=alert(1)&gt;" in html
    assert "Weekly &lt;b&gt;digest&lt;/b&gt;" in html
    assert f'<a href="https://example.org/{TAG}/a" rel="noopener noreferrer nofollow">' in html
    assert '<meta http-equiv="Content-Security-Policy"' in html  # for the PDF and email
    assert html.index(f"{TAG} A &lt;") < html.index(f"{TAG} NIS2 scope")  # sorted
    assert "official" in html  # the source's credibility
    assert 'content: "x\\000022 ' in html and "color: red" not in html  # CSS-escaped footer


async def test_a_shared_layout_renders_with_the_viewers_rights(
    admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    await corpus(admin, db)
    view = (await admin.post(_api("/views"), json={"name": "Shared", "period_days": 30,
                                                    "shared": True})).json()  # fmt: skip
    made = (await admin.post(_api("/reports/layouts"), json=body(
        TABLE, shared=True, data_source={"saved_view_id": view["id"]}))).json()  # fmt: skip
    ana = await _as_new_user(admin, "ann@example.org", ["analyst"])
    assert (await ana.post(_api(f"/reports/layouts/{made['id']}/preview"))).status_code == 200
    unshared = await admin.patch(_api(f"/views/{view['id']}"), json={"shared": False})
    assert unshared.status_code == 200, unshared.text
    refused = await ana.post(_api(f"/reports/layouts/{made['id']}/preview"))
    assert refused.status_code in (404, 409), refused.text  # never the owner's private view
    await ana.aclose()


async def test_renders_are_limited(
    admin: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    lid = (await admin.post(_api("/reports/layouts"), json=body(TABLE))).json()["id"]
    monkeypatch.setattr(render, "RENDER_RATE", 1)
    assert (await admin.post(_api(f"/reports/layouts/{lid}/preview"))).status_code == 200
    limited = await admin.post(_api(f"/reports/layouts/{lid}/preview"))
    assert limited.status_code == 429 and limited.headers["Retry-After"]


async def test_the_preview_as_a_page_for_a_frame(
    admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    """CP-35 (BL-140 g): the same HTML by GET, framed by this site only, with its own CSP; the
    settings come as JSON in `params`, checked as in the POST form."""
    await corpus(admin, db)
    made = (await admin.post(_api("/reports/layouts"), json=body(TABLE))).json()
    url = _api(f"/reports/layouts/{made['id']}/preview")
    got = await admin.get(url)
    assert got.status_code == 200, got.text
    assert got.headers["x-frame-options"] == "SAMEORIGIN"
    csp = got.headers["content-security-policy"]
    assert "sandbox" in csp and "frame-ancestors 'self'" in csp and "script-src" not in csp
    posted = (await admin.post(url)).text
    assert f"{TAG} NIS2 scope" in got.text and f"{TAG} NIS2 scope" in posted  # the same rows
    for bad in ("not json", "[1, 2]", '{"no_such": 1}'):
        refused = await admin.get(url, params={"params": bad})
        assert refused.status_code == 422, (bad, refused.text)
    assert (await admin.get(url, params={"params": "x" * 2001})).status_code == 422
