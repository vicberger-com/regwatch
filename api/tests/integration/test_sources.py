"""Integration: source and capture-job routes (M3 acceptance 3 and 4; REQ-02, REQ-05)."""

from __future__ import annotations

import httpx
import pytest

from regwatch.capture import services
from tests.integration.test_admin import _api, _as_new_user, admin
from tests.integration.test_auth import clear_limits, db_url

pytestmark = pytest.mark.integration
__all__ = ["admin", "clear_limits", "db_url"]  # fixtures shared with test_admin and test_auth

HOSTS = {"feeds.example": ["93.184.215.14"], "inside.example": ["10.0.0.5"],
         "mixed.example": ["93.184.215.14", "169.254.169.254"]}  # fmt: skip


@pytest.fixture(autouse=True)
def fixed_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Made-up names with fixed answers; every answer is still checked by SafeFetcher's policy."""

    async def resolver(host: str, port: int) -> list[str]:
        if host not in HOSTS:
            raise OSError("no such host")
        return HOSTS[host]

    monkeypatch.setattr(services, "RESOLVER", resolver)


def rss(**extra: object) -> dict[str, object]:
    return {"name": "Feed", "kind": "rss", "config": {"feed_url": "https://feeds.example/rss"},
            **extra}  # fmt: skip


async def test_create_read_update_and_disable(admin: httpx.AsyncClient) -> None:
    body = rss(default_jurisdiction_codes=["AT", "AU"], job={"interval_seconds": 1800})
    created = await admin.post(_api("/sources"), json=body)
    assert created.status_code == 201, created.text
    source = created.json()
    assert source["default_jurisdiction_codes"] == ["AT", "AU"]
    assert source["job"]["interval_seconds"] == 1800 and source["job"]["cron"] is None
    assert source["robots_policy"] == "respect" and source["health"] == "unknown"
    sid = source["id"]
    assert (await admin.get(_api(f"/sources/{sid}"))).json()["name"] == "Feed"

    cron = await admin.patch(_api(f"/sources/{sid}"), json={"job": {"cron": "*/30 * * * *"}})
    assert cron.status_code == 200, cron.text
    assert cron.json()["job"]["cron"] == "*/30 * * * *"
    assert cron.json()["job"]["interval_seconds"] is None  # one schedule replaces the other

    listed = (await admin.get(_api("/sources"), params={"q": "fe", "kind": "rss"})).json()
    assert listed["total"] == 1 and listed["items"][0]["job"]["id"] == source["job"]["id"]
    assert (await admin.get(_api("/sources"), params={"q": "%"})).json()["total"] == 0
    assert (await admin.get(_api("/sources"), params={"health": "unknown"})).json()["total"] == 1
    jobs = (await admin.get(_api("/capture-jobs"), params={"source_id": sid})).json()
    assert [j["id"] for j in jobs] == [source["job"]["id"]]

    change = {"rate_limit_per_minute": 10, "timezone": "Europe/Vienna"}
    job = await admin.patch(_api(f"/capture-jobs/{jobs[0]['id']}"), json=change)
    assert job.status_code == 200 and job.json()["rate_limit_per_minute"] == 10

    assert (await admin.delete(_api(f"/sources/{sid}"))).status_code == 204
    gone = (await admin.get(_api(f"/sources/{sid}"))).json()
    assert gone["enabled"] is False and gone["job"]["enabled"] is False  # kept, not deleted
    assert (await admin.delete(_api(f"/sources/{sid}"))).status_code == 204
    audit = (await admin.get(_api("/admin/audit"), params={"entity_type": "source"})).json()
    assert [r["action"] for r in audit["items"]] == ["source.disable", "source.update",
                                                     "source.create"]  # fmt: skip
    jobs_audit = await admin.get(_api("/admin/audit"), params={"entity_type": "capture_job"})
    assert jobs_audit.json()["items"][0]["after"]["rate_limit_per_minute"] == 10


@pytest.mark.parametrize(
    ("body", "field"),
    [
        (rss(config={"feed_url": "http://127.0.0.1/rss"}), "config.feed_url"),
        (rss(config={"feed_url": "http://169.254.169.254/latest/"}), "config.feed_url"),
        (rss(config={"feed_url": "https://inside.example/rss"}), "config.feed_url"),
        (rss(config={"feed_url": "https://mixed.example/rss"}), "config.feed_url"),
        (rss(config={"feed_url": "https://nowhere.example/rss"}), "config.feed_url"),
        (rss(url="http://2130706433/"), "url"),
        ({"name": "Crawl", "kind": "web_crawl",
          "config": {"seed_urls": ["https://feeds.example/", "http://[::1]/"],
                     "allowed_domains": ["feeds.example"]}},
         "config.seed_urls.1"),
        (rss(config={}), "config.feed_url"),
        (rss(config={"feed_url": "https://feeds.example/rss", "extra": 1}), "config.extra"),
        (rss(job={"cron": "* * *"}), "job.cron"),
        (rss(job={"cron": "* * * * *", "interval_seconds": 900}), "job.cron"),
        (rss(job={"timezone": "Mars/Base"}), "job.timezone"),
        (rss(job={"extraction_rules": {"bogus": True}}), "extraction_rules.bogus"),
        (rss(default_jurisdiction_codes=["ZZZ"]), "default_jurisdiction_codes"),
        (rss(robots_policy="override"), "override_reason"),
        (rss(robots_policy="override", override_reason="   "), "override_reason"),
        (rss(robots_policy="override", override_reason="x" * 1001), "override_reason"),
        ({"kind": "rss", "config": {}}, "name"),
        (rss(name="   "), "name"),
        (rss(credibility=None), "credibility"),
        (rss(default_term_ids=["00000000-0000-7000-8000-000000000001"]), "default_term_ids"),
        (rss(job={"max_items_per_run": 0}), "job.max_items_per_run"),
        (rss(job={"render_js": None}), "job.render_js"),
    ],
)  # fmt: skip
async def test_invalid_sources_are_refused_with_the_field(
    admin: httpx.AsyncClient, body: dict[str, object], field: str
) -> None:
    """M3 acceptance 3: private, metadata and unresolvable hosts are refused when saved."""
    got = await admin.post(_api("/sources"), json=body)
    assert got.status_code == 422, got.text
    errors = got.json()["errors"]
    assert field in [e["field"] for e in errors]
    # A name that resolves privately is refused without saying what it resolved to.
    assert not any("10.0.0.5" in e["message"] or "169.254" in e["message"] for e in errors)
    assert (await admin.get(_api("/sources"))).json()["total"] == 0


async def test_the_robots_override_needs_its_permission_and_is_audited(
    admin: httpx.AsyncClient,
) -> None:
    """M3 acceptance 4 and review finding 22 (a): an editor manages sources but cannot
    override robots.txt; an admin can, with a reason, and the override has its own audit row."""
    editor = await _as_new_user(admin, "ed@example.org", ["editor"])
    made = await editor.post(_api("/sources"), json=rss())
    assert made.status_code == 201, made.text
    sid = made.json()["id"]
    body = {"robots_policy": "override", "override_reason": "Owner agreed in writing"}
    denied = await editor.patch(_api(f"/sources/{sid}"), json=body)
    assert denied.status_code == 403
    assert (await editor.post(_api("/sources"), json=rss(**body))).status_code == 403

    allowed = await admin.patch(_api(f"/sources/{sid}"), json=body)
    assert allowed.status_code == 200 and allowed.json()["override_reason"] == body[
        "override_reason"]  # fmt: skip
    rename = await editor.patch(_api(f"/sources/{sid}"), json={"name": "Renamed"})
    assert rename.status_code == 200  # untouched override: no extra permission needed
    reason = await editor.patch(_api(f"/sources/{sid}"), json={"override_reason": "Other"})
    assert reason.status_code == 403  # a new reason is a new override
    back = await editor.patch(_api(f"/sources/{sid}"), json={"robots_policy": "respect"})
    assert back.status_code == 200 and back.json()["override_reason"] is None

    rows = (await admin.get(_api("/admin/audit"),
                            params={"action": "source.robots_override"})).json()  # fmt: skip
    assert rows["total"] == 1
    assert rows["items"][0]["after"]["override_reason"] == body["override_reason"]
    viewer = await _as_new_user(admin, "vw@example.org", ["viewer"])
    assert (await viewer.get(_api(f"/sources/{sid}"))).status_code == 403  # no sources.read
    assert (await viewer.patch(_api(f"/sources/{sid}"), json={"name": "x"})).status_code == 403


async def test_kind_is_fixed_and_unknown_ids_are_404(admin: httpx.AsyncClient) -> None:
    sid = (await admin.post(_api("/sources"), json=rss())).json()["id"]
    kind = await admin.patch(_api(f"/sources/{sid}"),
                             json={"kind": "manual", "config": {}})  # fmt: skip
    assert kind.status_code == 422
    missing = "00000000-0000-7000-8000-000000000000"
    assert (await admin.get(_api(f"/sources/{missing}"))).status_code == 404
    assert (await admin.patch(_api(f"/capture-jobs/{missing}"), json={})).status_code == 404
    job = (await admin.get(_api("/sources/" + sid))).json()["job"]["id"]
    neither = await admin.patch(_api(f"/capture-jobs/{job}"), json={"interval_seconds": None})
    assert neither.status_code == 422
