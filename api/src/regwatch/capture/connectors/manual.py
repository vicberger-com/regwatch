"""The manual connector: one document an admin added (CP-17; ``capture/manual.py``).

A manual source has no schedule of its own to follow: its runs come from
``POST /sources/{id}/documents``. The run's request is read from
``manual/{source_id}/{run_id}.json``, by that exact key; a run without one (a scheduled tick, or
"Run now") offers nothing and succeeds empty.

- A URL is fetched through ``ctx.fetcher`` (SafeFetcher, robots.txt, the per-host rate) and must
  answer 2xx. HTML is read in the isolated extraction child, never in process; PDF and plain
  text are stored as they are (M4 extracts PDF text).
- A file was stored by the API after its size and content were checked; it is read back under
  its exact key and handled the same way.
- The document is always ``new``: there is no previous version to compare with. M4 tells a
  repeated upload from a new one by its content hash.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel

from regwatch.capture.connectors.base import (
    Candidate,
    ConnectorContext,
    ConnectorError,
    HealthReport,
    JobSettings,
    RawDocument,
    register,
)
from regwatch.capture.connectors.config import ExtractionRules, ManualConfig
from regwatch.capture.connectors.web_page import _charset
from regwatch.capture.extract.isolate import ParseError, extract_isolated

KINDS = frozenset({"text/html", "application/pdf", "text/plain"})
FETCHED_KINDS = {"text/html": "text/html", "application/xhtml+xml": "text/html",
                 "application/pdf": "application/pdf", "text/plain": "text/plain"}  # fmt: skip


def _request_ref(source_id: str, run_id: Any) -> str | None:  # noqa: ANN401
    if not isinstance(run_id, str) or not re.fullmatch(r"[0-9a-f-]{36}", run_id):
        return None
    return f"manual/{source_id}/{run_id}.json"


def _upload_ref(value: Any, source_id: str) -> str | None:  # noqa: ANN401
    if isinstance(value, str) and re.fullmatch(rf"upload/{re.escape(source_id)}/[0-9a-f]{{64}}",
                                               value):  # fmt: skip
        return value
    return None


async def _request(job: JobSettings, ctx: ConnectorContext) -> dict[str, Any] | None:
    ref = _request_ref(job.source_id, ctx.scratch.get("run_id"))
    if ref is None or ctx.load is None:
        return None
    try:
        raw = await ctx.load(ref)
        data = json.loads(raw) if raw else None
    except (OSError, ValueError):
        raise ConnectorError("bad-request", "the document request could not be read") from None
    return data if isinstance(data, dict) else None


async def fetch_document(candidate: Candidate, job: JobSettings, ctx: ConnectorContext,
                     extra: dict[str, Any]) -> RawDocument:  # fmt: skip
    """A URL (fetched through SafeFetcher, robots.txt always obeyed) or a stored upload, as a
    new document: HTML read in the isolated child, PDF and text stored. Shared with the search
    connector, whose result pages are fetched the same way."""
    if candidate.hints.get("kind") == "url":
        got = await ctx.fetcher.fetch(candidate.url, rate_per_minute=job.rate_per_minute,
                                      robots_override=None)  # fmt: skip
        # Never the override: anyone with sources.manage can submit any URL here, and the
        # override's reason was written about another site (8.3; manual review finding 1).
        if not 200 <= got.status < 300:
            raise ConnectorError("http-status", f"the page answered HTTP {got.status}")
        mime = FETCHED_KINDS.get(got.mime or "")
        if mime is None:
            raise ConnectorError("unsupported-type", "the address is not HTML, PDF or text")
        body, final_url, status = got.body, got.url, got.status
        charset = _charset(got.headers.get("content-type", ""))
        key = f"raw/{job.source_id}/{hashlib.sha256(body).hexdigest()}"
        await ctx.store(key, body)
    else:
        key = candidate.hints["body_ref"]
        loaded = await ctx.load(key) if ctx.load is not None else None
        if loaded is None:
            raise ConnectorError("bad-request", "the uploaded file is no longer stored")
        body, final_url, status, mime, charset = (
            loaded,
            None,
            200,
            candidate.hints["mime"],
            None,
        )
    text: str | None = None
    metadata: dict[str, Any] = {"title": candidate.title, **extra}
    if mime == "text/html":
        rules = job.rules if isinstance(job.rules, ExtractionRules) else ExtractionRules()
        try:
            found = await extract_isolated(body, charset, rules)
        except ParseError as exc:
            raise ConnectorError(exc.reason, "the page could not be read within the "
                                 "limits") from None  # fmt: skip
        text = found.text
        metadata.update({"title": candidate.title or found.title,
                         "content_hash": found.content_hash, "warnings": found.warnings,
                         "published_at": found.published_at.isoformat()
                         if found.published_at else None})  # fmt: skip
    elif mime == "text/plain":
        text = body.decode("utf-8", errors="replace")
    return RawDocument(url=candidate.url, fetched_at=ctx.now(), status=status, body_ref=key,
                       mime=mime, final_url=final_url, text=text, metadata=metadata,
                       change="new")  # fmt: skip


class ManualConnector:
    kind = "manual"
    config_schema: type[BaseModel] = ManualConfig

    async def discover(self, job: JobSettings, ctx: ConnectorContext) -> AsyncIterator[Candidate]:
        request = await _request(job, ctx)
        if request is None:
            return  # a run that no document request started: nothing to add
        title = request.get("title") if isinstance(request.get("title"), str) else None
        if request.get("kind") == "url" and isinstance(request.get("url"), str):
            yield Candidate(url=request["url"], title=title, hints={"kind": "url"})
        elif request.get("kind") == "file" and request.get("mime") in KINDS:
            ref = _upload_ref(request.get("body_ref"), job.source_id)
            if ref is None:
                raise ConnectorError("bad-request", "the document request is not this source's")
            yield Candidate(url=f"urn:sha256:{ref.rsplit('/', 1)[1]}", title=title,
                            hints={"kind": "file", "body_ref": ref,
                                   "mime": request["mime"]})  # fmt: skip
        else:
            raise ConnectorError("bad-request", "the document request is not one this run takes")

    async def fetch(self, candidate: Candidate, job: JobSettings,
                    ctx: ConnectorContext) -> RawDocument:  # fmt: skip
        return await fetch_document(candidate, job, ctx, {"manual": True})

    def health(self, job: JobSettings) -> HealthReport:
        return HealthReport("unknown", "a manual source has no schedule to be healthy on")


register(ManualConnector())
