"""Stock reports (M7.3, REQ-10): the seeded templates, copied into a user's own layout, and the
parameters they take when they render (E17 at print time).

Parameters only narrow the data source: a jurisdiction (an active code), the days covered, and
facet terms (checked by the search service). Each is validated before it reaches the query.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.core.errors import ProblemError, ProblemFieldError
from regwatch.identity.services import Principal
from regwatch.reports import services
from regwatch.reports.models import ReportTemplate as TemplateRow
from regwatch.reports.schemas import (
    ReportDataSource,
    ReportLayout,
    ReportLayoutWrite,
    ReportParameterDef,
    ReportTemplate,
    TemplateParameter,
)
from regwatch.search.schemas import Query

_PARAMETERS = TypeAdapter(list[TemplateParameter])


def _invalid(field: str, message: str) -> ProblemError:
    return ProblemError(422, "validation", "The report parameters are not valid.",
                        errors=[ProblemFieldError(field=field, message=message)])  # fmt: skip


def parameters_of(row: TemplateRow | None) -> list[TemplateParameter]:
    if row is None:
        return []
    return _PARAMETERS.validate_python((row.query or {}).get("parameters", []))


async def list_templates(db: AsyncSession) -> list[ReportTemplate]:
    rows = (await db.scalars(select(TemplateRow).order_by(TemplateRow.label))).all()
    return [ReportTemplate(
        key=r.key, label=r.label, description=r.description or "", thumbnail_url=None,
        version=r.version,
        parameters=[ReportParameterDef(key=p.key, label=p.label, type=p.type,
                                       required=p.required, default=p.default)
                    for p in parameters_of(r)],
    ) for r in rows]  # fmt: skip


async def instantiate(db: AsyncSession, key: str, principal: Principal,
                      ip: str | None) -> ReportLayout:  # fmt: skip
    row = await db.scalar(select(TemplateRow).where(TemplateRow.key == key))
    if row is None:
        raise ProblemError(404, "not-found", "No such stock report.")
    source = ReportDataSource.model_validate((row.query or {}).get("data_source", {}))
    body = ReportLayoutWrite(name=row.label, layout=row.layout, data_source=source)
    return await services.create_layout(db, body, principal, ip, template_key=row.key)


async def apply(db: AsyncSession, query: Query, template_key: str | None,
                given: dict[str, Any]) -> Query:  # fmt: skip
    """``query`` narrowed by the parameters the layout's template defines; others refused."""
    from regwatch.taxonomy.models import Jurisdiction

    row = (await db.scalar(select(TemplateRow).where(TemplateRow.key == template_key))
           if template_key else None)  # fmt: skip
    defined = {p.key: p for p in parameters_of(row)}
    if unknown := sorted(set(given) - set(defined)):
        raise _invalid(unknown[0], "this report takes no such parameter")
    filters = query.filters.model_dump(mode="json", exclude_unset=True, by_alias=True) \
        if "filters" in query.model_fields_set else {}  # fmt: skip
    for key, definition in defined.items():
        value = given.get(key, definition.default)
        if value is None:
            if definition.required:
                raise _invalid(key, f"{definition.label} is needed")
            continue
        if key == "jurisdiction":
            code = str(value).upper()
            active = await db.scalar(select(Jurisdiction.code).where(
                Jurisdiction.code == code, Jurisdiction.active.is_(True)))  # fmt: skip
            if active is None:
                raise _invalid(key, "an active jurisdiction code, such as DE")
            filters["jurisdictions"] = [code]
        elif key == "period_days":
            if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 3660:
                raise _invalid(key, "a number of days from 1 to 3660")
            since = datetime.now(UTC) - timedelta(days=value)
            filters["changed"] = {"from": since.isoformat()}
        elif key == "facet_terms":
            try:
                filters["terms"] = TypeAdapter(dict[str, list[str]]).validate_python(value)
            except ValidationError:
                raise _invalid(key, "facet keys with lists of term keys") from None
    try:
        return query.model_copy(update={"filters": type(query).model_validate(
            {"filters": filters}).filters})  # fmt: skip
    except ValidationError as exc:
        raise _invalid("params", exc.errors(include_url=False)[0]["msg"]) from None
