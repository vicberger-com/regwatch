"""The report component palette and layout validation (M7, ADR-0005).

A layout is Puck data: ``{root: {props}, content: [{type, props: {id, ...}}]}``. Every
component's props are checked against its schema here, before a layout is saved or rendered:
unknown types and unknown props are refused, text has length limits and no control or
direction-changing characters, and field keys must be on the whitelist (``fields.py``).
``zones`` (Puck's legacy DropZone) is refused: layouts use a flat list (R-02 S8).

Charts and the map snapshot need a JavaScript renderer or a browser; they arrive with their
own slice (M7.5) and are refused until then.
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError

from regwatch.core.errors import ProblemError, ProblemFieldError
from regwatch.core.schemas import has_control

MAX_COMPONENTS = 200
MAX_LAYOUT_BYTES = 256 * 1024


def _plain(value: str) -> str:
    if has_control(value):
        raise ValueError("control and direction-changing characters are not allowed")
    return value


def _plain_block(value: str) -> str:
    """Paragraph text may hold line breaks; nothing else that controls the display."""
    if has_control(value.replace("\n", " ").replace("\r", " ")):
        raise ValueError("control and direction-changing characters are not allowed")
    return value


Line = Annotated[str, AfterValidator(_plain)]
Block = Annotated[str, AfterValidator(_plain_block)]
Key = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:-]{1,80}$")]


class _Props(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")]


class Heading(_Props):
    text: Line = Field(max_length=200)
    level: Literal[1, 2, 3] = 2


class Paragraph(_Props):
    text: Block = Field(max_length=5000)


class FieldValue(_Props):
    """One field of the first row, for a single-item or single-jurisdiction page."""

    field: Key
    label: Line | None = Field(default=None, max_length=120)


class ItemsTable(_Props):
    columns: list[Key] = Field(min_length=1, max_length=12)
    sort: Key | None = None
    direction: Literal["asc", "desc"] = "desc"
    limit: int = Field(default=50, ge=1, le=500)
    caption: Line | None = Field(default=None, max_length=200)


class ChangeList(_Props):
    title: Line | None = Field(default=None, max_length=200)
    limit: int = Field(default=10, ge=1, le=100)


class JurisdictionSummary(_Props):
    title: Line | None = Field(default=None, max_length=200)


class PageBreak(_Props):
    pass


class HeaderFooter(_Props):
    header_text: Line | None = Field(default=None, max_length=200)
    footer_text: Line | None = Field(default=None, max_length=200)
    page_numbers: bool = True
    date: bool = True


class LegalMarkings(_Props):
    """The company's legal markings and branding from M1 (M7 question 3)."""


class StatusMatrix(_Props):
    """Items per jurisdiction and status (new, updated, unchanged, archived) in the rows."""

    title: Line | None = Field(default=None, max_length=200)


class SourceHealth(_Props):
    """Every source's health and last success; shown only to viewers with sources.read."""

    title: Line | None = Field(default=None, max_length=200)


PALETTE: dict[str, type[_Props]] = {
    "Heading": Heading, "Paragraph": Paragraph, "FieldValue": FieldValue,
    "ItemsTable": ItemsTable, "ChangeList": ChangeList,
    "JurisdictionSummary": JurisdictionSummary, "PageBreak": PageBreak,
    "HeaderFooter": HeaderFooter, "LegalMarkings": LegalMarkings,
    "StatusMatrix": StatusMatrix, "SourceHealth": SourceHealth,
}  # fmt: skip


class RootProps(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Line | None = Field(default=None, max_length=200)


class Component(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    props: dict[str, Any]


class Layout(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root: dict[str, Any] = Field(default_factory=dict)
    content: list[Component] = Field(default_factory=list, max_length=MAX_COMPONENTS)
    zones: dict[str, Any] = Field(default_factory=dict)


def _fail(field: str, message: str) -> ProblemError:
    return ProblemError(422, "validation", "The layout is not valid.",
                        errors=[ProblemFieldError(field=field, message=message)])  # fmt: skip


def _first_error(exc: ValidationError, prefix: str) -> ProblemError:
    error = exc.errors(include_url=False)[0]
    where = ".".join(str(p) for p in error["loc"])
    return _fail(f"{prefix}.{where}" if where else prefix, error["msg"])


def validate_layout(data: dict[str, Any], fields: set[str],
                    sortable: set[str]) -> dict[str, Any]:  # fmt: skip
    """The layout as stored: every component checked, defaults filled in, ids unique."""
    if len(json.dumps(data, separators=(",", ":"))) > MAX_LAYOUT_BYTES:
        raise _fail("layout", f"at most {MAX_LAYOUT_BYTES // 1024} KB")
    try:
        layout = Layout.model_validate(data)
    except ValidationError as exc:
        raise _first_error(exc, "layout") from None
    if layout.zones:
        raise _fail("layout.zones", "zones are not used; place components in content")
    try:
        root = RootProps.model_validate(layout.root.get("props", {}))
    except ValidationError as exc:
        raise _first_error(exc, "layout.root.props") from None
    seen: set[str] = set()
    content: list[dict[str, Any]] = []
    for n, component in enumerate(layout.content):
        where = f"layout.content.{n}"
        model = PALETTE.get(component.type)
        if model is None:
            raise _fail(f"{where}.type", f"one of: {', '.join(sorted(PALETTE))}")
        try:
            props = model.model_validate(component.props)
        except ValidationError as exc:
            raise _first_error(exc, f"{where}.props") from None
        if props.id in seen:
            raise _fail(f"{where}.props.id", "each component needs its own id")
        seen.add(props.id)
        for key in _field_keys(props):
            if key not in fields:
                raise _fail(f"{where}.props", f"{key!r} is not a report field")
        if isinstance(props, ItemsTable) and props.sort and props.sort not in sortable:
            raise _fail(f"{where}.props.sort", f"{props.sort!r} cannot be sorted on")
        content.append({"type": component.type, "props": props.model_dump(mode="json")})
    return {"root": {"props": root.model_dump(mode="json", exclude_none=True)},
            "content": content}  # fmt: skip


def _field_keys(props: _Props) -> list[str]:
    if isinstance(props, ItemsTable):
        return [*props.columns, *([props.sort] if props.sort else [])]
    if isinstance(props, FieldValue):
        return [props.field]
    return []
