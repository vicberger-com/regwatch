"""The API feed connector (M3 scope; connectors.yaml ``api_feed``; R-06 sections 2 and 4).

One connector for official APIs, with an adapter per ``provider``. Every request goes through
``ctx.fetcher`` (SafeFetcher, robots.txt, per-host rate limits). This slice has the Federal
Register adapter; ``eur_lex``, ``legislation_gov_uk`` and ``generic_json`` answer
``not-implemented`` until their adapters land.

Federal Register (R-06 section 2):

- the endpoint is fixed (``https://www.federalregister.gov/api/v1/documents.json``); the job's
  ``params`` are its query parameters, strings or lists of strings, bounded in number and size;
- a ``{last_success_date - N days}`` placeholder becomes a date N days before the job's last run
  (30 days back on the first run), so runs stay far below the API's paging cap;
- paging follows ``next_page_url`` only, never computed page numbers: past page 50 the API
  silently answers page 1 (E-FR-8). The next page must be on the same origin, and at most
  ``MAX_PAGES`` are read;
- a block by the provider's firewall (a 202 with ``x-amzn-waf-action``, or a redirect to
  ``unblock.federalregister.gov``) is the typed failure ``blocked-by-provider``, never retried
  and never worked around (8.3: no CAPTCHA solving);
- full text is blocked (E-FR-14), so the document is the API's own record (abstract and
  metadata, stored as JSON) and ``html_url`` is the link readers follow.

Values from the API are hostile like any captured content: titles and abstracts become plain
text (``rss.plain_text``), links pass SafeFetcher's URL checks (``rss.entry_link``), and JSON is
parsed with depth and size limits.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo

import anyio
from pydantic import BaseModel

from regwatch.capture.connectors import legislation
from regwatch.capture.connectors.base import (
    Candidate,
    ConnectorContext,
    ConnectorError,
    HealthReport,
    JobSettings,
    RawDocument,
    register,
)
from regwatch.capture.connectors.config import ApiFeedConfig
from regwatch.capture.connectors.rss import (
    MAX_SUMMARY,
    MAX_TITLE,
    entry_link,
    identifier,
    plain_text,
)
from regwatch.capture.safe_fetch.policy import FetchRefusedError

FEDERAL_REGISTER = "https://www.federalregister.gov/api/v1/documents.json"
FR_BLOCK_HOST = "unblock.federalregister.gov"
# Hosts a Federal Register record may link to: its own pages, and the PDFs on GovInfo.
FR_LINK_HOSTS = frozenset({"www.federalregister.gov", "federalregister.gov", "www.govinfo.gov",
                           "govinfo.gov"})  # fmt: skip
FR_EASTERN = ZoneInfo("America/New_York")  # Federal Register dates are US Eastern
MAX_JSON_BYTES = 5 * 1024 * 1024  # a page of 1,000 records is about 2 MiB (review finding 6)
MAX_LIST = 50
MAX_QUERY = 1500  # stays well under SafeFetcher's 2,048-character URL limit
LOWER_BOUND = "conditions[publication_date][gte]"
MAX_FIXED_LOOKBACK = timedelta(days=366)
MAX_PAGES = 10
MAX_PARAMS = 50
MAX_PARAM_VALUE = 2000
MAX_JSON_DEPTH = 32
FIRST_RUN_LOOKBACK = timedelta(days=30)
_PLACEHOLDER = re.compile(r"^\{last_success_date\s*-\s*(\d{1,3})\s*days?\}$")
_RECORD_FIELDS = ("document_number", "title", "type", "abstract", "publication_date", "html_url",
                  "pdf_url", "effective_on", "comments_close_on")  # fmt: skip


def _config(job: JobSettings) -> ApiFeedConfig:
    if not isinstance(job.config, ApiFeedConfig):
        raise TypeError("an api_feed job needs an ApiFeedConfig")
    return job.config


def _depth(value: Any, limit: int) -> int:
    """How deeply ``value`` nests, stopping at ``limit``."""
    if limit <= 0:
        return 1
    if isinstance(value, dict):
        return 1 + max((_depth(v, limit - 1) for v in value.values()), default=0)
    if isinstance(value, list):
        return 1 + max((_depth(v, limit - 1) for v in value), default=0)
    return 0


def parse_json(body: bytes) -> Any:
    """An API answer as JSON, or ``malformed-answer``; large bodies and deep nesting are
    refused."""
    if len(body) > MAX_JSON_BYTES:
        raise ConnectorError("too-large", f"the API's answer is over {MAX_JSON_BYTES} bytes")
    try:
        data = json.loads(body)
    except (ValueError, RecursionError):
        raise ConnectorError("malformed-answer", "the API's answer is not valid JSON") from None
    if _depth(data, MAX_JSON_DEPTH + 1) > MAX_JSON_DEPTH:
        raise ConnectorError("malformed-answer", "the API's answer is nested too deeply")
    return data


def _scalar(key: str, item: Any) -> str:
    if isinstance(item, bool):
        return "true" if item else "false"
    if isinstance(item, (int, float)) and not isinstance(item, bool):
        return str(item)  # the R-06 starter config writes per_page: 100 (review finding 7)
    if isinstance(item, str) and len(item) <= MAX_PARAM_VALUE:
        return item
    raise ConnectorError("bad-config", f"query parameter {key[:50]!r} is not a short value")


def query(params: dict[str, Any], last_success: datetime | None, now: datetime,
          cursor: dict[str, Any] | None = None) -> str:  # fmt: skip
    """The query string for the job's ``params``: short texts, numbers and booleans, or lists of
    them, with the last-success placeholder filled in (R-06 section 4)."""
    if len(params) > MAX_PARAMS:
        raise ConnectorError("bad-config", f"at most {MAX_PARAMS} query parameters")
    pairs: list[tuple[str, str]] = []
    for key, value in params.items():
        if len(key) > 200:
            raise ConnectorError("bad-config", "a query parameter name is too long")
        if key == "page":  # paging is by next_page_url only (E-FR-8; review finding 8)
            raise ConnectorError("bad-config", "page is set by the API's next_page_url")
        values = value if isinstance(value, list) else [value]
        if len(values) > MAX_LIST:
            raise ConnectorError("bad-config", f"query parameter {key[:50]!r} has too many values")
        for raw in values:
            item = _scalar(key, raw)
            if "{last_success_date" in item:
                placeholder = _PLACEHOLDER.match(item.strip())
                if placeholder is None:
                    raise ConnectorError("bad-config", "write the placeholder as "
                                         "{last_success_date - N days}")  # fmt: skip
                since = (_cursor_time(cursor) or last_success or now - FIRST_RUN_LOOKBACK
                         ) - timedelta(days=int(placeholder.group(1)))  # fmt: skip
                item = since.astimezone(FR_EASTERN).date().isoformat()
            elif key == LOWER_BOUND and _cursor_time(cursor) is not None:
                # A fixed start date moves up to the cursor too, so oldest-first reading always
                # moves forward (CP-13/14 review finding 2).
                item = _later(item, _cursor_time(cursor))
            pairs.append((key, item))
    text = urlencode(pairs)
    if len(text) > MAX_QUERY:
        raise ConnectorError("bad-config", f"the query is longer than {MAX_QUERY} characters")
    return text


def _later(fixed: str, cursor: datetime | None) -> str:
    """The later of a fixed ISO date and the cursor's date; a fixed value that is not a date is
    left for the API (save-time checks refuse it)."""
    try:
        day = date.fromisoformat(fixed)
    except ValueError:
        return fixed
    return max(day, cursor.date()).isoformat() if cursor else fixed


def _cursor_time(cursor: dict[str, Any] | None) -> datetime | None:
    """The cursor's date (CP-14) as the start of that day, US Eastern, or None."""
    value = (cursor or {}).get("publication_date")
    try:
        day = date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None
    return datetime.combine(day, datetime.min.time(), FR_EASTERN) if day else None


def check_params(config: ApiFeedConfig) -> None:
    """The checks a source's settings must pass when saved (review findings 7 and 8)."""
    if config.provider != "generic_json" and config.endpoint_url is not None:
        raise ConnectorError("bad-config", "endpoint_url is for generic_json only")
    if config.provider == "federal_register":
        query(config.params, None, datetime.now(UTC))
        _check_lower_bound(config.params.get(LOWER_BOUND))
    elif config.provider == "legislation_gov_uk":
        legislation.check(config.params)


def _check_lower_bound(value: Any) -> None:
    """R-06: each run is bounded from below by the last success, or by a recent fixed date. An
    upper bound alone, or a date years back, truncates every run (re-verification R4)."""
    if isinstance(value, str) and _PLACEHOLDER.match(value.strip()):
        return
    try:
        since = date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        since = None
    if since is None or since < (datetime.now(UTC) - MAX_FIXED_LOOKBACK).date():
        wanted = "{last_success_date - N days} or a date within the last year"
        raise ConnectorError("bad-config", f"set {LOWER_BOUND} to {wanted}")


def _blocked(headers: dict[str, str], url: str) -> bool:
    """The firewall's header, at any status (a 202, 403 or 405; review finding 5)."""
    return "x-amzn-waf-action" in headers or (urlsplit(url).hostname or "") == FR_BLOCK_HOST


def _fr_link(value: Any) -> str | None:
    """A Federal Register or GovInfo link, checked as any captured link (finding 4)."""
    link = entry_link({"link": value}, FEDERAL_REGISTER)
    if link is None:
        return None
    parts = urlsplit(link)  # https on the default port only (re-verification R3)
    ok = parts.scheme == "https" and parts.port is None and parts.hostname in FR_LINK_HOSTS
    return link if ok else None


def _published(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.combine(date.fromisoformat(value[:10]), datetime.min.time(), UTC)
    except ValueError:
        return None


def _record(result: dict[str, Any]) -> dict[str, Any]:
    """The stored document: known fields only, text fields as plain text."""
    record: dict[str, Any] = {}
    for key in ("html_url", "pdf_url"):
        link = _fr_link(result.get(key))
        if link is not None:
            record[key] = link
    for key in _RECORD_FIELDS:
        value = result.get(key)
        if key in ("html_url", "pdf_url"):
            continue
        if key == "document_number":
            ident = identifier(value)
            if ident is not None:
                record[key] = ident
            continue
        if isinstance(value, str):
            text = plain_text(value, MAX_SUMMARY if key == "abstract" else MAX_TITLE)
            if text is not None:
                record[key] = text
    agencies = result.get("agencies")
    if isinstance(agencies, list):
        names = [plain_text(a.get("name"), 200) for a in agencies[:20] if isinstance(a, dict)]
        record["agencies"] = [n for n in names if n]
    return record


class ApiFeedConnector:
    kind = "api_feed"
    config_schema: type[BaseModel] = ApiFeedConfig

    async def discover(self, job: JobSettings, ctx: ConnectorContext) -> AsyncIterator[Candidate]:
        config = _config(job)
        if config.provider == "legislation_gov_uk":
            async for candidate in legislation.discover(config.params, job, ctx):
                yield candidate
            return
        if config.provider != "federal_register":
            raise ConnectorError("not-implemented",
                                 f"the {config.provider} adapter is not built yet")  # fmt: skip
        async for candidate in self._federal_register(config, job, ctx):
            yield candidate

    async def _federal_register(self, config: ApiFeedConfig, job: JobSettings,
                                ctx: ConnectorContext) -> AsyncIterator[Candidate]:  # fmt: skip
        # Oldest first, from the cursor less the overlap: a run cut short by its limits stops at
        # a date the next run starts from (CP-14). Any `order` in the params is replaced.
        params = {**config.params, "order": "oldest"}
        ctx.notes.add("resumes")  # this connector continues from the job's cursor
        url = f"{FEDERAL_REGISTER}?{query(params, job.last_success_at, ctx.now(), job.cursor)}"
        origin = urlsplit(FEDERAL_REGISTER)
        seen: set[str] = set()
        asked: set[str] = set()
        for _ in range(MAX_PAGES):
            asked.add(url)
            try:
                got = await ctx.fetcher.fetch(url, rate_per_minute=job.rate_per_minute,
                                              robots_override=job.robots_override,
                                              refuse_hosts=frozenset({FR_BLOCK_HOST}))  # fmt: skip
            except FetchRefusedError as exc:
                if exc.reason == "refused-host":  # redirected to the block page; not contacted
                    raise ConnectorError("blocked-by-provider", "the Federal Register's "
                                         "firewall refused the request") from None  # fmt: skip
                raise
            if _blocked(got.headers, got.url):
                refused = "the Federal Register's firewall refused the request"
                raise ConnectorError("blocked-by-provider", refused)
            if not 200 <= got.status < 300:
                raise ConnectorError("http-status", f"the API answered HTTP {got.status}")
            data = await anyio.to_thread.run_sync(parse_json, got.body)  # off the loop (6)
            results = data.get("results") if isinstance(data, dict) else None
            if not isinstance(results, list):
                raise ConnectorError("malformed-answer", "the API's answer has no results list")
            for result in results:
                if not isinstance(result, dict):
                    continue
                record = _record(result)
                link = record.get("html_url")
                number = record.get("document_number")
                if link is None or link in seen or (number and number in seen):
                    continue  # one document under two links is still one document (finding 10)
                seen.update(x for x in (link, number) if x)
                yield Candidate(url=link, title=record.get("title"),
                                published_at=_published(result.get("publication_date")),
                                external_id=record.get("document_number"),
                                summary=record.get("abstract"), language="en",
                                hints={"record": record})  # fmt: skip
            following = data.get("next_page_url")
            if not isinstance(following, str) or not following:
                return
            parts = urlsplit(following)
            if (parts.scheme, parts.netloc, parts.path) != (origin.scheme, origin.netloc,
                                                            origin.path):  # fmt: skip
                raise ConnectorError("malformed-answer", "the next page is not the same endpoint")
            if following in asked:
                raise ConnectorError("malformed-answer", "the next page repeats an earlier one")
            url = following
        ctx.notes.add("truncated")  # pages remained past MAX_PAGES (review finding 2)

    async def fetch(self, candidate: Candidate, job: JobSettings,
                    ctx: ConnectorContext) -> RawDocument:  # fmt: skip
        """legislation.gov.uk: the entry's data.xml. Federal Register: the API's own record is
        the document, as full text is blocked (R-06, E-FR-14)."""
        if candidate.hints.get("provider") == "legislation_gov_uk":
            return await legislation.fetch(candidate, job, ctx)
        record = candidate.hints.get("record") or {}
        body = json.dumps(record, sort_keys=True).encode("utf-8")
        key = f"raw/{job.source_id}/{hashlib.sha256(body).hexdigest()}.json"
        await ctx.store(key, body)
        return RawDocument(url=candidate.url, fetched_at=ctx.now(), status=200, body_ref=key,
                           mime="application/json", text=candidate.summary,
                           metadata={"provider": "federal_register"})  # fmt: skip

    def health(self, job: JobSettings) -> HealthReport:
        return HealthReport("unknown", "health comes from the job's runs")


register(ApiFeedConnector())
