"""The development proxy keeps a route's own CSP (BL-68 review finding 1).

Caddy applies a ``header`` block that deletes a field when the response is written, so an
unconditional ``Content-Security-Policy`` there replaced the sandboxing policy of
``GET /branding/logo``. A ``?`` prefix sets the site policy only when the upstream sent none.
This reads the file; the reviewer checked the behaviour against the pinned Caddy image.
"""

from __future__ import annotations

import re
from pathlib import Path

CADDYFILE = Path(__file__).resolve().parents[2] / "deploy" / "Caddyfile"


def _directives() -> list[str]:
    lines = CADDYFILE.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]


def test_site_csp_is_a_default_not_an_override() -> None:
    csp = [d for d in _directives() if re.match(r"[?+-]?Content-Security-Policy\b", d)]
    assert csp, "the proxy must still send a site CSP"
    assert all(d.startswith("?Content-Security-Policy ") for d in csp), csp


def test_site_csp_keeps_its_core_directives() -> None:
    (csp,) = [d for d in _directives() if d.startswith("?Content-Security-Policy ")]
    for directive in ("default-src 'self'", "script-src 'self'", "object-src 'none'",
                      "frame-ancestors 'none'", "base-uri 'none'"):  # fmt: skip
        assert directive in csp
