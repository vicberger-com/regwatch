"""Integration: source and capture-job routes (M3 acceptance 3 and 4; REQ-02, REQ-05)."""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from regwatch.capture import services
from regwatch.capture.safe_fetch.policy import is_ip
from tests.integration.test_admin import _api, _as_new_user, admin
from tests.integration.test_auth import clear_limits, db_url

pytestmark = pytest.mark.integration
__all__ = ["admin", "clear_limits", "db_url"]  # fixtures shared with test_admin and test_auth

HOSTS = {"feeds.example": ["93.184.215.14"], "inside.example": ["10.0.0.5"],
         "mixed.example": ["93.184.215.14", "169.254.169.254"]}  # fmt: skip


SLOW = {"slow.example"}


@pytest.fixture(autouse=True)
def fixed_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Made-up names with fixed answers; every answer is still checked by SafeFetcher's policy."""

    async def resolver(host: str, port: int) -> list[str]:
        if host in SLOW:
            await asyncio.sleep(5)
        if is_ip(host):  # as getaddrinfo does: a literal resolves to itself (review finding 5)
            return [host]
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
        (rss(terms_url="javascript:alert(document.cookie)"), "terms_url"),
        (rss(terms_url="https://[bad/"), "terms_url"),
        (rss(language="x" * 100), "language"),
        (rss(name="Feed \u202egnp.exe"), "name"),
        (rss(robots_policy="override", override_reason="ok\x00"), "override_reason"),
        (rss(job={"cron": "99 99 99 99 99"}), "job.cron"),
        (rss(job={"cron": "5-1 * * * *"}), "job.cron"),
        (rss(job={"cron": "*/0 * * * *"}), "job.cron"),
        (rss(job={"cron": "* * * * " + "1," * 200 + "1"}), "job.cron"),
        (rss(job={"interval_seconds": 2**31}), "job.interval_seconds"),
        (rss(job={"cron": "\u00b2 * * * *"}), "job.cron"),
        (rss(job={"cron": "*/\u00b2 * * * *"}), "job.cron"),
        (rss(job={"cron": "\u0661 * * * *"}), "job.cron"),
        (rss(language="en\n"), "language"),
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
    # One message for private and unresolvable names: no address, no DNS oracle (findings 4).
    assert not any("10.0.0.5" in e["message"] or "169.254" in e["message"] for e in errors)
    if field.startswith(("config.feed_url", "url", "config.seed")) and "{}" not in str(body):
        assert services._NOT_PUBLIC in [e["message"] for e in errors]
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


async def test_editors_cannot_move_or_restart_an_override(admin: httpx.AsyncClient) -> None:
    """Review finding 1: on an overridden source, new URLs or turning it back on is a new
    override, which needs the permission and gets its own audit row naming the URLs."""
    editor = await _as_new_user(admin, "ed2@example.org", ["editor"])
    body = rss(robots_policy="override", override_reason="Owner agreed in writing")
    sid = (await admin.post(_api("/sources"), json=body)).json()["id"]
    moved = {"config": {"feed_url": "https://feeds.example/other"}}
    assert (await editor.patch(_api(f"/sources/{sid}"), json=moved)).status_code == 403
    home = {"url": "https://feeds.example/"}
    assert (await editor.patch(_api(f"/sources/{sid}"), json=home)).status_code == 403
    same = {"config": {"feed_url": "https://feeds.example/rss"}}  # unchanged: allowed
    assert (await editor.patch(_api(f"/sources/{sid}"), json=same)).status_code == 200
    assert (await editor.delete(_api(f"/sources/{sid}"))).status_code == 204  # stopping is fine
    restart = await editor.patch(_api(f"/sources/{sid}"), json={"enabled": True})
    assert restart.status_code == 403

    assert (await admin.patch(_api(f"/sources/{sid}"), json=moved)).status_code == 200
    rows = (await admin.get(_api("/admin/audit"),
                            params={"action": "source.robots_override"})).json()  # fmt: skip
    assert rows["total"] == 2
    assert rows["items"][0]["after"]["config"]["feed_url"] == "https://feeds.example/other"
    assert rows["items"][0]["before"]["config"]["feed_url"] == "https://feeds.example/rss"


async def test_lookups_have_one_deadline_and_run_before_the_lock(
    admin: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review finding 2: a name server that never answers is cut off, and other saves of the
    same source do not wait for it."""
    monkeypatch.setattr(services, "DNS_DEADLINE_S", 0.5)
    sid = (await admin.post(_api("/sources"), json=rss())).json()["id"]
    slow_feed = {"config": {"feed_url": "https://slow.example/rss"}}
    started = time.monotonic()
    slow, rename = await asyncio.gather(
        admin.patch(_api(f"/sources/{sid}"), json=slow_feed),
        admin.patch(_api(f"/sources/{sid}"), json={"name": "Renamed"}),
    )  # the same source: the slow save must not hold its row (re-verification 16)
    assert slow.status_code == 422 and rename.status_code == 200
    seeds = {"seed_urls": [f"https://slow.example/{n}" for n in range(20)],
             "allowed_domains": ["slow.example"]}  # fmt: skip
    crawl_body = {"name": "Crawl", "kind": "web_crawl", "config": seeds}
    crawl = await admin.post(_api("/sources"), json=crawl_body)
    assert crawl.status_code == 422
    assert time.monotonic() - started < 2.0  # 20 lookups together, not 20 after another


async def test_the_config_is_stored_as_checked_and_pages_are_bounded(
    admin: httpx.AsyncClient,
) -> None:
    """Review findings 6 and 8."""
    made = await admin.post(_api("/sources"),
                            json=rss(config={"feed_url": "HTTPS://Feeds.Example/rss"}))  # fmt: skip
    assert made.status_code == 201
    assert made.json()["config"]["feed_url"] == "https://feeds.example/rss"
    assert (await admin.get(_api("/sources"), params={"page": 10**17})).status_code == 422
    assert (await admin.get(_api("/admin/users"), params={"page": 10**17})).status_code == 422


async def test_resuming_an_overridden_job_is_a_new_override(admin: httpx.AsyncClient) -> None:
    """Re-verification 13: an admin pauses only the job; an editor may not resume it."""
    editor = await _as_new_user(admin, "ed3@example.org", ["editor"])
    body = rss(robots_policy="override", override_reason="Owner agreed in writing")
    made = (await admin.post(_api("/sources"), json=body)).json()
    sid, jid = made["id"], made["job"]["id"]
    assert (await admin.patch(_api(f"/capture-jobs/{jid}"),
                              json={"enabled": False})).status_code == 200  # fmt: skip
    on = {"enabled": True}
    assert (await editor.patch(_api(f"/capture-jobs/{jid}"), json=on)).status_code == 403
    nested = await editor.patch(_api(f"/sources/{sid}"), json={"job": on})
    assert nested.status_code == 403
    assert (await editor.patch(_api(f"/capture-jobs/{jid}"),
                               json={"rate_limit_per_minute": 5})).status_code == 200  # fmt: skip
    assert (await admin.patch(_api(f"/capture-jobs/{jid}"), json=on)).status_code == 200
    rows = (await admin.get(_api("/admin/audit"),
                            params={"action": "source.robots_override"})).json()  # fmt: skip
    assert rows["total"] == 2  # the create and the resume
    made = (await admin.post(_api("/sources"), json=rss(url=""))).json()
    assert made.get("url") is None  # an empty URL is no URL (re-verification 14)
    assert rows["items"][0]["before"]["job_enabled"] is False  # the resume row names the job
    assert rows["items"][0]["after"]["job_enabled"] is True


async def test_the_real_save_resolver_refuses_private_literals(
    admin: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The resolver used in production, exercised without the network: IP literals need no
    lookup, so they answer whatever the name servers do (re-verification 2, third note)."""
    monkeypatch.setattr(services, "RESOLVER", None)
    for url, status in (("http://127.0.0.1/rss", 422), ("http://[::1]/rss", 422),
                        ("http://169.254.169.254/rss", 422),
                        ("https://93.184.215.14/rss", 201)):  # fmt: skip
        got = await admin.post(_api("/sources"), json=rss(config={"feed_url": url}))
        assert got.status_code == status, f"{url}: {got.text}"
