"""Integration: PDF outputs (M8.1; acceptance 1 apart from the real Gotenberg, checked on the
QA stack; the M7 reviews' rules for M8)."""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.core.internal import InternalClient
from regwatch.outputs import pdf, tasks
from regwatch.outputs.models import OutputJob
from regwatch.reports import render
from tests.integration.test_admin import _api, _as_new_user, admin
from tests.integration.test_auth import _login, clear_limits, db_url
from tests.integration.test_capture_runs import db

pytestmark = pytest.mark.integration
__all__ = ["admin", "clear_limits", "db", "db_url"]  # shared fixtures

PDF = b"%PDF-1.7\n1 0 obj << /Type /Pages /Count 2 >>\n<< /Type /Page >>\n<< /Type /Page >>\n%%EOF"
LAYOUT = {"name": "Mine", "layout": {"root": {"props": {"title": "Mine"}}, "content": [
    {"type": "Heading", "props": {"id": "h", "text": "Changes"}}]}}  # fmt: skip


class Gotenberg:
    def __init__(self) -> None:
        self.answer: tuple[int, bytes] = (200, PDF)
        self.seen: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        request.read()  # the multipart body is a stream: read it once, here
        self.seen.append(request)
        status, body = self.answer
        return httpx.Response(status, stream=httpx.ByteStream(body))  # unread, as sent


@pytest.fixture
def gotenberg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Gotenberg]:
    from regwatch.core.settings import get_settings

    monkeypatch.setenv("REGWATCH_OBJECT_STORE_PATH", str(tmp_path))
    get_settings.cache_clear()
    fake = Gotenberg()
    monkeypatch.setattr(pdf, "client_factory", lambda max_bytes: InternalClient(
        "http://pdf:3000", transport=httpx.MockTransport(fake), max_answer=max_bytes))  # fmt: skip
    queued: list[tuple[str, uuid.UUID]] = []

    async def enqueue(name: str, job_id: uuid.UUID) -> None:
        queued.append((name, job_id))

    monkeypatch.setattr(tasks, "enqueue", enqueue)
    render.renders.clear()
    yield fake


async def _pdf(client: httpx.AsyncClient, source: dict[str, Any], **extra: Any) -> httpx.Response:
    return await client.post(_api("/outputs"), json={"kind": "pdf", "source": source, **extra})


async def test_a_pdf_is_rendered_and_downloaded_by_its_owner(
    admin: httpx.AsyncClient, db: AsyncSession, gotenberg: Gotenberg
) -> None:
    ana = await _as_new_user(admin, "aya@example.org", ["analyst"])
    bob = await _as_new_user(admin, "ben@example.org", ["analyst"])
    lid = (await ana.post(_api("/reports/layouts"), json=LAYOUT)).json()["id"]
    made = await _pdf(ana, {"report_layout_id": lid})
    assert made.status_code == 202, made.text
    job = made.json()
    assert (job["status"], job["artifact_available"]) == ("queued", False)
    assert await tasks.run_pdf(db, uuid.UUID(job["id"])) == "sent"
    sent = gotenberg.seen[0]
    assert sent.url.path == "/forms/chromium/convert/html"
    assert b'filename="index.html"' in sent.content and b"<script" not in sent.content
    shown = (await ana.get(_api(f"/outputs/{job['id']}"))).json()
    assert (shown["status"], shown["artifact_available"], shown["artifact_bytes"]) == (
        "sent", True, len(PDF))  # fmt: skip

    redirect = await ana.get(_api(f"/outputs/{job['id']}/artifact"))
    assert redirect.status_code == 302
    link = redirect.headers["location"]
    parts = urlsplit(link)
    got = await ana.get(parts.path + "?" + parts.query)
    assert got.status_code == 200 and got.content == PDF
    assert got.headers["content-type"] == "application/pdf"
    assert got.headers["content-disposition"].startswith("attachment;")
    assert re.search(
        r'filename="regwatch-mine-\d{4}-\d\d-\d\d\.pdf"', got.headers["content-disposition"]
    )  # named, not an id (U-M8-1)
    assert shown["source_summary"] == "report Mine"
    forged = await ana.get(parts.path + "?" + parts.query.replace("sig=", "sig=0"))
    assert forged.status_code == 403
    expired = await ana.get(parts.path + "?exp=1&sig=" + parts.query.split("sig=")[1])
    assert expired.status_code == 403
    assert (await bob.get(parts.path + "?" + parts.query)).status_code == 404  # not his
    assert (await bob.get(_api(f"/outputs/{job['id']}"))).status_code == 404
    mine = (await bob.get(_api("/outputs"))).json()
    assert mine["total"] == 0
    assert (await bob.get(_api("/outputs"), params={"scope": "all"})).status_code == 403
    every = (await admin.get(_api("/outputs"), params={"scope": "all"})).json()
    assert job["id"] in [j["id"] for j in every["items"]]  # outputs.read_all
    rows = (await admin.get(_api("/admin/audit"), params={"entity_type": "output_job"})).json()
    assert [r["action"] for r in rows["items"]][:2] == ["output.sent", "output.create"]
    await ana.aclose()
    await bob.aclose()


async def test_who_may_print_what(admin: httpx.AsyncClient, db: AsyncSession,
                                  gotenberg: Gotenberg) -> None:  # fmt: skip
    vic = await _as_new_user(admin, "vin@example.org", ["viewer"])  # reports.print, outputs.pdf
    stock = await _pdf(vic, {"report_template_key": "source-health"})
    assert stock.status_code == 202, stock.text
    assert await tasks.run_pdf(db, uuid.UUID(stock.json()["id"])) == "sent"
    shared = (await admin.post(_api("/reports/layouts"), json={**LAYOUT, "shared": True})).json()
    assert (await _pdf(vic, {"report_layout_id": shared["id"]})).status_code == 403  # not own
    needs = await _pdf(admin, {"report_template_key": "jurisdiction-profile"})
    assert needs.status_code == 422 and "Jurisdiction is needed" in needs.text
    ok = await _pdf(admin, {"report_template_key": "jurisdiction-profile"},
                    params={"jurisdiction": "DE"})  # fmt: skip
    assert ok.status_code == 202
    for bad in ({"kind": "email", "source": {"report_template_key": "source-health"}},
                {"kind": "pdf", "source": {}},
                {"kind": "pdf", "source": {"report_template_key": "source-health",
                                           "report_layout_id": shared["id"]}}):  # fmt: skip
        assert (await admin.post(_api("/outputs"), json=bad)).status_code == 422, bad
    await vic.aclose()


async def test_a_run_uses_the_requesters_current_rights(
    admin: httpx.AsyncClient, db: AsyncSession, gotenberg: Gotenberg
) -> None:
    ana = await _as_new_user(admin, "ari@example.org", ["analyst"])
    aid = (await ana.get(_api("/auth/me"))).json()["id"]
    shared = (await admin.post(_api("/reports/layouts"), json={**LAYOUT, "shared": True})).json()
    first = (await _pdf(ana, {"report_layout_id": shared["id"]})).json()
    second = (await _pdf(ana, {"report_layout_id": shared["id"]})).json()
    await admin.patch(_api(f"/reports/layouts/{shared['id']}"), json={"shared": False})
    assert await tasks.run_pdf(db, uuid.UUID(first["id"])) == "failed"  # no longer visible
    assert (await ana.get(_api(f"/outputs/{first['id']}"))).json()["error_class"] == "not-found"
    await admin.patch(_api(f"/admin/users/{aid}"), json={"status": "disabled"})
    assert await tasks.run_pdf(db, uuid.UUID(second["id"])) == "failed"
    shown = (await admin.get(_api(f"/outputs/{second['id']}"))).json()
    assert shown["error_class"] == "requester-inactive"
    await ana.aclose()


async def test_pdf_failures_are_reported_and_can_be_retried(
    admin: httpx.AsyncClient, db: AsyncSession, gotenberg: Gotenberg
) -> None:
    lid = (await admin.post(_api("/reports/layouts"), json=LAYOUT)).json()["id"]
    job = (await _pdf(admin, {"report_layout_id": lid})).json()
    gotenberg.answer = (500, b"boom")
    assert await tasks.run_pdf(db, uuid.UUID(job["id"])) == "failed"
    shown = (await admin.get(_api(f"/outputs/{job['id']}"))).json()
    assert shown["error_class"] == "sidecar-status" and "boom" not in (shown["error_message"] or "")
    gotenberg.answer = (200, b"<html>not a pdf</html>")
    assert (await admin.post(_api(f"/outputs/{job['id']}/retry"))).status_code == 202
    assert await tasks.run_pdf(db, uuid.UUID(job["id"])) == "failed"
    assert (await admin.get(_api(f"/outputs/{job['id']}"))).json()["error_class"] == "pdf-malformed"
    gotenberg.answer = (200, PDF)
    assert (await admin.post(_api(f"/outputs/{job['id']}/retry"))).status_code == 202
    assert await tasks.run_pdf(db, uuid.UUID(job["id"])) == "sent"
    final = (await admin.get(_api(f"/outputs/{job['id']}"))).json()
    assert (final["status"], final["attempts"]) == ("sent", 3)
    assert (await admin.post(_api(f"/outputs/{job['id']}/retry"))).status_code == 409
    assert await tasks.run_pdf(db, uuid.UUID(job["id"])) == "skipped"  # not queued


async def test_outputs_are_limited_per_hour(admin: httpx.AsyncClient,
                                            gotenberg: Gotenberg) -> None:  # fmt: skip
    limit = await admin.put(_api("/admin/settings/outputs.rate_per_hour_per_user"),
                              json={"value": 1})  # fmt: skip
    assert limit.status_code == 200, limit.text
    source = {"report_template_key": "source-health"}
    assert (await _pdf(admin, source)).status_code == 202
    limited = await _pdf(admin, source)
    assert limited.status_code == 429 and limited.headers["Retry-After"]


def test_pages_are_counted_without_the_page_tree() -> None:
    assert pdf.page_count(PDF) == 2


async def test_a_cancel_during_the_render_wins(
    admin: httpx.AsyncClient, db: AsyncSession, gotenberg: Gotenberg,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    """M8.1 review finding 2: the render stores nothing once its job was cancelled."""
    job = (await _pdf(admin, {"report_template_key": "source-health"})).json()
    real = pdf.render

    async def slow(html: str, title: str, max_bytes: int) -> tuple[bytes, int]:
        assert (await admin.delete(_api(f"/outputs/{job['id']}"))).status_code == 409  # busy
        await db.execute(update(OutputJob).where(OutputJob.id == uuid.UUID(job["id"]))
                         .values(status="cancelled"))  # fmt: skip
        await db.commit()  # as a cancel by the owner would, between render and store
        return await real(html, title, max_bytes)

    monkeypatch.setattr(pdf, "render", slow)
    assert await tasks.run_pdf(db, uuid.UUID(job["id"])) == "cancelled"
    shown = (await admin.get(_api(f"/outputs/{job['id']}"))).json()
    assert (shown["status"], shown["artifact_available"]) == ("cancelled", False)


async def test_an_interrupted_render_is_swept_and_attempts_are_capped(
    admin: httpx.AsyncClient, db: AsyncSession, gotenberg: Gotenberg
) -> None:
    """M8.1 review findings 1 and 3."""
    from regwatch.outputs import services

    job = (await _pdf(admin, {"report_template_key": "source-health"})).json()
    jid = uuid.UUID(job["id"])
    await db.execute(
        update(OutputJob).where(OutputJob.id == jid).values(status="rendering", attempts=1)
    )  # as a render that then crashed
    await db.commit()
    assert await services.sweep_stale(db) == 0  # not stale yet
    later = datetime.now(UTC) + timedelta(minutes=10)
    assert await services.sweep_stale(db, now=later) == 1
    shown = (await admin.get(_api(f"/outputs/{job['id']}"))).json()
    assert (shown["status"], shown["error_class"]) == ("failed", "interrupted")
    gotenberg.answer = (500, b"down")
    for _ in range(2):  # attempts 2 and 3
        assert (await admin.post(_api(f"/outputs/{job['id']}/retry"))).status_code == 202
        assert await tasks.run_pdf(db, jid) == "failed"
    capped = await admin.post(_api(f"/outputs/{job['id']}/retry"))
    assert capped.status_code == 409 and "tried 3 times" in capped.text


class Smtp:
    """Stands in for the mail server: records messages, or fails."""

    def __init__(self) -> None:
        self.sent: list[Any] = []
        self.envelope: list[str] = []
        self.down = False
        self.fail_after: int | None = None  # fail once this many messages went out

    def __call__(self, messages: list[tuple[Any, str]]) -> None:
        import smtplib

        if self.down or (self.fail_after is not None and len(self.sent) >= self.fail_after):
            raise smtplib.SMTPServerDisconnected("gone")
        for message, to in messages:
            self.sent.append(message)
            self.envelope.append(to)


@pytest.fixture
def smtp(monkeypatch: pytest.MonkeyPatch, gotenberg: Gotenberg) -> Smtp:
    from regwatch.outputs import mail

    fake = Smtp()
    monkeypatch.setattr(mail, "_send_sync", fake)
    return fake


async def _domains(admin: httpx.AsyncClient, *domains: str) -> None:
    got = await admin.put(_api("/admin/settings/outputs.allowed_recipient_domains"),
                          json={"value": list(domains)})  # fmt: skip
    assert got.status_code == 200, got.text


def _email(to: list[str], **extra: Any) -> dict[str, Any]:
    return {"kind": "email", "source": {"report_template_key": "source-health"},
            "destination": {"emails": to, **extra}}  # fmt: skip


async def test_a_stock_report_is_emailed_to_allowed_addresses(
    admin: httpx.AsyncClient, db: AsyncSession, smtp: Smtp
) -> None:
    """Acceptance 2: two allowed recipients get the PDF, audited; others refused clearly."""
    off = await admin.post(_api("/outputs"), json=_email(["ana@example.org"]))
    assert off.status_code == 422 and "email is turned off" in off.text
    await _domains(admin, "example.org")
    outside = await admin.post(_api("/outputs"), json=_email(["ana@example.org", "x@evil.com"]))
    assert outside.status_code == 422 and "x@evil.com is not on an allowed domain" in outside.text
    injected = _email(["ana@example.org"], subject="Hi\r\nBcc: x@evil.com")
    header = await admin.post(_api("/outputs"), json=injected)
    assert header.status_code == 422
    two = _email(["ana@example.org", "bo@legal.example.org"], subject="Sources",
                 message="For you.")  # fmt: skip
    made = await admin.post(_api("/outputs"), json=two)
    assert made.status_code == 202, made.text
    job = made.json()
    assert job["destination_summary"] == "email to 2 recipients"
    assert await tasks.run_email(db, uuid.UUID(job["id"])) == "sent"
    assert sorted(m["To"] for m in smtp.sent) == ["ana@example.org", "bo@legal.example.org"]
    attached = next(iter(smtp.sent[0].iter_attachments()))
    assert attached.get_content() == PDF and smtp.sent[0]["Subject"] == "Sources"
    rows = (await admin.get(_api("/admin/audit"), params={"entity_type": "output_job"})).json()
    sent = next(r for r in rows["items"] if r["action"] == "output.sent")
    assert len(sent["after"]["recipients"]) == 2  # hashed
    assert sent["after"]["recipient_domains"] == ["example.org", "legal.example.org"]
    assert "ana@" not in str(sent["after"]) and "bo@" not in str(sent["after"])  # no addresses
    viewer = await _as_new_user(admin, "vee@example.org", ["viewer"])  # no outputs.email
    assert (await viewer.post(_api("/outputs"), json=_email(["ana@example.org"]))
            ).status_code == 403  # fmt: skip
    await viewer.aclose()


async def test_a_failed_delivery_is_retried_with_backoff(
    admin: httpx.AsyncClient, db: AsyncSession, smtp: Smtp, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Acceptance 5: three attempts with growing waits, then failed with its error class."""
    waits: list[float] = []

    async def enqueue(name: str, job_id: uuid.UUID, countdown: float = 0) -> None:
        waits.append(countdown)

    monkeypatch.setattr(tasks, "enqueue", enqueue)
    await _domains(admin, "example.org")
    job = (await admin.post(_api("/outputs"), json=_email(["ana@example.org"]))).json()
    smtp.down = True
    assert await tasks.run_email(db, uuid.UUID(job["id"])) == "retrying"
    assert await tasks.run_email(db, uuid.UUID(job["id"])) == "retrying"
    assert await tasks.run_email(db, uuid.UUID(job["id"])) == "failed"
    assert waits[-2:] == [30, 120]
    shown = (await admin.get(_api(f"/outputs/{job['id']}"))).json()
    assert (shown["status"], shown["error_class"], shown["attempts"]) == (
        "failed", "smtp-unavailable", 3)  # fmt: skip


async def test_recipients_are_checked_again_when_sent(
    admin: httpx.AsyncClient, db: AsyncSession, smtp: Smtp
) -> None:
    await _domains(admin, "example.org")
    job = (await admin.post(_api("/outputs"), json=_email(["ana@example.org"]))).json()
    await _domains(admin, "other.org")  # the admin narrowed the list meanwhile
    assert await tasks.run_email(db, uuid.UUID(job["id"])) == "failed"
    shown = (await admin.get(_api(f"/outputs/{job['id']}"))).json()
    assert shown["error_class"] == "recipient-refused" and smtp.sent == []


async def test_a_partial_failure_resends_only_to_the_rest(
    admin: httpx.AsyncClient, db: AsyncSession, smtp: Smtp, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M8.2 review Low: recipients reached before a failure are not sent the report again."""

    async def enqueue(name: str, job_id: uuid.UUID, countdown: float = 0) -> None:
        return None

    monkeypatch.setattr(tasks, "enqueue", enqueue)
    await _domains(admin, "example.org")
    to = ["a@example.org", "b@example.org", "c@example.org"]
    job = (await admin.post(_api("/outputs"), json=_email(to))).json()
    smtp.fail_after = 1
    assert await tasks.run_email(db, uuid.UUID(job["id"])) == "retrying"
    smtp.fail_after = None
    assert await tasks.run_email(db, uuid.UUID(job["id"])) == "sent"
    assert smtp.envelope == to  # each once, in order


async def test_the_bypass_addresses_are_refused(admin: httpx.AsyncClient, smtp: Smtp) -> None:
    """M8.2 review High: each passed the old check but would have gone to evil.com."""
    await _domains(admin, "example.org")
    bypasses = (
        "attacker@evil.com x@example.org",
        "a@evil.com;x@example.org",
        "<a@evil.com> x@example.org",
        "attacker@evil.com (c) x@example.org",
    )
    for bypass in bypasses:
        got = await admin.post(_api("/outputs"), json=_email([bypass]))
        assert got.status_code == 422 and "single plain email address" in got.text, bypass
    assert smtp.sent == []


WEEKLY = {"cron": "0 7 * * 1", "timezone": "Europe/Berlin"}


async def test_a_weekly_schedule_runs_each_monday_at_seven_local(
    admin: httpx.AsyncClient, db: AsyncSession, gotenberg: Gotenberg
) -> None:
    """Acceptance 4, with a frozen clock: one run each Monday 07:00 in the user's time zone."""
    from zoneinfo import ZoneInfo

    made = await _pdf(admin, {"report_template_key": "source-health"}, schedule=WEEKLY)
    assert made.status_code == 202, made.text
    sid = made.json()["id"]
    first = datetime.fromisoformat(made.json()["next_run_at"]).astimezone(ZoneInfo("Europe/Berlin"))
    assert (first.weekday(), first.hour, first.minute) == (0, 7, 0)
    assert made.json()["scheduled_cron"] == "0 7 * * 1"
    just_before = first.astimezone(UTC) - timedelta(minutes=1)
    assert await tasks.tick_once(db, now=just_before) == 0
    assert await tasks.tick_once(db, now=first.astimezone(UTC) + timedelta(seconds=30)) == 1
    assert await tasks.tick_once(db, now=first.astimezone(UTC) + timedelta(minutes=5)) == 0  # once
    shown = (await admin.get(_api(f"/outputs/{sid}"))).json()
    nxt = datetime.fromisoformat(shown["next_run_at"]).astimezone(ZoneInfo("Europe/Berlin"))
    assert nxt - first == timedelta(days=7) and (nxt.hour, nxt.minute) == (7, 0)
    children = [j for j in (await admin.get(_api("/outputs"))).json()["items"] if j["id"] != sid]
    assert len(children) == 1 and children[0]["status"] == "queued"
    listed = (await admin.get(_api("/outputs?scheduled=true"))).json()["items"]
    assert [j["id"] for j in listed] == [sid]  # the Schedules tab (8.6)
    runs = (await admin.get(_api("/outputs?scheduled=false&kind=pdf&status=queued"))).json()
    assert [j["id"] for j in runs["items"]] == [children[0]["id"]]
    assert await tasks.run_pdf(db, uuid.UUID(sid)) == "skipped"  # the schedule never renders
    assert await tasks.run_pdf(db, uuid.UUID(children[0]["id"])) == "sent"
    assert (await admin.delete(_api(f"/outputs/{sid}"))).status_code == 204
    assert await tasks.tick_once(db, now=nxt.astimezone(UTC) + timedelta(minutes=1)) == 0


@pytest.mark.parametrize(
    ("schedule", "message"),
    [
        ({"cron": "*/5 * * * *", "timezone": "UTC"}, "at least an hour"),
        ({"cron": "0 7 * *", "timezone": "UTC"}, "five cron fields"),
        ({"cron": "0 7 30 2 *", "timezone": "UTC"}, "never runs"),
        ({"cron": "0 7 * * 1", "timezone": "Mars/Olympus"}, "IANA time zone"),
    ],
)
async def test_bad_schedules_are_refused(
    admin: httpx.AsyncClient, gotenberg: Gotenberg, schedule: dict[str, str], message: str
) -> None:
    got = await _pdf(admin, {"report_template_key": "source-health"}, schedule=schedule)
    assert got.status_code == 422 and message in got.text, got.text


async def test_schedules_are_capped_need_their_permission_and_pause(
    admin: httpx.AsyncClient, db: AsyncSession, gotenberg: Gotenberg,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    from regwatch.outputs import schedules

    vic = await _as_new_user(admin, "vim@example.org", ["viewer"])  # no outputs.schedule
    assert (await _pdf(vic, {"report_template_key": "source-health"}, schedule=WEEKLY)
            ).status_code == 403  # fmt: skip
    await vic.aclose()
    monkeypatch.setattr(schedules, "MAX_SCHEDULES", 1)
    ana = await _as_new_user(admin, "amo@example.org", ["analyst"])
    aid = (await ana.get(_api("/auth/me"))).json()["id"]
    sid = (await _pdf(ana, {"report_template_key": "source-health"}, schedule=WEEKLY)).json()["id"]
    capped = await _pdf(ana, {"report_template_key": "source-health"}, schedule=WEEKLY)
    assert capped.status_code == 409 and "At most 1 schedules" in capped.text
    await admin.patch(_api(f"/admin/users/{aid}"), json={"status": "disabled"})
    later = datetime.now(UTC) + timedelta(days=8)
    assert await tasks.tick_once(db, now=later) == 0
    shown = (await admin.get(_api(f"/outputs/{sid}"))).json()
    assert (shown["status"], shown["error_class"], shown["next_run_at"]) == (
        "failed",
        "owner-inactive",
        None,
    )  # paused, audited
    await admin.patch(_api(f"/admin/users/{aid}"), json={"status": "active"})
    # Disabling ended her sessions: she signs in again to resume it.
    assert (await _login(ana, "amo@example.org", "a long new passphrase")).status_code == 200
    # Resuming counts against the cap, too (M8.3 review): with another schedule active, no.
    other = (await _pdf(ana, {"report_template_key": "source-health"}, schedule=WEEKLY)).json()
    refused = await ana.post(_api(f"/outputs/{sid}/retry"))
    assert refused.status_code == 409 and "At most 1 schedules" in refused.text
    assert (await ana.delete(_api(f"/outputs/{other['id']}"))).status_code == 204
    resumed = await ana.post(_api(f"/outputs/{sid}/retry"))
    assert resumed.status_code == 202 and resumed.json()["status"] == "queued"
    assert resumed.json()["next_run_at"] is not None
    await ana.aclose()


async def test_one_tick_keeps_to_the_hourly_limit(
    admin: httpx.AsyncClient, db: AsyncSession, gotenberg: Gotenberg
) -> None:
    """Schedules due together each count the runs the same tick has started (M8.3 review)."""
    source = {"report_template_key": "source-health"}
    ids = [(await _pdf(admin, source, schedule=WEEKLY)).json()["id"] for _ in range(2)]
    limit = await admin.put(
        _api("/admin/settings/outputs.rate_per_hour_per_user"), json={"value": 3}
    )  # the two schedules, and room for one run
    assert limit.status_code == 200, limit.text
    assert await tasks.tick_once(db, now=datetime.now(UTC) + timedelta(days=8)) == 1
    runs = [j for j in (await admin.get(_api("/outputs"))).json()["items"] if j["id"] not in ids]
    assert len(runs) == 1  # the other run was skipped (audited), its schedule still active
    shown = [(await admin.get(_api(f"/outputs/{i}"))).json()["status"] for i in ids]
    assert shown == ["queued", "queued"]


async def test_a_run_that_cannot_succeed_pauses_its_schedule(
    admin: httpx.AsyncClient, db: AsyncSession, smtp: Smtp
) -> None:
    """A recipient's domain removed: the run fails, and its schedule pauses (M8.3 review)."""
    await _domains(admin, "example.org")
    made = await admin.post(_api("/outputs"), json={**_email(["kim@example.org"]),
                                                    "schedule": WEEKLY})  # fmt: skip
    assert made.status_code == 202, made.text
    sid = made.json()["id"]
    assert await tasks.tick_once(db, now=datetime.now(UTC) + timedelta(days=8)) == 1
    run = next(j for j in (await admin.get(_api("/outputs"))).json()["items"] if j["id"] != sid)
    await _domains(admin, "example.com")
    assert await tasks.run_email(db, uuid.UUID(run["id"])) == "failed"
    assert smtp.sent == []
    shown = (await admin.get(_api(f"/outputs/{sid}"))).json()
    assert (shown["status"], shown["error_class"], shown["next_run_at"]) == (
        "failed", "recipient-refused", None)  # fmt: skip


async def test_a_printed_layout_can_still_be_deleted(
    admin: httpx.AsyncClient, db: AsyncSession, gotenberg: Gotenberg
) -> None:
    """Its outputs keep their history; a schedule of it stops (FK on output_job)."""
    lid = (await admin.post(_api("/reports/layouts"), json=LAYOUT)).json()["id"]
    done = (await _pdf(admin, {"report_layout_id": lid})).json()["id"]
    assert await tasks.run_pdf(db, uuid.UUID(done)) == "sent"
    sid = (await _pdf(admin, {"report_layout_id": lid}, schedule=WEEKLY)).json()["id"]
    gone = await admin.delete(_api(f"/reports/layouts/{lid}"))
    assert gone.status_code == 204, gone.text
    kept = (await admin.get(_api(f"/outputs/{done}"))).json()
    assert kept["status"] == "sent" and kept["artifact_available"]
    assert kept["source_summary"] == "Mine (deleted layout)"  # its name kept (U-M8-1)
    stopped = (await admin.get(_api(f"/outputs/{sid}"))).json()
    assert (stopped["status"], stopped["error_class"]) == ("cancelled", "source-deleted")
    from regwatch.core.models import AuditLog

    me = (await admin.get(_api("/auth/me"))).json()["id"]
    row = await db.scalar(select(AuditLog).where(AuditLog.action == "output.cancel",
                                                 AuditLog.entity_id == sid))  # fmt: skip
    assert row is not None and str(row.actor_user_id) == me  # who deleted the layout
    assert row.after["reason"] == "source-deleted" and row.after["owner"] == me


async def test_files_older_than_the_retention_are_removed_and_jobs_kept(
    admin: httpx.AsyncClient, db: AsyncSession, gotenberg: Gotenberg, tmp_path: Path
) -> None:
    """M8.7: a file past ``outputs.artifact_retention_days`` goes; the job stays in history."""
    source = {"report_template_key": "source-health"}
    old, new = [(await _pdf(admin, source)).json()["id"] for _ in range(2)]
    for job in (old, new):
        assert await tasks.run_pdf(db, uuid.UUID(job)) == "sent"
    days = await admin.put(_api("/admin/settings/outputs.artifact_retention_days"),
                           json={"value": 30})  # fmt: skip
    assert days.status_code == 200, days.text
    await db.execute(update(OutputJob).where(OutputJob.id == uuid.UUID(old))
                     .values(finished_at=datetime.now(UTC) - timedelta(days=31)))  # fmt: skip
    await db.commit()
    assert (tmp_path / "outputs" / f"{old}.pdf").exists()
    await tasks.tick_once(db)
    assert not (tmp_path / "outputs" / f"{old}.pdf").exists()
    gone = (await admin.get(_api(f"/outputs/{old}"))).json()
    assert (gone["status"], gone["artifact_available"]) == ("sent", False)
    assert (await admin.get(_api(f"/outputs/{old}/artifact"))).status_code == 404
    kept = (await admin.get(_api(f"/outputs/{new}"))).json()
    assert kept["artifact_available"] and (tmp_path / "outputs" / f"{new}.pdf").exists()


async def test_a_failing_sweep_does_not_stop_schedules(
    admin: httpx.AsyncClient, db: AsyncSession, gotenberg: Gotenberg,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    """M8.7 review: each step of the tick stands alone."""
    from regwatch.outputs import services

    async def broken(db: AsyncSession, now: datetime | None = None) -> int:
        raise OSError("the store is not writable")

    monkeypatch.setattr(services, "sweep_retention", broken)
    monkeypatch.setattr(services, "sweep_stale", broken)
    await _pdf(admin, {"report_template_key": "source-health"}, schedule=WEEKLY)
    assert await tasks.tick_once(db, now=datetime.now(UTC) + timedelta(days=8)) == 1


async def test_an_output_no_worker_took_is_handed_over_again_then_failed(
    admin: httpx.AsyncClient, db: AsyncSession, gotenberg: Gotenberg,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    """Use testing U-M8-3: a job stayed Queued for hours when its message never reached a
    worker. The tick hands it over again, and after an hour fails it with a clear message."""
    from regwatch.outputs import services

    sent: list[tuple[str, uuid.UUID]] = []

    async def enqueue(name: str, job_id: uuid.UUID, countdown: float = 0) -> None:
        sent.append((name, job_id))

    job = (await _pdf(admin, {"report_template_key": "source-health"})).json()["id"]
    sid = (await _pdf(admin, {"report_template_key": "source-health"}, schedule=WEEKLY)).json()[
        "id"
    ]
    monkeypatch.setattr(tasks, "enqueue", enqueue)  # from here on: the tick's hand-overs
    monkeypatch.setattr(services, "UNSENT_AFTER", timedelta(0))
    await tasks.tick_once(db)
    assert sent == [("outputs.render_pdf", uuid.UUID(job))]  # not the schedule itself
    assert (await admin.get(_api(f"/outputs/{job}"))).json()["status"] == "queued"
    monkeypatch.setattr(services, "GIVE_UP_AFTER", timedelta(0))
    await tasks.tick_once(db)
    shown = (await admin.get(_api(f"/outputs/{job}"))).json()
    assert (shown["status"], shown["error_class"]) == ("failed", "queue-unavailable")
    assert "try again" in shown["error_message"]
    assert (await admin.get(_api(f"/outputs/{sid}"))).json()["status"] == "queued"
