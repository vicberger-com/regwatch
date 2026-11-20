"""SQLAlchemy models. Tables come from docs/contracts/schema.sql (migration 0001, #28)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    ColumnElement,
    ForeignKey,
    Select,
    and_,
    column,
    exists,
    func,
    or_,
    select,
    table,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from regwatch.core.db import Base


class Source(Base):
    __tablename__ = "source"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("uuidv7()"))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    name: Mapped[str]
    kind: Mapped[str]
    url: Mapped[str | None]
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    default_jurisdiction_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), server_default=text("'{}'")
    )
    default_term_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), server_default=text("'{}'")
    )
    credibility: Mapped[str] = mapped_column(server_default=text("'official'"))
    robots_policy: Mapped[str] = mapped_column(server_default=text("'respect'"))
    override_reason: Mapped[str | None]
    terms_url: Mapped[str | None]
    language: Mapped[str | None]
    enabled: Mapped[bool] = mapped_column(server_default=text("true"))
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user.id"))
    health: Mapped[str] = mapped_column(server_default=text("'unknown'"))
    consecutive_failures: Mapped[int] = mapped_column(server_default=text("0"))
    catalogue_key: Mapped[str | None]  # CP-25: from seed/catalogue.yaml
    summary: Mapped[str | None]


class SourceFollower(Base):
    """A user who follows a catalogue source (CP-25, migration 0008)."""

    __tablename__ = "source_follower"

    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


def capturing() -> ColumnElement[bool]:
    """Whether a source is captured (ADR-0012): enabled, or a catalogue source that someone
    follows. Every capture gate uses this with ``CaptureJob.enabled``, so an admin still stops
    a followed source by turning its job off (``DELETE /sources/{id}``). Only active users'
    follows count: a disabled or locked user keeps nothing fetched (11.2b review)."""
    return or_(Source.enabled, and_(Source.catalogue_key.is_not(None), _followed()))


# The user table by name: capture never imports identity's models (one-way dependency).
_USERS = table("user", column("id"), column("status"))


def _followed() -> ColumnElement[bool]:
    """Whether an active user follows the source in the enclosing query."""
    return exists().where(SourceFollower.source_id == Source.id,
                          _USERS.c.id == SourceFollower.user_id,
                          _USERS.c.status == "active")  # fmt: skip


def active_followers() -> Select[tuple[int]]:
    """How many active users follow the source in the enclosing query (admins' count)."""
    return (select(func.count()).select_from(SourceFollower)
            .join(_USERS, _USERS.c.id == SourceFollower.user_id)
            .where(SourceFollower.source_id == Source.id, _USERS.c.status == "active"))  # fmt: skip


async def is_capturing(db: AsyncSession, source_id: uuid.UUID) -> bool:
    return bool(await db.scalar(select(capturing()).where(Source.id == source_id)))


class CaptureJob(Base):
    __tablename__ = "capture_job"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("uuidv7()"))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source.id", ondelete="CASCADE"))
    cron: Mapped[str | None]
    interval_seconds: Mapped[int | None]
    timezone: Mapped[str] = mapped_column(server_default=text("'UTC'"))
    max_items_per_run: Mapped[int] = mapped_column(server_default=text("200"))
    rate_limit_per_minute: Mapped[int] = mapped_column(server_default=text("30"))
    render_js: Mapped[bool] = mapped_column(server_default=text("false"))
    extraction_rules: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    change_threshold_pct: Mapped[Decimal] = mapped_column(server_default=text("5"))
    enabled: Mapped[bool] = mapped_column(server_default=text("true"))
    next_run_at: Mapped[datetime | None]
    last_run_at: Mapped[datetime | None]
    # CP-14; the worker writes it. None is SQL NULL, never JSON null (migration 0004).
    cursor: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))


class CaptureRun(Base):
    __tablename__ = "capture_run"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("uuidv7()"))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("capture_job.id", ondelete="CASCADE"))
    started_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    finished_at: Mapped[datetime | None]
    status: Mapped[str] = mapped_column(server_default=text("'running'"))
    items_new: Mapped[int] = mapped_column(server_default=text("0"))
    items_changed: Mapped[int] = mapped_column(server_default=text("0"))
    items_unchanged: Mapped[int] = mapped_column(server_default=text("0"))
    http_status: Mapped[int | None]
    bytes_fetched: Mapped[int] = mapped_column(server_default=text("0"))
    error_class: Mapped[str | None]
    error_message: Mapped[str | None]  # at most 500 characters, never page content
    robots_decision: Mapped[str | None]
    triggered_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user.id"))
