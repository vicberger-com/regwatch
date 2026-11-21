"""Integration: network printing (M8.5b; BL-15, CP-33; M8 acceptance 3 against a mock IPP
printer; the real printer is the QA stack's ippeveprinter)."""

from __future__ import annotations

import uuid

import httpx
import ippx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.core.models import AuditLog
from regwatch.outputs import ipp, tasks
from tests.integration.test_admin import _api, _as_new_user, admin
from tests.integration.test_auth import clear_limits, db_url
from tests.integration.test_capture_runs import db
from tests.integration.test_outputs import Gotenberg, gotenberg
from tests.unit.test_outputs_ipp import MockPrinter

pytestmark = pytest.mark.integration
__all__ = ["admin", "clear_limits", "db", "db_url", "gotenberg"]

URL = "ipps://printer.example.internal/ipp/print"


@pytest.fixture
def printer(monkeypatch: pytest.MonkeyPatch) -> MockPrinter:
    fake = MockPrinter()
    monkeypatch.setattr(ipp, "transport_factory", lambda verify: httpx.MockTransport(fake))

    async def lookup(host: str) -> set[str]:
        return {"printer.example.internal": {"10.20.0.7"}}.get(host, set())

    monkeypatch.setattr(ipp, "lookup", lookup)
    return fake


async def _flag(admin: httpx.AsyncClient, on: bool) -> None:
    got = await admin.patch(_api("/admin/feature-flags/outputs.server_print"),
                            json={"enabled": on})  # fmt: skip
    assert got.status_code == 200, got.text


async def _printer(admin: httpx.AsyncClient, **over: object) -> dict[str, object]:
    made = await admin.post(_api("/admin/printers"),
                            json={"name": f"Floor 2 {uuid.uuid4().hex[:6]}", "ipp_url": URL,
                                  **over})  # fmt: skip
    assert made.status_code == 201, made.text
    return dict(made.json())


async def test_printers_are_checked_when_saved_and_audited(
    admin: httpx.AsyncClient, db: AsyncSession, printer: MockPrinter
) -> None:
    made = await _printer(admin, tls_sha256="AB:" * 31 + "AB")
    assert made["ipp_url"] == "ipps://printer.example.internal:631/ipp/print"
    assert made["tls_sha256"] == "ab" * 32 and made["enabled"] is True
    for url, message in [("ipp://printer.example.internal/", "clear-text"),
                         ("ipps://db/", "own services"),
                         ("ipps://10.0.0.1@evil.example/", "no user name"),
                         ("ipps://printer.elsewhere.example/", "does not resolve")]:  # fmt: skip
        bad = await admin.post(_api("/admin/printers"), json={"name": "Bad", "ipp_url": url})
        assert bad.status_code == 422 and message in bad.text, (url, bad.text)
    twice = await admin.post(_api("/admin/printers"), json={"name": made["name"], "ipp_url": URL})
    assert twice.status_code == 422 and "another printer" in twice.text
    changed = await admin.patch(_api(f"/admin/printers/{made['id']}"), json={"enabled": False})
    assert changed.status_code == 200 and changed.json()["enabled"] is False
    actions = (await db.scalars(select(AuditLog.action).where(
        AuditLog.entity_id == str(made["id"])))).all()  # fmt: skip
    assert {"printer.create", "printer.update"} <= set(actions)
    assert (await admin.delete(_api(f"/admin/printers/{made['id']}"))).status_code == 204
    viewer = await _as_new_user(admin, "pv@example.org", ["viewer"])
    assert (await viewer.get(_api("/admin/printers"))).status_code == 403
    await viewer.aclose()


async def test_a_report_reaches_the_printer_and_shows_sent(
    admin: httpx.AsyncClient, db: AsyncSession, gotenberg: Gotenberg, printer: MockPrinter
) -> None:
    """Acceptance 3 with a mock printer: with the flag on, the job reaches the printer's queue
    and the output shows sent, its printer job id kept."""
    pid = str((await _printer(admin))["id"])
    request = {"kind": "print", "source": {"report_template_key": "source-health"},
               "destination": {"printer_id": pid, "copies": 2}}  # fmt: skip
    off = await admin.post(_api("/outputs"), json=request)
    assert off.status_code == 409 and "off" in off.text  # the flag is off by default
    assert (await admin.get(_api("/printers"))).status_code == 404
    await _flag(admin, True)
    assert [p["id"] for p in (await admin.get(_api("/printers"))).json()] == [pid]
    made = await admin.post(_api("/outputs"), json=request)
    assert made.status_code == 202, made.text
    job = made.json()["id"]
    assert made.json()["destination_summary"] == "printer, 2 copies"
    assert await tasks.run_print(db, uuid.UUID(job)) == "sent"
    assert printer.requests[0].code == ippx.Operation.PRINT_JOB
    assert printer.requests[0].data.startswith(b"%PDF-")
    shown = (await admin.get(_api(f"/outputs/{job}"))).json()
    assert shown["status"] == "sent" and shown["artifact_available"]
    row = await db.scalar(select(AuditLog).where(AuditLog.action == "output.sent",
                                                 AuditLog.entity_id == job))  # fmt: skip
    assert row is not None and row.after["ipp_job_id"] == 42


async def test_print_rights_and_the_printer_are_checked_again_at_run_time(
    admin: httpx.AsyncClient, db: AsyncSession, gotenberg: Gotenberg, printer: MockPrinter
) -> None:
    pid = str((await _printer(admin))["id"])
    await _flag(admin, True)
    analyst = await _as_new_user(admin, "pa@example.org", ["analyst"])  # no outputs.print
    refused = await analyst.post(_api("/outputs"), json={
        "kind": "print", "source": {"report_template_key": "source-health"},
        "destination": {"printer_id": pid}})  # fmt: skip
    assert refused.status_code == 403
    await analyst.aclose()
    job = (await admin.post(_api("/outputs"), json={
        "kind": "print", "source": {"report_template_key": "source-health"},
        "destination": {"printer_id": pid}})).json()["id"]  # fmt: skip
    await admin.patch(_api(f"/admin/printers/{pid}"), json={"enabled": False})
    assert await tasks.run_print(db, uuid.UUID(job)) == "failed"
    shown = (await admin.get(_api(f"/outputs/{job}"))).json()
    assert shown["error_class"] == "printer-removed" and printer.requests == []


async def test_an_unreachable_printer_is_retried_then_fails(
    admin: httpx.AsyncClient, db: AsyncSession, gotenberg: Gotenberg,
    monkeypatch: pytest.MonkeyPatch, printer: MockPrinter,
) -> None:  # fmt: skip
    down = MockPrinter(http=503, body=b"")
    monkeypatch.setattr(ipp, "transport_factory", lambda verify: httpx.MockTransport(down))
    pid = str((await _printer(admin))["id"])
    await _flag(admin, True)
    job = uuid.UUID((await admin.post(_api("/outputs"), json={
        "kind": "print", "source": {"report_template_key": "source-health"},
        "destination": {"printer_id": pid}})).json()["id"])  # fmt: skip
    assert await tasks.run_print(db, job) == "retrying"
    assert await tasks.run_print(db, job) == "retrying"
    assert await tasks.run_print(db, job) == "failed"
    shown = (await admin.get(_api(f"/outputs/{job}"))).json()
    assert (shown["error_class"], shown["attempts"]) == ("printer-unavailable", 3)


async def test_the_test_page(
    admin: httpx.AsyncClient, db: AsyncSession, gotenberg: Gotenberg, printer: MockPrinter
) -> None:
    pid = str((await _printer(admin))["id"])
    off = await admin.post(_api(f"/admin/printers/{pid}/test-page"))
    assert off.status_code == 409
    await _flag(admin, True)
    queued = await admin.post(_api(f"/admin/printers/{pid}/test-page"))
    assert queued.status_code == 202, queued.text
    assert queued.json()["source_summary"] == "stock report Printer test page"
    assert await tasks.run_print(db, uuid.UUID(queued.json()["id"])) == "sent"
    assert len(printer.requests) == 1
