"""SQLAlchemy models. Tables come from docs/contracts/schema.sql (migration 0001, #28).

Columns M2 reads or writes are mapped; ``created_at`` and ``updated_at`` stay server-side.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from regwatch.core.db import Base


class Jurisdiction(Base):
    __tablename__ = "jurisdiction"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("uuidv7()"))
    code: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str]
    kind: Mapped[str]
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jurisdiction.id"))
    region_code: Mapped[str | None]
    geometry_ref: Mapped[str | None]
    active: Mapped[bool] = mapped_column(server_default=text("true"))


class Facet(Base):
    __tablename__ = "facet"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("uuidv7()"))
    key: Mapped[str] = mapped_column(unique=True)
    label: Mapped[str]
    value_type: Mapped[str]
    multi: Mapped[bool]
    required: Mapped[bool]
    show_in_view_selector: Mapped[bool]
    show_in_filters: Mapped[bool]
    sort_order: Mapped[int]
    system: Mapped[bool]
    hidden: Mapped[bool] = mapped_column(server_default=text("false"))


class Term(Base):
    __tablename__ = "term"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("uuidv7()"))
    facet_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facet.id", ondelete="CASCADE"))
    key: Mapped[str]
    label: Mapped[str]
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("term.id"))
    synonyms: Mapped[list[str]] = mapped_column(ARRAY(Text))
    match_rules: Mapped[dict[str, Any]] = mapped_column(JSONB)
    color_token: Mapped[str | None]
    active: Mapped[bool] = mapped_column(server_default=text("true"))
