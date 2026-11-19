"""Sanitized HTML snapshots (M4 test plan: sanitiser against XSS payloads)."""

from __future__ import annotations

import uuid

import pytest

from regwatch.processing.snapshot import MAX_BYTES, sanitize, snapshot

PAYLOADS = [
    "<script>alert(1)</script>", "<img src=x onerror=alert(1)>", "<svg onload=alert(1)>",
    '<a href="javascript:alert(1)">x</a>', '<a href="data:text/html,<script>x</script>">x</a>',
    '<iframe src="https://evil.example"></iframe>', "<style>body{background:url(x)}</style>",
    '<p style="background:url(javascript:alert(1))">x</p>', "<form action=x><input></form>",
    '<div onclick="alert(1)">x</div>', "<!--<script>x</script>-->", "<base href=//evil>",
    '<meta http-equiv="refresh" content="0;url=//evil">', "<object data=x></object>",
    "<math><mtext><table><mglyph><style><img src=x onerror=alert(1)>",
]  # fmt: skip


@pytest.mark.parametrize("payload", PAYLOADS)
def test_xss_payloads_leave_nothing_active(payload: str) -> None:
    out = sanitize(f"<main><p>Text</p>{payload}</main>".encode()).lower()
    active_parts = ("<script", "onerror", "onload", "onclick", "javascript:", "<iframe",
                    "<style", "style=", "<form", "<img", "<svg", "<base", "<meta", "<object",
                    "data:")  # fmt: skip
    for active in active_parts:
        assert active not in out, (payload, out)


def test_structure_and_safe_links_survive() -> None:
    out = sanitize(
        b'<h1>Act</h1><p>See <a href="https://reg.example/a" target=_blank>it</a>.'
        b"</p><table><tr><td colspan=2>x</td></tr></table>"
    )
    assert "<h1>Act</h1>" in out and 'colspan="2"' in out
    assert 'href="https://reg.example/a"' in out and 'rel="noopener noreferrer nofollow"' in out
    assert "target" not in out


async def test_only_this_sources_html_is_snapshotted() -> None:
    sid, item = uuid.uuid4(), uuid.uuid4()
    stored: dict[str, bytes] = {}
    bodies = {f"raw/{sid}/" + "a" * 64: b"<p>ok</p>",
              f"raw/{uuid.uuid4()}/" + "b" * 64: b"<p>x</p>",
              f"raw/{sid}/" + "c" * 64: b"x" * (MAX_BYTES + 1)}  # fmt: skip

    async def load(k: str) -> bytes | None:
        return bodies.get(k)

    async def store(k: str, b: bytes) -> None:
        stored[k] = b

    async def shot(ref: str, mime: str = "text/html; charset=utf-8") -> str | None:
        return await snapshot({"body_ref": ref, "mime": mime}, sid, item, 2, load, store)

    keys = list(bodies)
    assert (
        await shot(keys[0]) == f"html/{item}/2.html"
        and stored[f"html/{item}/2.html"] == b"<p>ok</p>"
    )
    assert await shot(keys[1]) is None  # another source's body
    assert await shot(keys[2]) is None  # too large
    assert await shot(keys[0], "application/pdf") is None
    assert await shot("../../etc/passwd") is None

    async def broken(k: str) -> bytes | None:
        raise OSError("store down")

    assert await snapshot({"body_ref": keys[0], "mime": "text/html"}, sid, item, 3, broken,
                          store) is None  # fmt: skip
