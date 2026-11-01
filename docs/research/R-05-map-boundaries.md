# R-05: Map boundary dataset, resolution and delivery format

**Issue:** #7 · **Module:** M6 · **Requirements:** REQ-06, REQ-18 · **Date:** 2026-11-01 · **ADR:** ADR-0004 (proposed)
**Inputs:** `docs/03-architecture.md` 3.2, 3.5, 3.6, 3.8 · `docs/04-data-model.md` 4.2, 4.5 · `docs/modules/M6-shell-map-ui.md` · `docs/contracts/screens.md` · R-01 (N6, N7, BL-12)

## Question

Which boundary dataset, resolution and delivery format should the map vendor, and does MapLibre GL JS meet the M6 budgets with it (map render under 1 s for 250 features; bundle under 600 KB gzip excluding map data; equal-earth projection by default; hatch patterns in the high-contrast theme)?

## Answer (summary)

Vendor **Natural Earth v5.1.2 admin-0 countries at 1:50m**, simplified at build time and delivered as **one static GeoJSON file** (about 170 KB gzip). Produce it from the Natural Earth release with **mapshaper** (MPL-2.0, build-time tooling) in a small build script. Drop world-atlas and topojson-client. Do not use PMTiles for the boundary layer. Natural Earth's default (de facto) point of view applies, with its 1:50m disputed and breakaway areas drawn on top as a neutral layer. MapLibre GL JS 6.16.0 rendered every 1:50m candidate in well under 1 s, and the hatch patterns work. Equal Earth works only through an *experimental* custom-projection API, so it needs a Mercator fallback. MapLibre alone takes about 451 KB gzip of the 600 KB bundle budget.

## Candidates

| ID | Dataset | Format | How produced |
| --- | --- | --- | --- |
| `raw_*` | NE admin-0 countries, all 169 attributes | GeoJSON | the release file unchanged (baseline only) |
| `slim_*` | the same, fields `id` (ADM0_A3), `iso` (ISO_A2_EH), `name`; coordinates rounded to 0.001° | GeoJSON | `mapshaper … -filter-fields … -rename-fields … -o format=geojson precision=0.001` |
| `topo_*` | the same fields, quantization 1e5 | TopoJSON | `mapshaper … -o format=topojson quantization=100000`; decoded in the browser by topojson-client 3.1.0 |
| `pm_*` | the `slim_*` file cut into MVT tiles z0 to z5 | PMTiles v3 | geojson-vt 4.0.3 and vt-pbf 3.1.3 (tiles), then the `pmtiles` 3.8.1 Python writer |
| `*_50s` | 1:50m simplified (`-simplify 25% keep-shapes`) | each of the formats above | as above, with the extra simplify step |

Resolutions: 1:110m and 1:50m. 1:10m was measured as an upper bound only (see "Why not 1:10m").

## Tool licenses (read from each project's own LICENSE file)

| Tool | Role | Repository | Tag | Commit | Last commit | File | SPDX | Policy |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Natural Earth vector | boundary data | nvkelso/natural-earth-vector | v5.1.2 | f1890d9f152c896d250a77557a5751a93d494776 | 2022-05-13 (tag) | LICENSE.md | public domain | allowed |
| mapshaper | build-time conversion and simplification | mbloch/mapshaper | v0.7.101 | b44c0fa95effac3d91526c8b62dc0de0ab88b464 | 2026-10-28 | LICENSE | MPL-2.0 | allowed; tooling, not bundled |
| topojson-server | alternative TopoJSON encoder | topojson/topojson-server | v3.0.1 | a6b85929df5dfc3de06d2bb0a4507b76967ce899 | 2019-09-05 | LICENSE | ISC | allowed, but inactive since 2019 |
| topojson-client | TopoJSON decoder (only if TopoJSON is chosen) | topojson/topojson-client | v3.1.0 | 71e5bd6428fd8b7a40fa980d2ef7862140851f03 | 2019-11-05 | LICENSE | ISC | allowed (R-01 row 32) |
| world-atlas | prebuilt TopoJSON | topojson/world-atlas | v2.0.2 | a912c0a22c3fbd1979cb6defdd6389d8c35e7c2a | archived | LICENSE | ISC | allowed, but archived (R-01 N7) |
| tippecanoe | vector-tile builder (PMTiles path only) | felt/tippecanoe | 2.79.0 | 68ab8dcc229f95b8b25877697d5e8d66783af503 | 2025-07-24 (tag) | LICENSE.md | BSD-2-Clause | allowed; tooling |
| PMTiles | archive format and readers | protomaps/PMTiles | none; `main` HEAD on 2026-11-01 (untagged) | aec8fa1341222fdddb3318e9ffa8e18e19b312f7 | 2026-09-16 | LICENSE | BSD-3-Clause (code); specification CC0 | allowed |
| MapLibre GL JS | renderer | maplibre/maplibre-gl-js | v6.16.0 | 538a7680ab16d5cf5a6564ee0ce72a11be14d142 | 2026-10-25 | LICENSE.txt | BSD-3-Clause | allowed (R-01 row 29) |

Method: `git ls-remote --tags` to find the tag and its peeled commit, then `git clone --depth 1 --branch <tag> --filter=blob:limit=200k` and read the file. The GitHub REST API was not available for these repositories in this session, so the archived and activity status come from R-01 and from the date of the commit read. Tippecanoe was not built: compiling it was declined in this session, so the PMTiles candidate was cut with geojson-vt and vt-pbf instead. Both are already MapLibre dependencies, so tile content is equivalent for this comparison.

## Jurisdiction model

### ISO 3166-1 coverage

Reference list: `i18n-iso-countries` 7.14.0, which has 250 alpha-2 codes: 249 ISO 3166-1 codes plus `XK` (Kosovo, user-assigned). Natural Earth key: `ISO_A2_EH`. Plain `ISO_A2` is `-99` for France and Norway, and `CN-TW` for Taiwan, so it is not usable as a key.

| Resolution | Features | Distinct `ISO_A2_EH` | Codes covered | Codes with no polygon of their own |
| --- | --- | --- | --- | --- |
| 1:110m | 177 | 175 | 175 / 250 | 75, including **SG, HK, MO, MT, BH**, AD, LI, MC, SM, VA, MV, MU and most small island states |
| 1:50m | 242 | 237 | 237 / 250 | 13: BQ, BV, CC, CX, GF, GI, GP, MQ, RE, SJ, TK, UM, YT |
| 1:10m | 258 | 239 | 239 / 250 | 11: the 1:50m list without GI and UM |

1:110m cannot draw Singapore (a day-one starter source, `docs/04-data-model.md` 4.5), Hong Kong, Malta or Bahrain. In a point-in-polygon test, Singapore falls inside Malaysia. This rules out 1:110m on its own. The 13 codes missing at 1:50m are overseas parts drawn inside a parent feature, or uninhabited islands. They stay reachable through the jurisdiction listbox and the table view (REQ-18).

### Quirks and mapping rules (1:50m)

`geometry_ref` should hold Natural Earth's `ADM0_A3`: it is unique across all 242 features and never `-99`. A build-time table maps each feature to a `jurisdiction.code`.

| NE feature (`ADM0_A3`) | `ISO_A2` | `ISO_A2_EH` | Quirk | Mapping rule |
| --- | --- | --- | --- | --- |
| France (FRA) | -99 | FR | Polygon includes French Guiana, Guadeloupe, Martinique, Réunion and Mayotte | FRA → `FR`; GF, GP, MQ, RE and YT have no own geometry. They shade with FR only if a later rule rolls them up (open question Q2) |
| Norway (NOR) | -99 | NO | Svalbard, Jan Mayen and Bouvet are not separate features | NOR → `NO`; SJ and BV are list-only |
| Netherlands (NLD) | NL | NL | Caribbean Netherlands (BQ) is inside the feature | NLD → `NL`; BQ is list-only |
| Kosovo (KOS) | -99 | XK | `XK` is user-assigned, not ISO 3166-1; TYPE Disputed | KOS → `XK` (custom code, already in `i18n-iso-countries`) |
| Taiwan (TWN) | CN-TW | TW | `ISO_A2` holds a subdivision-style code | TWN → `TW` (use `_EH`) |
| N. Cyprus (CYN) | -99 | -99 | no ISO code; listed in the disputed layer ("Self admin.; Claimed by Cyprus") | no jurisdiction; drawn neutral |
| Somaliland (SOL) | -99 | -99 | no ISO code; disputed layer ("Claimed by Somalia") | no jurisdiction; drawn neutral |
| Siachen Glacier (KAS) | -99 | -99 | TYPE Indeterminate | no jurisdiction; drawn neutral |
| Indian Ocean Ter. (IOA), Ashmore and Cartier Is. (ATC) | -99 | AU | three features share `AU` with Australia; IOA holds Christmas Island (CX) and Cocos (CC) | IOA, ATC → `AU` (several features per code) |
| W. Sahara (SAH) | EH | EH | TYPE Indeterminate; the test point (-13.0, 24.5) lies inside the Morocco polygon, not SAH | SAH → `EH`; the disputed layer covers the area |
| Palestine (PSX), Israel (ISR) | PS, IL | PS, IL | TYPE Indeterminate and Disputed; Golan Heights is inside Israel | normal mapping; the disputed layer covers Golan |
| Falkland Is. (FLK), Br. Indian Ocean Ter. (IOT) | FK, IO | FK, IO | TYPE Disputed | normal mapping |
| Antarctica (ATA) | AQ | AQ | TYPE Indeterminate; very large in every projection | AQ → `AQ`; consider hiding (open question Q3) |
| Hong Kong (HKG), Macao (MAC) | HK, MO | HK, MO | separate polygons at 1:50m, absent at 1:110m | normal mapping |

Day-one jurisdictions from 4.5 that are drawn at 1:50m: all of them, including China and Singapore.

### Supranational bodies (EU, COE, OECD, UN, INTL)

These are rows of `kind = supranational` with no geometry (`geometry_ref` null). Recommended display, with no extra map data:
1. A "Supranational" group at the top of the jurisdiction listbox, and a fixed legend chip above the map that uses the same colour scale. Selecting it opens the normal jurisdiction panel.
2. When the EU chip is hovered or selected, member states get an outline highlight (a `line` layer filtered to member codes). Their fill is not changed, so national and EU activity are never merged. Membership comes from `jurisdiction.parent_id` or a membership list in M2, not from the geometry.

### ISO 3166-2 subdivisions (later)

Natural Earth admin-1 at 1:50m covers only 9 countries (AUS, BRA, CAN, CHN, IDN, IND, RUS, USA, ZAF; 294 features, 293 with a usable `iso_3166_2`). At 1:10m it covers 251 countries in 4,596 features, 4,407 of them with a usable code (60 codes repeat), but the file is 40.7 MB raw. Subdivisions are feasible later as a lazily loaded, per-country layer cut from 1:10m with the same build script (simplified per country) or served as PMTiles under Mercator. They are not part of this decision.

### Disputed-borders policy (recommended)

- **Geometry:** Natural Earth's default point of view, which NE describes as de facto control. For example, Crimea falls inside the Russia polygon and Aksai Chin inside China.
- **Neutral overlay:** draw `ne_50m_admin_0_breakaway_disputed_areas` (28 features, 147 KB raw) above the choropleth in the "no data" colour with a dashed outline and no shading. The tooltip shows NE's `NOTE_BRK` text (for example "Admin. by Russia; Claimed by Ukraine"). No claimant's activity is painted over a disputed area, so the map takes no side in its encoding.
- **Statement:** the legal page and the map's text alternative state that boundaries come from Natural Earth and do not imply endorsement.
- **Why not another point of view:** NE ships 31 country worldviews and an `_iso` view only at 1:10m (13 MB each). The `_iso` file leaves the disputed areas as gaps, maps N. Cyprus to `CY`, Somaliland to `SO` and Kosovo to `RS`, but still places the Western Sahara test point inside Morocco. A per-deployment worldview can be added later by running the same build script on a 1:10m worldview file (proposed as a backlog item).

## Measurements

### Environment

- **Runner:** cloud container, 4 vCPU Intel Xeon @ 2.80 GHz, 15 GB RAM, **no GPU**. Node 22.23.4, pnpm 10.28.0.
- **Browser:** Playwright 1.63.0 headless Chromium 153.0.8010.12. WebGL reports `ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero)))`, which is a CPU software rasteriser. Every frame rate below is therefore a pessimistic lower bound, not what a laptop GPU would show. Load and parse times are less affected.
- **Page:** 1280 × 800 at device scale 1, world view (zoom 1.2 Mercator, 1.25 Equal Earth). A fill layer uses a `match` expression on `id` over five colour steps (`--map-0` to `--map-4`), with a white 0.6 px border line layer. Files come from a local static server with `Cache-Control: no-store` and no compression, so fetch times exclude network transfer.
- **Runs:** 5 runs per case, each in a fresh browser context. The tables show the median.

### Payload (bytes)

| Candidate | 1:110m raw | 1:110m gzip -9 | 1:50m raw | 1:50m gzip -9 | 1:50m simplified raw | 1:50m simplified gzip -9 | 1:10m raw | 1:10m gzip -9 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| NE release GeoJSON (all fields) | 838,726 | 209,293 | 3,083,490 | 1,023,959 | n/a | n/a | 13,287,234 | 4,723,018 |
| Slim GeoJSON | 194,851 | 65,647 | 1,678,732 | 566,757 | **470,726** | **169,015** | 9,107,447 | 2,637,198 |
| TopoJSON | 108,379 | 39,021 | 746,786 | 229,808 | 242,086 | 83,226 | 3,643,202 | 910,636 |
| PMTiles archive, z0 to z5 (tiles gzip inside) | 282,569 | n/a | 742,751 | n/a | 443,336 | n/a | not built | not built |

Disputed-areas overlay (1:50m, simplified the same way): 13,043 raw, 4,046 gzip. For PMTiles, the browser downloads only the header, the directory and the visible tiles: {{PMXFER}}.

Code (gzip -9): `maplibre-gl.mjs` 294,033, `maplibre-gl-worker.mjs` 146,852, `maplibre-gl.css` 10,180, which totals **451,065** (75% of the 600 KB budget). `pmtiles` reader 7,542. `topojson-client` `feature` 735.

### Timing, Mercator (median of 5, ms)

"Parse" is main-thread `JSON.parse`, plus the TopoJSON decode where it applies. "First render" runs from `addSource` to the first `idle`, including worker tiling and drawing. "Ready" runs from navigation start to that `idle`. "Recolor" is `setPaintProperty` with a new step mapping, up to `idle`. "fps" is the requestAnimationFrame rate during a 6 s scripted pan and zoom (four `easeTo` legs, zoom 1.3 to 4).

| Candidate | Parse | First render (min to max) | Ready | Recolor | fps | p95 frame |
| --- | --- | --- | --- | --- | --- | --- |
| raw 1:110m | 14 | 528 (498 to 621) | 858 | 318 | 13 | 117 |
| slim 1:110m | 2 | 451 (414 to 526) | 747 | 313 | 14 | 100 |
| topo 1:110m | 2 + 7 | 493 (462 to 567) | 805 | 337 | 14 | 100 |
| pm 1:110m | n/a | 516 (485 to 582) | 705 | 72¹ | 17 | 83 |
| raw 1:50m | 40 | 896 (870 to 987) | 1,302 | 412 | 10 | 133 |
| slim 1:50m | 27 | 828 (704 to 1,005) | 1,178 | 365 | 11 | 133 |
| topo 1:50m | 16 + 23 | 765 (722 to 903) | 1,146 | 368 | 10 | 150 |
| pm 1:50m | n/a | 544 (495 to 598) | 776 | 91¹ | 14 | 100 |
| **slim 1:50m simplified** | 10 | **579** (552 to 667) | 896 | 339 | 11 | 133 |
| topo 1:50m simplified | 2 + 11 | 546 (506 to 691) | 868 | 366 | 11 | 133 |
| pm 1:50m simplified | n/a | 521 (511 to 608) | 717 | 84¹ | 15 | 83 |
| raw 1:10m | 122 | 2,372 (2,143 to 2,927) | 3,073 | 550 | 8 | 217 |
| slim 1:10m | 93 | 2,289 (2,067 to 2,420) | 2,839 | 589 | 8 | 183 |
| topo 1:10m | 89 + 57 | 2,307 (1,910 to 2,523) | 2,812 | 466 | 8 | 183 |

¹ Not comparable: the PMTiles page used a five-branch expression instead of the 240-entry `match`, because it has no feature list in the main thread.

### Timing, Equal Earth and high contrast (median of 5, ms)

| Candidate | Projection | Theme | Parse | First render (min to max) | Ready | Recolor | fps |
| --- | --- | --- | --- | --- | --- | --- | --- |
| slim 1:110m | Equal Earth | default | 2 | 412 (339 to 443) | 752 | 232 | 14 |
| slim 1:50m | Equal Earth | default | 19 | 643 (613 to 788) | 966 | 263 | 11 |
| **slim 1:50m simplified** | Equal Earth | default | 8 | **451** (426 to 538) | 804 | 241 | 12 |
| topo 1:50m simplified | Equal Earth | default | 2 + 10 | 479 (449 to 528) | 851 | 242 | 13 |
| slim 1:10m | Equal Earth | default | 110 | 1,829 (1,744 to 1,937) | 2,353 | 261 | 9 |
| slim 1:50m simplified | Mercator | hatch patterns | 9 | 641 (599 to 659) | 936 | n/a | 10 |
| slim 1:50m simplified | Equal Earth | hatch patterns | 8 | 523 (496 to 560) | 838 | n/a | 10 |
| slim 1:50m simplified + disputed overlay | Equal Earth | default | {{DISPARSE}} | {{DISFIRST}} | {{DISREADY}} | {{DISRECOLOR}} | {{DISFPS}} |

### Reading the numbers

- **Render budget (under 1 s for 250 features):** every 1:110m and 1:50m candidate met it in software rendering. The worst was unsimplified 1:50m at 896 ms. 1:10m missed it (1.8 s to 2.4 s).
- **Recolour (M6 acceptance criterion 1, under 500 ms):** met at 1:50m (239 ms to 412 ms) but not at 1:10m (466 ms to 589 ms).
- **Frame rate:** 8 to 17 fps everywhere, including 1:110m. The software rasteriser sets the ceiling, not the data. Simplifying 1:50m did not change the frame rate measurably here, but it cut payload by 70% and first render by about 30%. A frame-rate check on GPU hardware remains for M6 (Lighthouse CI and Playwright on a GPU runner).
- **GeoJSON or TopoJSON:** at 1:50m simplified they are equal within run-to-run spread (579 ms against 546 ms in Mercator; 451 ms against 479 ms in Equal Earth). TopoJSON saves 86 KB gzip, but it adds a main-thread decode and a runtime dependency whose last release was in 2019.
- **PMTiles:** fastest first render and fewest bytes per view in Mercator, but see the projection section.
- **Errors:** none. The only console output was Chromium's "GPU stall due to ReadPixels" notice, caused by the screenshot.

### Commands

The proof of concept lived in a scratch directory outside the repository (`$S`) and is not committed.
```
# data: NE v5.1.2 sparse checkout (commit f1890d9)
git clone --depth 1 --branch v5.1.2 --filter=blob:none --no-checkout https://github.com/nvkelso/natural-earth-vector $S/ne
git -C $S/ne sparse-checkout set --no-cone /LICENSE.md /geojson/ne_{110m,50m,10m}_admin_0_countries.geojson /geojson/ne_50m_admin_0_breakaway_disputed_areas.geojson && git -C $S/ne checkout
# proof-of-concept packages
cd $S/poc && pnpm add maplibre-gl@6.16.0 pmtiles@4.5.0 topojson-client@3.1.0 i18n-iso-countries@7.14.0 && pnpm add -D mapshaper@0.7.101 geojson-vt@4 vt-pbf@3 esbuild
# slim GeoJSON, TopoJSON, simplified variant (r = 110m | 50m | 10m)
pnpm exec mapshaper ne_${r}_admin_0_countries.geojson -filter-fields ADM0_A3,ISO_A2_EH,NAME -rename-fields id=ADM0_A3,iso=ISO_A2_EH,name=NAME -o slim_${r}.geojson format=geojson precision=0.001
pnpm exec mapshaper ne_${r}_admin_0_countries.geojson -filter-fields … -rename-fields … -o topo_${r}.json format=topojson quantization=100000
pnpm exec mapshaper ne_50m_admin_0_countries.geojson -filter-fields … -rename-fields … -simplify 25% keep-shapes -o slim_50s.geojson format=geojson precision=0.001
# PMTiles: geojson-vt (maxZoom 5, tolerance 3, extent 4096, buffer 64) -> vt-pbf -> pmtiles 3.8.1 Writer (gzip tiles)
node tile.mjs $S/poc slim_${r}.geojson tiles_${r} 5 && uv run --no-project --with 'pmtiles==3.*' python -I topm.py tiles_${r} pm_${r}.pmtiles
# sizes
stat -c %s FILE; gzip -9 -c FILE | wc -c
# benchmark: static server, then 5 runs per case in headless Chromium
node serve.mjs $S/site 8765 &
node bench.cjs results/full.json 5 raw_110m:mercator slim_110m:mercator … slim_50s:ee:1 pm_50s:ee
python3 -I summarize.py results/full.json
```

## Projection and high-contrast patterns

- **Equal Earth:** MapLibre GL JS 6.16.0 has no built-in Equal Earth. Its style specification (26.5.1) accepts `mercator`, `globe` and `vertical-perspective`. Version 6.16.0 does have an **experimental** `addProjection(crs)` that takes `forward` and `inverse` functions and a quad tile matrix set. GeoJSON sources need a worker-side `setProjectionHandler`, loaded with `importScriptInWorkers`. The proof of concept registered `custom:equal-earth` with a 25-line Equal Earth function (Šavrič, Patterson and Jenny 2018, spherical, Newton inverse). It used `origin [-XMAX, XMAX]` and an extent of `2 × XMAX`, where `XMAX` is `forward([180, 0])[0]`. Countries rendered correctly in the Equal Earth shape, with fills, borders, recolouring and feature state, and first render was no slower than Mercator. Limits: the API is marked experimental; a registered projection renders a single world with no wrap-around; and **every tile source must already be cut in the CRS's own grid**. A PMTiles archive cut in Web Mercator rendered under Equal Earth with no error, but kept its Mercator shapes, so it would silently show the wrong projection.
- **Hatch patterns (high-contrast theme):** `fill-pattern` with a data-driven `match` over five 16 px images generated on a canvas and added with `map.addImage` rendered correctly in both projections. It added about 60 ms to 70 ms to first render. Hatch density and line weight grow with the colour step, so the step can be read without colour (WCAG 1.4.1). Line spacing and contrast should be tuned with the design tokens in M6.

## Why not 1:10m

1:10m adds only two codes over 1:50m (GI, UM). Its slim GeoJSON is 2.6 MB gzip, its first render took 1.8 s to 2.4 s (over budget), and recolouring took up to 589 ms (over the 500 ms criterion). It is needed only as the source of NE's worldview files (BL-25) and admin-1 subdivisions (BL-26), and both would be simplified at build time.

## Recommendation

1. **Dataset:** Natural Earth v5.1.2 `ne_50m_admin_0_countries`, plus `ne_50m_admin_0_breakaway_disputed_areas` as a neutral overlay.
2. **Resolution:** 1:50m simplified at build time (`-simplify 25% keep-shapes`, `precision=0.001`). It draws every day-one jurisdiction at 169 KB gzip, and first render took 451 ms in Equal Earth and 579 ms in Mercator.
3. **Format:** slim GeoJSON (`id`, `iso`, `name`), served compressed. TopoJSON is an acceptable fallback if payload ever matters more than a runtime dependency. PMTiles is rejected for boundaries because it cannot follow the Equal Earth CRS. It stays an option for a Mercator basemap or for subdivisions.
4. **TopoJSON tooling:** none is needed. world-atlas (archived) and topojson-client are dropped (BL-12). mapshaper (MPL-2.0, active, tooling only) does the build. topojson-server was not chosen because it has been inactive since 2019.
5. **MapLibre:** it meets the render budget. The bundle budget is tight: 451 KB of 600 KB. Equal Earth relies on an experimental API, so pin the version exactly, keep a Mercator fallback and add a projection test.
6. **Jurisdictions:** `geometry_ref = ADM0_A3`, using the mapping rules above. Supranational bodies have no geometry. Subdivisions come later (BL-26).
7. **Borders:** NE default point of view, with a neutral overlay for disputed and breakaway areas and a non-endorsement statement on the legal page. A different worldview per deployment is BL-25.

Open questions for the owner, recorded as `assumed` in `docs/decisions/ASSUMPTIONS.md`:
- **Q1:** Is NE's default point of view with a neutral disputed overlay acceptable, or must the default be a named worldview?
- **Q2:** Should overseas regions (GF, GP, MQ, RE, YT) shade with France?
- **Q3:** Should Antarctica be hidden?

Not covered: register rows for `pmtiles` and tippecanoe were not added, because neither is adopted. The 3.2 basemap note that mentions PMTiles is unchanged.
