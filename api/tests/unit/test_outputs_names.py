"""Output summaries and file names (use testing U-M8-1, and its review): named by the source,
but another user's private layout or view only for ``reports.read_all``."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from regwatch.identity.models import User
from regwatch.identity.services import Principal
from regwatch.outputs.models import OutputJob
from regwatch.outputs.services import file_name, summary


def _viewer(user_id: uuid.UUID, *permissions: str) -> Principal:
    user = User(id=user_id, email="v@example.org", display_name="V", status="active")
    return Principal(user=user, session_id=uuid.UUID(int=0), roles=[], permissions=set(permissions))


def _job(owner: uuid.UUID, **source: object) -> OutputJob:
    return OutputJob(requested_by=owner, kind="pdf", status="sent",
                     destination={"source_name": "Acquisition target X"},
                     created_at=datetime(2026, 11, 21, tzinfo=UTC), **source)  # fmt: skip


def test_the_owner_sees_the_name_and_the_file_carries_it() -> None:
    owner = uuid.uuid4()
    job = _job(owner, report_layout_id=uuid.uuid4())
    assert summary(job, _viewer(owner)) == "report Acquisition target X"
    assert file_name(job, "pdf", _viewer(owner)) == (
        "regwatch-acquisition-target-x-2026-11-21.pdf")  # fmt: skip


def test_others_need_reports_read_all_for_a_private_name() -> None:
    job = _job(uuid.uuid4(), report_layout_id=uuid.uuid4())
    auditor = _viewer(uuid.uuid4(), "outputs.read_all")
    assert summary(job, auditor) == "a report"
    assert file_name(job, "pdf", auditor) == "regwatch-output-2026-11-21.pdf"
    view = _job(uuid.uuid4(), saved_view_id=uuid.uuid4())
    assert summary(view, auditor) == "a saved view"
    admin = _viewer(uuid.uuid4(), "outputs.read_all", "reports.read_all")
    assert summary(job, admin) == "report Acquisition target X"


def test_stock_report_names_are_public() -> None:
    job = _job(uuid.uuid4(), report_template_key="source-health")
    job.destination = {"source_name": "Source health"}
    assert summary(job, _viewer(uuid.uuid4(), "outputs.read_all")) == "stock report Source health"


def test_file_names_hold_only_letters_digits_and_hyphens() -> None:
    owner = uuid.uuid4()
    job = _job(owner, report_layout_id=uuid.uuid4())
    job.destination = {"source_name": 'Ünter "x"; filename=evil.exe\r\n../..'}
    name = file_name(job, "pdf", _viewer(owner))
    assert name == "regwatch-nter-x-filename-evil-exe-2026-11-21.pdf"
