"""``POST /sources/{id}/documents``: add one document to a manual source (CP-17; BL-103).

The API never fetches (architecture 3.1). For a URL it checks the address as a source URL is
checked when saved, and records it; a worker fetches it through SafeFetcher. For a file it
checks the size and what the bytes are (HTML, PDF or plain text, by their content, not by the
name or the declared type) and stores them. Either way it writes the request as
``manual/{source_id}/{run_id}.json``, creates and audits a run, and hands it to the queue like
"Run now". The ``manual`` connector reads that request by the run's id, so a run handed over
after a worker died still finds it.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.capture import services
from regwatch.capture.models import CaptureJob, CaptureRun, Source, is_capturing
from regwatch.capture.runs import Enqueue, _handed_over
from regwatch.capture.safe_fetch.policy import FetchRefusedError, validate_source_url
from regwatch.core.errors import ProblemError
from regwatch.core.schemas import has_control
from regwatch.core.services import audit
from regwatch.identity.services import Principal

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TITLE = 500
Store = Callable[[str, bytes], Awaitable[None]]


def request_key(source_id: uuid.UUID | str, run_id: uuid.UUID | str) -> str:
    return f"manual/{source_id}/{run_id}.json"


def sniff(data: bytes) -> str:
    """What the bytes are: ``application/pdf``, ``text/html`` or ``text/plain``; anything else
    is refused (415). Decided from the content alone."""
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    head = data.lstrip(b"\xef\xbb\xbf \t\r\n\x0c")[:4096].lower()
    if b"\x00" in data[:8192]:
        raise ProblemError(415, "unsupported-media-type", "Send HTML, PDF or plain text.")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        raise ProblemError(415, "unsupported-media-type", "Send HTML, PDF or plain text "
                           "(text as UTF-8).") from None  # fmt: skip
    # HTML in its common openings, XHTML after an XML prolog, and any markup that names an
    # html element near the start: read by the isolated extraction child, never as text
    # (manual review finding 4).
    if head.startswith((b"<!doctype html", b"<html", b"<head", b"<body", b"<!--", b"<meta",
                        b"<title", b"<?xml")) or b"<html" in head:  # fmt: skip
        return "text/html"
    return "text/plain"


def _title(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if len(value) > MAX_TITLE or has_control(value):
        raise ProblemError(422, "validation", "The title is at most 500 characters, without "
                           "control characters.")  # fmt: skip
    return value or None


async def add_document(db: AsyncSession, source_id: uuid.UUID, principal: Principal,
                       ip: str | None, *, url: str | None, data: bytes | None,
                       title: str | None, store: Store,
                       enqueue: Enqueue) -> uuid.UUID:  # fmt: skip
    """The run that adds the document; raises the route's problems (404, 409, 413, 415, 422).
    Everything about the request is checked before any row is locked, so a slow name server
    holds no lock (as source saves; review finding 2 of the source routes)."""
    title = _title(title)
    if url is not None:
        resolver = services.RESOLVER or services._save_resolver
        try:
            async with asyncio.timeout(services.DNS_DEADLINE_S):
                await validate_source_url(url, resolver)
        except (FetchRefusedError, TimeoutError):
            raise ProblemError(422, "validation", "The URL must be http or https and its host "
                               "must resolve to public addresses only.") from None  # fmt: skip
        request: dict[str, str | None] = {"kind": "url", "url": url, "title": title}
        # The query can carry a signed link's token: the append-only audit keeps the address
        # without it (manual review info).
        parts = urlsplit(url)
        shown = f"{parts.scheme}://{parts.netloc}{parts.path}" + ("?..." if parts.query else "")
        detail: dict[str, object] = {"url": shown}
        upload: tuple[str, bytes] | None = None
    else:
        if data is None:  # the route passes one of the two
            raise ValueError("a manual document needs a URL or a file")
        if len(data) > MAX_FILE_BYTES:
            raise ProblemError(413, "payload-too-large", "Files are limited to 10 MB.")
        if not data:
            raise ProblemError(422, "validation", "The file is empty.")
        mime = sniff(data)
        digest = hashlib.sha256(data).hexdigest()
        body_ref = f"upload/{source_id}/{digest}"
        request = {"kind": "file", "body_ref": body_ref, "mime": mime, "sha256": digest,
                   "title": title}  # fmt: skip
        detail = {"sha256": digest, "bytes": len(data), "mime": mime}
        upload = (body_ref, data)
    source = await db.scalar(select(Source).where(Source.id == source_id).with_for_update())
    if source is None:
        raise ProblemError(404, "not-found", "No such source.")
    if source.kind != "manual":
        raise ProblemError(409, "conflict", "Documents can be added to manual sources only.")
    job = await db.scalar(select(CaptureJob).where(CaptureJob.source_id == source_id)
                          .with_for_update())  # fmt: skip
    if job is None or not job.enabled or not await is_capturing(db, source.id):
        raise ProblemError(409, "conflict", "The source is disabled; enable it first.")
    unfinished = (CaptureRun.job_id == job.id, CaptureRun.finished_at.is_(None))
    busy = await db.scalar(select(CaptureRun.id).where(*unfinished))
    if busy is not None:
        raise ProblemError(409, "conflict", "A run of this source is in progress; try again "
                           "when it ends.")  # fmt: skip
    if upload is not None:
        await store(*upload)
    run = CaptureRun(job_id=job.id, triggered_by=principal.user.id, started_at=datetime.now(UTC))
    db.add(run)
    await db.flush()
    await store(request_key(source_id, run.id), json.dumps(request).encode())
    audit(db, "source.document_added", "source", source_id, actor=principal.user.id, ip=ip,
          after={"run_id": str(run.id), **detail})  # fmt: skip
    run_id = run.id
    await db.commit()
    if not await _handed_over(db, run, enqueue, 0.0):
        raise ProblemError(503, "queue-unavailable", "The run could not be queued; try again.")
    return run_id
