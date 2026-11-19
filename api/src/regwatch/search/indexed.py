"""Search and map activity on the OpenSearch index (ADR-0011), used when it is configured.

The validated ``Query`` (``query.check`` has run) becomes one OpenSearch request; the index
answers ids, the total and the facet counts, and PostgreSQL then gives the page's summaries
(the system of record; highlights are built there as before).

Meaning, kept the same as the PostgreSQL path (``search.query``):
- ``q``:
  - plain words match any of them, through BM25 over title, summary, their per-language stems
    and the English translations, so items with more of the words rank first;
  - websearch syntax (quotes, ``-word``, ``or``) goes through ``simple_query_string``, every
    word required;
- filters combine with AND, and the values of one filter with OR;
- ``severity`` means an event of that severity inside ``filters.changed`` when it is given;
- region 150 includes EU and COE.
Map activity counts, per jurisdiction or region, the matching items with an event in the period
there (``reverse_nested``).

A user's request runs under ``SEARCH_TIMEOUT`` on the index and ``SEARCH_DEADLINE_S`` at the
client; a query the index stopped early is a timeout, never a partial answer. An answer of an
unexpected shape is an ``IndexFailedError``, so PostgreSQL answers instead.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from regwatch.search.index import (
    ALIAS,
    SEARCH_DEADLINE_S,
    SEARCH_PARAMS,
    IndexClient,
    IndexFailedError,
)
from regwatch.search.query import _WEBSEARCH, MAX_WINDOW, regions
from regwatch.search.schemas import Query, QueryFilters

FIELDS = ["title^3", "title.*^2", "summary", "summary.*", "title_en^2", "summary_en"]
FACET_TERMS = 1000  # distinct facet:key values counted per request
FACET_SAMPLE = 2000
JURISDICTIONS = 400
_SORT = {
    "last_changed_desc": [{"last_changed_at": "desc"}, {"_id": "desc"}],
    "last_changed_asc": [{"last_changed_at": "asc"}, {"_id": "asc"}],
    "published_desc": [{"published_at": {"order": "desc", "missing": "_last"}}, {"_id": "desc"}],
    "published_asc": [{"published_at": {"order": "asc", "missing": "_last"}}, {"_id": "asc"}],
    "title_asc": [{"title.sort": "asc"}, {"_id": "asc"}],
}  # fmt: skip


async def _call(client: IndexClient, request: dict[str, Any],
                params: dict[str, str] | None = None) -> Any:  # noqa: ANN401 - JSON  # fmt: skip
    return await client.call("POST", f"/{ALIAS}/_search", request,
                       params={**SEARCH_PARAMS, **(params or {})},
                       deadline=SEARCH_DEADLINE_S)  # fmt: skip


def _answered(got: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
    if not isinstance(got, dict):
        raise IndexFailedError("index-answer", "the index's answer has an unexpected shape")
    if got.get("timed_out"):  # stopped at SEARCH_TIMEOUT: the counts would be partial
        raise IndexFailedError("index-timeout", "the index did not answer in time")
    return got


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _range(field: str, start: datetime | None, end: datetime | None) -> list[dict[str, Any]]:
    bounds = {k: v for k, v in (("gte", _iso(start)), ("lte", _iso(end))) if v}
    return [{"range": {field: bounds}}] if bounds else []


def filters(found: QueryFilters | None, with_changed: bool = True) -> list[dict[str, Any]]:
    if found is None:
        return []
    out: list[dict[str, Any]] = []
    if found.jurisdictions:
        out.append({"terms": {"jurisdictions": [c.upper() for c in found.jurisdictions]}})
    if found.regions:
        out.append({"terms": {"regions": sorted(regions(found.regions) | set(found.regions))}})
    for facet, keys in (found.terms or {}).items():
        if keys:
            out.append({"terms": {"terms": [f"{facet}:{k}" for k in keys]}})
    for field, values in (("source_id", [str(s) for s in found.sources or []]),
                          ("status", list(found.status or [])),
                          ("language", list(found.languages or [])),
                          ("credibility", list(found.credibility or []))):  # fmt: skip
        if values:
            out.append({"terms": {field: values}})
    if found.needs_review is not None:
        out.append({"term": {"needs_review": found.needs_review}})
    changed = found.changed
    start, end = (changed.from_, changed.to) if changed is not None else (None, None)
    if found.severity:
        within = _range("events.occurred_at", start, end)
        out.append({"nested": {"path": "events", "query": {"bool": {"filter": [
            {"terms": {"events.severity": list(found.severity)}}, *within]}}}})  # fmt: skip
    if found.published is not None:
        out += _range("published_at", found.published.from_, found.published.to)
    if with_changed:
        out += _range("last_changed_at", start, end)
    return out


def text_query(q: str) -> dict[str, Any] | None:
    q = q.strip()
    if not q:
        return None
    if _WEBSEARCH.search(q):  # quotes, -word, or: every word required (the PostgreSQL meaning)
        # ``or`` between words is OR; inside a phrase it is a word (review finding 10).
        parts = q.split('"')
        syntax = '"'.join(re.sub(r"\bor\b", "|", part, flags=re.IGNORECASE) if n % 2 == 0
                          else part for n, part in enumerate(parts))  # fmt: skip
        flags = "AND|OR|NOT|PHRASE|PRECEDENCE|WHITESPACE"
        return {"simple_query_string": {"query": syntax, "fields": FIELDS,
                                        "default_operator": "and", "flags": flags}}  # fmt: skip
    return {"multi_match": {"query": q, "fields": FIELDS, "type": "most_fields",
                            "operator": "or"}}  # fmt: skip


def body(query: Query, facets: bool) -> dict[str, Any]:
    must = text_query(query.q or "")
    out: dict[str, Any] = {
        "query": {"bool": {"filter": filters(query.filters), **({"must": [must]} if must else {})}},
        "from": (query.page - 1) * query.page_size, "size": query.page_size,
        "track_total_hits": MAX_WINDOW, "_source": False,
        "sort": (["_score", {"last_changed_at": "desc"}, {"_id": "desc"}]
                 if query.sort == "relevance" and must else _SORT.get(query.sort,
                                                                       _SORT["last_changed_desc"])),
    }  # fmt: skip
    if facets:
        # Counted over the best FACET_SAMPLE matches, as the PostgreSQL path samples them (the
        # 1M-item load test: counting every match cost most of the request).
        counts = {
            "terms": {"terms": {"field": "terms", "size": FACET_TERMS}},
            "jurisdiction": {"terms": {"field": "jurisdictions", "size": JURISDICTIONS}},
        }
        out["aggs"] = {"sample": {"sampler": {"shard_size": FACET_SAMPLE}, "aggs": counts}}
    return out


async def search(client: IndexClient, query: Query,
                 facets: bool) -> tuple[list[uuid.UUID], int, dict[str, Any]]:  # fmt: skip
    """The page's ids, the total (at most ``MAX_WINDOW``) and the raw aggregations."""
    got = _answered(await _call(client, body(query, facets)))
    try:
        hits = got.get("hits", {})
        ids = [uuid.UUID(h["_id"]) for h in hits.get("hits", [])]
        total = min(int(hits.get("total", {}).get("value", 0)), MAX_WINDOW)
        sample = got.get("aggregations", {}).get("sample", {})
        if not isinstance(sample, dict):
            raise TypeError
    except (KeyError, TypeError, ValueError, AttributeError):
        raise IndexFailedError("index-answer",
                               "the index's answer has an unexpected shape") from None  # fmt: skip
    return ids, total, sample


async def activity(client: IndexClient, found: QueryFilters | None, start: datetime,
                   end: datetime, view_by: str) -> list[dict[str, Any]]:  # fmt: skip
    """Rows per jurisdiction or region: items, the latest event, and items per severity."""
    field = "events.jurisdiction" if view_by == "country" else "events.region"
    period = {"range": {"events.occurred_at": {"gte": start.isoformat(),
                                               "lte": end.isoformat()}}}  # fmt: skip
    items: dict[str, Any] = {"items": {"reverse_nested": {}}}
    request = {
        "size": 0, "query": {"bool": {"filter": filters(found, with_changed=False)}},
        "aggs": {"events": {"nested": {"path": "events"}, "aggs": {"period": {
            "filter": period, "aggs": {"places": {
                "terms": {"field": field, "size": JURISDICTIONS},
                "aggs": {**items, "last": {"max": {"field": "events.occurred_at"}},
                         "levels": {"terms": {"field": "events.severity", "size": 3},
                                    "aggs": items}}}}}}}},
    }  # fmt: skip
    # Identical map requests within a minute share OpenSearch's request cache (the caller
    # rounds a default period to the minute).
    got = _answered(await _call(client, request, {"request_cache": "true"}))
    rows = []
    try:
        buckets = (got.get("aggregations", {}).get("events", {}).get("period", {})
                   .get("places", {}).get("buckets", []))  # fmt: skip
        for bucket in buckets:
            levels = {str(b["key"]): int(b["items"]["doc_count"])
                      for b in bucket["levels"]["buckets"]}  # fmt: skip
            last = bucket["last"].get("value_as_string")
            rows.append({"code": str(bucket["key"]), "count": int(bucket["items"]["doc_count"]),
                         "last": str(last) if last is not None else None,
                         "levels": levels})  # fmt: skip
    except (KeyError, TypeError, ValueError, AttributeError):
        raise IndexFailedError("index-answer",
                               "the index's answer has an unexpected shape") from None  # fmt: skip
    return rows
