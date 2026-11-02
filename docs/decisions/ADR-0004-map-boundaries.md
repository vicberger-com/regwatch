# ADR-0004: Natural Earth 1:50m admin-0 as a build-time GeoJSON for the MapLibre choropleth

**Status:** accepted at Gate G0 on 2026-11-02 · **Date:** 2026-11-01 · **Requirements:** REQ-06, REQ-18 (also REQ-19, REQ-20)
**Research:** R-05, `docs/research/R-05-map-boundaries.md` (#7); licenses in R-01 rows 29 to 32 and in R-05

## Context

The main screen is a world choropleth (REQ-06) with light, dark and high-contrast themes (REQ-18). The M6 budgets are a map render under 1 s for 250 features and a bundle under 600 KB gzip excluding map data. Equal Earth is the default projection, and high-contrast mode adds hatch patterns (`docs/contracts/screens.md`). Shading is keyed by `jurisdiction.code` (ISO 3166-1 alpha-2 plus custom codes) through `jurisdiction.geometry_ref`. The 3.2 stack already names MapLibre GL JS and Natural Earth. R-01 found that world-atlas, the planned source of prebuilt TopoJSON, is archived (BL-12).

R-05 measured MapLibre GL JS 6.16.0 in headless Chromium against Natural Earth v5.1.2 admin-0 at 1:110m, 1:50m and 1:10m, delivered as GeoJSON, TopoJSON and PMTiles:
- 1:110m has no polygon for 75 of 250 codes, among them Singapore (a day-one source), Hong Kong, Malta and Bahrain.
- 1:50m covers 237 codes. The 13 it misses are overseas parts drawn inside a parent, or uninhabited islands.
- MapLibre 6.16.0 has no built-in Equal Earth projection. Its experimental `addProjection` API renders GeoJSON in a custom CRS, but tile sources must be cut in that CRS's own grid.

## Decision

1. **Dataset and resolution:** Natural Earth v5.1.2 `ne_50m_admin_0_countries`, simplified at build time (`mapshaper -simplify 25% keep-shapes`, coordinates rounded to 0.001°), with fields reduced to `id` (`ADM0_A3`), `iso` (`ISO_A2_EH`) and `name`. Also vendor `ne_50m_admin_0_breakaway_disputed_areas`, processed the same way.
2. **Delivery:** one static GeoJSON file per layer, served by Caddy with compression and loaded through a MapLibre `geojson` source URL, so parsing runs in the worker. No TopoJSON and no PMTiles for the boundary layers.
3. **Build:** a script under `scripts/` (written in M6) downloads the tagged Natural Earth release, checks the file hash, runs mapshaper (MPL-2.0, tooling only) and writes the files and a `geometry_ref` to `jurisdiction.code` mapping table. Its output is committed, so the application build needs no network and no mapshaper.
4. **`geometry_ref`** holds Natural Earth's `ADM0_A3`. The quirk table in R-05 is the seed for the mapping (FRA → FR, NOR → NO, KOS → XK, TWN → TW, IOA and ATC → AU; CYN, SOL and KAS map to no jurisdiction).
5. **Disputed borders:** Natural Earth's default point of view, with the disputed and breakaway areas drawn on top in the neutral colour, with a dashed outline and NE's `NOTE_BRK` text in the tooltip. The legal page states that boundaries imply no endorsement.
6. **Projection:** Equal Earth through MapLibre's experimental `addProjection` and a worker projection handler, using a project-owned Equal Earth function (about 25 lines, from the published formula). Mercator is the automatic fallback if registration fails, and a setting can force it. The MapLibre version is pinned exactly, and upgrades re-run the projection test.
7. **High contrast:** `fill-pattern` with five hatch images generated at runtime (`map.addImage`), one per colour step.
8. **Supranational bodies** (EU, COE, OECD, UN, INTL) have no geometry. They appear in the listbox and as legend chips; selecting the EU outlines its members.

## Alternatives considered

| Option | License | Pros | Cons |
| --- | --- | --- | --- |
| **NE 1:50m simplified, GeoJSON (chosen)** | public domain; mapshaper MPL-2.0 (tooling) | Draws every day-one jurisdiction; no runtime decoder; worker-side parse; works with the custom Equal Earth CRS | About twice the gzip size of the same data as TopoJSON |
| NE 1:50m simplified, TopoJSON | public domain; topojson-client ISC | Smallest payload; shared borders | Main-thread decode; adds a runtime dependency last released in 2019; world-atlas is archived, so a build step is needed anyway |
| NE 1:110m (any format) | public domain | Smallest and fastest | Misses 75 codes, including Singapore, Hong Kong, Malta and Bahrain |
| NE 1:50m unsimplified | public domain | Most detail at 1:50m | Payload more than three times larger with no visible gain at world zoom |
| NE 1:10m | public domain | Covers 2 more codes (GI, UM); worldview files exist only here | Payload in megabytes (2.6 MB gzip as slim GeoJSON); render time in R-05 |
| PMTiles vector tiles | BSD-3 (PMTiles), BSD-2 (tippecanoe) | Range requests; scales to subdivisions | Tiles are Web Mercator only, so they do not render in the Equal Earth CRS; extra reader in the bundle (7.5 KB gzip) |
| world-atlas prebuilt TopoJSON | ISC | No build step | Archived upstream (R-01 N7); fixed to 1:110m and 1:50m with its own field choices |
| Leaflet with raster tiles; D3 geo with SVG; ECharts geo | BSD-2; ISC; Apache-2.0 | D3 and ECharts have Equal Earth built in | Rejected in 3.2 and 3.7 (raster tiles need a tile service); not re-measured in R-05 |

## Consequences

- Positive: one public-domain data file, about 170 KB gzip, that the build reproduces from a tagged release. The map renders within the 1 s budget on the measured hardware. Patterns work for the high-contrast theme. No archived dependency remains.
- Negative: Equal Earth depends on an experimental MapLibre API, so an upgrade may change it (mitigation: exact pin, projection test, Mercator fallback). MapLibre alone takes about 451 KB of the 600 KB gzip bundle budget, which leaves about 150 KB for React, TanStack, Radix and application code on the map route (ECharts must be lazy-loaded). Thirteen ISO codes have no polygon of their own and rely on the listbox and table view.
- Register: world-atlas and topojson-client are rejected; mapshaper is added as tooling (3.6). BL-12 is resolved by this ADR.
- Follow-up backlog rows: BL-25 (per-deployment worldview from NE 1:10m worldview files), BL-26 (ISO 3166-2 subdivision layer, loaded per country).


## Owner decisions at Gate G0 (2026-11-02)

- Accepted as written. The R-05 assumptions are accepted: Natural Earth default view with disputed areas drawn neutral and a non-endorsement statement on the legal page; French overseas regions are list-only; Antarctica is drawn neutral as AQ.
