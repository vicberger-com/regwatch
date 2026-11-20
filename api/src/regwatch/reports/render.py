"""Server-side report rendering (M7.2; the Jinja2 path of the M7 spec, ADR-0005 decision 3
deferred as BL-17). The preview, the PDF (M8) and the email body share this HTML.

What it holds to (M7.1 review, "what 7.2 must guard"):
- Autoescape on every template; nothing from a layout or an item is marked safe. Header and
  footer text inside ``<style>`` is hex-escaped as CSS.
- A link only for http and https URLs; no URL reaches ``src`` or CSS.
- The stored layout is validated again against the current field whitelist, and a saved view
  is used only if the *viewer* can see it; a shared layout renders with the viewer's rights.
- Rows come only through the search service, with its limits and the viewer's rate; field
  keys map to values through a fixed table here, never to SQL.
- Cost: at most ``MAX_ROWS`` rows, ``RENDER_RATE`` renders a minute per user, and HTML of at
  most ``MAX_HTML`` bytes.
"""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from functools import cache
from typing import Any
from urllib.parse import urlsplit

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.core.errors import ProblemError
from regwatch.identity.services import Principal, SlidingWindow
from regwatch.processing.schemas import ItemSummary
from regwatch.reports.components import validate_layout
from regwatch.reports.fields import field_keys, report_fields
from regwatch.reports.models import ReportLayout
from regwatch.reports.schemas import ReportDataSource
from regwatch.search.schemas import Query

MAX_ROWS = 500  # rows one render reads, whatever the layout's limit (5000) says
PAGE = 200  # the search service's largest page
RENDER_RATE = 20  # renders a minute, per user
MAX_HTML = 5 * 1024 * 1024
renders = SlidingWindow(60.0)
SEVERITY_ORDER = {"none": 0, "info": 1, "notable": 2, "major": 3}
CSP = ("default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; "
       "form-action 'none'; frame-ancestors 'self'; sandbox")  # fmt: skip


def css_text(value: object) -> str:
    """``value`` as the inside of a CSS string: everything but letters, digits and spaces as a
    hex escape, so nothing can end the string or the rule."""
    # Each escape ends with a space, which CSS consumes, so a space after it survives.
    return "".join(c if c.isascii() and (c.isalnum() or c == " ") else f"\\{ord(c):06x} "
                   for c in str(value))  # fmt: skip


@cache
def _environment() -> Environment:
    env = Environment(loader=PackageLoader("regwatch.reports", "templates"),
                      autoescape=select_autoescape(default=True, default_for_string=True),
                      undefined=StrictUndefined)  # fmt: skip
    env.filters["css_text"] = css_text
    return env


def web_link(url: str | None) -> str | None:
    """A link the report may show: http or https with a host, nothing else (as the web's
    ``safeUrl``)."""
    if not url or len(url) > 2048:
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname or parts.username:
        return None
    return url


def _limited(user_id: uuid.UUID) -> None:
    key = str(user_id)
    if renders.count(key) >= RENDER_RATE:
        raise ProblemError(429, "rate-limited", "Too many report renders; try again shortly.",
                           headers={"Retry-After": str(renders.retry_after(key))})  # fmt: skip
    renders.hit(key)


async def _query(db: AsyncSession, source: ReportDataSource, principal: Principal) -> Query:
    """The data source as a search query, with the viewer's visibility of a saved view."""
    from regwatch.search.models import SavedView

    if source.saved_view_id is not None:
        view = await db.scalar(select(SavedView).where(
            SavedView.id == source.saved_view_id,
            or_(SavedView.user_id == principal.user.id, SavedView.shared.is_(True))))  # fmt: skip
        if view is None:
            raise ProblemError(409, "conflict", "The saved view this report uses is not "
                               "available to you; choose another data source.")  # fmt: skip
        filters = dict(view.filters or {})
        if "changed" not in filters:
            since = datetime.now(UTC) - timedelta(days=view.period_days)
            filters["changed"] = {"from": since.isoformat()}
        return Query.model_validate({"filters": filters, "sort": "last_changed_desc"})
    if "query" in source.model_fields_set:
        return source.query
    return Query(sort="last_changed_desc")


async def _rows(db: AsyncSession, source: ReportDataSource, principal: Principal,
                template_key: str | None, given: dict[str, Any]) -> list[ItemSummary]:  # fmt: skip
    from regwatch.reports import templates
    from regwatch.search import services as search

    query = await templates.apply(db, await _query(db, source, principal), template_key, given)
    wanted = min(source.limit, MAX_ROWS)
    rows: list[ItemSummary] = []
    page = 1
    while len(rows) < wanted:
        size = min(PAGE, wanted - len(rows))
        result = await search.search(db, query.model_copy(update={
            "page": page, "page_size": size, "highlight": False, "facet_counts": False}),
            principal.user.id)  # fmt: skip
        rows += result.items
        if len(result.items) < size or page * size >= result.total:
            break
        page += 1
    return rows[:wanted]


async def _extras(db: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, Any]]:
    """Fields the search summary does not carry: when it was first seen, and the source's
    credibility."""
    from regwatch.capture.models import Source
    from regwatch.processing.models import Item

    if not ids:
        return {}
    found = await db.execute(select(Item.id, Item.discovered_at, Source.credibility)
                             .join(Source, Source.id == Item.source_id)
                             .where(Item.id.in_(ids)))  # fmt: skip
    return {i: {"discovered_at": seen, "credibility": cred} for i, seen, cred in found.tuples()}


def _date(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d") if value else ""


def _value(key: str, row: ItemSummary, extra: dict[str, Any]) -> tuple[str, str | None]:
    """The text, and a link when there is one, of field ``key`` for ``row``. A fixed table: an
    unknown key reads as empty, never as a lookup by name."""
    if key == "item.url":
        return row.canonical_url, web_link(row.canonical_url)
    if key.startswith("facet."):
        facet = key.removeprefix("facet.")
        terms = row.terms if "terms" in row.model_fields_set else []
        return ", ".join(t.label for t in terms if t.facet_key == facet), None
    table: dict[str, Any] = {
        "item.title": row.title, "item.title_en": row.title_en or "",
        "item.summary": row.summary or "", "item.published_at": _date(row.published_at),
        "item.last_changed_at": _date(row.last_changed_at),
        "item.discovered_at": _date(extra.get("discovered_at")),
        "item.status": row.status, "item.severity": row.severity or "",
        "item.language": row.language or "",
        "source.name": row.source_name if "source_name" in row.model_fields_set else "",
        "source.credibility": extra.get("credibility") or "",
        "jurisdiction.codes": ", ".join(j.code for j in row.jurisdictions),
        "jurisdiction.names": ", ".join(j.name for j in row.jurisdictions),
    }  # fmt: skip
    return str(table.get(key, "")), None


_SORT = re.compile(r"_at$")


def _sorted(rows: list[ItemSummary], extras: dict[uuid.UUID, dict[str, Any]], key: str,
            direction: str) -> list[ItemSummary]:  # fmt: skip
    def by(row: ItemSummary) -> tuple[bool, str]:
        text = _value(key, row, extras.get(row.id, {}))[0]
        if key == "item.severity":
            text = str(SEVERITY_ORDER.get(text, -1))
        return (text == "", text.lower() if not _SORT.search(key) else text)

    ordered = sorted(rows, key=by, reverse=direction == "desc")
    return [r for r in ordered if by(r)[1]] + [r for r in ordered if not by(r)[1]]


async def _changes(db: AsyncSession, ids: list[uuid.UUID], limit: int) -> list[dict[str, str]]:
    from regwatch.processing.models import ChangeEvent, Item

    if not ids:
        return []
    found = await db.execute(select(ChangeEvent.occurred_at, Item.title, ChangeEvent.kind,
                                    ChangeEvent.severity)
                             .join(Item, Item.id == ChangeEvent.item_id)
                             .where(ChangeEvent.item_id.in_(ids))
                             .order_by(ChangeEvent.occurred_at.desc()).limit(limit))  # fmt: skip
    kinds = {"new_item": "new", "content_changed": "changed", "status_changed": "status",
             "effective_date_reached": "in effect"}  # fmt: skip
    return [{"when": _date(at), "title": title, "kind": kinds.get(kind, kind),
             "severity": severity} for at, title, kind, severity in found.tuples()]  # fmt: skip


def _places(rows: list[ItemSummary]) -> list[dict[str, Any]]:
    counts: dict[str, int] = defaultdict(int)
    worst: dict[str, str] = {}
    for row in rows:
        for j in row.jurisdictions:
            counts[j.name] += 1
            level = row.severity or "none"
            if SEVERITY_ORDER.get(level, 0) >= SEVERITY_ORDER.get(worst.get(j.name, "none"), 0):
                worst[j.name] = level
    return [{"name": n, "count": c, "severity": worst.get(n, "none")}
            for n, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]  # fmt: skip


def _matrix(rows: list[ItemSummary]) -> dict[str, Any]:
    statuses = ["new", "updated", "unchanged", "archived"]
    counts: dict[str, dict[str, int]] = defaultdict(lambda: dict.fromkeys(statuses, 0))
    for row in rows:
        for j in row.jurisdictions:
            counts[j.name][row.status] = counts[j.name].get(row.status, 0) + 1
    table = [{"name": n, "counts": [c[s] for s in statuses]} for n, c in sorted(counts.items())]
    return {"statuses": statuses, "rows": table}


async def _sources(db: AsyncSession, principal: Principal) -> list[dict[str, Any]] | None:
    """The sources' health, for viewers who may read sources; None means "not allowed"."""
    from regwatch.capture.models import Source

    if "sources.read" not in principal.permissions:
        return None
    found = await db.execute(select(Source.name, Source.health, Source.enabled,
                                    Source.consecutive_failures).order_by(Source.name))  # fmt: skip
    return [{"name": n, "health": h, "state": "enabled" if e else "disabled", "failures": f}
            for n, h, e, f in found.tuples()]  # fmt: skip


async def render_layout(db: AsyncSession, row: ReportLayout, principal: Principal,
                        given: dict[str, Any] | None = None) -> str:  # fmt: skip
    """The layout's HTML for ``principal`` (the viewer, owner or not), with the parameters its
    stock report takes (M7.3)."""
    from regwatch.admin.services import values

    if "items.read" not in principal.permissions:
        raise ProblemError(403, "forbidden", "Reports show items; this needs items.read.")
    _limited(principal.user.id)
    fields, sortable = await field_keys(db)
    try:
        layout = validate_layout(row.layout, fields, sortable)
    except ProblemError as exc:  # a field or facet removed since it was saved
        stale = "The layout uses something that no longer exists; edit and save it again."
        raise ProblemError(409, "conflict", stale, errors=exc.errors) from None
    source = ReportDataSource.model_validate(row.query or {})
    rows = await _rows(db, source, principal, row.based_on_template_key, given or {})
    extras = await _extras(db, [r.id for r in rows])
    labels = {f.key: f.label for f in await report_fields(db)}
    settings = await values(db, ["branding.company_name", "branding.company_address",
                                 "legal.required_markings"])  # fmt: skip
    root = layout["root"]["props"]
    header = footer = None
    page_numbers = date = False
    blocks: list[dict[str, Any]] = []
    changes: list[dict[str, str]] | None = None
    for component in layout["content"]:
        kind, props = component["type"], component["props"]
        block: dict[str, Any] = {"type": kind, "props": props}
        if kind == "HeaderFooter":
            header, footer = props["header_text"], props["footer_text"]
            page_numbers, date = props["page_numbers"], props["date"]
            continue
        if kind == "ItemsTable":
            chosen = rows
            if props["sort"]:
                chosen = _sorted(rows, extras, props["sort"], props["direction"])
            block["columns"] = [labels.get(c, c) for c in props["columns"]]
            block["rows"] = [
                [dict(zip(("text", "href"), _value(c, r, extras.get(r.id, {})), strict=True))
                 for c in props["columns"]] for r in chosen[: props["limit"]]
            ]  # fmt: skip
        elif kind == "FieldValue":
            block["label"] = labels.get(props["field"], props["field"])
            block["value"] = (_value(props["field"], rows[0], extras.get(rows[0].id, {}))[0]
                              if rows else "")  # fmt: skip
        elif kind == "ChangeList":  # the changes are read once, for the largest list
            if changes is None:
                most = max(c["props"]["limit"] for c in layout["content"]
                           if c["type"] == "ChangeList")  # fmt: skip
                changes = await _changes(db, [r.id for r in rows], most)
            block["changes"] = changes[: props["limit"]]
        elif kind == "JurisdictionSummary":
            block["places"] = _places(rows)
        elif kind == "StatusMatrix":
            block["matrix"] = _matrix(rows)
        elif kind == "SourceHealth":
            block["sources"] = await _sources(db, principal)
        blocks.append(block)
    html = _environment().get_template("page.html.j2").render(
        title=root.get("title") or row.name, page_size=row.page_size,
        orientation=row.orientation, header=header, footer=footer,
        page_numbers=page_numbers, date=date,
        prepared=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"), blocks=blocks,
        company=settings.get("branding.company_name") or "",
        address=settings.get("branding.company_address") or "",
        markings=settings.get("legal.required_markings") or "",
    )  # fmt: skip
    if len(html.encode()) > MAX_HTML:
        raise ProblemError(422, "validation", "The report is too large to render; lower the "
                           "rows or the components.")  # fmt: skip
    return html
