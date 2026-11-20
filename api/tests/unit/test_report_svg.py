"""Unit: report charts and the map snapshot as SVG (M7.5)."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

from regwatch.reports.svg import NO_DATA, STEPS, bar_chart, line_chart, map_snapshot

WEB_COPY = Path(__file__).resolve().parents[3] / "web" / "public" / "map" / "countries.geojson"
API_COPY = Path(__file__).resolve().parents[2] / "src/regwatch/reports/data/countries.geojson"


def _parse(svg: str) -> ElementTree.Element:
    return ElementTree.fromstring(svg)  # noqa: S314 - our own output, well-formed or the test fails


def test_labels_are_escaped_and_the_svg_is_well_formed() -> None:
    hostile = '<script>x</script>" onload="y'
    for svg in (bar_chart([(hostile, 3), ("b", 1)], hostile), line_chart([(hostile, 2)], hostile),
                map_snapshot({"DE": 3}, hostile)):  # fmt: skip
        root = _parse(svg)
        assert "<script>" not in svg and 'onload="y' not in svg
        assert root.find("{http://www.w3.org/2000/svg}title") is not None


def test_bars_scale_to_the_largest_value() -> None:
    root = _parse(bar_chart([("a", 10), ("b", 5)], "T"))
    widths = [float(r.get("width", "0")) for r in root.iter("{http://www.w3.org/2000/svg}rect")]
    assert widths[0] == 2 * widths[1] > 0


def test_the_map_shades_countries_with_items() -> None:
    svg = map_snapshot({"DE": 10, "FR": 1}, "Items")
    fills = {p.findtext("{http://www.w3.org/2000/svg}title", "").split(":")[0]: p.get("fill")
             for p in _parse(svg).iter("{http://www.w3.org/2000/svg}path")}  # fmt: skip
    assert fills["Germany"] == STEPS[-1] and fills["France"] == STEPS[0]
    assert fills["Brazil"] == NO_DATA


def test_the_api_copy_of_the_boundaries_matches_the_web_map() -> None:
    assert API_COPY.read_bytes() == WEB_COPY.read_bytes()
