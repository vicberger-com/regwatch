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
from regwatch.capture.connectors.config import ApiFeedConfig
from regwatch.capture.connectors.rss import MAX_SUMMARY, MAX_TITLE, entry_link, plain_text

FEDERAL_REGISTER = "https://www.federalregister.gov/api/v1/documents.json"
FR_BLOCK_HOST = "unblock.federalregister.gov"
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
    """An API answer as JSON, or ``malformed-answer``; deep nesting is refused."""
    try:
        data = json.loads(body)
    except (ValueError, RecursionError):
        raise ConnectorError("malformed-answer", "the API's answer is not valid JSON") from None
    if _depth(data, MAX_JSON_DEPTH + 1) > MAX_JSON_DEPTH:
        raise ConnectorError("malformed-answer", "the API's answer is nested too deeply")
    return data


def query(params: dict[str, Any], last_run: datetime | None, now: datetime) -> str:
    """The query string for the job's ``params``: strings and lists of strings only, with the
    last-success placeholder filled in (R-06 section 4)."""
    if len(params) > MAX_PARAMS:
        raise ConnectorError("bad-config", f"at most {MAX_PARAMS} query parameters")
    pairs: list[tuple[str, str]] = []
    for key, value in params.items():
        values = value if isinstance(value, list) else [value]
        for item in values:
            if not isinstance(item, str) or len(item) > MAX_PARAM_VALUE or len(key) > 200:
                raise ConnectorError(
                    "bad-config", f"query parameter {key[:50]!r} is not a short text"
                )
            placeholder = _PLACEHOLDER.match(item.strip())
            if placeholder:
                since = (last_run or now - FIRST_RUN_LOOKBACK) - timedelta(
                    days=int(placeholder.group(1)))  # fmt: skip
                item = since.date().isoformat()
            pairs.append((key, item))
    return urlencode(pairs)


def _blocked(status: int, headers: dict[str, str], url: str) -> bool:
    host = urlsplit(url).hostname or ""
    return (status == 202 and "x-amzn-waf-action" in headers) or host == FR_BLOCK_HOST


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
    for key in _RECORD_FIELDS:
        value = result.get(key)
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
        if config.provider != "federal_register":
            raise ConnectorError("not-implemented",
                                 f"the {config.provider} adapter is not built yet")  # fmt: skip
        async for candidate in self._federal_register(config, job, ctx):
            yield candidate

    async def _federal_register(self, config: ApiFeedConfig, job: JobSettings,
                                ctx: ConnectorContext) -> AsyncIterator[Candidate]:  # fmt: skip
        url = f"{FEDERAL_REGISTER}?{query(config.params, job.last_run_at, ctx.now())}"
        origin = urlsplit(FEDERAL_REGISTER)
        seen: set[str] = set()
        for _ in range(MAX_PAGES):
            got = await ctx.fetcher.fetch(url, rate_per_minute=job.rate_per_minute,
                                          robots_override=job.robots_override)  # fmt: skip
            if _blocked(got.status, got.headers, got.url):
                refused = "the Federal Register's firewall refused the request"
                raise ConnectorError("blocked-by-provider", refused)
            if not 200 <= got.status < 300:
                raise ConnectorError("http-status", f"the API answered HTTP {got.status}")
            data = parse_json(got.body)
            results = data.get("results") if isinstance(data, dict) else None
            if not isinstance(results, list):
                raise ConnectorError("malformed-answer", "the API's answer has no results list")
            for result in results:
                if not isinstance(result, dict):
                    continue
                link = entry_link({"link": result.get("html_url")}, FEDERAL_REGISTER)
                if link is None or link in seen:
                    continue
                seen.add(link)
                record = _record(result)
                yield Candidate(url=link, title=record.get("title"),
                                published_at=_published(result.get("publication_date")),
                                external_id=record.get("document_number"),
                                summary=record.get("abstract"), language="en",
                                hints={"record": record})  # fmt: skip
            following = data.get("next_page_url")
            if not isinstance(following, str) or not following:
                return
            parts = urlsplit(following)
            if (parts.scheme, parts.netloc) != (origin.scheme, origin.netloc):
                raise ConnectorError("malformed-answer", "the next page is on another host")
            url = following

    async def fetch(self, candidate: Candidate, job: JobSettings,
                    ctx: ConnectorContext) -> RawDocument:  # fmt: skip
        """The API's own record is the document: full text is blocked (R-06, E-FR-14)."""
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
