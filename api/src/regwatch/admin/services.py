"""Service layer; other modules call this module only through here (ADR-0001).

Runtime settings (``setting`` table, vocabulary in registries.yaml), feature flags and
the audit viewer (#32, M1). Every write adds an ``audit_log`` row with before and after
values in the same transaction.

Settings are read from the database on each use rather than cached per process, so a
write is visible to every API worker at once (M1 "within one reload").
"""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.admin.models import FeatureFlag, Setting
from regwatch.admin.schemas import (
    AuditEntry,
)
from regwatch.admin.schemas import FeatureFlag as FeatureFlagOut
from regwatch.admin.schemas import Setting as SettingOut
from regwatch.core import registry
from regwatch.core.errors import ProblemError, ProblemFieldError
from regwatch.core.models import AuditLog
from regwatch.core.registry import SettingDef
from regwatch.core.schemas import Page
from regwatch.core.services import audit

MAX_STRING = 200_000
HOSTED = {"translation.provider": "http"}
BASIS_KEY = "translation.data_processing_basis"
# Bounds the registry types cannot express; the code reads these settings (#31).
INT_BOUNDS: dict[str, tuple[int, int]] = {
    "auth.lockout_threshold": (3, 100),
    "auth.lockout_minutes": (1, 1440),
    "auth.password_min_length": (12, 128),
    "sessions.idle_timeout_max_minutes": (15, 1440),
    "sessions.absolute_lifetime_hours": (1, 168),
}
BRANDING_KEYS = {
    "site_title": "general.site_title",
    "company_name": "branding.company_name",
    "company_short_name": "branding.company_short_name",
    "company_address": "branding.company_address",
    "primary_color": "branding.primary_color",
}
LEGAL_KEYS = {
    "page_markdown": "legal.page_markdown",
    "required_markings": "legal.required_markings",
}


def _now() -> datetime:
    return datetime.now(UTC)


def invalid(field: str, message: str, status: int = 400) -> ProblemError:
    slug = "invalid-setting" if status == 400 else "validation"
    return ProblemError(status, slug, message,
                        errors=[ProblemFieldError(field=field, message=message)])  # fmt: skip


def not_found(what: str) -> ProblemError:
    return ProblemError(404, "not-found", f"No such {what}.")


def check_value(defn: SettingDef, value: Any) -> Any:
    """``value`` if it fits the definition, else a 400 problem."""
    ok: bool
    match defn.type:
        case "string":
            ok = isinstance(value, str) and len(value) <= MAX_STRING
        case "integer":
            ok = isinstance(value, int) and not isinstance(value, bool)
            low, high = INT_BOUNDS.get(defn.key, (0, 2**31 - 1))
            if ok and not low <= value <= high:
                raise invalid("value", f"must be between {low} and {high}")
        case "number":
            ok = (isinstance(value, int | float) and not isinstance(value, bool)
                  and math.isfinite(value) and value >= 0)  # fmt: skip
        case "boolean":
            ok = isinstance(value, bool)
        case "enum":
            ok = isinstance(value, str) and value in defn.values
        case "list":
            ok = isinstance(value, list) and all(isinstance(v, str) for v in value)
        case _:  # pragma: no cover - SETTING_TYPES is checked by a unit test
            ok = False
    if not ok:
        expected = f"one of {', '.join(defn.values)}" if defn.type == "enum" else defn.type
        raise invalid("value", f"must be {expected}")
    return value


async def values(db: AsyncSession, keys: list[str] | None = None) -> dict[str, Any]:
    """Current values with registry defaults for keys that have no row."""
    defs = registry.settings()
    wanted = keys if keys is not None else list(defs)
    out = {k: defs[k].default for k in wanted if k in defs}
    rows = await db.execute(select(Setting.key, Setting.value).where(Setting.key.in_(wanted)))
    out.update(dict(rows.tuples().all()))
    return out


def _setting_out(defn: SettingDef, row: Setting | None) -> SettingOut:
    out = SettingOut(key=defn.key, value=row.value if row else defn.default, type=defn.type,
                     default=defn.default)  # fmt: skip
    if defn.values:
        out.values = list(defn.values)
    if defn.note:
        out.note = defn.note
    if row is not None:
        out.updated_at = row.updated_at
        out.updated_by = row.updated_by
    return out


async def list_settings(db: AsyncSession) -> list[SettingOut]:
    rows = {r.key: r for r in (await db.scalars(select(Setting))).all()}
    return [_setting_out(d, rows.get(k)) for k, d in sorted(registry.settings().items())]


async def _write(db: AsyncSession, key: str, value: Any, actor: uuid.UUID, ip: str | None,
                 action: str = "setting.update") -> Setting:  # fmt: skip
    row = await db.get(Setting, key)
    before = row.value if row is not None else registry.settings()[key].default
    if row is None:
        row = Setting(key=key, value=value)
        db.add(row)
    row.value, row.updated_by, row.updated_at = value, actor, _now()
    if before != value:
        audit(db, action, "setting", key, actor=actor, ip=ip,
              before={"value": before}, after={"value": value})  # fmt: skip
    return row


async def put_setting(
    db: AsyncSession, key: str, value: Any, actor: uuid.UUID, ip: str | None
) -> SettingOut:
    defn = registry.settings().get(key)
    if defn is None:
        raise not_found("setting")
    check_value(defn, value)
    if HOSTED.get(key) == value and not (await values(db, [BASIS_KEY]))[BASIS_KEY].strip():
        raise invalid("value", f"record {BASIS_KEY} before selecting a hosted provider (8.4)")
    if key == BASIS_KEY and not value.strip():
        current = await values(db, list(HOSTED))
        if any(current[k] == v for k, v in HOSTED.items()):
            raise invalid("value", "a hosted provider is selected; the basis cannot be emptied")
    row = await _write(db, key, value, actor, ip)
    await db.commit()
    return _setting_out(defn, row)


def _flag_out(row: FeatureFlag) -> FeatureFlagOut:
    return FeatureFlagOut(key=row.key, enabled=row.enabled, description=row.description)


async def list_flags(db: AsyncSession) -> list[FeatureFlagOut]:
    rows = await db.scalars(select(FeatureFlag).order_by(FeatureFlag.key))
    return [_flag_out(r) for r in rows.all()]


async def set_flag(
    db: AsyncSession, key: str, enabled: bool, actor: uuid.UUID, ip: str | None
) -> FeatureFlagOut:
    row = await db.get(FeatureFlag, key)
    if row is None:
        raise not_found("feature flag")
    if enabled and key == "translation.enabled":
        current = await values(db, ["translation.provider", BASIS_KEY])
        if current["translation.provider"] == "http" and not current[BASIS_KEY].strip():
            raise ProblemError(409, "precondition", f"Record {BASIS_KEY} first (8.4).")
    if row.enabled != enabled:
        audit(db, "feature_flag.update", "feature_flag", key, actor=actor, ip=ip,
              before={"enabled": row.enabled}, after={"enabled": enabled})  # fmt: skip
        row.enabled, row.updated_by, row.updated_at = enabled, actor, _now()
    await db.commit()
    return _flag_out(row)


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
