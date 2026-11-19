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
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from regwatch.search.index import ALIAS, IndexClient
from regwatch.search.query import _WEBSEARCH, MAX_WINDOW, regions
from regwatch.search.schemas import Query, QueryFilters

FIELDS = ["title^3", "title.*^2", "summary", "summary.*", "title_en^2", "summary_en"]
FACET_TERMS = 1000  # distinct facet:key values counted per request
JURISDICTIONS = 400
_SORT = {
    "last_changed_desc": [{"last_changed_at": "desc"}, {"_id": "desc"}],
    "last_changed_asc": [{"last_changed_at": "asc"}, {"_id": "asc"}],
    "published_desc": [{"published_at": {"order": "desc", "missing": "_last"}}, {"_id": "desc"}],
    "published_asc": [{"published_at": {"order": "asc", "missing": "_last"}}, {"_id": "asc"}],
    "title_asc": [{"last_changed_at": "desc"}, {"_id": "asc"}],  # no keyword copy of titles
}  # fmt: skip


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
        syntax = re.sub(r"\bor\b", "|", q, flags=re.IGNORECASE)
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
        out["aggs"] = {"terms": {"terms": {"field": "terms", "size": FACET_TERMS}},
                       "jurisdiction": {"terms": {"field": "jurisdictions",
                                                  "size": JURISDICTIONS}}}  # fmt: skip
    return out


async def search(client: IndexClient, query: Query,
                 facets: bool) -> tuple[list[uuid.UUID], int, dict[str, Any]]:  # fmt: skip
    """The page's ids, the total (at most ``MAX_WINDOW``) and the raw aggregations."""
    got = await client.call("POST", f"/{ALIAS}/_search", body(query, facets))
    hits = got.get("hits", {})
    ids = [uuid.UUID(h["_id"]) for h in hits.get("hits", [])]
    total = min(int(hits.get("total", {}).get("value", 0)), MAX_WINDOW)
    return ids, total, got.get("aggregations", {})


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
    got = await client.call("POST", f"/{ALIAS}/_search", request)
    buckets = (got.get("aggregations", {}).get("events", {}).get("period", {})
               .get("places", {}).get("buckets", []))  # fmt: skip
    rows = []
    for bucket in buckets:
        levels = {b["key"]: b["items"]["doc_count"] for b in bucket["levels"]["buckets"]}
        rows.append({"code": bucket["key"], "count": bucket["items"]["doc_count"],
                     "last": bucket["last"].get("value_as_string"), "levels": levels})  # fmt: skip
    return rows
