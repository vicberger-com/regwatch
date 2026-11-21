"""Pydantic schemas matching openapi/regwatch.v1.yaml (output jobs and printers)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from regwatch.core.schemas import UNSET, Email
from regwatch.reports.schemas import ReportParams
from regwatch.search.schemas import Query


class OutputKind(StrEnum):
    pdf = "pdf"
    email = "email"
    print = "print"
    csv = "csv"


class OutputSource(BaseModel):
    """Exactly one of the properties."""

    report_layout_id: UUID = UNSET
    report_template_key: str = UNSET
    saved_view_id: UUID = UNSET
    query: Query = UNSET


class OutputDestination(BaseModel):
    emails: list[Email] = Field(default=UNSET, max_length=50)
    subject: str = Field(default=UNSET, max_length=200)
    message: str = Field(default=UNSET, max_length=5000)
    printer_id: UUID = UNSET
    copies: int = Field(default=1, ge=1, le=20)


class OutputSchedule(BaseModel):
    cron: str = UNSET
    timezone: str = UNSET


class OutputRequest(BaseModel):
    kind: OutputKind
    source: OutputSource
    params: ReportParams = UNSET
    destination: OutputDestination = UNSET
    schedule: OutputSchedule | None = None


class OutputJob(BaseModel):
    id: UUID
    kind: OutputKind
    status: Literal["queued", "rendering", "sent", "failed", "cancelled"]
    requested_by: UUID = UNSET
    source_summary: str = UNSET
    destination_summary: str = UNSET
    artifact_available: bool = UNSET
    artifact_bytes: int | None = None
    error_class: str | None = None
    error_message: str | None = None
    scheduled_cron: str | None = None
    next_run_at: datetime | None = None
    attempts: int = UNSET
    created_at: datetime
    finished_at: datetime | None = None


class Printer(BaseModel):
    id: UUID = UNSET
    name: str = UNSET
    ipp_url: str = UNSET
    default_media: str = UNSET
    enabled: bool = UNSET
    tls_sha256: str | None = UNSET  # CP-33


class PrinterWrite(BaseModel):
    name: str = Field(default=UNSET, min_length=1, max_length=100)
    ipp_url: str = Field(default=UNSET, pattern=r"^ipps?://", max_length=500)
    default_media: str = Field(default=UNSET, pattern=r"^[a-z0-9_.-]{1,64}$")
    enabled: bool = UNSET
    # CP-33: the SHA-256 of the printer's DER certificate, 64 hex digits (colons allowed)
    tls_sha256: str | None = Field(default=UNSET, pattern=r"^[0-9A-Fa-f:]{64,95}$")


class PrinterChoice(BaseModel):
    """CP-33 ``GET /printers``: what New output offers (``outputs.print``)."""

    id: UUID
    name: str
