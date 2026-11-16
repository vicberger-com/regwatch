"""Sources and capture jobs: validation, the robots.txt override, audit (M3; REQ-02, REQ-05).

Every URL a source names, its ``url`` and the URLs inside its ``config``, passes SafeFetcher's
``validate_source_url`` when it is saved (M3 acceptance 3); SafeFetcher checks again at fetch
time. Setting ``robots_policy=override`` needs ``sources.override_robots`` and a reason, and is
audited as ``source.robots_override`` besides the usual create or update row (acceptance 4).
"""

from __future__ import annotations

import re
import uuid
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.capture.connectors.config import validate_config, validate_rules
from regwatch.capture.models import CaptureJob, Source
from regwatch.capture.safe_fetch.policy import FetchRefusedError, Resolver, validate_source_url
from regwatch.capture.schemas import CaptureJob as JobOut
from regwatch.capture.schemas import CaptureJobWrite, SourceWrite
from regwatch.capture.schemas import Source as SourceOut
from regwatch.core.errors import ProblemError, ProblemFieldError
from regwatch.core.schemas import Page
from regwatch.core.services import audit
from regwatch.identity.services import Principal
from regwatch.taxonomy.models import Jurisdiction, Term

RESOLVER: Resolver | None = None  # None: the system resolver; tests set a fixed answer
OVERRIDE = "sources.override_robots"
MAX_REASON = 1000
DEFAULT_INTERVAL = 3600  # a job with neither cron nor interval runs hourly (ASSUMPTIONS M3)
_URL_FIELDS = {"rss": ("feed_url",), "web_page": ("page_url",), "web_crawl": ("seed_urls",),
               "api_feed": ("endpoint_url",)}  # fmt: skip
_CRON_FIELD = re.compile(r"^[0-9A-Za-z*/,\-]+$")
# Refusals that describe what a host resolved to name no address, so a saved URL cannot be used
# to learn internal addresses; the others describe only the URL as typed.
_REASONS = {"private-address": "the host resolves to a private or reserved address",
            "dns": "the host name could not be resolved"}  # fmt: skip


def invalid(field: str, message: str) -> ProblemError:
    errors = [ProblemFieldError(field=field, message=message)]
    return ProblemError(422, "validation", "The source settings are not valid.", errors=errors)


def not_found(what: str) -> ProblemError:
    return ProblemError(404, "not-found", f"No such {what}.")


async def check_url(field: str, url: str) -> None:
    try:
        await validate_source_url(url, RESOLVER)
    except FetchRefusedError as exc:
        raise invalid(field, _REASONS.get(exc.reason, exc.detail)) from None


async def check_config(kind: str, config: dict[str, Any]) -> dict[str, Any]:
    parsed = validate_config(kind, config)
    for name in _URL_FIELDS.get(kind, ()):
        value = getattr(parsed, name)
        for n, url in enumerate(value if isinstance(value, list) else [value]):
            if url is not None:
                await check_url(f"config.{name}" + (f".{n}" if isinstance(value, list) else ""),
                                str(url))  # fmt: skip
    return config


def check_robots(values: dict[str, Any], source: Source | None, principal: Principal) -> None:
    """The robots.txt override: the permission and a reason (M3 acceptance 4, review 22 (a))."""
    policy = values.get("robots_policy", source.robots_policy if source else "respect")
    if policy != "override":
        values["override_reason"] = None
        return
    reason = values.get("override_reason", source.override_reason if source else None)
    reason = (reason or "").strip()
    if not reason:
        raise invalid("override_reason", "a reason is needed to override robots.txt")
    if len(reason) > MAX_REASON:
        raise invalid("override_reason", f"at most {MAX_REASON} characters")
    values["override_reason"] = reason
    changed = source is None or (source.robots_policy, source.override_reason) != (
        "override", reason)  # fmt: skip
    if changed and OVERRIDE not in principal.permissions:
        raise ProblemError(403, "forbidden", "Overriding robots.txt needs its own permission.")


def check_job(values: dict[str, Any], job: CaptureJob | None) -> None:
    """A job runs on a cron expression or an interval; setting one clears the other."""
    if values.get("cron") is not None and "interval_seconds" not in values:
        values["interval_seconds"] = None
    if values.get("interval_seconds") is not None and "cron" not in values:
        values["cron"] = None
    cron = values.get("cron", job.cron if job else None)
    interval = values.get("interval_seconds", job.interval_seconds if job else None)
    if cron is not None and interval is not None:
        raise invalid("job.cron", "give a cron expression or an interval, not both")
    if cron is not None and (len(cron.split()) != 5 or not all(
            _CRON_FIELD.match(f) for f in cron.split())):  # fmt: skip
        raise invalid("job.cron", "a cron expression has five fields")
    if cron is None and interval is None:
        if job is not None:
            raise invalid("job.interval_seconds", "a job needs a cron expression or an interval")
        values["interval_seconds"] = DEFAULT_INTERVAL
    if "timezone" in values:
        try:
            ZoneInfo(values["timezone"])
        except (ValueError, KeyError):
            raise invalid("job.timezone", "not a known time zone") from None
    if values.get("max_items_per_run", 1) < 1:
        raise invalid("job.max_items_per_run", "at least 1")
    if "extraction_rules" in values:
        validate_rules(values["extraction_rules"])
    for key in ("timezone", "max_items_per_run", "rate_limit_per_minute", "render_js",
                "extraction_rules", "change_threshold_pct", "enabled"):  # fmt: skip
        if key in values and values[key] is None:
            raise invalid(f"job.{key}", "may not be empty")


async def jurisdiction_ids(db: AsyncSession, codes: list[str]) -> list[uuid.UUID]:
    query = select(Jurisdiction.code, Jurisdiction.id).where(Jurisdiction.code.in_(codes))
    rows: dict[str, uuid.UUID] = {code: id_ for code, id_ in (await db.execute(query)).all()}
    missing = [c for c in codes if c not in rows]
    if missing:
        raise invalid("default_jurisdiction_codes", f"unknown codes: {', '.join(missing)}")
    return [rows[c] for c in dict.fromkeys(codes)]


async def check_terms(db: AsyncSession, ids: list[uuid.UUID]) -> list[uuid.UUID]:
    found = set((await db.scalars(select(Term.id).where(Term.id.in_(ids)))).all())
    if len(found) != len(set(ids)):
        raise invalid("default_term_ids", "unknown term ids")
    return list(dict.fromkeys(ids))


async def _source_values(db: AsyncSession, body: SourceWrite, source: Source | None,
                         principal: Principal) -> dict[str, Any]:  # fmt: skip
    values = body.model_dump(exclude_unset=True, exclude={"job"})
    for key in ("name", "kind", "config", "default_jurisdiction_codes", "default_term_ids",
                "credibility", "robots_policy", "enabled"):  # fmt: skip
        if key in values and values[key] is None:
            raise invalid(key, "may not be empty")
    if source is None:
        for key in ("name", "kind"):
            if not values.get(key):
                raise invalid(key, f"{key} is required")
        values.setdefault("config", {})
    elif "kind" in values and values["kind"] != source.kind:
        raise invalid("kind", "the kind of a source cannot change; create a new source")
    if "name" in values and not values["name"].strip():
        raise invalid("name", "name is required")
    kind = values.get("kind", source.kind if source else "")
    if "config" in values:
        await check_config(kind, values["config"])
    if values.get("url"):
        await check_url("url", values["url"])
    if "default_jurisdiction_codes" in values:
        values["default_jurisdiction_ids"] = await jurisdiction_ids(
            db, values.pop("default_jurisdiction_codes"))  # fmt: skip
    if "default_term_ids" in values:
        values["default_term_ids"] = await check_terms(db, values["default_term_ids"])
    check_robots(values, source, principal)
    return values


def job_snapshot(job: CaptureJob) -> dict[str, Any]:
    return JobOut.model_validate(job, from_attributes=True).model_dump(mode="json")


def source_snapshot(source: Source) -> dict[str, Any]:
    fields = ("name", "kind", "url", "config", "credibility", "robots_policy", "override_reason",
              "terms_url", "language", "enabled")  # fmt: skip
    snap = {f: getattr(source, f) for f in fields}
    snap["default_jurisdiction_ids"] = [str(i) for i in source.default_jurisdiction_ids]
    snap["default_term_ids"] = [str(i) for i in source.default_term_ids]
    return snap


async def source_out(db: AsyncSession, source: Source, job: CaptureJob | None) -> SourceOut:
    query = select(Jurisdiction.id, Jurisdiction.code).where(
        Jurisdiction.id.in_(source.default_jurisdiction_ids))  # fmt: skip
    codes: dict[uuid.UUID, str] = {id_: code for id_, code in (await db.execute(query)).all()}
    out = SourceOut.model_validate(
        {**{c.key: getattr(source, c.key) for c in Source.__table__.columns},
         "default_jurisdiction_codes": [codes[i] for i in source.default_jurisdiction_ids
                                        if i in codes]},
    )  # fmt: skip
    if job is not None:
        out.job = JobOut.model_validate(job, from_attributes=True)
    return out


async def _source_and_job(db: AsyncSession, source_id: uuid.UUID,
                          lock: bool = False) -> tuple[Source, CaptureJob | None]:  # fmt: skip
    query = select(Source).where(Source.id == source_id)
    source = await db.scalar(query.with_for_update() if lock else query)
    if source is None:
        raise not_found("source")
    job = await db.scalar(select(CaptureJob).where(CaptureJob.source_id == source_id))
    return source, job


def _audit_robots(db: AsyncSession, source: Source, before: dict[str, Any] | None,
                  actor: uuid.UUID, ip: str | None) -> None:  # fmt: skip
    was = (before or {}).get("robots_policy"), (before or {}).get("override_reason")
    if source.robots_policy == "override" and was != ("override", source.override_reason):
        audit(db, "source.robots_override", "source", source.id, actor=actor, ip=ip,
              before={"robots_policy": was[0], "override_reason": was[1]},
              after={"robots_policy": "override",
                     "override_reason": source.override_reason})  # fmt: skip


async def create_source(db: AsyncSession, body: SourceWrite, principal: Principal,
                        ip: str | None) -> SourceOut:  # fmt: skip
    values = await _source_values(db, body, None, principal)
    job_values = body.job.model_dump(exclude_unset=True) if "job" in body.model_fields_set else {}
    check_job(job_values, None)
    actor = principal.user.id
    source = Source(owner_user_id=actor, **values)
    db.add(source)
    await db.flush()
    job = CaptureJob(source_id=source.id, **job_values)
    db.add(job)
    await db.flush()
    await db.refresh(source)
    await db.refresh(job)
    audit(db, "source.create", "source", source.id, actor=actor, ip=ip,
          after={**source_snapshot(source), "job": job_snapshot(job)})  # fmt: skip
    _audit_robots(db, source, None, actor, ip)
    out = await source_out(db, source, job)
    await db.commit()
    return out


async def update_source(db: AsyncSession, source_id: uuid.UUID, body: SourceWrite,
                        principal: Principal, ip: str | None) -> SourceOut:  # fmt: skip
    source, job = await _source_and_job(db, source_id, lock=True)
    values = await _source_values(db, body, source, principal)
    job_values = body.job.model_dump(exclude_unset=True) if "job" in body.model_fields_set else {}
    if job is None and job_values:  # pragma: no cover - every source is created with its job
        raise not_found("capture job")
    if job is not None:
        check_job(job_values, job)
    before = source_snapshot(source)
    job_before = job_snapshot(job) if job is not None else None
    for key, value in values.items():
        setattr(source, key, value)
    for key, value in job_values.items():
        setattr(job, key, value)
    await db.flush()
    await db.refresh(source)
    if job is not None:
        await db.refresh(job)
    after = source_snapshot(source)
    job_after = job_snapshot(job) if job is not None else None
    if (before, job_before) != (after, job_after):
        audit(db, "source.update", "source", source.id, actor=principal.user.id, ip=ip,
              before={**before, "job": job_before}, after={**after, "job": job_after})  # fmt: skip
        _audit_robots(db, source, before, principal.user.id, ip)
    out = await source_out(db, source, job)
    await db.commit()
    return out


async def disable_source(db: AsyncSession, source_id: uuid.UUID, actor: uuid.UUID,
                         ip: str | None) -> None:  # fmt: skip
    """``DELETE /sources/{id}``: the source and its job stop; the source and its items stay."""
    source, job = await _source_and_job(db, source_id, lock=True)
    if not source.enabled and (job is None or not job.enabled):
        return
    before = {"enabled": source.enabled, "job_enabled": job.enabled if job else None}
    source.enabled = False
    if job is not None:
        job.enabled = False
    audit(db, "source.disable", "source", source.id, actor=actor, ip=ip, before=before,
          after={"enabled": False, "job_enabled": False if job else None})  # fmt: skip
    await db.commit()


async def get_source(db: AsyncSession, source_id: uuid.UUID) -> SourceOut:
    source, job = await _source_and_job(db, source_id)
    return await source_out(db, source, job)


async def list_sources(db: AsyncSession, page: int, page_size: int, kind: str | None,
                       health: str | None, q: str | None) -> Page[SourceOut]:  # fmt: skip
    query = select(Source)
    if kind is not None:
        query = query.where(Source.kind == kind)
    if health is not None:
        query = query.where(Source.health == health)
    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(Source.name.ilike(f"%{escaped}%", escape="\\"))
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = (await db.scalars(query.order_by(Source.name, Source.id)
                             .offset((page - 1) * page_size).limit(page_size))).all()  # fmt: skip
    jobs = {j.source_id: j for j in (await db.scalars(select(CaptureJob).where(
        CaptureJob.source_id.in_([s.id for s in rows])))).all()}  # fmt: skip
    items = [await source_out(db, s, jobs.get(s.id)) for s in rows]
    return Page[SourceOut](items=items, total=total, page=page, page_size=page_size)


async def list_jobs(db: AsyncSession, source_id: uuid.UUID | None) -> list[JobOut]:
    query = select(CaptureJob).order_by(CaptureJob.created_at, CaptureJob.id)
    if source_id is not None:
        query = query.where(CaptureJob.source_id == source_id)
    return [JobOut.model_validate(j, from_attributes=True) for j in (await db.scalars(query))]


async def update_job(db: AsyncSession, job_id: uuid.UUID, body: CaptureJobWrite,
                     actor: uuid.UUID, ip: str | None) -> JobOut:  # fmt: skip
    job = await db.scalar(select(CaptureJob).where(CaptureJob.id == job_id).with_for_update())
    if job is None:
        raise not_found("capture job")
    values = body.model_dump(exclude_unset=True)
    check_job(values, job)
    before = job_snapshot(job)
    for key, value in values.items():
        setattr(job, key, value)
    await db.flush()
    await db.refresh(job)
    after = job_snapshot(job)
    if before != after:
        audit(db, "capture_job.update", "capture_job", job.id, actor=actor, ip=ip,
              before=before, after=after)  # fmt: skip
    out = JobOut.model_validate(job, from_attributes=True)
    await db.commit()
    return out
