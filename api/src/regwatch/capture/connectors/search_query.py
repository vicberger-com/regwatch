"""The search query connector: SearXNG for discovery only (ADR-0010; R-07 section 4; M3 design
notes: search connector; connectors.yaml ``search_query``).

- Search runs only when the ``search.internet`` flag is on and ``search.provider`` is
  ``searxng``; the worker then hands the connector the internal client (``ctx.search``).
  Otherwise the run fails ``search-disabled``.
- One query at a time across the deployment, at least ``PACE_S`` apart with random extra
  spacing (``ctx.pace``), one page of results per ``RESULTS_PER_PAGE`` asked, at most
  ``MAX_PAGES`` pages.
- SearXNG's answer is hostile like any capture: each result's URL is checked as a captured link,
  kept only on ``site_filters`` when there are any (and only on official hosts when
  ``official_domains_only``), and taken once. Its title and snippet become plain text.
- A run where no engine answered, or only Bing did, fails ``search-unavailable`` and names the
  engines that did not answer, so repeated failures mark the source unhealthy (BL-33).
- Each result's page is then fetched through SafeFetcher like a manual URL (robots.txt always
  obeyed, never an override), and read in the isolated extraction child. Its credibility is
  ``official`` when its host is an official source's, else ``secondary``.
"""

from __future__ import annotations

import random
import re
from collections.abc import AsyncIterator
from dataclasses import replace
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
from regwatch.capture.connectors.config import SearchQueryConfig
from regwatch.capture.connectors.manual import fetch_document
from regwatch.capture.connectors.rss import MAX_SUMMARY, MAX_TITLE, entry_link, plain_text
from regwatch.capture.safe_fetch.policy import FetchRefusedError, parse_target
from regwatch.core.internal import InternalError

PACE_S = 60.0
JITTER_S = 30.0
RESULTS_PER_PAGE = 10
MAX_PAGES = 5
MAX_SITE_FILTERS = 20
MAX_LANGUAGES = 5
TIME_RANGES = {"day": "day", "week": "week", "month": "month", "year": "year", "any": ""}
_HOST = re.compile(r"(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+"
                   r"([a-z]{2,63}|xn--[a-z0-9]([a-z0-9-]{0,57}[a-z0-9])?)")  # fmt: skip
_LANGUAGE = re.compile(r"[a-z]{2,3}(-[A-Za-z0-9]{2,8})?")
_ENGINE = re.compile(r"[a-z0-9 _-]{1,40}")
ONLY_UNUSABLE = frozenset({"bing"})  # R-07: Bing's answers were off-topic


def check(config: SearchQueryConfig) -> None:
    """When saved: site filters are host names, languages are tags, the query has text."""
    if not config.query.strip() or any(ord(c) < 32 for c in config.query):
        raise ConnectorError("bad-config", "the query is text without control characters")
    if len(config.site_filters) > MAX_SITE_FILTERS or not all(
            _HOST.fullmatch(s) for s in config.site_filters):  # fmt: skip
        raise ConnectorError("bad-config", f"site_filters are at most {MAX_SITE_FILTERS} host "
                             "names such as example.org")  # fmt: skip
    if len(config.languages) > MAX_LANGUAGES or not all(
            _LANGUAGE.fullmatch(x) for x in config.languages):  # fmt: skip
        raise ConnectorError("bad-config", "languages are tags such as en or de-AT")


def _host(url: str) -> str | None:
    """The host of an https or http URL on its default port, by SafeFetcher's parse; another
    port is never an official host's (search review finding 5)."""
    try:
        target = parse_target(url)
    except FetchRefusedError:
        return None
    if (target.scheme, target.port) not in (("http", 80), ("https", 443)):
        return None
    return target.host


def _on(host: str, domains: list[str] | frozenset[str]) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def _engines(value: Any) -> list[str]:  # noqa: ANN401 - SearXNG's JSON
    """The names of the engines SearXNG reports as unresponsive, checked as plain names."""
    names: list[str] = []
    for item in value if isinstance(value, list) else []:
        name = item[0] if isinstance(item, list) and item else item
        if isinstance(name, str) and _ENGINE.fullmatch(name.lower()):
            names.append(name.lower())
    return names[:20]


class SearchQueryConnector:
    kind = "search_query"
    config_schema: type[BaseModel] = SearchQueryConfig

    async def discover(self, job: JobSettings, ctx: ConnectorContext) -> AsyncIterator[Candidate]:
        config = job.config
        assert isinstance(config, SearchQueryConfig)  # noqa: S101 - job_settings validated it
        check(config)
        if ctx.search is None or ctx.pace is None:
            raise ConnectorError("search-disabled", "internet search is off (the search.internet "
                                 "flag, or search.provider is not searxng)")  # fmt: skip
        if config.official_domains_only and not ctx.official_hosts:
            raise ConnectorError("bad-config", "no official source exists to take domains from")
        sites = " OR ".join(f"site:{s}" for s in config.site_filters)
        query = f"{config.query.strip()} ({sites})" if sites else config.query.strip()
        params = {"q": query, "format": "json", "safesearch": "0",
                  "language": config.languages[0] if config.languages else "all",
                  "time_range": TIME_RANGES[config.time_range]}  # fmt: skip
        pages = min(MAX_PAGES, -(-config.max_results // RESULTS_PER_PAGE))
        seen: set[str] = set()
        taken = 0
        for page in range(1, pages + 1):
            await ctx.pace("search", PACE_S + random.uniform(0, JITTER_S))  # noqa: S311 - spacing
            try:
                answer = await ctx.search.get_json("/search", {**params, "pageno": str(page)})
            except InternalError as exc:
                raise ConnectorError(exc.reason, exc.detail) from None
            results = answer.get("results") if isinstance(answer, dict) else None
            if not isinstance(results, list):
                raise ConnectorError("malformed-answer", "the search answer has no results list")
            if page == 1:
                answered = {e for r in results if isinstance(r, dict)
                            and isinstance(r.get("engines"), list)
                            for e in r["engines"] if isinstance(e, str)}  # finding 6  # fmt: skip
                if not results or answered <= ONLY_UNUSABLE:
                    down = ", ".join(_engines(answer.get("unresponsive_engines"))) or "none named"
                    raise ConnectorError("search-unavailable", "no usable search engine "
                                         f"answered (unresponsive: {down})")  # fmt: skip
            for result in results:
                if taken >= config.max_results:
                    break
                url = entry_link({"link": result.get("url")}, "https://invalid.example/") \
                    if isinstance(result, dict) else None  # fmt: skip
                if url is None or url in seen:
                    continue
                host = _host(url)
                if host is None:
                    continue
                if config.site_filters and not _on(host, config.site_filters):
                    continue
                if config.official_domains_only and not _on(host, ctx.official_hosts):
                    continue
                seen.add(url)
                taken += 1
                credibility = "official" if _on(host, ctx.official_hosts) else "secondary"
                yield Candidate(url=url, title=plain_text(result.get("title"), MAX_TITLE),
                                summary=plain_text(result.get("content"), MAX_SUMMARY),
                                hints={"kind": "url", "credibility": credibility})  # fmt: skip
            if taken >= config.max_results or len(results) < RESULTS_PER_PAGE:
                break

    async def fetch(self, candidate: Candidate, job: JobSettings,
                    ctx: ConnectorContext) -> RawDocument:  # fmt: skip
        """The result's page. Every redirect hop must stay where the source's filters allow,
        and credibility is judged on where the page ends up, not on the result's address
        (search review finding 2)."""
        config = job.config
        assert isinstance(config, SearchQueryConfig)  # noqa: S101 - job_settings validated it

        def allowed(hop: str) -> bool:
            host = _host(hop)
            return host is not None and (
                (not config.site_filters or _on(host, config.site_filters))
                and (not config.official_domains_only or _on(host, ctx.official_hosts))
            )

        doc = await fetch_document(candidate, job, ctx, {"search": True,
                                                         "snippet": candidate.summary},
                                   allow_hop=allowed)  # fmt: skip
        final = _host(doc.final_url or candidate.url)
        official = final is not None and _on(final, ctx.official_hosts)
        credibility = "official" if official else "secondary"
        return replace(doc, metadata={**doc.metadata, "credibility": credibility})

    def health(self, job: JobSettings) -> HealthReport:
        return HealthReport("unknown", "health comes from the job's runs")


register(SearchQueryConnector())
