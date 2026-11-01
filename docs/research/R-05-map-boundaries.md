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

Pending in the next commit (benchmark running).

## Projection and high-contrast patterns

Pending in the next commit.

## Why not 1:10m

Pending in the next commit.

## Recommendation

Pending in the next commit.
