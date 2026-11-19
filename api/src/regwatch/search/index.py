"""The OpenSearch index (ADR-0011, CP-22): its client, its mapping and the item documents.

The client follows the internal client's rules (ADR-0001; ``core/internal.py``):
- one base URL from the settings, https only, verified against the stack's own CA (never the
  system store, never unverified);
- HTTP basic authentication as the least-privilege ``regwatch`` user;
- only the paths this module names, with no redirects, no environment proxies and no cookies;
- a deadline on every call, a cap on the answer's raw size, and an uncompressed answer only.

An error is an ``IndexFailedError`` with a fixed text that never quotes the answer.

**Documents.** One per item, in ``regwatch-items`` (an alias over ``regwatch-items-v1``), built
from PostgreSQL, which stays the system of record:
- the text fields: title, summary and their English translations, with a language-stemmed
  copy per configuration;
- the filter fields: source, credibility, status, language, review flag, dates, jurisdiction
  and region codes, and terms as ``facet:key`` (never an ``incorrect`` one);
- the events, nested: time, severity and jurisdiction, for severity in a period and the map.
"""

from __future__ import annotations

import asyncio
import base64
import json
import ssl
import uuid
from collections.abc import Iterable
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.capture.models import Source
from regwatch.core.settings import Settings, get_settings
from regwatch.processing.models import ChangeEvent, Item, ItemJurisdiction, ItemTerm
from regwatch.taxonomy.models import Facet, Jurisdiction, Term

ALIAS = "regwatch-items"
INDEX = "regwatch-items-v1"
MAX_ANSWER = 16 * 1024 * 1024
DEADLINE_S = 20.0
TIMEOUT = httpx.Timeout(connect=3.0, read=15.0, write=10.0, pool=3.0)
BATCH = 500
SUPRANATIONAL = {"EU": "150", "COE": "150"}  # bodies without a region, by the region they belong to
STEMMED = {"en": "english", "de": "german", "fr": "french", "es": "spanish", "pt": "portuguese"}
PATHS = frozenset({f"/{INDEX}", f"/{INDEX}/_bulk", f"/{ALIAS}/_search", f"/{ALIAS}/_count",
                   f"/{ALIAS}/_refresh", "/_aliases", "/_cluster/health"})  # fmt: skip


class IndexFailedError(Exception):
    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason, self.detail = reason, detail


def configured(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    return bool(settings.index_url and settings.index_password and settings.index_ca_b64)


def _ssl(ca_b64: str) -> ssl.SSLContext:
    pem = base64.b64decode(ca_b64).decode("ascii")
    context = ssl.create_default_context(cadata=pem)  # our CA only; hostname checked
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


class IndexClient:
    def __init__(self, settings: Settings | None = None,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:  # fmt: skip
        settings = settings or get_settings()
        if not configured(settings):
            raise IndexFailedError("index-unconfigured", "the index is not configured")
        url = str(settings.index_url).rstrip("/")
        if not url.startswith("https://"):
            raise IndexFailedError("index-unconfigured", "the index URL must be https")
        assert settings.index_password is not None and settings.index_ca_b64 is not None  # noqa: S101
        self.base_url = url
        self.auth = (settings.index_user, settings.index_password.get_secret_value())
        self.verify: ssl.SSLContext | bool = (
            _ssl(settings.index_ca_b64.get_secret_value()) if transport is None else True
        )
        self.transport = transport

    async def call(
        self,
        method: str,
        path: str,
        body: Any = None,  # noqa: ANN401 - JSON
        ndjson: bytes | None = None,
        params: dict[str, str] | None = None,
        allow: tuple[int, ...] = (),
    ) -> Any:  # noqa: ANN401 - JSON
        if path not in PATHS:
            raise ValueError("an index path is one this module names")
        headers = {"accept": "application/json", "accept-encoding": "identity"}
        content: bytes | None = None
        if ndjson is not None:
            headers["content-type"] = "application/x-ndjson"
            content = ndjson
        elif body is not None:
            headers["content-type"] = "application/json"
            content = json.dumps(body).encode()
        async with httpx.AsyncClient(base_url=self.base_url, auth=self.auth, verify=self.verify,
                                     transport=self.transport, timeout=TIMEOUT,
                                     follow_redirects=False,
                                     trust_env=False) as client:  # fmt: skip
            try:
                async with asyncio.timeout(DEADLINE_S), client.stream(
                        method, path, content=content, params=params,
                        headers=headers) as got:  # fmt: skip
                    data = bytearray()
                    async for chunk in got.aiter_raw():
                        data += chunk
                        if len(data) > MAX_ANSWER:
                            raise IndexFailedError(
                                "index-too-large", "the index's answer is too large"
                            )
                    status = got.status_code
            except (httpx.TimeoutException, TimeoutError):
                raise IndexFailedError(
                    "index-timeout", "the index did not answer in time"
                ) from None
            except httpx.HTTPError:
                raise IndexFailedError(
                    "index-unavailable", "the index could not be reached"
                ) from None
        if not (200 <= status < 300 or status in allow):
            raise IndexFailedError("index-status", f"the index answered HTTP {status}")
        try:
            return json.loads(bytes(data)) if data else {}
        except ValueError:
            raise IndexFailedError("index-answer", "the index's answer is not JSON") from None


def _text(analyzer: str | None = None) -> dict[str, Any]:
    return {"type": "text", **({"analyzer": analyzer} if analyzer else {})}


MAPPING: dict[str, Any] = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0, "refresh_interval": "1s"},
    "mappings": {
        "dynamic": "strict",
        "properties": {
            "title": {**_text("standard"), "fields": {
                c: _text(a) for c, a in STEMMED.items()}},  # fmt: skip
            "summary": {**_text("standard"), "fields": {c: _text(a) for c, a in STEMMED.items()}},
            "title_en": _text("english"), "summary_en": _text("english"),
            "language": {"type": "keyword"}, "source_id": {"type": "keyword"},
            "credibility": {"type": "keyword"}, "status": {"type": "keyword"},
            "needs_review": {"type": "boolean"}, "published_at": {"type": "date"},
            "last_changed_at": {"type": "date"}, "jurisdictions": {"type": "keyword"},
            "regions": {"type": "keyword"}, "terms": {"type": "keyword"},
            "events": {"type": "nested", "properties": {
                "occurred_at": {"type": "date"}, "severity": {"type": "keyword"},
                "jurisdiction": {"type": "keyword"}, "region": {"type": "keyword"}}},
        },
    },
}  # fmt: skip


async def ensure(client: IndexClient) -> None:
    """The index and its alias, made once (an existing index is left as it is)."""
    await client.call("PUT", f"/{INDEX}", MAPPING, allow=(400,))
    await client.call("POST", "/_aliases",
                      {"actions": [{"add": {"index": INDEX, "alias": ALIAS}}]})  # fmt: skip


async def documents(db: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, Any]]:
    """The index documents of ``ids``; an id with no item is absent (to be deleted)."""
    items = {i.id: i for i in (await db.scalars(select(Item).where(Item.id.in_(ids)))).all()}
    if not items:
        return {}
    cred = dict((await db.execute(select(Source.id, Source.credibility).where(
        Source.id.in_({i.source_id for i in items.values()})))).tuples().all())  # fmt: skip
    places: dict[uuid.UUID, list[tuple[str, str | None]]] = {i: [] for i in items}
    for item_id, code, region in (await db.execute(
            select(ItemJurisdiction.item_id, Jurisdiction.code, Jurisdiction.region_code)
            .join(Jurisdiction, Jurisdiction.id == ItemJurisdiction.jurisdiction_id)
            .where(ItemJurisdiction.item_id.in_(list(items))))).tuples():  # fmt: skip
        places[item_id].append((code, region))
    tags: dict[uuid.UUID, list[str]] = {i: [] for i in items}
    for item_id, facet, key in (await db.execute(
            select(ItemTerm.item_id, Facet.key, Term.key).join(Term, Term.id == ItemTerm.term_id)
            .join(Facet, Facet.id == Term.facet_id)
            .where(ItemTerm.item_id.in_(list(items)),
                   ItemTerm.feedback.is_distinct_from("incorrect")))).tuples():  # fmt: skip
        tags[item_id].append(f"{facet}:{key}")
    events: dict[uuid.UUID, list[dict[str, Any]]] = {i: [] for i in items}
    for item_id, when, level, code, region in (await db.execute(
            select(ChangeEvent.item_id, ChangeEvent.occurred_at, ChangeEvent.severity,
                   Jurisdiction.code, Jurisdiction.region_code)
            .join(Jurisdiction, Jurisdiction.id == ChangeEvent.jurisdiction_id)
            .where(ChangeEvent.item_id.in_(list(items))))).tuples():  # fmt: skip
        events[item_id].append({"occurred_at": when.isoformat(), "severity": level,
                                "jurisdiction": code,
                                "region": region or SUPRANATIONAL.get(code, code)})  # fmt: skip
    out = {}
    for item_id, item in items.items():
        codes = [c for c, _ in places[item_id]]
        regions = sorted({r or SUPRANATIONAL.get(c, c) for c, r in places[item_id]})
        out[item_id] = {
            "title": item.title, "summary": item.summary, "title_en": item.title_en,
            "summary_en": item.summary_en, "language": item.language,
            "source_id": str(item.source_id), "credibility": cred.get(item.source_id),
            "status": item.status, "needs_review": item.needs_review,
            "published_at": item.published_at.isoformat() if item.published_at else None,
            "last_changed_at": item.last_changed_at.isoformat(), "jurisdictions": codes,
            "regions": regions, "terms": tags[item_id], "events": events[item_id],
        }  # fmt: skip
    return out


def bulk_body(docs: dict[uuid.UUID, dict[str, Any]], gone: Iterable[uuid.UUID]) -> bytes:
    lines: list[str] = []
    for item_id, doc in docs.items():
        lines += [json.dumps({"index": {"_index": INDEX, "_id": str(item_id)}}), json.dumps(doc)]
    for item_id in gone:
        lines.append(json.dumps({"delete": {"_index": INDEX, "_id": str(item_id)}}))
    return ("\n".join(lines) + "\n").encode()


async def index_items(db: AsyncSession, ids: list[uuid.UUID],
                      client: IndexClient | None = None) -> int:  # fmt: skip
    """Write the documents of ``ids`` (delete the ones with no item); how many were sent."""
    client = client or IndexClient()
    sent = 0
    for at in range(0, len(ids), BATCH):
        batch = ids[at : at + BATCH]
        docs = await documents(db, batch)
        got = await client.call("POST", f"/{INDEX}/_bulk",
                                ndjson=bulk_body(docs, set(batch) - set(docs)))  # fmt: skip
        if got.get("errors"):
            failed = sum(
                1
                for i in got.get("items", [])
                if next(iter(i.values())).get("status", 200) >= 300
                and next(iter(i.values())).get("status") != 404
            )
            if failed:
                raise IndexFailedError("index-bulk", f"{failed} documents were not indexed")
        sent += len(batch)
    return sent
