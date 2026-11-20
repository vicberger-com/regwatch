"""Integration: stock reports and their parameters (M7.3; REQ-10; acceptance 3 without the map
snapshot, which is M7.5)."""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.reports import render
from tests.integration.test_admin import _api, _as_new_user, admin
from tests.integration.test_auth import clear_limits, db_url
from tests.integration.test_capture_runs import db
from tests.integration.test_report_preview import corpus
from tests.integration.test_sources import fixed_dns

pytestmark = pytest.mark.integration
__all__ = ["admin", "clear_limits", "db", "db_url", "fixed_dns"]  # shared fixtures


@pytest.fixture(autouse=True)
def clear_rates() -> Iterator[None]:
    from regwatch.search import services

    services.searches._hits.clear()
    render.renders.clear()
    yield


async def _instantiate(client: httpx.AsyncClient, key: str) -> str:
    made = await client.post(_api(f"/reports/templates/{key}/instantiate"))
    assert made.status_code == 201, made.text
    assert made.json()["based_on_template_key"] == key
    return str(made.json()["id"])


async def test_the_five_stock_reports_are_offered(admin: httpx.AsyncClient) -> None:
    viewer = await _as_new_user(admin, "pat@example.org", ["viewer"])
    got = await viewer.get(_api("/reports/templates"))  # reports.print, which viewers hold
    assert got.status_code == 200, got.text
    keys = {t["key"]: t for t in got.json()}
    assert set(keys) == {"weekly-change-digest", "jurisdiction-profile", "topic-overview",
                         "source-health", "regulation-status-matrix"}  # fmt: skip
    profile = {p["key"]: p for p in keys["jurisdiction-profile"]["parameters"]}
    assert profile["jurisdiction"]["required"] is True
    assert profile["period_days"]["default"] == 90
    # Viewers may print stock reports but not copy them into layouts (reports.build).
    assert (await viewer.post(_api("/reports/templates/source-health/instantiate"))
            ).status_code == 403  # fmt: skip
    assert (await admin.post(_api("/reports/templates/nope/instantiate"))).status_code == 404
    await viewer.aclose()


async def test_a_jurisdiction_profile_for_one_place(
    admin: httpx.AsyncClient, db: AsyncSession
) -> None:
    """Acceptance 3 (map snapshot aside): latest ten changes and a status matrix for one place."""
    await corpus(admin, db)
    lid = await _instantiate(admin, "jurisdiction-profile")
    missing = await admin.post(_api(f"/reports/layouts/{lid}/preview"), json={})
    assert missing.status_code == 422 and "Jurisdiction is needed" in missing.text
    for bad in ({"jurisdiction": "ZZ"}, {"jurisdiction": "DE", "period_days": 0},
                {"jurisdiction": "DE", "colour": "red"}):  # fmt: skip
        assert (await admin.post(_api(f"/reports/layouts/{lid}/preview"), json=bad)
                ).status_code == 422, bad  # fmt: skip
    got = await admin.post(_api(f"/reports/layouts/{lid}/preview"), json={"jurisdiction": "DE"})
    assert got.status_code == 200, got.text
    html = got.text
    assert "Latest ten changes" in html and "Status" in html
    assert '<th scope="col">new</th>' in html and "Germany" in html  # the corpus is German
    other = await admin.post(_api(f"/reports/layouts/{lid}/preview"), json={"jurisdiction": "FR"})
    assert other.status_code == 200 and "Germany" not in other.text  # the filter applies


async def test_source_health_needs_sources_read(admin: httpx.AsyncClient) -> None:
    ana = await _as_new_user(admin, "sam@example.org", ["analyst"])  # has sources.read
    lid = await _instantiate(ana, "source-health")
    shown = await ana.post(_api(f"/reports/layouts/{lid}/preview"))
    assert shown.status_code == 200 and "Failures in a row" in shown.text
    admin_made = await _instantiate(admin, "source-health")
    shared = await admin.patch(_api(f"/reports/layouts/{admin_made}"), json={"shared": True})
    assert shared.status_code == 200, shared.text
    role = await admin.post(_api("/admin/roles"), json={
        "key": "builders", "label": "Builders",
        "permissions": ["reports.build", "items.read"]})  # fmt: skip
    assert role.status_code == 201, role.text
    bea = await _as_new_user(admin, "bea@example.org", ["builders"])
    hidden = await bea.post(_api(f"/reports/layouts/{admin_made}/preview"))
    assert hidden.status_code == 200
    assert (
        "shown to readers of sources only" in hidden.text and "Failures in a row" not in hidden.text
    )
    await ana.aclose()
    await bea.aclose()
