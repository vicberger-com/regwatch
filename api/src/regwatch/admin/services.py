"""Service layer; other modules call this module only through here (ADR-0001).

The audit viewer (#32): ``audit_log`` rows filtered by actor, action, entity and time,
newest first, with the actor's email.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.admin.schemas import (
    AuditEntry,
)
from regwatch.core.models import AuditLog
from regwatch.core.schemas import Page


async def list_audit(
    db: AsyncSession,
    page: int,
    page_size: int,
    *,
    actor: uuid.UUID | None = None,
    action: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    from_: datetime | None = None,
    to: datetime | None = None,
) -> Page[AuditEntry]:
    from regwatch.identity.models import User

    conds: list[Any] = []
    if actor is not None:
        conds.append(AuditLog.actor_user_id == actor)
    if action:
        conds.append(AuditLog.action == action)
    if entity_type:
        conds.append(AuditLog.entity_type == entity_type)
    if entity_id:
        conds.append(AuditLog.entity_id == entity_id)
    if from_ is not None:
        conds.append(AuditLog.occurred_at >= from_)
    if to is not None:
        conds.append(AuditLog.occurred_at < to)
    total = await db.scalar(select(func.count()).select_from(AuditLog).where(*conds)) or 0
    rows = await db.execute(
        select(AuditLog, User.email)
        .outerjoin(User, User.id == AuditLog.actor_user_id)
        .where(*conds)
        .order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    items = [
        AuditEntry(
            id=r.id,
            occurred_at=r.occurred_at,
            actor_user_id=r.actor_user_id,
            actor_email=email,
            action=r.action,
            entity_type=r.entity_type,
            entity_id=r.entity_id,
            before=r.before,
            after=r.after,
            ip=str(r.ip) if r.ip else None,
            request_id=r.request_id,
        )  # fmt: skip
        for r, email in rows.tuples().all()
    ]
    return Page[AuditEntry](items=items, total=total, page=page, page_size=page_size)
