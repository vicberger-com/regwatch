"""Shared services other modules call (ADR-0001): audit logging."""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.core.models import AuditLog


def audit(
    db: AsyncSession,
    action: str,
    entity_type: str,
    entity_id: str | uuid.UUID | None = None,
    *,
    actor: uuid.UUID | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    ip: str | None = None,
) -> None:
    """Add an ``audit_log`` row to ``db``; it is written when the caller commits."""
    db.add(
        AuditLog(
            actor_user_id=actor,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            before=before,
            after=after,
            ip=ip,
            request_id=structlog.contextvars.get_contextvars().get("request_id"),
        )
    )
