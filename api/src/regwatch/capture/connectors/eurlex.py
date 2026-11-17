"""The EUR-Lex adapter of the API feed connector: Cellar's SPARQL endpoint (R-06 section 1 and
the section 4 starter configuration).

- One SPARQL query per run to the fixed endpoint ``https://publications.europa.eu/webapi/rdf/
  sparql``, built only from validated values: EuroVoc concept URIs, CELEX sector digits, a date
  and a limit. No setting is pasted into the query as text.
- Works are read oldest first from the job's cursor (CP-14), less ``lookback_days``; a full page
  (``limit`` rows) means more remain, so the run is ``truncated`` and continues next time.
- A work's document is its content in Cellar: ``/resource/celex/{celex}`` with
  ``Accept: application/xhtml+xml`` and the content language. Cellar answers 303 to plain http,
  which is rewritten to https before it is fetched (E-EU-9, E-EU-13); every hop must be https on
  publications.europa.eu. eur-lex.europa.eu is never fetched: its pages are WAF-challenged
  (E-EU-15); its address is only the reader's link.
- At most 10 requests a minute (R-06's proposal; no limit is published). A WAF challenge is
  ``blocked-by-provider``, never worked around.
- ``exclude_celex_regex`` is RE2 (linear time, bounded program size), as match rules are.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

import anyio

from regwatch.capture.connectors.base import (
    Candidate,
    ConnectorContext,
    ConnectorError,
    JobSettings,
    RawDocument,
)
from regwatch.capture.connectors.rss import MAX_TITLE, entry_link, plain_text
from regwatch.capture.safe_fetch.policy import FetchRefusedError

PROVIDER = "eur_lex"
CELLAR = "publications.europa.eu"
ENDPOINT = f"https://{CELLAR}/webapi/rdf/sparql"
CONTENT = f"https://{CELLAR}/resource/celex/{{celex}}"
DISPLAY = "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{celex}"
LANGUAGES = "http://publications.europa.eu/resource/authority/language/"
KNOWN = frozenset({"method", "sparql_endpoint", "eurovoc_concepts", "celex_sectors",
                   "exclude_celex_regex", "lookback_days", "limit", "content_language",
                   "content_url_template", "display_url_template"})  # fmt: skip
MAX_RATE_PER_MINUTE = 10
MAX_CONCEPTS = 50
MAX_LIMIT = 1000
MAX_LOOKBACK = 90
FIRST_RUN = timedelta(days=30)
MAX_REGEX = 200
_CONCEPT = re.compile(r"http://eurovoc\.europa\.eu/[A-Za-z0-9_]{1,40}")
_CELEX = re.compile(r"[0-9][0-9A-Z]{4,20}(\([0-9]{1,3}\))?(-[0-9]{8})?")
# The EU's 24 official languages: Cellar's three-letter code and the two-letter one a candidate
# carries (review finding 9; ENG is en, EST et, SLK sk, not their first two letters).
LANGUAGE_CODES = {"BUL": "bg", "CES": "cs", "DAN": "da", "DEU": "de", "ELL": "el", "ENG": "en",
                  "EST": "et", "FIN": "fi", "FRA": "fr", "GLE": "ga", "HRV": "hr", "HUN": "hu",
                  "ITA": "it", "LAV": "lv", "LIT": "lt", "MLT": "mt", "NLD": "nl", "POL": "pl",
                  "POR": "pt", "RON": "ro", "SLK": "sk", "SLV": "sl", "SPA": "es",
                  "SWE": "sv"}  # fmt: skip
# Cellar's answer for a work it has no XHTML of in that language (review finding 1): a skip.
UNAVAILABLE_STATUSES = frozenset({404, 406})
# Well under the 2,048 characters some proxies allow a request line (review finding 5).
MAX_QUERY_URL = 1800
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def _exclusion(pattern: Any) -> Any:  # noqa: ANN401 - RE2 has no type stubs
    from regwatch.taxonomy.rules import PatternError, compile_pattern

    if pattern is None:
        return None
    if not isinstance(pattern, str) or len(pattern) > MAX_REGEX:
        raise ConnectorError("bad-config", f"exclude_celex_regex is at most {MAX_REGEX} "
                             "characters")  # fmt: skip
    try:
        return compile_pattern(pattern)
    except PatternError as exc:
        raise ConnectorError("bad-config", f"exclude_celex_regex: {exc}") from None


def check(params: dict[str, Any]) -> None:
    """The EUR-Lex settings a source must have when saved."""
    unknown = set(params) - KNOWN
    if unknown:
        raise ConnectorError("bad-config", f"unknown setting {sorted(unknown)[0][:50]!r}")
    if params.get("method", "sparql") != "sparql":
        raise ConnectorError("bad-config", "method must be sparql")
    # The endpoint and the URL templates are fixed: a setting can never choose the host.
    for key, fixed in (("sparql_endpoint", ENDPOINT), ("content_url_template", CONTENT),
                       ("display_url_template", DISPLAY)):  # fmt: skip
        if key in params and params[key] != fixed:
            raise ConnectorError("bad-config", f"{key} must be {fixed}")
    concepts = params.get("eurovoc_concepts")

    def concept(c: Any) -> bool:
        return isinstance(c, str) and _CONCEPT.fullmatch(c) is not None

    if (not isinstance(concepts, list) or not 1 <= len(concepts) <= MAX_CONCEPTS
            or not all(map(concept, concepts))):  # fmt: skip
        raise ConnectorError("bad-config", "eurovoc_concepts is a list of EuroVoc concept URIs")
    sectors = params.get("celex_sectors", ["3"])
    if (not isinstance(sectors, list) or not 1 <= len(sectors) <= 10
            or not all(isinstance(x, str) and x.isascii() and len(x) == 1 and x.isdigit()
                       for x in sectors)):  # fmt: skip
        raise ConnectorError("bad-config", "celex_sectors is a list of single digits")
    _exclusion(params.get("exclude_celex_regex"))
    for key, low, high, default in (("lookback_days", 0, MAX_LOOKBACK, 14),
                                    ("limit", 1, MAX_LIMIT, 500)):  # fmt: skip
        value = params.get(key, default)
        if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
            raise ConnectorError("bad-config", f"{key} is {low} to {high}")
    language = params.get("content_language", "ENG")
    if not isinstance(language, str) or language not in LANGUAGE_CODES:
        raise ConnectorError("bad-config", "content_language is an EU language code such as ENG")
    if len(query_url(params, "2000-01-01")) > MAX_QUERY_URL:
        raise ConnectorError("bad-config", "too many eurovoc_concepts for one query; split the "
                             "source in two")  # fmt: skip


def since(params: dict[str, Any], job: JobSettings, now: datetime) -> str:
    """The first date to read: the cursor, else the last success, else 30 days back, less the
    lookback (CP-14)."""
    cursor = (job.cursor or {}).get("publication_date")
    start: date
    if isinstance(cursor, str) and _DATE.fullmatch(cursor):
        start = date.fromisoformat(cursor)
    else:
        start = (job.last_success_at or now - FIRST_RUN).date()
    return (start - timedelta(days=params.get("lookback_days", 14))).isoformat()


def sparql(params: dict[str, Any], start: str) -> str:
    """The query, from checked values only (check() ran first)."""
    concepts = " ".join(f"<{c}>" for c in params["eurovoc_concepts"])
    sectors = "".join(params.get("celex_sectors", ["3"]))
    language = params.get("content_language", "ENG")
    return f"""PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
SELECT DISTINCT ?celex ?date ?title WHERE {{
  VALUES ?concept {{ {concepts} }}
  ?work cdm:work_is_about_concept_eurovoc ?concept ; cdm:resource_legal_id_celex ?celex ;
        cdm:work_date_document ?date .
  FILTER(?date >= "{start}"^^<http://www.w3.org/2001/XMLSchema#date>)
  FILTER(REGEX(STR(?celex), "^[{sectors}]"))
  OPTIONAL {{ ?expr cdm:expression_belongs_to_work ?work ;
                   cdm:expression_uses_language <{LANGUAGES}{language}> ;
                   cdm:expression_title ?title . }}
}} ORDER BY ASC(?date) ?celex LIMIT {int(params.get("limit", 500))}"""


def query_url(params: dict[str, Any], start: str) -> str:
    return f"{ENDPOINT}?{urlencode({'query': sparql(params, start)})}"


def _content(celex: str) -> str:
    return CONTENT.format(celex=quote(celex, safe="()-"))


def _cellar_hop(url: str) -> bool:
    """Every hop: https on publications.europa.eu, default port."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme == "https" and parts.hostname == CELLAR and parts.port is None


async def _get(ctx: ConnectorContext, url: str, job: JobSettings, accept: str,
               language: str | None = None, unavailable: bool = False) -> Any:  # fmt: skip
    headers = {"Accept": accept, **({"Accept-Language": language} if language else {})}
    try:
        got = await ctx.fetcher.fetch(
            url, rate_per_minute=min(job.rate_per_minute, MAX_RATE_PER_MINUTE),
            robots_override=job.robots_override, allow_hop=_cellar_hop, headers=headers,
            upgrade_hosts=frozenset({CELLAR}))  # fmt: skip
    except FetchRefusedError as exc:
        if exc.reason == "refused-host":
            raise ConnectorError("off-host", "a redirect left publications.europa.eu") from None
        raise
    if "x-amzn-waf-action" in got.headers:
        raise ConnectorError("blocked-by-provider", "the provider's firewall refused the request")
    if unavailable and got.status in UNAVAILABLE_STATUSES:
        raise ConnectorError("unavailable", f"Cellar has no such document (HTTP {got.status})")
    if not 200 <= got.status < 300:
        raise ConnectorError("http-status", f"Cellar answered HTTP {got.status}")
    return got


def _value(binding: Any, key: str) -> str | None:
    cell = binding.get(key) if isinstance(binding, dict) else None
    value = cell.get("value") if isinstance(cell, dict) else None
    return value if isinstance(value, str) else None


def _published(day: str) -> datetime | None:
    """The work's date, or None when it is no real date: 2026-02-30 matches the pattern but is
    not a day, and must not end the run (review finding 2)."""
    if not _DATE.fullmatch(day[:10]):
        return None
    try:
        return datetime.combine(date.fromisoformat(day[:10]), datetime.min.time(), UTC)
    except ValueError:
        return None


async def discover(params: dict[str, Any], job: JobSettings,
                   ctx: ConnectorContext) -> AsyncIterator[Candidate]:  # fmt: skip
    from regwatch.capture.connectors.api_feed import parse_json  # one module imports the other

    check(params)
    exclude = _exclusion(params.get("exclude_celex_regex"))
    ctx.notes.add("resumes")  # reads oldest first from the cursor
    got = await _get(ctx, query_url(params, since(params, job, ctx.now())), job,
                     "application/sparql-results+json")  # fmt: skip
    data = await anyio.to_thread.run_sync(parse_json, got.body)
    results = data.get("results") if isinstance(data, dict) else None
    bindings = results.get("bindings") if isinstance(results, dict) else None
    if not isinstance(bindings, list):
        raise ConnectorError("malformed-answer", "the answer is not SPARQL JSON results")
    seen: set[str] = set()
    for binding in bindings:
        celex = _value(binding, "celex")
        if celex is None or not _CELEX.fullmatch(celex) or celex in seen:
            continue
        if exclude is not None and exclude.search(celex):
            continue
        seen.add(celex)
        link = entry_link({"link": DISPLAY.format(celex=celex)}, ENDPOINT)
        published = _published(_value(binding, "date") or "")
        if link is None:  # pragma: no cover - a checked CELEX always makes a valid link
            continue
        yield Candidate(url=link, title=plain_text(_value(binding, "title"), MAX_TITLE),
                        published_at=published, external_id=celex,
                        language=LANGUAGE_CODES[params.get("content_language", "ENG")],
                        hints={"provider": PROVIDER, "fetch": _content(celex)})  # fmt: skip
    if len(bindings) >= int(params.get("limit", 500)):
        ctx.notes.add("truncated")  # a full page: more works remain


async def fetch(candidate: Candidate, job: JobSettings, ctx: ConnectorContext) -> RawDocument:
    target = candidate.hints.get("fetch")
    if not isinstance(target, str) or not _cellar_hop(target):
        raise ConnectorError("bad-link", "the document is not in Cellar")
    language = (job.config.params if hasattr(job.config, "params") else {}).get(
        "content_language", "ENG").lower()  # fmt: skip
    got = await _get(ctx, target, job, "application/xhtml+xml", language, unavailable=True)
    key = f"raw/{job.source_id}/{hashlib.sha256(got.body).hexdigest()}"
    await ctx.store(key, got.body)
    return RawDocument(url=candidate.url, fetched_at=ctx.now(), status=got.status, body_ref=key,
                       mime=got.mime or "application/octet-stream", final_url=got.url,
                       metadata={"provider": PROVIDER, "fetched": got.url,
                                 "celex": candidate.external_id})  # fmt: skip
