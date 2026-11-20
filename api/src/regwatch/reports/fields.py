"""The report field whitelist (M7 interfaces: ``GET /reports/fields``).

Report components name fields only by these keys, never by SQL, column or JSON path from the
client. The fixed fields come from M4's item record; one field per visible M2 facet holds its
term labels. The renderer (M7.2) maps each key to its value itself.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.reports.schemas import ReportField
from regwatch.taxonomy.models import Facet

# key, label, type, sortable, group
_FIXED = (
    ("item.title", "Title", "text", True, "Item"),
    ("item.title_en", "Title (English)", "text", True, "Item"),
    ("item.summary", "Summary", "text", False, "Item"),
    ("item.url", "Link", "url", False, "Item"),
    ("item.published_at", "Published", "date", True, "Item"),
    ("item.last_changed_at", "Last changed", "date", True, "Item"),
    ("item.discovered_at", "First seen", "date", True, "Item"),
    ("item.status", "Status", "text", True, "Item"),
    ("item.severity", "Severity of the last change", "text", True, "Item"),
    ("item.language", "Language", "text", True, "Item"),
    ("source.name", "Source", "text", True, "Source"),
    ("source.credibility", "Credibility", "text", True, "Source"),
    ("jurisdiction.codes", "Jurisdiction codes", "list", False, "Jurisdiction"),
    ("jurisdiction.names", "Jurisdictions", "list", False, "Jurisdiction"),
)
FIXED = tuple(ReportField(key=k, label=lb, type=t, sortable=srt, group=g)
              for k, lb, t, srt, g in _FIXED)  # fmt: skip


async def report_fields(db: AsyncSession) -> list[ReportField]:
    query = (select(Facet.key, Facet.label)
             .where(Facet.hidden.is_(False), Facet.value_type == "term")
             .order_by(Facet.sort_order, Facet.label))  # fmt: skip
    facets = (await db.execute(query)).tuples().all()
    return [*FIXED, *(ReportField(key=f"facet.{key}", label=label, type="list", sortable=False,
                                  group="Taxonomy") for key, label in facets)]  # fmt: skip


async def field_keys(db: AsyncSession) -> tuple[set[str], set[str]]:
    """Every field key, and those a table may sort on."""
    fields = await report_fields(db)
    return {f.key for f in fields}, {f.key for f in fields if f.sortable}
