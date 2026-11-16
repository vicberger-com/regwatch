"""Service layer; other modules call this module only through here (ADR-0001).

Runtime settings (``setting`` table, vocabulary in registries.yaml), feature flags, branding,
the legal page text and the audit viewer (#32, M1). Every write adds an ``audit_log`` row with
before and after values in the same transaction.

Settings are read from the database on each use rather than cached per process, so a write
is visible to every API worker at once (M1 "within one reload").
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.admin import legal as legal_page
from regwatch.admin import logo
from regwatch.admin.models import FeatureFlag, Setting
from regwatch.admin.schemas import (
    AuditEntry,
    Branding,
    BrandingPublic,
    BrandingWrite,
    Legal,
    LegalWrite,
)
from regwatch.admin.schemas import FeatureFlag as FeatureFlagOut
from regwatch.admin.schemas import Setting as SettingOut
from regwatch.core import objectstore, registry
from regwatch.core.errors import ProblemError, ProblemFieldError
from regwatch.core.models import AuditLog
from regwatch.core.registry import SettingDef
from regwatch.core.schemas import Page, check_email, has_control
from regwatch.core.services import audit

MAX_STRING = 200_000
# Hosted model providers need a recorded data-processing basis first (8.4). The registry has one
# basis key, named for translation; it covers the classification model too until a CP gives it
# a general name (BL-85; PR 11 peer review).
HOSTED = {"translation.provider": "http", "classification.model_provider": "http"}
BASIS_KEY = "translation.data_processing_basis"
# Flags that switch on a step using one of those providers.
FLAG_PROVIDER = {"translation.enabled": "translation.provider",
                 "classification.model": "classification.model_provider"}  # fmt: skip
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


# Settings that also have a dedicated route keep that route's limits here (review finding 8).
_DEDICATED: dict[str, tuple[type[BaseModel], str]] = {
    **{key: (BrandingWrite, field) for field, key in BRANDING_KEYS.items()},
    **{key: (LegalWrite, field) for field, key in LEGAL_KEYS.items()},
}


# String settings that are multi-line text; every other string goes into headers, titles or
# URLs and must hold no control characters (re-review N3).
MULTILINE = {"legal.page_markdown", "legal.required_markings", "branding.company_address"}


def _check_owned_by_dedicated_route(key: str, value: Any) -> None:
    texts = value if isinstance(value, list) else [value]
    if any(isinstance(t, str) and has_control(t, allow_newlines=key in MULTILINE) for t in texts):
        raise invalid("value", "must not contain control characters")
    if key == "general.contact_email" and value:
        try:
            check_email(value)
        except ValueError as exc:
            raise invalid("value", str(exc)) from exc
    if key == "taxonomy.version":
        raise invalid("value", "maintained by the taxonomy service, not by the settings API")
    if key == "branding.logo_ref":
        raise invalid("value", "set by the logo upload, not by the settings API")
    if key in _DEDICATED:
        model, field = _DEDICATED[key]
        try:
            empty_colour = field == "primary_color" and value == ""
            model.model_validate({field: None if empty_colour else value})
        except ValidationError as exc:
            raise invalid("value", exc.errors()[0]["msg"]) from exc


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
    _check_owned_by_dedicated_route(key, value)
    if HOSTED.get(key) == value and not (await values(db, [BASIS_KEY]))[BASIS_KEY].strip():
        raise invalid("value", f"record {BASIS_KEY} before selecting a hosted provider (8.4)")
    if key == BASIS_KEY and not value.strip():
        current = await values(db, list(HOSTED))
        if any(current[k] == v for k, v in HOSTED.items()):
            raise invalid("value", "a hosted provider is selected; the basis cannot be emptied")
    if key == "legal.page_markdown":  # the same budget as PUT /admin/legal (review N1)
        await _check_legal_budget("value", value)
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
    provider_key = FLAG_PROVIDER.get(key)
    if enabled and provider_key:
        current = await values(db, [provider_key, BASIS_KEY])
        if current[provider_key] == HOSTED[provider_key] and not current[BASIS_KEY].strip():
            raise ProblemError(409, "precondition", f"Record {BASIS_KEY} first (8.4).")
    if row.enabled != enabled:
        audit(db, "feature_flag.update", "feature_flag", key, actor=actor, ip=ip,
              before={"enabled": row.enabled}, after={"enabled": enabled})  # fmt: skip
        row.enabled, row.updated_by, row.updated_at = enabled, actor, _now()
    await db.commit()
    return _flag_out(row)


async def branding(db: AsyncSession) -> Branding:
    keys = [*BRANDING_KEYS.values(), "branding.logo_ref", "legal.required_markings"]
    current = await values(db, keys)
    out = Branding(**{field: current[key] for field, key in BRANDING_KEYS.items()})
    out.primary_color = current["branding.primary_color"] or None
    # The key holds the content hash, so a new upload gives a new URL (CP-07).
    ref = current["branding.logo_ref"]
    match = LOGO_KEY.fullmatch(ref) if ref else None
    out.logo_url = f"/api/v1/branding/logo?v={match['sha'][:12]}" if match else None
    out.required_markings = current["legal.required_markings"]
    return out


async def branding_public(db: AsyncSession) -> BrandingPublic:
    """The sign-in page's subset of the branding (CP-08)."""
    full = await branding(db)
    page = (await values(db, ["legal.page_markdown"]))["legal.page_markdown"]
    return BrandingPublic(site_title=full.site_title, logo_url=full.logo_url,
                          primary_color=full.primary_color,
                          has_legal_page=bool(page.strip()))  # fmt: skip


async def put_branding(
    db: AsyncSession, body: BrandingWrite, actor: uuid.UUID, ip: str | None
) -> Branding:
    for field in body.model_fields_set:
        value = getattr(body, field)
        key = BRANDING_KEYS[field]
        if isinstance(value, str) and has_control(value, allow_newlines=key in MULTILINE):
            raise invalid(field, "must not contain control characters")  # re-review N3b
        await _write(db, key, "" if value is None else value, actor, ip,
                     action="branding.update")  # fmt: skip
    await db.commit()
    return await branding(db)


LOGO_KEY = re.compile(r"branding/logo-(?P<sha>[0-9a-f]{64})\.(?P<ext>png|svg)")
LOGO_TYPES = {"png": logo.PNG, "svg": logo.SVG}


async def upload_logo(db: AsyncSession, data: bytes, actor: uuid.UUID, ip: str | None) -> Branding:
    """Check, store and select a new logo (BL-68). Old logo files stay for the audit trail."""
    try:  # parsing an SVG costs up to about 40 times its size, so not on the event loop
        media_type = await asyncio.to_thread(logo.check, data)
    except logo.LogoRejectedError as exc:
        raise ProblemError(415, "unsupported-media-type", str(exc)) from None
    ext = "png" if media_type == logo.PNG else "svg"
    key = f"branding/logo-{hashlib.sha256(data).hexdigest()}.{ext}"
    await objectstore.put(key, data)
    await _write(db, "branding.logo_ref", key, actor, ip, action="branding.logo")
    await db.commit()
    return await branding(db)


async def logo_file(db: AsyncSession) -> tuple[bytes, str, str] | None:
    """The current logo's bytes, media type and content hash, or None (CP-07)."""
    ref = (await values(db, ["branding.logo_ref"]))["branding.logo_ref"]
    match = LOGO_KEY.fullmatch(ref) if ref else None
    if match is None:
        return None
    data = await objectstore.get(ref)
    return (data, LOGO_TYPES[match["ext"]], match["sha"]) if data is not None else None


async def _check_legal_budget(field: str, markdown: str) -> None:
    try:
        await legal_page.check_budget(markdown)
    except legal_page.LegalTooComplexError:
        raise invalid(field, "takes too long to render; simplify the page") from None


async def legal(db: AsyncSession) -> Legal:
    """The legal page as sanitized HTML, with the footer markings (BL-68)."""
    current = await values(db, list(LEGAL_KEYS.values()))
    return Legal(html=await legal_page.render_async(current["legal.page_markdown"]),
                 required_markings=current["legal.required_markings"])  # fmt: skip


async def put_legal(db: AsyncSession, body: LegalWrite, actor: uuid.UUID, ip: str | None) -> None:
    for field in body.model_fields_set:
        value = getattr(body, field)
        if value is None:
            raise invalid(field, "must be a string", status=422)
        if has_control(value, allow_newlines=True):
            raise invalid(field, "must not contain control characters")
        if field == "page_markdown":
            await _check_legal_budget(field, value)
        await _write(db, LEGAL_KEYS[field], value, actor, ip, action="legal.update")
    await db.commit()


def _audit_conds(
    actor: uuid.UUID | None = None,
    action: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    from_: datetime | None = None,
    to: datetime | None = None,
) -> list[Any]:
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
    return conds


def _audit_entry(r: AuditLog, email: str | None) -> AuditEntry:
    return AuditEntry(
        id=r.id, occurred_at=r.occurred_at, actor_user_id=r.actor_user_id, actor_email=email,
        action=r.action, entity_type=r.entity_type, entity_id=r.entity_id, before=r.before,
        after=r.after, ip=str(r.ip) if r.ip else None, request_id=r.request_id,
    )  # fmt: skip


def _audit_select(conds: list[Any]) -> Any:  # noqa: ANN401 - a SQLAlchemy select
    from regwatch.identity.models import User

    return (
        select(AuditLog, User.email)
        .outerjoin(User, User.id == AuditLog.actor_user_id)
        .where(*conds)
        .order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc())
    )


EXPORT_BATCH = 100  # rows read at a time, so memory stays bounded by the batch (review R1)


async def export_audit(
    db: AsyncSession, actor_id: uuid.UUID, ip: str | None, **filters: Any
) -> tuple[str, int, bool]:
    """The filtered audit log as CSV, newest first, capped; the export itself is audited (CP-10).

    Rows are read in keyset-paged batches of ``EXPORT_BATCH`` and written until the row or size
    cap, so a log of huge values cannot load 10,000 of them at once (re-verification R1).
    """
    from regwatch.admin import audit_export

    conds = _audit_conds(**filters)
    out = audit_export.CsvBuilder()
    last: tuple[datetime, uuid.UUID] | None = None
    full = False
    while not full:
        stmt = _audit_select(conds)
        if last is not None:
            # The plain bound lets PostgreSQL use the occurred_at index (re-verification 2, S1).
            stmt = stmt.where(
                AuditLog.occurred_at <= last[0], tuple_(AuditLog.occurred_at, AuditLog.id) < last
            )
        batch = (await db.execute(stmt.limit(EXPORT_BATCH))).tuples().all()
        for r, email in batch:
            if not out.add(_audit_entry(r, email)):
                full = True
                break
            last = (r.occurred_at, r.id)
        if len(batch) < EXPORT_BATCH:
            break
        await asyncio.sleep(0)  # let other requests run between batches (review R3)
    recorded = {k: (str(v) if v is not None else None) for k, v in filters.items() if v is not None}
    audit(db, "audit.export", "audit_log", None, actor=actor_id, ip=ip,
          after={"filters": recorded, "rows": out.rows, "truncated": full})  # fmt: skip
    await db.commit()
    return out.text(), out.rows, full


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
    conds = _audit_conds(actor, action, entity_type, entity_id, from_, to)
    total = await db.scalar(select(func.count()).select_from(AuditLog).where(*conds)) or 0
    rows = await db.execute(_audit_select(conds).limit(page_size).offset((page - 1) * page_size))
    items = [_audit_entry(r, email) for r, email in rows.tuples().all()]
    return Page[AuditEntry](items=items, total=total, page=page, page_size=page_size)
