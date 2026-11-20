"""SQLAlchemy models. Tables come from docs/contracts/schema.sql (migration 0001, #28)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from regwatch.core.db import Base


class OutputJob(Base):
    __tablename__ = "output_job"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("uuidv7()"))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id"))
    kind: Mapped[str]
    report_layout_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("report_layout.id"))
    report_template_key: Mapped[str | None] = mapped_column(ForeignKey("report_template.key"))
    saved_view_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("saved_view.id"))
    # SQL NULL, not JSON null, so the one-source CHECK counts it as absent.
    query: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    destination: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(server_default=text("'queued'"))
    artifact_ref: Mapped[str | None]
    artifact_bytes: Mapped[int | None]
    error_class: Mapped[str | None]
    error_message: Mapped[str | None]
    scheduled_cron: Mapped[str | None]
    schedule_timezone: Mapped[str | None]
    next_run_at: Mapped[datetime | None]
    parent_job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("output_job.id"))
    layout_version: Mapped[int | None]
    attempts: Mapped[int] = mapped_column(server_default=text("0"))
    finished_at: Mapped[datetime | None]
