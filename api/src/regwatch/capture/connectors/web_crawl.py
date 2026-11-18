"""The bounded web crawl (M3 scope; M3 design notes: crawl connector; connectors.yaml
``web_crawl``; ADR-0009 amendment 2: the project's own crawl, not Scrapy).

- Breadth first from ``seed_urls``: each page is fetched once through ``ctx.fetcher``
  (SafeFetcher, robots.txt, the per-host rate) and read in the isolated extraction child, which
  returns its text and its links in one pass. The page is then handed on as a candidate with
  what was fetched, so ``fetch`` builds the document without asking the site again.
- Links are resolved and checked as any captured link, query stripped by ``strip_query_params``,
  filtered by the URL patterns (RE2), kept only on ``allowed_domains`` (a host equal to one, or
  below it), and followed to at most ``max_depth``. Every redirect hop must stay on those
  domains too. At most ``max_pages_per_run`` pages (and the job's item limit) a run; pages left
  in the frontier make the run ``truncated``. Pages that are not HTML are passed over.
- The robots.txt override applies only to the seeds' own origins, the sites its reason was
  written about (8.3); every other host's robots.txt is obeyed.
- The rate is the slower of the job's and ``politeness_delay_seconds`` (M3 acceptance 5).
- Change detection is listing mode's (CP-16): each page's last hash per URL, in two state slots
  the cursor points to; unchanged pages are counted and never handed to M4. After
  ``MAX_UNREADABLE`` pages that cannot be read within the extraction limits, the run stops.
- ``follow_sitemaps`` answers ``not-implemented`` until it lands (BL-101).
"""

from __future__ import annotations

import heapq
import re
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel

from regwatch.capture.connectors import web_page
from regwatch.capture.connectors.base import (
    Candidate,
    ConnectorContext,
    ConnectorError,
    HealthReport,
    JobSettings,
    RawDocument,
    register,
)
from regwatch.capture.connectors.config import WebCrawlConfig
from regwatch.capture.connectors.rss import entry_link
from regwatch.capture.connectors.web_page import (
    HTML,
    MAX_UNREADABLE,
    UNREADABLE,
    _extract,
    _origin,
    _previous_listing,
    _url_filter,
    document,
    finish_state,
)
from regwatch.capture.safe_fetch.policy import FetchRefusedError, parse_target

GONE = frozenset({404, 410})
MAX_FAILURES = 3  # runs in a row a remembered page failed before it is forgotten (R16 (C))
TRANSIENT = frozenset({"timeout", "connect"})  # as execution.TRANSIENT, which imports this module
MAX_FRONTIER = 5000  # URLs waiting; about 1 MB of strings at the URL limit's typical length
# The last label: letters, or an internationalised one in punycode (R5).
_DOMAIN = re.compile(
    r"(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"([a-z]{2,63}|xn--[a-z0-9]([a-z0-9-]{0,57}[a-z0-9])?)"  # no trailing hyphen (R9)
)


def check(config: WebCrawlConfig) -> None:
    """When saved: domains are plain host names, and every seed is on one of them."""
    for domain in config.allowed_domains:
        if not _DOMAIN.fullmatch(domain):
            raise ConnectorError("bad-config", "allowed_domains are host names such as "
                                 "example.org")  # fmt: skip
    for seed in config.seed_urls:
        if not _allowed(str(seed), config.allowed_domains):
            raise ConnectorError("bad-config", "every seed URL must be on an allowed domain")


def _allowed(url: str, domains: list[str]) -> bool:
    """On an allowed domain, http on 80 or https on 443, by SafeFetcher's own parse of the URL
    (review finding 8: never the raw host name)."""
    try:
        target = parse_target(url)
    except FetchRefusedError:
        return False
    if (target.scheme, target.port) not in (("http", 80), ("https", 443)):
        return False
    if not _DOMAIN.fullmatch(target.host):  # a plain DNS name: no "\\", "%" or IP (finding 8)
        return False
    return any(target.host == d or target.host.endswith("." + d) for d in domains)


class WebCrawlConnector:
    kind = "web_crawl"
    config_schema: type[BaseModel] = WebCrawlConfig

    async def discover(self, job: JobSettings, ctx: ConnectorContext) -> AsyncIterator[Candidate]:
        config = job.config
        assert isinstance(config, WebCrawlConfig)  # noqa: S101 - job_settings validated it
        if job.render_js:
            raise ConnectorError("not-implemented", "JavaScript rendering is not built yet")
        if config.follow_sitemaps:
            raise ConnectorError("not-implemented", "following sitemaps is not built yet")
        check(config)
        domains = config.allowed_domains
        seeds = {_origin(str(s)) for s in config.seed_urls}
        rate = min(job.rate_per_minute, max(1, int(60 / config.politeness_delay_seconds)))
        keep = _url_filter(job.rules)
        strip = getattr(job.rules, "strip_query_params", True)
        limit = min(config.max_pages_per_run, job.max_items)
        previous = await _previous_listing(job, ctx)
        listed: list[str] = []
        ctx.notes.add("state-per-document")
        ctx.scratch["listing"] = {"listed": listed, "pages": {}, "previous": previous,
                                  "origin": None, "unreadable": 0, "tried": {},
                                  "keep_unlisted": True, "gone": set(),
                                  "depths": {}, "max_failures": MAX_FAILURES,
                                  "passed": set()}  # fmt: skip
        # Seeds first (their links are the crawl); then pages never checked, at any depth;
        # then the longest unchecked, shallower first among equals. A crawl cut short by its
        # limits reaches other pages, deeper ones too, next time (finding 3, R1, R2).
        frontier: list[tuple[int, str, int, int, str]] = []
        order = 0

        best: dict[str, int] = {}  # the shallowest depth each URL was pushed at (R17)
        done: set[str] = set()

        def push(url: str, depth: int) -> None:
            nonlocal order
            order += 1
            best[url] = depth
            checked = previous.get(url, ["", "", ""])[2]
            heapq.heappush(frontier, (0 if depth == 0 else 1, checked, depth, order, url))

        for seed in config.seed_urls:
            push(str(seed), 0)
        seen = {str(s) for s in config.seed_urls}
        # Every remembered page is asked again in its turn, at the depth it was found at, so a
        # page that has gone answers 404 or 410 and leaves the state, and one still there keeps
        # its baseline. Nothing is forgotten by age or evicted (re-verification R13, R14).
        # A remembered page the domains or URL patterns no longer allow is forgotten now, so
        # narrowing them frees room (re-verification R16 (A)).
        for url in [u for u in previous if not (_allowed(u, domains) and keep(u))]:
            del previous[url]
        for url, entry in previous.items():
            if url not in seen:
                depth = int(entry[3]) if entry[3].isdigit() else config.max_depth
                seen.add(url)
                push(url, min(max(depth, 1), config.max_depth))
        known = set(previous) | seen  # pages the state remembers, or will after this run
        requests = 0
        while frontier:
            if requests >= limit:  # every request counts, pages or not (finding 4)
                ctx.notes.update({"truncated", "crawl-limit"})
                return
            _seed, _checked, depth, _n, url = heapq.heappop(frontier)
            if url in done or depth > best.get(url, depth):
                continue  # a deeper copy of a page already taken at a shallower depth (R17)
            done.add(url)
            ctx.scratch["listing"]["depths"][url] = str(depth)
            requests += 1
            listed.append(url)
            origin = _origin(url)
            # The override only for a seed's origin, and then no hop may leave it: the fetcher
            # applies it to every hop (finding 1, 8.3).
            override = job.robots_override if origin in seeds else None

            def hop(
                target: str, _origin_: Any = origin, _strict: bool = override is not None
            ) -> bool:
                return _allowed(target, domains) and (not _strict or _origin(target) == _origin_)

            try:
                got = await ctx.fetcher.fetch(url, rate_per_minute=rate, robots_override=override,
                                              allow_hop=hop)  # fmt: skip
            except FetchRefusedError as exc:
                if override is not None and exc.reason == "refused-host" and depth == 0:
                    # A seed that redirects (to https, to www) under the override: the crawl
                    # cannot start, so it stops and says why (R3, R8). An inner page that
                    # redirects is one failed document (R11); the override never follows a
                    # hop off its address (8.3).
                    why = (
                        "under the robots.txt override a seed may not redirect off its own "
                        "address; save the address it redirects to as the seed"
                    )
                    if len(config.seed_urls) == 1:
                        raise ConnectorError("override-redirect", why) from None
                    # Other seeds still run (R15): this one is a failed document with the reason.
                    failed_seed = ConnectorError("override-redirect", why)
                    yield Candidate(url=url, hints={"error": failed_seed})
                    continue
                yield Candidate(url=url, hints={"error": exc})
                continue
            if got.status in GONE:  # no longer on the site: dropped, and a skip (R10, R18)
                ctx.scratch["listing"]["gone"].add(url)
                gone = ConnectorError("unavailable", f"the page is gone (HTTP {got.status})")
                yield Candidate(url=url, hints={"error": gone})
                continue
            final = got.url.split("?", 1)[0] if strip else got.url
            if depth > 0 and final != url:
                # A page that redirects to another page is gone under this address; the page it
                # leads to is crawled under its own, if allowed (R16 (B)).
                ctx.scratch["listing"]["gone"].add(url)
                if final not in seen and _allowed(final, domains) and keep(final):
                    seen.add(final)
                    known.add(final)
                    push(final, depth)
                continue
            if not 200 <= got.status < 300:
                failed = ConnectorError("http-status", f"the page answered HTTP {got.status}")
                yield Candidate(url=url, hints={"error": failed})
                continue
            if (got.mime or "") not in HTML:
                # Not a page of the site's text: no document, but tried, so it rotates to the
                # back like a failed page instead of taking the budget every run (R1).
                ctx.scratch["listing"]["tried"][url] = ctx.now().isoformat()
                ctx.scratch["listing"]["passed"].add(url)  # answered: not a failure (R16 (C))
                continue
            try:
                found = await _extract(got, job, "a" if depth < config.max_depth else None)
            except ConnectorError as exc:
                yield Candidate(url=url, hints={"error": exc})
                continue
            for href in found.links:
                link = entry_link({"link": href}, got.url)
                if link is not None and strip:
                    link = link.split("?", 1)[0]
                if link is not None and link in seen and depth + 1 < best.get(link, 0):
                    push(link, depth + 1)  # found again, nearer the seed: follow it from there
                    continue
                if (link is None or link in seen or not _allowed(link, domains)
                        or not keep(link)):  # fmt: skip
                    continue
                if len(frontier) >= MAX_FRONTIER:  # memory stays bounded (finding 5 (a))
                    ctx.notes.update({"truncated", "crawl-limit"})
                    break
                if link not in known and len(known) >= web_page.MAX_STATE:
                    # The state remembers MAX_STATE pages (R6); a new page past that would
                    # lose its baseline, so it is refused until gone pages make room (R13).
                    ctx.notes.update({"truncated", "state-full"})
                    continue
                known.add(link)
                seen.add(link)
                push(link, depth + 1)
            hints = {"got": got, "found": found, "previous": previous.get(url, [None, None])[:2]}
            yield Candidate(url=url, title=found.title, hints=hints)

    async def fetch(self, candidate: Candidate, job: JobSettings,
                    ctx: ConnectorContext) -> RawDocument:  # fmt: skip
        """The page discovery fetched and read: built from what it brought, never fetched
        again. A page discovery could not fetch or read raises its error here, so the run
        counts it as a failed document."""
        listing = ctx.scratch["listing"]
        listing["tried"][candidate.url] = ctx.now().isoformat()
        error = candidate.hints.get("error")
        if isinstance(error, ConnectorError) and error.reason in UNREADABLE:
            listing["unreadable"] += 1
            if listing["unreadable"] >= MAX_UNREADABLE:
                stop = f"{MAX_UNREADABLE} pages could not be read within the limits"
                raise ConnectorError("unreadable-pages", stop) from None
        if isinstance(error, FetchRefusedError) and error.reason in TRANSIENT:
            # Already tried once in discovery: the run must not wait and retry what it cannot
            # ask again (finding 7), so it counts as one failed document.
            raise ConnectorError(error.reason, "the page could not be fetched") from None
        if isinstance(error, (ConnectorError, FetchRefusedError)):
            raise error
        try:
            return await document(candidate, candidate.hints["got"], candidate.hints["found"],
                                  job, ctx)  # fmt: skip
        finally:  # the run keeps the candidate for its manifest: let the body go (finding 5 (b))
            candidate.hints.pop("got", None)
            candidate.hints.pop("found", None)

    async def finish(self, job: JobSettings, ctx: ConnectorContext) -> None:
        await finish_state(job, ctx)

    def health(self, job: JobSettings) -> HealthReport:
        return HealthReport("unknown", "health comes from the job's runs")


register(WebCrawlConnector())
