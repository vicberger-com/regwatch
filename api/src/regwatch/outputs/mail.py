"""Email delivery (M8.2; REQ-15), with the standard library's ``smtplib`` and ``email``.

What it holds to (M8.1 review, BL-143 e):
- Recipients only in ``outputs.allowed_recipient_domains``, compared after lower-casing and
  IDNA; an empty list means no email at all. At most ``MAX_RECIPIENTS`` a job; each is sent
  its own message, so nobody sees the other recipients.
- The sender is the configured ``smtp_from``; the subject and every header from user text
  refuse line breaks and control characters, so no header can be injected.
- The body is plain text plus escaped HTML with no remote content; the report itself is the
  attached PDF (inline SVG is often dropped by mail clients), never a signed link.
- Server, port, STARTTLS and credentials come from the environment (secrets), not the
  database (M8 question 1).
"""

from __future__ import annotations

import hashlib
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from html import escape

import anyio

from regwatch.core.schemas import has_control
from regwatch.core.settings import get_settings

MAX_RECIPIENTS = 20
TIMEOUT_S = 30.0


class MailError(Exception):
    def __init__(self, error_class: str, message: str) -> None:
        super().__init__(message)
        self.error_class = error_class
        self.message = message


def domain_of(address: str) -> str:
    """The address's domain, lower-cased and in IDNA form, or "" when it has none."""
    _, _, domain = address.strip().rpartition("@")
    try:
        return domain.strip().rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError:
        return ""


def allowed(address: str, domains: list[str]) -> bool:
    """Whether ``address`` is on an allowed domain (exactly, or a subdomain of one)."""
    wanted = {domain_of("x@" + d) for d in domains if d.strip()}
    got = domain_of(address)
    return bool(got) and any(got == d or got.endswith("." + d) for d in wanted if d)


def check_recipients(addresses: list[str], domains: list[str]) -> list[str]:
    """The recipients, de-duplicated; a ``ValueError`` naming the first that is refused."""
    if not domains:
        raise ValueError("email is turned off: no recipient domains are allowed")
    seen: list[str] = []
    for address in addresses:
        clean = address.strip()
        if not clean or has_control(clean) or "\n" in clean or "\r" in clean or "," in clean:
            raise ValueError("an address may hold no line breaks, commas or control characters")
        if not allowed(clean, domains):
            raise ValueError(f"{clean} is not on an allowed domain")
        if clean.lower() not in {s.lower() for s in seen}:
            seen.append(clean)
    if not seen:
        raise ValueError("at least one recipient is needed")
    if len(seen) > MAX_RECIPIENTS:
        raise ValueError(f"at most {MAX_RECIPIENTS} recipients")
    return seen


def plain_line(value: str, limit: int) -> str:
    """A subject or name: one line, no control characters (no header injection)."""
    text = value.strip()
    if has_control(text) or "\n" in text or "\r" in text:
        raise ValueError("one line of plain text")
    return text[:limit]


def hashed(address: str) -> str:
    """What the audit log keeps of an address."""
    return hashlib.sha256(address.strip().lower().encode()).hexdigest()[:16]


def build(to: str, subject: str, message: str, pdf: bytes, filename: str) -> EmailMessage:
    settings = get_settings()
    mail = EmailMessage()
    mail["From"] = settings.smtp_from
    mail["To"] = to
    mail["Subject"] = subject
    mail["Date"] = formatdate(localtime=False)
    mail["Message-ID"] = make_msgid(domain=domain_of(settings.smtp_from) or None)
    text = (message.strip() + "\n\n" if message.strip() else "") + (
        "The report is attached as a PDF. Sent by regwatch.")  # fmt: skip
    mail.set_content(text)
    html = "".join(f"<p>{escape(p)}</p>" for p in text.split("\n\n"))
    mail.add_alternative(f"<!doctype html><html><body>{html}</body></html>", subtype="html")
    mail.add_attachment(pdf, maintype="application", subtype="pdf", filename=filename)
    return mail


def _send_sync(messages: list[EmailMessage]) -> None:
    settings = get_settings()
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=TIMEOUT_S) as smtp:
        if settings.smtp_starttls:
            smtp.starttls(context=ssl.create_default_context())
        if settings.smtp_username and settings.smtp_password is not None:
            smtp.login(settings.smtp_username, settings.smtp_password.get_secret_value())
        for message in messages:
            smtp.send_message(message)


async def send(messages: list[EmailMessage]) -> None:
    """Send every message over one connection, off the event loop; a ``MailError`` by class."""
    try:
        await anyio.to_thread.run_sync(_send_sync, messages)
    except smtplib.SMTPRecipientsRefused:
        raise MailError("smtp-recipient-refused", "the mail server refused a recipient") \
            from None  # fmt: skip
    except smtplib.SMTPAuthenticationError:
        raise MailError("smtp-auth", "the mail server refused the credentials") from None
    except (smtplib.SMTPException, OSError, ssl.SSLError) as exc:
        raise MailError("smtp-unavailable", f"the mail server could not be used "
                        f"({type(exc).__name__})") from None  # fmt: skip
