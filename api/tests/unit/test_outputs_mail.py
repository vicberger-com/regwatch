"""Unit: recipient domains, header safety and the message (M8.2)."""

from __future__ import annotations

import pytest

from regwatch.outputs import mail


@pytest.mark.parametrize(
    ("address", "ok"),
    [
        ("ana@example.org", True), ("Ana@EXAMPLE.ORG", True), ("ana@legal.example.org", True),
        ("ana@example.org.evil.com", False), ("ana@notexample.org", False),
        ("ana@exämple.org", False), ("ana@", False), ("@example.org", True),
    ],
)  # fmt: skip
def test_domains_are_matched_exactly_or_as_subdomains(address: str, ok: bool) -> None:
    assert mail.allowed(address, ["example.org"]) is ok


def test_idn_domains_compare_in_ascii() -> None:
    assert mail.allowed("ana@exämple.org", ["xn--exmple-cua.org"])
    assert mail.allowed("ana@xn--exmple-cua.org", ["exämple.org"])


@pytest.mark.parametrize(
    ("addresses", "domains", "error"),
    [
        (["a@example.org"], [], "turned off"),
        (["a@example.org\nBcc: x@evil.com"], ["example.org"], "line breaks"),
        (["a@example.org, x@evil.com"], ["example.org"], "commas"),
        (["x@evil.com"], ["example.org"], "not on an allowed domain"),
        ([], ["example.org"], "at least one"),
        ([f"u{n}@example.org" for n in range(21)], ["example.org"], "at most 20"),
    ],
)
def test_bad_recipients_are_refused(addresses: list[str], domains: list[str], error: str) -> None:
    with pytest.raises(ValueError, match=error):
        mail.check_recipients(addresses, domains)


def test_duplicates_are_dropped() -> None:
    got = mail.check_recipients(["a@example.org", "A@example.org"], ["example.org"])
    assert got == ["a@example.org"]


def test_subjects_cannot_add_headers() -> None:
    with pytest.raises(ValueError):
        mail.plain_line("Report\r\nBcc: x@evil.com", 200)
    assert mail.plain_line("  Weekly digest  ", 200) == "Weekly digest"


def test_the_message_has_one_recipient_text_html_and_the_pdf(valid_env: dict[str, str]) -> None:
    from regwatch.core.settings import get_settings

    get_settings.cache_clear()
    built = mail.build("ana@example.org", "Weekly", "Hi <b>team</b>", b"%PDF-1.7", "r.pdf")
    assert built["To"] == "ana@example.org" and "Bcc" not in built and "Cc" not in built
    html = next(p for p in built.walk() if p.get_content_type() == "text/html").get_content()
    assert "&lt;b&gt;team&lt;/b&gt;" in html and "<img" not in html and "http" not in html
    pdf = next(p for p in built.iter_attachments())
    assert (pdf.get_content_type(), pdf.get_filename()) == ("application/pdf", "r.pdf")
    assert len(mail.hashed("ana@example.org")) == 16
