# M7 Report builder and stock reports: module status record

**Branch:** `feat/M7-reports` (stacked on `feat/M11-interests`) · **Date:** 2026-11-20 · **Status:**
- **Acceptance:** criteria 1, 2 and 3 are met. Criterion 4 needs M8's PDF.
- **Security:** each slice (7.1 to 7.5) is signed off by the independent reviewer, with fixes re-verified.
- **Tests:**
  - `make test-api`: 1,505 unit tests (95.76% coverage) and 438 database tests pass at `2097c01`. The later review fixes (`ee4fbf4`) were re-run on the report tests (23 integration, 19 unit).
  - `make test-web` passes and `make lint` is clean.
  - `make e2e` on the QA stack passes the reports journeys: create, edit, save and preview, plus a keyboard-only walkthrough with zero serious or critical axe findings.
  - The license scan: 701 allowed, 0 failing.

## Acceptance criteria (`docs/modules/M7-report-builder.md`)

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Drag ItemsTable onto a page, pick five fields, bind the saved view "Europe 30 days", preview the same rows as the item list | **Met** | `ReportsPage.test.tsx` and `web/e2e/reports.spec.ts` (Puck editor, save, preview). `test_report_preview.py` (rows come from the search service, sorted; the saved view is checked for the viewer). |
| 2 | A saved layout is visible only to its owner until shared; an admin sees all | **Met** | `test_report_layouts.py::test_layouts_are_private_until_shared` (CP-30 `reports.read_all`). The review fixes: a shared layout needs a shared view, and owners can always unshare. |
| 3 | "Jurisdiction profile" for Germany renders with a map snapshot, the latest ten changes and a status matrix | **Met** | `test_report_templates.py`: `test_a_jurisdiction_profile_for_one_place` and `test_charts_and_the_map_render_as_svg`. |
| 4 | Preview HTML and M8's PDF match in pagination for a three-page report (1% visual tolerance) | **Waits for M8** | The PDF path (Gotenberg) is M8. The HTML already carries `@page` size, orientation, margin boxes and page breaks. |

## Built

| Slice | What | Commits |
| --- | --- | --- |
| 7.1 | Layouts API, field whitelist, the component schemas, sharing (CP-30) | `b5f25a6`, `c05c66e` |
| 7.2 | Server-rendered preview: Jinja2 with autoescape, strict CSP, the viewer's rights, rate and size caps | `5145998`, `331b05c` |
| 7.3 | Five stock reports with parameters (CP-31), StatusMatrix, SourceHealth | `9ef3826`, `cf4c309` |
| 7.4 | Reports pages, the Puck 0.24.0 builder (lazy-loaded), and the BL-16 keyboard layer | `19aaf80` to `9258dd8` |
| 7.5 | Bar and line charts and the map snapshot, as SVG drawn in Python | `2097c01`, `ee4fbf4` |

## Decisions (accepted on recommendation; listed for the owner at G4)
- **Jinja2 server rendering:** the M7 spec's path. ADR-0005 decision 3, the Node render worker, stays open as BL-17.
- **Charts and maps as SVG in Python,** instead of ECharts on Node and a Playwright screenshot (BL-140 j).
- **CP-30:** the `reports.read_all` permission.
- **CP-31:** `ReportParameterDef.default`.
- **0BSD on the license allow-list:** ADR-0003 amendment 4, BL-142.

## Open (BACKLOG BL-140)
- (d) Deleting a layout that outputs refer to.
- (e) The M8 PDF and email security list.
- (f) Renders charge the search rate.
- (g) The preview's styles under the production CSP. Must be fixed before BL-76.
- (h) Check the bundle for happy-dom.
- **M8 email:** inline SVG is often dropped by email clients, so attach the PDF or give the figures as text.
