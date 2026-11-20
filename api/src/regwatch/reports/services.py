"""Saved report layouts (M7 acceptance 2, REQ-13).

A layout belongs to the user who made it. Others see it only once it is shared, which needs
``reports.share``; ``reports.read_all`` (administrators) sees every layout (CP-30). Only the
owner changes or deletes a layout. Every layout is validated component by component before it
is stored (``components.validate_layout``), and its data source may only name a saved view the
owner can see. Saving a new layout or data source moves the version on, so outputs can record
which version they rendered (M8).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.core.errors import ProblemError, ProblemFieldError
from regwatch.core.schemas import has_control
from regwatch.core.services import audit
from regwatch.identity.services import Principal
from regwatch.reports.components import validate_layout
from regwatch.reports.fields import field_keys
from regwatch.reports.models import ReportLayout
from regwatch.reports.schemas import ReportDataSource, ReportLayoutWrite
from regwatch.reports.schemas import ReportLayout as LayoutOut

SHARE = "reports.share"
READ_ALL = "reports.read_all"
MAX_LAYOUTS = 500  # listed; a user's own are always first


def _invalid(field: str, message: str) -> ProblemError:
    return ProblemError(422, "validation", "The layout is not valid.",
                        errors=[ProblemFieldError(field=field, message=message)])  # fmt: skip


def out(row: ReportLayout) -> LayoutOut:
    return LayoutOut(
        id=row.id, user_id=row.user_id, name=row.name,
        based_on_template_key=row.based_on_template_key, layout=row.layout,
        data_source=ReportDataSource.model_validate(row.query or {}),
        page_size=row.page_size, orientation=row.orientation,
        shared=row.shared, version=row.version, updated_at=row.updated_at,
    )  # fmt: skip


def _visible(principal: Principal) -> Any:
    if READ_ALL in principal.permissions:
        return True
    return or_(ReportLayout.user_id == principal.user.id, ReportLayout.shared.is_(True))


async def list_layouts(db: AsyncSession, principal: Principal) -> list[LayoutOut]:
    mine = ReportLayout.user_id == principal.user.id
    rows = (await db.scalars(select(ReportLayout).where(_visible(principal))
                             .order_by(mine.desc(), ReportLayout.name, ReportLayout.id)
                             .limit(MAX_LAYOUTS))).all()  # fmt: skip
    return [out(r) for r in rows]


async def get_layout(db: AsyncSession, layout_id: uuid.UUID, principal: Principal) -> ReportLayout:
    """A layout the principal may see; one they may not is not found, not forbidden."""
    row = await db.scalar(select(ReportLayout).where(ReportLayout.id == layout_id,
                                                     _visible(principal)))  # fmt: skip
    if row is None:
        raise ProblemError(404, "not-found", "No such report layout.")
    return row


async def _own(db: AsyncSession, layout_id: uuid.UUID, principal: Principal) -> ReportLayout:
    row = await get_layout(db, layout_id, principal)
    if row.user_id != principal.user.id:
        raise ProblemError(403, "forbidden", "Only the owner can change this layout.")
    return row


async def _data_source(db: AsyncSession, source: ReportDataSource,
                       principal: Principal) -> dict[str, Any]:  # fmt: skip
    """The data source as stored: a saved view the owner can see, or a query (not both)."""
    from regwatch.search.models import SavedView

    chosen = source.model_dump(mode="json", exclude_unset=True, exclude_none=True)
    if "saved_view_id" in chosen and "query" in chosen:
        raise _invalid("data_source", "a saved view or a query, not both")
    if source.saved_view_id is not None:
        visible = await db.scalar(select(SavedView.id).where(
            SavedView.id == source.saved_view_id,
            or_(SavedView.user_id == principal.user.id, SavedView.shared.is_(True))))  # fmt: skip
        if visible is None:
            raise _invalid("data_source.saved_view_id", "a saved view you can see")
    return chosen


async def _apply(db: AsyncSession, row: ReportLayout, body: ReportLayoutWrite,
                 principal: Principal) -> bool:  # fmt: skip
    """Set what the body gives; True when the layout or its data changed (a new version)."""
    values = body.model_dump(exclude_unset=True)
    for key in ("name", "layout", "page_size", "orientation", "shared"):
        if key in values and values[key] is None:
            raise _invalid(key, "may not be empty")
    if "name" in values:
        name = values["name"].strip()
        if not name or has_control(name):
            raise _invalid("name", "a name of plain text is required")
        row.name = name
    if values.get("shared") is not None and values["shared"] != row.shared:
        # Sharing needs reports.share; withdrawing never does (M7.1 review finding 2).
        if values["shared"] and SHARE not in principal.permissions:
            raise ProblemError(403, "forbidden", "Sharing a layout needs reports.share.")
        row.shared = values["shared"]
    if "page_size" in values:
        row.page_size = values["page_size"]
    if "orientation" in values:
        row.orientation = values["orientation"]
    changed = False
    if "layout" in values:
        fields, sortable = await field_keys(db)
        layout = validate_layout(values["layout"], fields, sortable)
        changed = changed or layout != row.layout
        row.layout = layout
    if "data_source" in values and body.data_source is not None:
        query = await _data_source(db, body.data_source, principal)
        changed = changed or query != (row.query or {})
        row.query = query
    await _shared_view(db, row)
    return changed


async def _shared_view(db: AsyncSession, row: ReportLayout) -> None:
    """A shared layout uses a shared saved view, or none: never shows others the owner's
    private view (M7.1 review finding 1). The renderer checks again for whoever views it."""
    from regwatch.search.models import SavedView

    view_id = (row.query or {}).get("saved_view_id")
    if not row.shared or view_id is None:
        return
    shared = await db.scalar(select(SavedView.shared).where(SavedView.id == uuid.UUID(view_id)))
    if not shared:
        raise _invalid("data_source.saved_view_id",
                       "a shared layout needs a shared saved view, or a query")  # fmt: skip


async def create_layout(db: AsyncSession, body: ReportLayoutWrite, principal: Principal,
                        ip: str | None, template_key: str | None = None) -> LayoutOut:  # fmt: skip
    if "name" not in body.model_fields_set or "layout" not in body.model_fields_set:
        raise _invalid("name" if "name" not in body.model_fields_set else "layout",
                       "a name and a layout are required")  # fmt: skip
    row = ReportLayout(user_id=principal.user.id, name="", layout={}, query={}, shared=False,
                       based_on_template_key=template_key)  # fmt: skip
    await _apply(db, row, body, principal)
    db.add(row)
    await db.flush()
    await db.refresh(row)
    audit(db, "report_layout.create", "report_layout", row.id, actor=principal.user.id, ip=ip,
          after={"name": row.name, "shared": row.shared, "template": template_key})  # fmt: skip
    result = out(row)
    await db.commit()
    return result


async def update_layout(db: AsyncSession, layout_id: uuid.UUID, body: ReportLayoutWrite,
                        principal: Principal, ip: str | None) -> LayoutOut:  # fmt: skip
    row = await _own(db, layout_id, principal)
    before = {"name": row.name, "shared": row.shared, "version": row.version}
    if await _apply(db, row, body, principal):
        row.version += 1
    await db.flush()
    await db.refresh(row)
    after = {"name": row.name, "shared": row.shared, "version": row.version}
    if after != before:
        audit(db, "report_layout.update", "report_layout", row.id, actor=principal.user.id,
              ip=ip, before=before, after=after)  # fmt: skip
    result = out(row)
    await db.commit()
    return result


async def delete_layout(db: AsyncSession, layout_id: uuid.UUID, principal: Principal,
                        ip: str | None) -> None:  # fmt: skip
    row = await _own(db, layout_id, principal)
    audit(db, "report_layout.delete", "report_layout", row.id, actor=principal.user.id, ip=ip,
          before={"name": row.name, "shared": row.shared, "version": row.version})  # fmt: skip
    from regwatch.outputs.models import OutputJob
    from regwatch.outputs.services import detach

    await detach(db, OutputJob.report_layout_id, row.id, "layout")
    await db.delete(row)
    await db.commit()
