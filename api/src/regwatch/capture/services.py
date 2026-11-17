"""Sources and capture jobs: validation, the robots.txt override, audit (M3; REQ-02, REQ-05).

Every URL a source names, its ``url`` and the URLs inside its ``config``, passes SafeFetcher's
``validate_source_url`` when it is saved (M3 acceptance 3); SafeFetcher checks again at fetch
time. Setting ``robots_policy=override`` needs ``sources.override_robots`` and a reason, and is
audited as ``source.robots_override`` besides the usual create or update row (acceptance 4).
"""

from __future__ import annotations

import asyncio
import functools
import re
import socket
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.capture.connectors.api_feed import check_params
from regwatch.capture.connectors.base import ConnectorError
from regwatch.capture.connectors.config import ApiFeedConfig, validate_config, validate_rules
from regwatch.capture.execution import RUN_DEADLINE_S
from regwatch.capture.models import CaptureJob, CaptureRun, Source
from regwatch.capture.safe_fetch.policy import (
    FetchRefusedError,
    Resolver,
    is_ip,
    validate_source_url,
)
from regwatch.capture.schedule import CronError, next_run, parse_cron
from regwatch.capture.schemas import CaptureJob as JobOut
from regwatch.capture.schemas import CaptureJobWrite, SourceHealth, SourceWrite
from regwatch.capture.schemas import CaptureRun as RunOut
from regwatch.capture.schemas import Source as SourceOut
from regwatch.core.errors import ProblemError, ProblemFieldError
from regwatch.core.schemas import Page, has_control
from regwatch.core.services import audit
from regwatch.identity.services import Principal
from regwatch.taxonomy.models import Jurisdiction, Term

RESOLVER: Resolver | None = None  # None: _save_resolver below; tests set a fixed answer
# Save-time lookups get threads of their own: a cancelled getaddrinfo keeps its thread until the
# system resolver gives up, so a name server that never answers can fill this pool, but not the
# loop's default one that object-store reads use (re-verification 15).
_DNS_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="source-dns")


async def _save_resolver(host: str, port: int) -> list[str]:
    if is_ip(host):  # a literal needs no lookup, so a stuck pool cannot refuse it
        return [host]
    infos = await asyncio.get_running_loop().run_in_executor(
        _DNS_POOL,
        functools.partial(socket.getaddrinfo, host, port, type=socket.SOCK_STREAM,
                          proto=socket.IPPROTO_TCP),
    )  # fmt: skip
    return [str(info[4][0]) for info in infos]


OVERRIDE = "sources.override_robots"
NO_OVERRIDE = frozenset({"legislation_gov_uk"})
MAX_REASON = 1000
MAX_URL = 2048
MAX_INTERVAL = 366 * 86400  # a job runs at least once a year
DNS_DEADLINE_S = 10.0  # all of a save's lookups together (review finding 2)
DEFAULT_INTERVAL = 3600  # a job with neither cron nor interval runs hourly (ASSUMPTIONS M3)
_URL_FIELDS = {"rss": ("feed_url",), "web_page": ("page_url",), "web_crawl": ("seed_urls",),
               "api_feed": ("endpoint_url",)}  # fmt: skip
# Fields whose change on an overridden source points the override somewhere new (finding 1).
_OVERRIDE_TARGET = ("url", "config")
# One message for every refusal about what a name resolves to, private or unresolvable, so
# saving sources tells nothing about internal names or addresses (findings 4 and the record).
_NOT_PUBLIC = "the host must resolve to public addresses only"
_LANGUAGE = re.compile(r"^[A-Za-z]{2,8}(-[A-Za-z0-9]{1,8}){0,4}$")


def invalid(field: str, message: str) -> ProblemError:
    return invalid_all([(field, message)])


def invalid_all(errors: list[tuple[str, str]]) -> ProblemError:
    fields = [ProblemFieldError(field=f, message=m) for f, m in errors]
    return ProblemError(422, "validation", "The source settings are not valid.", errors=fields)


def not_found(what: str) -> ProblemError:
    return ProblemError(404, "not-found", f"No such {what}.")


def _refusal(exc: FetchRefusedError) -> str:
    return _NOT_PUBLIC if exc.reason in ("private-address", "dns", "address") else exc.detail


async def check_urls(kind: str, values: dict[str, Any]) -> None:
    """Every URL the source names, checked together under one deadline, before the database
    is touched, so slow name servers hold no connection or row lock (review finding 2). The
    config is stored as parsed, so what is stored is what was checked (finding 6)."""
    urls: list[tuple[str, str]] = []
    if "config" in values:
        parsed = validate_config(kind, values["config"])
        if isinstance(parsed, ApiFeedConfig):  # its query parameters too (API feed review 7)
            try:
                check_params(parsed)
            except ConnectorError as exc:
                raise invalid("config.params", exc.detail) from None
        values["config"] = parsed.model_dump(mode="json", exclude_unset=True)
        for name in _URL_FIELDS.get(kind, ()):
            value = getattr(parsed, name)
            if isinstance(value, list):
                urls += [(f"config.{name}.{n}", str(u)) for n, u in enumerate(value)]
            elif value is not None:
                urls.append((f"config.{name}", str(value)))
    if values.get("url") == "":
        values["url"] = None  # no URL, rather than an empty one (re-verification 14)
    if values.get("url"):
        urls.append(("url", values["url"]))
    try:
        async with asyncio.timeout(DNS_DEADLINE_S):
            results = await asyncio.gather(
                *(validate_source_url(u, RESOLVER or _save_resolver) for _, u in urls),
                return_exceptions=True,
            )
    except TimeoutError:
        raise invalid_all([(f, _NOT_PUBLIC) for f, _ in urls]) from None
    errors = []
    for (field, _), result in zip(urls, results, strict=True):
        if isinstance(result, FetchRefusedError):
            errors.append((field, _refusal(result)))
        elif isinstance(result, BaseException):  # pragma: no cover - validate raises only that
            raise result
    if errors:
        raise invalid_all(errors)


def _text(values: dict[str, Any], key: str) -> None:
    if values.get(key) is not None and has_control(values[key]):
        raise invalid(key, "control and direction-changing characters are not allowed")


def _web_link(url: str) -> bool:
    """A link the UI may show: http or https only, so never ``javascript:`` (finding 3)."""
    if len(url) > MAX_URL or has_control(url):
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme.lower() in ("http", "https") and bool(parts.hostname)


def check_plain(values: dict[str, Any], kind: str | None) -> str:
    """Checks that need neither the network nor the database; returns the source's kind."""
    for key in ("name", "kind", "config", "default_jurisdiction_codes", "default_term_ids",
                "credibility", "robots_policy", "enabled"):  # fmt: skip
        if key in values and values[key] is None:
            raise invalid(key, "may not be empty")
    if kind is None:
        for key in ("name", "kind"):
            if not values.get(key):
                raise invalid(key, f"{key} is required")
        values.setdefault("config", {})
    elif "kind" in values and values["kind"] != kind:
        raise invalid("kind", "the kind of a source cannot change; create a new source")
    if "name" in values and not values["name"].strip():
        raise invalid("name", "name is required")
    for key in ("name", "override_reason", "url"):
        _text(values, key)
    if values.get("language") is not None and not _LANGUAGE.fullmatch(values["language"]):
        raise invalid("language", "a language tag such as en or pt-BR")
    if values.get("terms_url") is not None and not _web_link(values["terms_url"]):
        raise invalid("terms_url", f"an http or https URL of at most {MAX_URL} characters")
    return str(values.get("kind", kind))


def check_robots(values: dict[str, Any], source: Source | None, principal: Principal) -> bool:
    """The robots.txt override: the permission and a reason (M3 acceptance 4, review 22 (a)).

    Returns whether this save makes a new override: a new policy or reason, or new URLs, or
    turning a disabled overridden source back on (review finding 1). Each needs the permission.
    """
    policy = values.get("robots_policy", source.robots_policy if source else "respect")
    config = values.get("config", source.config if source else {}) or {}
    kind = values.get("kind", source.kind if source else None)
    if policy == "override" and kind == "api_feed" and config.get("provider") in NO_OVERRIDE:
        # Its fair use policy says robots.txt must be followed (R-06 E-UK-3; legislation
        # review finding 1); the adapter also always obeys it.
        raise invalid("robots_policy", "this provider's terms require robots.txt to be obeyed")
    if policy != "override":
        values["override_reason"] = None
        return False
    reason = values.get("override_reason", source.override_reason if source else None)
    reason = (reason or "").strip()
    if not reason:
        raise invalid("override_reason", "a reason is needed to override robots.txt")
    if len(reason) > MAX_REASON:
        raise invalid("override_reason", f"at most {MAX_REASON} characters")
    values["override_reason"] = reason
    new = source is None or (source.robots_policy, source.override_reason) != (
        "override", reason)  # fmt: skip
    if source is not None and not new:
        new = any(k in values and values[k] != getattr(source, k) for k in _OVERRIDE_TARGET) or (
            values.get("enabled") is True and not source.enabled)  # fmt: skip
    if new and OVERRIDE not in principal.permissions:
        raise ProblemError(403, "forbidden", "Overriding robots.txt needs its own permission.")
    return new


def check_resume(
    policy: str, job: CaptureJob | None, values: dict[str, Any], principal: Principal
) -> bool:
    """Turning the job of an overridden source back on is a new override (re-verification 13)."""
    if policy != "override" or job is None or job.enabled or values.get("enabled") is not True:
        return False
    if OVERRIDE not in principal.permissions:
        raise ProblemError(403, "forbidden", "Overriding robots.txt needs its own permission.")
    return True


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
    if cron is not None:
        try:
            parse_cron(cron)
        except CronError:
            raise invalid("job.cron", "five cron fields, each within its range") from None
    if interval is not None and interval > MAX_INTERVAL:
        raise invalid("job.interval_seconds", f"at most {MAX_INTERVAL} seconds (a year)")
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
    items = values.get("max_items_per_run", job.max_items_per_run if job else 200) or 200
    rate = values.get("rate_limit_per_minute", job.rate_limit_per_minute if job else 30) or 30
    if (items + 2) * 60 / rate > RUN_DEADLINE_S:  # the pages, plus robots.txt and the feed (R4)
        # A run that cannot finish in time stops partway every time (run review finding 1).
        raise invalid("job.max_items_per_run", f"at {rate} a minute, {items} items take longer"
                      f" than a run may last ({RUN_DEADLINE_S // 60} minutes); lower the items"
                      " or raise the rate")  # fmt: skip
    if "extraction_rules" in values:
        validate_rules(values["extraction_rules"])
    for key in ("timezone", "max_items_per_run", "rate_limit_per_minute", "render_js",
                "extraction_rules", "change_threshold_pct", "enabled"):  # fmt: skip
        if key in values and values[key] is None:
            raise invalid(f"job.{key}", "may not be empty")


_SCHEDULE = ("cron", "interval_seconds", "timezone", "enabled")


def reschedule(job: CaptureJob, values: dict[str, Any], *, new: bool = False,
               now: datetime | None = None) -> None:  # fmt: skip
    """Set ``next_run_at`` when a save changes when the job runs; a schedule that never fires
    (such as 30 February) is refused."""
    if not new and not any(k in values for k in _SCHEDULE):
        return
    now = now or datetime.now(UTC)
    when = next_run(job.cron, job.interval_seconds, job.timezone, now)
    if when is None:
        raise invalid("job.cron", "this schedule never runs")
    # An interval job runs first soon after it is created or changed, not one interval later.
    job.next_run_at = now if job.cron is None else when


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


async def _db_checks(db: AsyncSession, values: dict[str, Any]) -> None:
    if "default_jurisdiction_codes" in values:
        values["default_jurisdiction_ids"] = await jurisdiction_ids(
            db, values.pop("default_jurisdiction_codes"))  # fmt: skip
    if "default_term_ids" in values:
        values["default_term_ids"] = await check_terms(db, values["default_term_ids"])


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
    job_query = select(CaptureJob).where(CaptureJob.source_id == source_id)
    job = await db.scalar(job_query.with_for_update() if lock else job_query)  # finding 9
    return source, job


def _audit_robots(db: AsyncSession, source: Source, before: dict[str, Any] | None,
                  actor: uuid.UUID, ip: str | None,
                  job_enabled: tuple[bool, bool] | None = None) -> None:  # fmt: skip
    """The override's own row names what it applies to: the URL and config (finding 1)."""
    keys = ("robots_policy", "override_reason", "url", "config", "enabled")
    audit(db, "source.robots_override", "source", source.id, actor=actor, ip=ip,
          before={**({k: before[k] for k in keys} if before else {}),
                  **({"job_enabled": job_enabled[0]} if job_enabled else {})} or None,
          after={**{k: getattr(source, k) for k in keys},
                 **({"job_enabled": job_enabled[1]} if job_enabled else {})})  # fmt: skip


async def create_source(db: AsyncSession, body: SourceWrite, principal: Principal,
                        ip: str | None) -> SourceOut:  # fmt: skip
    values = body.model_dump(exclude_unset=True, exclude={"job"})
    kind = check_plain(values, None)
    job_values = body.job.model_dump(exclude_unset=True) if "job" in body.model_fields_set else {}
    check_job(job_values, None)
    new_override = check_robots(values, None, principal)
    await check_urls(kind, values)  # before the first query: no connection is held
    await _db_checks(db, values)
    actor = principal.user.id
    source = Source(owner_user_id=actor, **values)
    db.add(source)
    await db.flush()
    job = CaptureJob(source_id=source.id, **job_values)
    db.add(job)
    await db.flush()
    await db.refresh(source)
    await db.refresh(job)
    reschedule(job, job_values, new=True)
    await db.flush()
    audit(db, "source.create", "source", source.id, actor=actor, ip=ip,
          after={**source_snapshot(source), "job": job_snapshot(job)})  # fmt: skip
    if new_override:
        _audit_robots(db, source, None, actor, ip)
    out = await source_out(db, source, job)
    await db.commit()
    return out


async def update_source(db: AsyncSession, source_id: uuid.UUID, body: SourceWrite,
                        principal: Principal, ip: str | None) -> SourceOut:  # fmt: skip
    kind = await db.scalar(select(Source.kind).where(Source.id == source_id))
    await db.rollback()  # the kind never changes; end the read so DNS holds no connection
    if kind is None:
        raise not_found("source")
    values = body.model_dump(exclude_unset=True, exclude={"job"})
    check_plain(values, kind)
    await check_urls(kind, values)
    source, job = await _source_and_job(db, source_id, lock=True)
    await _db_checks(db, values)
    new_override = check_robots(values, source, principal)
    job_values = body.job.model_dump(exclude_unset=True) if "job" in body.model_fields_set else {}
    if job is None and job_values:  # pragma: no cover - every source is created with its job
        raise not_found("capture job")
    if job is not None:
        check_job(job_values, job)
    policy = values.get("robots_policy", source.robots_policy)
    new_override = check_resume(policy, job, job_values, principal) or new_override
    before = source_snapshot(source)
    job_before = job_snapshot(job) if job is not None else None
    for key, value in values.items():
        setattr(source, key, value)
    for key, value in job_values.items():
        setattr(job, key, value)
    if job is not None and "config" in values and values["config"] != before["config"]:
        job.cursor = None  # new settings, a new query: it starts from its own window (CP-14)
    if job is not None:
        reschedule(job, job_values)
    await db.flush()
    await db.refresh(source)
    if job is not None:
        await db.refresh(job)
    after = source_snapshot(source)
    job_after = job_snapshot(job) if job is not None else None
    if (before, job_before) != (after, job_after):
        audit(db, "source.update", "source", source.id, actor=principal.user.id, ip=ip,
              before={**before, "job": job_before}, after={**after, "job": job_after})  # fmt: skip
        if new_override:
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
                     principal: Principal, ip: str | None) -> JobOut:  # fmt: skip
    source_id = await db.scalar(select(CaptureJob.source_id).where(CaptureJob.id == job_id))
    if source_id is None:
        raise not_found("capture job")
    source, job = await _source_and_job(db, source_id, lock=True)  # source first, as PATCH does
    if job is None or job.id != job_id:  # pragma: no cover - one job per source
        raise not_found("capture job")
    values = body.model_dump(exclude_unset=True)
    check_job(values, job)
    resumed = check_resume(source.robots_policy, job, values, principal)
    before = job_snapshot(job)
    for key, value in values.items():
        setattr(job, key, value)
    reschedule(job, values)
    await db.flush()
    await db.refresh(job)
    after = job_snapshot(job)
    actor = principal.user.id
    if before != after:
        audit(db, "capture_job.update", "capture_job", job.id, actor=actor, ip=ip,
              before=before, after=after)  # fmt: skip
    if resumed:
        _audit_robots(db, source, source_snapshot(source), actor, ip, job_enabled=(False, True))
    out = JobOut.model_validate(job, from_attributes=True)
    await db.commit()
    return out


RUN_STATUSES = ("running", "success", "partial", "failed", "skipped")
SUCCEEDED = ("success", "partial")


async def list_runs(db: AsyncSession, page: int, page_size: int, job_id: uuid.UUID | None,
                    status: str | None) -> Page[RunOut]:  # fmt: skip
    """Run history, newest first (``ix_capture_run_job`` serves the per-job listing)."""
    if status is not None and status not in RUN_STATUSES:
        raise ProblemError(422, "validation", f"status is one of {', '.join(RUN_STATUSES)}.")
    query = select(CaptureRun)
    if job_id is not None:
        query = query.where(CaptureRun.job_id == job_id)
    if status is not None:
        query = query.where(CaptureRun.status == status)
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = await db.scalars(query.order_by(CaptureRun.started_at.desc(), CaptureRun.id.desc())
                            .offset((page - 1) * page_size).limit(page_size))  # fmt: skip
    items = [RunOut.model_validate(r, from_attributes=True) for r in rows]
    return Page[RunOut](items=items, total=total, page=page, page_size=page_size)


async def source_health(db: AsyncSession, source_id: uuid.UUID) -> SourceHealth:
    """Health over the last 7 days. Runs still going and skipped runs (robots.txt, a paused
    host) count in neither the runs nor the rate: they say nothing of the source's health."""
    source, job = await _source_and_job(db, source_id)
    health = SourceHealth(source_id=source.id, health=source.health,
                          consecutive_failures=source.consecutive_failures, runs_7d=0,
                          success_rate_7d=0.0, last_success_at=None, last_error=None)  # fmt: skip
    if job is None:  # pragma: no cover - every source is created with its job
        return health
    since = datetime.now(UTC) - timedelta(days=7)
    finished = CaptureRun.status.in_(("success", "partial", "failed"))
    counts = (await db.execute(
        select(func.count(), func.count(case((CaptureRun.status.in_(SUCCEEDED), 1))))
        .where(CaptureRun.job_id == job.id, CaptureRun.started_at >= since, finished)
    )).one()  # fmt: skip
    health.runs_7d = counts[0]
    health.success_rate_7d = round(counts[1] / counts[0], 4) if counts[0] else 0.0
    health.last_success_at = await db.scalar(
        select(func.max(CaptureRun.finished_at))
        .where(CaptureRun.job_id == job.id, CaptureRun.status.in_(SUCCEEDED)))  # fmt: skip
    failed = await db.scalar(
        select(CaptureRun).where(CaptureRun.job_id == job.id, CaptureRun.status == "failed")
        .order_by(CaptureRun.started_at.desc()).limit(1))  # fmt: skip
    if failed is not None and (health.last_success_at is None or (
            failed.finished_at or failed.started_at) > health.last_success_at):  # fmt: skip
        health.last_error = ": ".join(x for x in (failed.error_class, failed.error_message) if x)
    return health
