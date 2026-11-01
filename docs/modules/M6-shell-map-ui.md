# M6 Application shell and world map UI

**Phase:** P3 · **Size:** XL · **Parallelism:** shell and design system (one session), map (one session), item list and detail (one session) after shell merges.
**Requirements:** REQ-06, REQ-07, REQ-08, REQ-09, REQ-11, REQ-17, REQ-18

## Purpose
The corporate, accessible single-page interface: toolbar, settings icon, world map with highlighted jurisdictions, view selector, filters, search, item list and detail with diff view, and a table alternative for users who cannot use the map.

## Scope
In: application shell (header with product name and user menu, left toolbar or top toolbar as decided in questions, settings icon visible only with permission), world map choropleth, period selector, view selector, filter panel, search box with suggestions, jurisdiction drill-down panel, item list, item detail with versions and diff, table view equivalent, themes (light, dark, high-contrast), keyboard navigation, responsive layout to tablet width.
Out: report builder (M7), outputs (M8), user tab (M9).

## Interfaces
- Routes: `/` (map), `/items`, `/items/:id`, `/jurisdictions/:code`, `/reports` (M7), `/outputs` (M8), `/me` (M9), `/admin/*` (M1, M2), `/legal` (company legal page from M1 branding, linked from the footer and the About dialog).
- Consumes `GET /map/activity`, `POST /search`, `GET /taxonomy/view-dimensions`, `GET /views`.
- Toolbar command registry: `commands.ts` exports `{id, label, icon, permission, shortcut, run}`; modules register commands (display, filter, search, print stock report, print custom report, change view, export).

## Open-source components
React, TanStack Router and Query, MapLibre GL JS (BSD-3), Natural Earth GeoJSON (public domain), topojson-client (ISC), Radix UI and shadcn/ui (MIT), Tailwind (MIT), lucide-react icons (ISC), ECharts (Apache-2.0), cmdk (MIT) for command palette, react-diff-viewer-continued (MIT) or diff2html (MIT) for diffs, Inter font (SIL OFL 1.1, allowed for fonts).

## Design notes
- Map: MapLibre with a vendored low-detail world GeoJSON as a fill layer; fill colour from a sequential scale on recency (default) or count or max severity (view options); hover tooltip with count and last change; click opens the jurisdiction panel; keyboard users navigate jurisdictions through a listbox beside the map that syncs selection with the map.
- Colour scales are defined in tokens with light, dark and high-contrast variants; high-contrast mode adds patterns (hatching) to fills so colour is not the only channel (WCAG 1.4.1).
- Period selector: 7, 30, 90, 365 days and custom range; persisted per saved view.
- View selector: options from facets flagged in M2 plus country and region; switching changes the legend and the panel grouping.
- Filters: multi-select per facet with counts from M5, source, severity, status; active filters shown as removable chips in the toolbar.
- Table view: same data as the map, sortable, with the same filters, meets REQ-18 for users of screen readers.
- Header shows the configured logo and title from M1 branding; a neutral wordmark is used until branding is set.
- Shell layout: 56 px header, 64 px icon toolbar on the left with labels on hover and always-visible labels in accessibility mode, main area, right side panel for details; density setting changes spacing tokens.
- Performance budgets: first contentful paint under 2 s on a mid-range laptop, map render under 1 s for 250 features, bundle under 600 KB gzip excluding map data.

## Accessibility requirements (WCAG 2.2 AA)
Keyboard operability for every command; visible focus; skip links; landmark regions; live region announcing filter result counts; colour contrast 4.5:1 text and 3:1 UI; high-contrast theme 7:1; respects `prefers-reduced-motion`; font scale 100 to 200 percent without clipping; all icons with accessible names; map has a text alternative (table view and a per-jurisdiction summary list).

## Acceptance criteria
1. With 30-day period, jurisdictions with change events are shaded and those without are neutral; changing the period updates shading within 500 ms.
2. Selecting view "industry: finance" re-renders the map and legend to finance-tagged activity.
3. A keyboard-only user can log in, open filters, select "Europe", open Germany, read the latest item and its diff, and print a stock report.
4. Axe reports zero serious or critical issues on every route in all three themes.
5. Screen-reader user receives the same information through the table view and the jurisdiction list.

## Test plan
- Unit (Vitest): command registry, colour scale functions, filter state reducer.
- Component: map wrapper with mocked MapLibre, filter panel, diff viewer.
- E2E (Playwright): the journeys in acceptance criteria 1 to 3 in light, dark and high-contrast; visual regression snapshots per theme.
- Accessibility: axe on every route; manual screen-reader script recorded in evidence.
- Performance: Lighthouse budget in CI (Lighthouse CI, Apache-2.0).

## Question bank
1. Toolbar on the left or top? Default: left icon rail with labels on hover.
2. Which attribute is the default colour encoding: recency, count or severity? Default: recency.
3. Is a map projection preference (Mercator, equal-earth) important? Default: equal-earth for a corporate, less distorted look.
4. Branding: logo, primary colour, typeface? Default: neutral blue-grey, Inter.
5. Should jurisdictions without data be hidden or shown neutral? Default: neutral.
6. Minimum supported browsers? Default: last two versions of Chrome, Edge, Firefox, Safari.

## Enhancements to propose
E12 timeline view of changes; E13 comparison matrix of two or more jurisdictions; E14 watchlists with badges; E15 command palette with keyboard shortcuts.
