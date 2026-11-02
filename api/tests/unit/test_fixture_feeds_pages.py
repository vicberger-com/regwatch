"""Feed and page fixtures: structure, hostility and change sequences (issue #12, REQ-25).

These are smoke tests of the fixtures themselves. The feedparser and change-detection tests
that consume them belong to M3 and M4.
"""

from __future__ import annotations

import difflib
import html
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from tests.fixtures.feeds import generate

FEEDS = Path(generate.__file__).parent
PAGES = FEEDS.parent / "pages"
ATOM = "{http://www.w3.org/2005/Atom}"


def _xml(source: Path | bytes) -> ET.Element:
    """Stdlib parser on purpose: it shows how a non-hardened parser treats each fixture.

    It never resolves external entities and caps entity expansion; production code uses
    defusedxml or feedparser (M3).
    """
    if isinstance(source, bytes):
        return ET.fromstring(source)  # noqa: S314 - project fixture, see docstring
    return ET.parse(source).getroot()  # noqa: S314 - project fixture, see docstring


def _text(name: str) -> str:
    raw = (PAGES / name).read_text(encoding="utf-8")
    raw = re.sub(r"<!--.*?-->", "", raw, flags=re.S)
    raw = re.sub(r"<script.*?</script>", "", raw, flags=re.S)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", raw)).split())


def _change(a: str, b: str) -> float:
    return 1 - difflib.SequenceMatcher(None, _text(a).split(), _text(b).split()).ratio()


def test_valid_rss_and_atom_parse() -> None:
    rss = _xml(FEEDS / "valid_rss.xml")
    items = rss.findall("./channel/item")
    assert len(items) == 10
    assert all(i.findtext("title") and i.findtext("link", "").startswith("https://") for i in items)
    atom = _xml(FEEDS / "valid_atom.xml")
    entries = atom.findall(f"{ATOM}entry")
    assert len(entries) == 10
    assert all(e.find(f"{ATOM}updated") is not None for e in entries)


def test_latin1_feed_is_latin1_bytes() -> None:
    raw = (FEEDS / "encoding_latin1.xml").read_bytes()
    assert raw.startswith(b'<?xml version="1.0" encoding="ISO-8859-1"?>')
    with pytest.raises(UnicodeDecodeError):
        raw.decode("utf-8")
    title = _xml(raw).findtext("./channel/title") or ""
    assert "Europäische" in title


def test_malformed_feed_is_rejected_by_a_strict_parser() -> None:
    with pytest.raises(ET.ParseError):
        _xml(FEEDS / "malformed.xml")


def test_future_dates_feed_has_one_problem_per_item() -> None:
    items = _xml(FEEDS / "future_dates.xml").findall("./channel/item")
    dates = [i.findtext("pubDate") for i in items]
    assert len(items) == 8
    assert dates.count(None) == 1
    assert any(d and "2099" in d for d in dates) and any(d and "31 Feb" in d for d in dates)


def test_hostile_feed_entities_are_not_resolved_and_parsing_is_bounded() -> None:
    raw = (FEEDS / "hostile.xml").read_text(encoding="utf-8")
    assert "file:///etc/passwd" in raw and "169.254.169.254" in raw and "<script>" in raw
    assert raw.count("<x>") >= sys.getrecursionlimit()
    start = time.monotonic()
    with pytest.raises(ET.ParseError, match="undefined entity"):
        _xml(FEEDS / "hostile.xml")
    assert time.monotonic() - start < 1


def test_generated_feeds() -> None:
    huge = generate.huge_feed()
    assert len(huge) >= 10 * generate.MIB
    assert huge == generate.huge_feed(), "must be deterministic"
    assert _xml(huge).find("./channel/item") is not None
    bomb = generate.entity_expansion()
    assert len(bomb) < 2000 and b"&lol8;" in bomb
    deep = generate.deep_nesting(depth=5000)
    assert deep.count(b"<rw:x>") == 5000


def test_generator_cli_writes_only_to_the_given_directory(tmp_path: Path) -> None:
    assert generate.main(["--out", str(tmp_path)]) == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(generate.GENERATORS)


def test_page_versions_change_as_documented() -> None:
    assert _change("page_v1.html", "page_v1.html") == 0
    assert 0.03 <= _change("page_v1.html", "page_v2.html") <= 0.07
    v2, v3 = _text("page_v2.html"), _text("page_v3.html")
    diff = [
        d
        for d in difflib.ndiff(v2.split("Status: ")[1:2], v3.split("Status: ")[1:2])
        if d[0] in "+-"
    ]
    assert diff, "status line must differ"
    assert v2.split("Status: ")[0] == v3.split("Status: ")[0]
    assert v2.split("Published 14")[1] == v3.split("Published 14")[1]


def test_listing_has_thirty_item_links() -> None:
    raw = (PAGES / "listing.html").read_text(encoding="utf-8")
    block = raw.split('<ul class="results">')[1].split("</ul>")[0]
    links = re.findall(r'<a href="(/pages/listing/item-\d\d\.html)"', block)
    assert len(links) == 30 == len(set(links))
    assert len(re.findall(r"<a ", raw)) > 30, "links outside the list must exist to be ignored"


def test_js_rendered_content_is_absent_from_static_html() -> None:
    data = json.loads((PAGES / "js_rendered_data.json").read_text(encoding="utf-8"))
    first = data["items"][0]["title"]
    assert first not in _text("js_rendered.html")
    assert "/pages/js_rendered_data.json" in (PAGES / "js_rendered.html").read_text(
        encoding="utf-8"
    )


def test_robots_variants() -> None:
    assert "Allow: /" in (PAGES / "robots_allow.txt").read_text()
    assert "Disallow: /\n" in (PAGES / "robots_disallow.txt").read_text()
    assert "Crawl-delay: 10" in (PAGES / "robots_crawl_delay.txt").read_text()


def test_redirect_configs() -> None:
    chain = json.loads((PAGES / "redirect_chain.json").read_text())
    assert chain["default_hops"] == 5 and chain["final"].startswith("/pages/")
    targets = json.loads((PAGES / "private_redirect.json").read_text())["targets"]
    assert "127.0.0.1" in targets["loopback"] and "169.254.169.254" in targets["metadata"]
    sequences = json.loads((PAGES / "sequences.json").read_text())
    assert len(sequences["sequences"]["change_detection"]) == len(
        sequences["expected"]["change_detection"]
    )


def test_no_bomb_is_committed() -> None:
    fixtures = FEEDS.parent
    assert not list(fixtures.rglob("*.gz"))
    assert max(p.stat().st_size for p in fixtures.rglob("*") if p.is_file()) < 1024 * 1024
