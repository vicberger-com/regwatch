"""PDF rendering through Gotenberg (M8.1), from the report HTML M7 renders.

Gotenberg is an internal sidecar (ADR-0001): reached only through the fixed-URL internal
client, on the internal network, with no published port. Its Chromium runs with JavaScript
off and may load nothing but the files of the request (`deploy/compose.yaml` flags: the M7.2
review's list). The HTML also carries its own CSP meta tag. What comes back is checked: a PDF
signature, a size cap, a page cap.
"""

from __future__ import annotations

import re

from regwatch.core.internal import InternalClient, InternalError
from regwatch.core.settings import get_settings

ROUTE = "/forms/chromium/convert/html"
DEADLINE_S = 90.0  # a render: two minutes in all for acceptance 1, with the queue
MAX_PAGES = 500
_PAGE = re.compile(rb"/Type\s*/Page(?![a-zA-Z])")


def client_factory(max_bytes: int) -> InternalClient:
    """The client for the PDF sidecar; tests replace it with one on a mock transport."""
    return InternalClient(str(get_settings().pdf_url), max_answer=max_bytes)


class PdfError(Exception):
    def __init__(self, error_class: str, message: str) -> None:
        super().__init__(message)
        self.error_class = error_class
        self.message = message


def page_count(pdf: bytes) -> int:
    """The number of page objects (`/Type /Page`, not `/Pages`)."""
    return len(_PAGE.findall(pdf))


async def render(html: str, title: str, max_bytes: int) -> tuple[bytes, int]:
    """The PDF for ``html``, and its page count."""
    client = client_factory(max_bytes)
    try:
        pdf = await client.post_files(
            ROUTE,
            files={"files": ("index.html", html.encode("utf-8"), "text/html")},
            data={"preferCssPageSize": "true", "printBackground": "true",
                  "metadata": '{"Creator": "regwatch", "Title": ' + _json(title) + "}"},
            deadline_s=DEADLINE_S,
        )  # fmt: skip
    except InternalError as exc:
        raise PdfError(exc.reason, exc.detail) from None
    if not pdf.startswith(b"%PDF-"):
        raise PdfError("pdf-malformed", "the PDF service did not answer with a PDF")
    pages = page_count(pdf)
    if pages > MAX_PAGES:
        raise PdfError("pdf-too-long", f"the report has more than {MAX_PAGES} pages")
    return pdf, pages


def _json(text: str) -> str:
    import json

    return json.dumps(text[:200])
