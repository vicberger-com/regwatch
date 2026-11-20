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
import re
import smtplib
import ssl
from email.headerregistry import Address
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


# One plain address and nothing else: a dot-atom local part, one @, a domain of labels. No
# spaces, quotes, brackets, comments, ; or , : anything the email library would read as another
# address (M8.2 review: "attacker@evil.com x@example.org" was sent to evil.com).
_LOCAL = re.compile(r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*")
_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?")


def _ascii_domain(domain: str) -> str:
    """``domain`` lower-cased in IDNA form, or "" when it is not a valid host name."""
    try:
        ascii_ = domain.strip().rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError:
        return ""
    labels = ascii_.split(".")
    return ascii_ if len(labels) >= 2 and all(_LABEL.fullmatch(x) for x in labels) else ""


def parse(address: str) -> Address | None:
    """The address as an ``Address``, only if it is exactly one plain address."""
    text = address.strip()
    if text.count("@") != 1 or len(text) > 254:
        return None
    local, domain = text.split("@")
    ascii_domain = _ascii_domain(domain)
    if not _LOCAL.fullmatch(local) or len(local) > 64 or not ascii_domain:
        return None
    if "=?" in local:  # an encoded word, which a mail client could display decoded
        return None
    parsed = Address(username=local, domain=ascii_domain)
    return parsed if parsed.addr_spec == f"{local}@{ascii_domain}" else None


def domain_of(address: str) -> str:
    """The domain of a plain address (lower-cased, IDNA), or "" when it is not one."""
    parsed = parse(address)
    return parsed.domain if parsed else ""


def allowed(address: str, domains: list[str]) -> bool:
    """Whether ``address`` is one plain address on an allowed domain (exactly, or a subdomain;
    the setting's help says so)."""
    wanted = {_ascii_domain(d) for d in domains if d.strip()}
    got = domain_of(address)
    return bool(got) and any(got == d or got.endswith("." + d) for d in wanted if d)


def check_recipients(addresses: list[str], domains: list[str]) -> list[str]:
    """The recipients, de-duplicated; a ``ValueError`` naming the first that is refused."""
    if not domains:
        raise ValueError("email is turned off: no recipient domains are allowed")
    seen: list[str] = []
    for address in addresses:
        raw = address.strip()
        if not raw or has_control(raw) or "\n" in raw or "\r" in raw or "," in raw:
            raise ValueError("an address may hold no line breaks, commas or control characters")
        parsed = parse(raw)
        if parsed is None:
            raise ValueError(f"{raw[:80]} is not a single plain email address")
        clean = parsed.addr_spec  # the checked form, used for the header and the envelope
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
    checked = parse(to)
    if checked is None:  # check_recipients ran first; never build from anything else
        raise ValueError("not a single plain email address")
    mail = EmailMessage()
    mail["From"] = settings.smtp_from
    mail["To"] = checked
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


IN_STACK = frozenset({"localhost", "127.0.0.1", "::1", "mailpit"})  # deploy/compose.yaml


def _in_stack(host: str) -> bool:
    """A relay on loopback or the stack's own Mailpit: named, not any one-label host, which a
    resolver could complete into a corporate host outside the stack (M8.2 re-review)."""
    return host.lower() in IN_STACK


def _send_sync(messages: list[tuple[EmailMessage, str]]) -> None:
    settings = get_settings()
    login = bool(settings.smtp_username and settings.smtp_password is not None)
    if login and not settings.smtp_starttls and not _in_stack(settings.smtp_host):
        # Never the relay password in clear text over a network (M8.2 review).
        raise smtplib.SMTPException("login without STARTTLS is refused")
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=TIMEOUT_S) as smtp:
        if settings.smtp_starttls:
            smtp.starttls(context=ssl.create_default_context())
        if login and settings.smtp_password is not None:
            smtp.login(str(settings.smtp_username), settings.smtp_password.get_secret_value())
        for message, to in messages:
            # The envelope recipient is the checked address, never parsed from the header.
            smtp.send_message(message, to_addrs=[to])


async def send(messages: list[tuple[EmailMessage, str]]) -> None:
    """Send each (message, checked recipient) over one connection, off the event loop; a
    ``MailError`` by class."""
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
