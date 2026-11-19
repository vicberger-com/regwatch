"""PDF text in a sandboxed child (M4 roadmap 4.5; owner decision 2026-11-19)."""

from __future__ import annotations

import uuid

import pytest

from regwatch.processing import pdf
from regwatch.processing.pdf_child import answer


def make_pdf(text: str) -> bytes:
    """A one-page PDF showing ``text`` in Helvetica, built by hand (no writer library)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for n, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1, xref)  # fmt: skip
    return out


def test_the_child_reads_a_pdfs_text_and_refuses_garbage() -> None:
    assert "Article 1 applies" in answer(make_pdf("Article 1 applies"))["text"]
    for junk in (b"", b"%PDF-1.4\n garbage", b"not a pdf at all", b"%PDF-" + b"\x00" * 5000):
        assert "error" in answer(junk) or not answer(junk).get("text", "").strip()


async def test_a_stored_pdf_gets_its_text_in_a_child_process() -> None:
    sid = uuid.uuid4()
    ref = f"raw/{sid}/" + "a" * 64
    bodies = {ref: make_pdf("Operators must report incidents")}

    async def load(k: str) -> bytes | None:
        return bodies.get(k)

    row = {"url": "https://reg.example/a.pdf", "body_ref": ref, "mime": "application/pdf"}
    got = await pdf.with_text(row, sid, load)
    assert "Operators must report incidents" in got["text"]
    # Another source's body, a body over the cap, text already there: left as they are.
    assert "text" not in await pdf.with_text({**row, "body_ref": f"raw/{uuid.uuid4()}/" + "a" * 64},
                                            sid, load)  # fmt: skip
    assert (await pdf.with_text({**row, "text": "kept"}, sid, load))["text"] == "kept"
    bodies[ref] = b"x" * (pdf.MAX_BYTES + 1)
    assert "text" not in await pdf.with_text(row, sid, load)
    bodies[ref] = b"%PDF-1.4 broken"
    assert "text" not in await pdf.with_text(row, sid, load)


async def test_a_child_past_its_wall_clock_gives_no_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pdf, "COMMAND", ("/bin/sh", "-c", "sleep 5"))
    monkeypatch.setattr(pdf, "WALL_SECONDS", 0.2)
    assert await pdf.pdf_text(make_pdf("x")) is None


async def test_a_stored_xhtml_body_gets_its_text() -> None:
    """EUR-Lex and legislation.gov.uk XHTML, through M3's isolated extractor."""
    sid = uuid.uuid4()
    ref = f"raw/{sid}/" + "b" * 64
    body = (b'<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml"><body><main>'
            b"<p>Article 1. Member States shall ensure that operators report incidents.</p>"
            b"</main></body></html>")  # fmt: skip

    async def load(k: str) -> bytes | None:
        return body if k == ref else None

    row = {"body_ref": ref, "mime": "application/xhtml+xml; charset=utf-8"}
    assert "operators report incidents" in (await pdf.with_text(row, sid, load))["text"]
    assert "text" not in await pdf.with_text({**row, "mime": "text/html"}, sid, load)
