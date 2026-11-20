"""Charts and the map snapshot as static SVG, drawn in Python (M7.5).

The M7 spec named ECharts on a Node renderer and a Playwright screenshot for the map; ADR-0005
deferred the Node worker (BL-17), and the M7.2 review asks Gotenberg's Chromium to run without
JavaScript. So reports draw their own SVG: no JavaScript, no new runtime, and the same markup
in the preview, the PDF and the email.

Every label is escaped here (``escape``), numbers are formatted, never interpolated raw, and
colours come from a fixed palette: nothing from a layout or an item reaches an attribute
unescaped. The output is marked safe only by the caller, after this module built it.
"""

from __future__ import annotations

import json
from functools import cache
from html import escape
from importlib.resources import files
from typing import Any

# The design system's sequential blue (light to dark), with a neutral for "no data".
STEPS = ("#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b")
NO_DATA = "#e1e0d9"
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e1e0d9"
SERIES = "#2a78d6"


def _n(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def bar_chart(bars: list[tuple[str, int]], title: str, width: int = 640) -> str:
    """Horizontal bars, one per label, with the value at the end of each bar."""
    bars = bars[:30]
    row, left, right, top = 22, 180, 60, 28
    height = top + row * max(len(bars), 1) + 12
    most = max((v for _, v in bars), default=0) or 1
    span = width - left - right
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" role="img" width="{width}" '
           f'height="{height}" viewBox="0 0 {width} {height}" font-family="sans-serif" '
           f'font-size="11"><title>{escape(title)}</title>']  # fmt: skip
    out.append(f'<text x="0" y="16" font-size="13" font-weight="600" fill="{INK}">'
               f"{escape(title)}</text>")  # fmt: skip
    for i, (label, value) in enumerate(bars):
        y = top + i * row
        w = span * max(value, 0) / most
        out.append(f'<text x="{left - 8}" y="{y + 14}" text-anchor="end" fill="{INK}">'
                   f"{escape(label[:30])}</text>")  # fmt: skip
        out.append(f'<rect x="{left}" y="{y + 4}" width="{_n(w)}" height="{row - 8}" rx="3" '
                   f'fill="{SERIES}"/>')  # fmt: skip
        out.append(f'<text x="{_n(left + w + 6)}" y="{y + 14}" fill="{MUTED}">{int(value)}</text>')
    if not bars:
        out.append(f'<text x="0" y="{top + 14}" fill="{MUTED}">No data.</text>')
    out.append("</svg>")
    return "".join(out)


def line_chart(points: list[tuple[str, int]], title: str, width: int = 640) -> str:
    """One series over time: labels along the bottom, a 2 px line with 8 px markers."""
    points = points[:120]
    height, left, right, top, bottom = 220, 40, 16, 28, 36
    span_x, span_y = width - left - right, height - top - bottom
    most = max((v for _, v in points), default=0) or 1
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" role="img" width="{width}" '
           f'height="{height}" viewBox="0 0 {width} {height}" font-family="sans-serif" '
           f'font-size="11"><title>{escape(title)}</title>']  # fmt: skip
    out.append(f'<text x="0" y="16" font-size="13" font-weight="600" fill="{INK}">'
               f"{escape(title)}</text>")  # fmt: skip
    for k in range(5):
        y = top + span_y * k / 4
        out.append(f'<line x1="{left}" x2="{width - right}" y1="{_n(y)}" y2="{_n(y)}" '
                   f'stroke="{GRID}"/>')  # fmt: skip
        out.append(f'<text x="{left - 6}" y="{_n(y + 4)}" text-anchor="end" fill="{MUTED}">'
                   f"{round(most * (4 - k) / 4)}</text>")  # fmt: skip
    if points:
        step = span_x / max(len(points) - 1, 1)
        xy = [(left + i * step, top + span_y * (1 - v / most)) for i, (_, v) in enumerate(points)]
        path = " ".join(f"{'M' if i == 0 else 'L'}{_n(x)},{_n(y)}" for i, (x, y) in enumerate(xy))
        out.append(f'<path d="{path}" fill="none" stroke="{SERIES}" stroke-width="2"/>')
        for x, y in xy:
            out.append(f'<circle cx="{_n(x)}" cy="{_n(y)}" r="4" fill="{SERIES}" '
                       'stroke="#fcfcfb" stroke-width="2"/>')  # fmt: skip
        for i in sorted({0, len(points) // 2, len(points) - 1}):
            out.append(f'<text x="{_n(xy[i][0])}" y="{height - 12}" text-anchor="middle" '
                       f'fill="{MUTED}">{escape(points[i][0])}</text>')  # fmt: skip
    else:
        out.append(f'<text x="{left}" y="{top + 20}" fill="{MUTED}">No data.</text>')
    out.append("</svg>")
    return "".join(out)


@cache
def _countries() -> list[dict[str, Any]]:
    """The boundaries the web map draws, pre-projected to Equal Earth (ADR-0004 amendment 1)."""
    raw = files("regwatch.reports").joinpath("data/countries.geojson").read_text("utf-8")
    return list(json.loads(raw)["features"])


def _rings(geometry: dict[str, Any]) -> list[list[list[float]]]:
    polygons = (geometry["coordinates"] if geometry["type"] == "MultiPolygon"
                else [geometry["coordinates"]])  # fmt: skip
    return [ring for polygon in polygons for ring in polygon]


@cache
def _shapes(width: int) -> tuple[tuple[str, str, str], ...]:
    """Each country's code, escaped name and path, built once per width: only the fill
    changes from one render to the next (M7.5 review finding 1)."""
    scale = width / 180
    return tuple(
        (str(f["properties"].get("iso") or ""),
         escape(str(f["properties"].get("name", f["properties"].get("iso", "")))),
         " ".join("M" + " L".join(f"{_n((x + 90) * scale)},{_n((45 - y) * scale)}"
                                  for x, y in ring) + "Z" for ring in _rings(f["geometry"])))
        for f in _countries()
    )  # fmt: skip


def map_snapshot(counts: dict[str, int], title: str, width: int = 640) -> str:
    """A choropleth of item counts per country (ISO alpha-2), in five steps, with a legend.
    Projected x and y lie in -90..90 (ADR-0004); y is flipped for SVG."""
    height = round(width * 0.5)
    most = max(counts.values(), default=0)

    def colour(code: str) -> str:
        value = counts.get(code, 0)
        if value <= 0 or most <= 0:
            return NO_DATA
        return STEPS[min(len(STEPS) - 1, int((value / most) * len(STEPS) - 1e-9))]

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" role="img" width="{width}" '
           f'height="{height + 40}" viewBox="0 0 {width} {height + 40}" font-family="sans-serif" '
           f'font-size="11"><title>{escape(title)}</title>']  # fmt: skip
    for code, name, d in _shapes(width):
        out.append(f'<path d="{d}" fill="{colour(code)}" stroke="#fcfcfb" stroke-width="0.5">'
                   f"<title>{name}: {counts.get(code, 0)}</title></path>")  # fmt: skip
    for i, step in enumerate(STEPS):
        out.append(f'<rect x="{10 + i * 34}" y="{height + 14}" width="30" height="10" '
                   f'fill="{step}"/>')  # fmt: skip
    out.append(f'<text x="{10 + len(STEPS) * 34 + 6}" y="{height + 23}" fill="{MUTED}">'
               f"fewer to more items (most: {most})</text>")  # fmt: skip
    out.append("</svg>")
    return "".join(out)
