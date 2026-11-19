"""Saved views (M5 interfaces ``/views``; Q3: shareable with a ``shared`` flag and curation).

- A user sees their own views and every shared view. A shared view belongs to no user
  (``user_id`` NULL, as ``schema.sql`` says) and only ``views.manage_shared`` makes, edits,
  unshares or deletes one; that is audited. Another user's private view is a 404 (never a 403,
  so its existence is not told).
- ``filters`` must be a valid ``QueryFilters``; ``view_by`` is ``country``, ``region``,
  ``regulation`` or the key of a facet shown in the view selector.
- ``q``: ``saved_view`` has no column for it, so it is kept in ``filters`` under ``Q_KEY`` until
  the CP proposed in BL-113 adds one; it never reaches the query as a filter.
- One default view per user; at most ``MAX_VIEWS`` own views.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.admin.services import not_found
from regwatch.core.errors import ProblemError, ProblemFieldError
from regwatch.core.services import audit
from regwatch.identity.services import Principal
from regwatch.search.models import SavedView
from regwatch.search.schemas import QueryFilters, SavedViewWrite
from regwatch.search.schemas import SavedView as ViewOut
from regwatch.taxonomy.models import Facet

MANAGE_SHARED = "views.manage_shared"
MAX_VIEWS = 100
MAX_Q = 500
Q_KEY = "_q"
FIXED_VIEW_BY = ("country", "region", "regulation")


def _invalid(field: str, message: str) -> ProblemError:
    return ProblemError(422, "validation", message,
                        errors=[ProblemFieldError(field=field, message=message)])  # fmt: skip


def out(view: SavedView) -> ViewOut:
    stored = dict(view.filters or {})
    q = stored.pop(Q_KEY, None)
    return ViewOut(
        id=view.id, user_id=view.user_id, name=view.name, view_by=view.view_by,
        filters=QueryFilters.model_validate(stored), q=q if isinstance(q, str) else None,
        period_days=view.period_days, color_scheme=view.color_scheme,
        is_default=view.is_default, shared=view.shared, updated_at=view.updated_at,
    )  # fmt: skip


async def list_views(db: AsyncSession, principal: Principal) -> list[ViewOut]:
    rows = await db.scalars(select(SavedView).where(
        or_(SavedView.user_id == principal.user.id, SavedView.shared.is_(True)))
        .order_by(SavedView.shared, SavedView.name, SavedView.id))  # fmt: skip
    return [out(v) for v in rows.all()]


async def _check(db: AsyncSession, body: SavedViewWrite) -> None:
    if "view_by" in body.model_fields_set and body.view_by not in FIXED_VIEW_BY:
        known = await db.scalar(select(Facet.key).where(Facet.key == body.view_by,
                                                        Facet.show_in_view_selector))  # fmt: skip
        if known is None:
            raise _invalid("view_by", "country, region, regulation or a view selector facet")
    if body.q is not None and len(body.q) > MAX_Q:
        raise _invalid("q", f"at most {MAX_Q} characters")
    if "name" in body.model_fields_set and not (body.name or "").strip():
        raise _invalid("name", "a name is required")


def _apply(view: SavedView, body: SavedViewWrite) -> None:
    fields = body.model_fields_set
    if "name" in fields:
        view.name = (body.name or "").strip()
    for field in ("view_by", "period_days", "color_scheme"):
        if field in fields and getattr(body, field) is not None:
            setattr(view, field, getattr(body, field))
    stored = dict(view.filters or {})
    if "filters" in fields:
        q = stored.get(Q_KEY)
        stored = (body.filters or QueryFilters()).model_dump(mode="json", by_alias=True,
                                                              exclude_none=True)  # fmt: skip
        if q is not None:
            stored[Q_KEY] = q
    if "q" in fields:
        stored.pop(Q_KEY, None)
        if body.q:
            stored[Q_KEY] = body.q
    view.filters = stored


async def _default(db: AsyncSession, view: SavedView, principal: Principal,
                   wanted: bool | None) -> None:  # fmt: skip
    if wanted is None or view.shared:
        return
    if wanted:
        await db.execute(update(SavedView).where(SavedView.user_id == principal.user.id,
                                                 SavedView.id != view.id)
                         .values(is_default=False))  # fmt: skip
    view.is_default = wanted


def _shared_change(view: SavedView, principal: Principal) -> None:
    if MANAGE_SHARED not in principal.permissions:
        raise ProblemError(403, "forbidden", "Shared views need views.manage_shared.")


async def create_view(db: AsyncSession, body: SavedViewWrite, principal: Principal,
                      ip: str | None) -> ViewOut:  # fmt: skip
    if "name" not in body.model_fields_set:
        raise _invalid("name", "a name is required")
    await _check(db, body)
    shared = bool(body.shared)
    if shared:
        _shared_change(SavedView(), principal)
    else:
        mine = await db.scalar(select(func.count()).select_from(SavedView)
                               .where(SavedView.user_id == principal.user.id))  # fmt: skip
        if (mine or 0) >= MAX_VIEWS:
            raise _invalid("name", f"at most {MAX_VIEWS} views each")
    view = SavedView(user_id=None if shared else principal.user.id, shared=shared,
                     name="", filters={}, is_default=False)  # fmt: skip
    _apply(view, body)
    db.add(view)
    await db.flush()
    await _default(db, view, principal, body.is_default if "is_default" in body.model_fields_set
                   else None)  # fmt: skip
    if shared:
        audit(db, "saved_view.create", "saved_view", view.id, actor=principal.user.id, ip=ip,
              after={"name": view.name, "shared": True})  # fmt: skip
    await db.commit()
    await db.refresh(view)
    return out(view)


async def _mine(db: AsyncSession, view_id: uuid.UUID, principal: Principal) -> SavedView:
    view = await db.scalar(select(SavedView).where(SavedView.id == view_id).with_for_update())
    if view is None or (not view.shared and view.user_id != principal.user.id):
        raise not_found("view")
    if view.shared:
        _shared_change(view, principal)
    return view


async def update_view(db: AsyncSession, view_id: uuid.UUID, body: SavedViewWrite,
                      principal: Principal, ip: str | None) -> ViewOut:  # fmt: skip
    view = await _mine(db, view_id, principal)
    await _check(db, body)
    was_shared = view.shared
    before: dict[str, Any] = {"name": view.name, "shared": view.shared}
    if "shared" in body.model_fields_set and body.shared is not None and body.shared != view.shared:
        _shared_change(view, principal)
        view.shared = body.shared
        view.user_id = None if body.shared else principal.user.id
        view.is_default = False
    _apply(view, body)
    await _default(db, view, principal, body.is_default if "is_default" in body.model_fields_set
                   else None)  # fmt: skip
    view.updated_at = datetime.now(UTC)
    if was_shared or view.shared:
        audit(db, "saved_view.update", "saved_view", view.id, actor=principal.user.id, ip=ip,
              before=before, after={"name": view.name, "shared": view.shared})  # fmt: skip
    await db.commit()
    await db.refresh(view)
    return out(view)


async def delete_view(db: AsyncSession, view_id: uuid.UUID, principal: Principal,
                      ip: str | None) -> None:  # fmt: skip
    view = await _mine(db, view_id, principal)
    if view.shared:
        audit(db, "saved_view.delete", "saved_view", view.id, actor=principal.user.id, ip=ip,
              before={"name": view.name, "shared": True})  # fmt: skip
    await db.delete(view)
    await db.commit()
