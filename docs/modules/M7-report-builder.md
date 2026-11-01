# M7 Report builder and stock reports

**Phase:** P4 · **Size:** L · **Parallelism:** builder UI (one session), data-bound components and stock reports (one session).
**Requirements:** REQ-10, REQ-12, REQ-13

## Purpose
Drag-and-drop composition of report pages from predefined database fields and components, saved per user, plus five stock reports ready to print.

## Scope
In: Puck-based editor with a palette of field and block components, data-source binding to an M5 query or saved view, page settings (size, orientation, margins, header and footer), preview rendering identical to PDF output, save, duplicate, share, version layouts, stock report templates, print-ready HTML.
Out: pixel-level WYSIWYG beyond page blocks; charts beyond bar, line and the map snapshot.

## Interfaces
- `GET|POST|PATCH|DELETE /reports/layouts`, `POST /reports/layouts/{id}/preview` (returns HTML), `GET /reports/templates`, `POST /reports/templates/{key}/instantiate`.
- Component palette (React, registered in `reports/components/registry.ts`): Heading, Paragraph, FieldValue (any whitelisted item field), ItemsTable (columns from field list, sorting, limit), ChangeList, JurisdictionSummary, MapSnapshot (server-rendered PNG of the current view through Playwright), BarChart and LineChart (ECharts, server-rendered to SVG), PageBreak, HeaderFooter with page numbers and date, LegalMarkings (inserts the company legal page markings and branding fields from M1; owner answer to question 9).
- Field whitelist served by `GET /reports/fields` from M4 and M2 metadata (never raw SQL from the client).

## Data
`report_layout`, `report_template`.

## Open-source components
Puck (MIT), dnd-kit (MIT), ECharts (Apache-2.0) with SSR renderer, Paged.js (MIT) for print pagination in preview, Handlebars (MIT) or Jinja2 (BSD-3) for server-side HTML assembly.

## Design notes
- Layout JSON is Puck's data format plus a `dataSource` block `{query | saved_view_id, limit}`; server validates every component's props against schemas before rendering.
- Rendering is server-side (Jinja2 templates per component) so the browser preview, the PDF and the email body share one HTML; CSS print rules via Paged.js polyfill in preview and Chromium paging in Gotenberg.
- Stock reports (REQ-10): `weekly-change-digest`, `jurisdiction-profile`, `topic-overview`, `source-health`, `regulation-status-matrix`; each ships as a template with a default query and a thumbnail.
- Layouts are versioned; rendering records the layout version in `output_job`.

## Acceptance criteria
1. A user drags ItemsTable onto a page, picks five fields, binds the saved view "Europe 30 days", previews and sees the same rows as the item list.
2. Saved layout appears only for its owner until shared; an admin can see all.
3. Stock report "jurisdiction profile" for Germany renders with map snapshot, latest ten changes and a status matrix.
4. Preview HTML and PDF from M8 match in pagination for a 3-page report (visual regression tolerance 1 percent).

## Test plan
- Unit: component prop schemas, layout validation, template rendering with fixtures.
- Component: palette drag and drop with dnd-kit test utilities; keyboard drag alternative (Puck supports keyboard sensors; verified).
- E2E: build, save, reopen, print.
- Security: template injection fixtures (user text must be escaped), field whitelist bypass attempts, layout JSON size limits.
- Accessibility: builder is keyboard-operable; preview is semantic HTML with table headers.

## Question bank
1. Which five stock reports matter most? Default: the five listed.
2. Page size default: A4 or Letter? Default: A4, per-user override.
3. Must reports carry corporate header and footer with classification markings? *Answered:* yes; the LegalMarkings and HeaderFooter components pull logo, company name and required markings from M1 branding, and stock reports include them by default.
4. Are shared organisation-wide layouts needed? Default: yes, admin-curated.

## Enhancements to propose
E16 scheduled report runs; E17 report parameters at print time (jurisdiction picker); E18 Excel export of tables.
