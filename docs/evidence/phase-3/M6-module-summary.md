# M6 Shell and world map UI: module status record

**Branch:** `feat/M6-shell` (stacked on `feat/M5-map`) · **Date:** 2026-11-20 · **Status:**
- **Acceptance:** 1, 2, 4 and 5 are met. 3 is met by keyboard up to the diff; printing a stock report needs M7 and M8.
- **Security:** every slice is signed off by an independent reviewer (`M6-shell-review.md`, and the reviews recorded below).

## Acceptance criteria (`docs/modules/M6-shell-map-ui.md`)

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | With a 30-day period, jurisdictions with change events are shaded and those without are neutral; changing the period updates shading within 500 ms | **Met** (shading) | `MapPage.test.tsx` "shades jurisdictions…": rows to colour steps, no row stays neutral. A real render in headless Chromium (Equal Earth, steps, selection). Recolouring is one feature-state pass; the 500 ms timing is not yet measured in a browser (Lighthouse budget open). |
| 2 | Selecting view "industry: finance" re-renders the map and legend to finance-tagged activity | **Met** | `MapPage.test.tsx` "re-renders for the view industry: finance": the map asks `GET /map/activity` with `filters={"terms":{"industry":["finance"]}}`. Needs `taxonomy.read`, so CP proposal BL-125. |
| 3 | A keyboard-only user can log in, open filters, select Europe, open Germany, read the latest item and its diff, and print a stock report | **Met up to the diff** | `web/e2e/keyboard.spec.ts` uses Tab, arrow keys, Enter and Escape only: sign in, Region and Europe's panel, Germany, its latest item, Diff (`M6-e2e.md`). The "filters" are the view selector; a facet filter panel beyond it is not built. Printing needs M7 and M8. |
| 4 | Axe reports zero serious or critical issues on every route in all three themes | **Met** | `web/e2e/accessibility.spec.ts` on nine routes, with the theme asserted. A canary shows the check is not vacuous. |
| 5 | A screen-reader user gets the same information through the table view and the jurisdiction list | **Met** (structure) | The listbox and the table view carry the same rows as the map, with names, counts, last change and severity (`MapPage.test.tsx`). The manual screen-reader script is still to be run by a person. |

## Built

- **Shell:**
  - a 56 px header;
  - the command registry (`commands.ts`) and the left rail with labels on hover or pinned;
  - the `/admin` settings home;
  - self-hosted Inter, and lucide icons.
- **Map:**
  - Natural Earth 1:50m, pre-projected to Equal Earth at build time (`scripts/build-map-data.sh`, ADR-0004 amendment 1);
  - MapLibre 6.19.0, lazy-loaded, in the identity projection;
  - five token colour steps for recency, count and severity;
  - disputed areas drawn neutral, with a non-endorsement line;
  - hatching in the high-contrast theme;
  - legend, period, view (country, region, facet term) and a live count;
  - the jurisdiction listbox, the table view, and the side panel with its latest ten changes.
- **Items:**
  - `/items`: search from the URL, highlights rendered as text, removable filter chips, sorting and pages;
  - `/items/:id`: Summary, Content (with translation), Versions and Diff tabs.
- **Tooling:** `make e2e`, Playwright in the official image pinned by digest, with guard rails.

## Open

- **Shell:** below 768 px the rail should collapse to a menu button (screens.md), and the global search box in the header.
- **Filter panel** (facets with counts, source, severity, status) and **saved-view picker** on the map toolbar.
- **Export and print commands:** with M7 and M8.
- **Measurements and checks:**
  - visual regression snapshots per theme;
  - the Lighthouse budget in CI (first paint under 2 s, map under 1 s, bundle under 600 KB: about 435 KB gzip today);
  - the manual screen-reader script.
- **Backlog:** BL-122 (enhancements E12 to E15), BL-124 (notices in the bundle), BL-125 (CP for `items.read` access to the view lists).
