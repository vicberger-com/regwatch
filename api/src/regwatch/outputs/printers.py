"""Printers (M8.5b; BL-15, CP-33, BL-145): registered by administrators (``settings.manage``),
chosen by users with ``outputs.print`` while ``outputs.server_print`` is on.

An address is checked when it is saved (``ipp.parse`` and ``ipp.resolve``) and again before each
job (``ipp.send``), since names can move. Every change is audited.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.core.errors import ProblemError, ProblemFieldError
from regwatch.core.services import audit
from regwatch.core.settings import get_settings
from regwatch.identity.services import Principal
from regwatch.outputs import ipp
from regwatch.outputs.models import OutputJob, Printer
from regwatch.outputs.schemas import Printer as PrinterOut
from regwatch.outputs.schemas import PrinterChoice, PrinterWrite

FLAG = "outputs.server_print"
MAX_PRINTERS = 100


def _invalid(field: str, message: str) -> ProblemError:
    return ProblemError(422, "validation", "The printer is not valid.",
                        errors=[ProblemFieldError(field=field, message=message)])  # fmt: skip


def out(row: Printer) -> PrinterOut:
    return PrinterOut(id=row.id, name=row.name, ipp_url=row.ipp_url,
                      default_media=row.default_media, enabled=row.enabled,
                      tls_sha256=row.tls_sha256)  # fmt: skip


async def server_print_on(db: AsyncSession) -> bool:
    from regwatch.admin.models import FeatureFlag

    flag = await db.get(FeatureFlag, FLAG)
    return bool(flag and flag.enabled)


async def print_settings(db: AsyncSession) -> tuple[list[str], bool]:
    """The allowed printer networks and whether clear-text ipp:// is allowed."""
    from regwatch.admin.services import values

    got = await values(db, ["outputs.printer_networks", "outputs.printer_plain_ipp"])
    return list(got["outputs.printer_networks"] or []), bool(got["outputs.printer_plain_ipp"])


async def _check_address(db: AsyncSession, url: str) -> str:
    networks, plain = await print_settings(db)
    test = get_settings().print_test_printer
    try:
        target = ipp.parse(url, plain, test)
    except ValueError as exc:
        raise _invalid("ipp_url", str(exc)) from None
    if not (test and target.host == ipp.TEST_PRINTER):
        try:
            await ipp.resolve(target, ipp.networks_of(networks))
        except ipp.PrinterError as exc:
            raise _invalid("ipp_url", exc.message) from None
    return target.url()


def _fingerprint(value: str | None) -> str | None:
    if value is None:
        return None
    digest = value.replace(":", "").lower()
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise _invalid("tls_sha256", "the SHA-256 of the certificate: 64 hexadecimal digits")
    return digest


async def _apply(db: AsyncSession, row: Printer, body: PrinterWrite) -> None:
    given = body.model_fields_set
    if "name" in given:
        row.name = body.name.strip()
    if "ipp_url" in given:
        row.ipp_url = await _check_address(db, body.ipp_url)
    if "default_media" in given:
        row.default_media = body.default_media
    if "enabled" in given:
        row.enabled = body.enabled
    if "tls_sha256" in given:
        row.tls_sha256 = _fingerprint(body.tls_sha256)


def _changes(row: Printer) -> dict[str, Any]:
    return {"name": row.name, "ipp_url": row.ipp_url, "enabled": row.enabled,
            "pinned": row.tls_sha256 is not None}  # fmt: skip


async def list_printers(db: AsyncSession) -> list[PrinterOut]:
    rows = (await db.scalars(select(Printer).order_by(Printer.name))).all()
    return [out(r) for r in rows]


async def create_printer(db: AsyncSession, body: PrinterWrite, principal: Principal,
                         ip: str | None) -> PrinterOut:  # fmt: skip
    if not {"name", "ipp_url"} <= body.model_fields_set:
        raise _invalid("name" if "name" not in body.model_fields_set else "ipp_url",
                       "a name and an ipps:// address are required")  # fmt: skip
    if len((await db.scalars(select(Printer.id))).all()) >= MAX_PRINTERS:
        raise ProblemError(409, "conflict", f"At most {MAX_PRINTERS} printers.")
    row = Printer(name="", ipp_url="", enabled=True)
    await _apply(db, row, body)
    db.add(row)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise _invalid("name", "another printer has this name") from None
    await db.refresh(row)
    audit(db, "printer.create", "printer", row.id, actor=principal.user.id, ip=ip,
          after=_changes(row))  # fmt: skip
    result = out(row)
    await db.commit()
    return result


async def _get(db: AsyncSession, printer_id: uuid.UUID) -> Printer:
    row = await db.get(Printer, printer_id)
    if row is None:
        raise ProblemError(404, "not-found", "No such printer.")
    return row


async def update_printer(db: AsyncSession, printer_id: uuid.UUID, body: PrinterWrite,
                         principal: Principal, ip: str | None) -> PrinterOut:  # fmt: skip
    row = await _get(db, printer_id)
    before = _changes(row)
    await _apply(db, row, body)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise _invalid("name", "another printer has this name") from None
    await db.refresh(row)
    audit(db, "printer.update", "printer", row.id, actor=principal.user.id, ip=ip,
          before=before, after=_changes(row))  # fmt: skip
    result = out(row)
    await db.commit()
    return result


async def delete_printer(db: AsyncSession, printer_id: uuid.UUID, principal: Principal,
                         ip: str | None) -> None:  # fmt: skip
    row = await _get(db, printer_id)
    audit(db, "printer.delete", "printer", row.id, actor=principal.user.id, ip=ip,
          before=_changes(row))  # fmt: skip
    await db.delete(row)  # jobs keep its id in their destination; a later run fails clearly
    await db.commit()


async def choices(db: AsyncSession) -> list[PrinterChoice]:
    if not await server_print_on(db):
        raise ProblemError(404, "not-found", "Printing to network printers is off.")
    rows = (await db.scalars(select(Printer).where(Printer.enabled.is_(True))
                             .order_by(Printer.name))).all()  # fmt: skip
    return [PrinterChoice(id=r.id, name=r.name) for r in rows]


async def usable(db: AsyncSession, printer_id: Any) -> Printer:
    """The printer a job may use now: the flag on, the printer there and enabled."""
    if not await server_print_on(db):
        raise ProblemError(409, "printing-off", "Printing to network printers is off.")
    try:
        row = await db.get(Printer, uuid.UUID(str(printer_id)))
    except ValueError:
        row = None
    if row is None or not row.enabled:
        raise ProblemError(409, "printer-removed", "That printer is no longer available.")
    return row


async def test_page(db: AsyncSession, printer_id: uuid.UUID, principal: Principal,
                    ip: str | None) -> OutputJob:  # fmt: skip
    """A one-page stock report printed by the administrator (the source-health report)."""
    await usable(db, printer_id)
    job = OutputJob(requested_by=principal.user.id, kind="print",
                    report_template_key="source-health", status="queued",
                    destination={"printer_id": str(printer_id), "copies": 1,
                                 "report_params": {},
                                 "source_name": "Printer test page"})  # fmt: skip
    db.add(job)
    await db.flush()
    await db.refresh(job)
    audit(db, "printer.test_page", "printer", printer_id, actor=principal.user.id, ip=ip,
          after={"output_job": str(job.id)})  # fmt: skip
    await db.commit()
    return job
