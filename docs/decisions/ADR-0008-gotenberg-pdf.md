# ADR-0008: Gotenberg for PDF from the same server-rendered HTML; browser print only at launch

**Status:** accepted at Gate G0 on 2026-11-02 · **Date:** 2026-11-02 · **Requirements:** REQ-10, REQ-15 (also REQ-12, REQ-20)
**Research:** R-01 rows 37 and 38 (#3), R-02 (#4), R-04 (#6); `docs/modules/M7-report-builder.md`, `docs/modules/M8-output-delivery.md`; `docs/08-security-compliance.md` 8.1; ADR-0005

## Context

- **M8.** PDFs come from Gotenberg's Chromium route, using the report HTML with CSS and fonts inlined. M8 lists a PDF/A-2b option and sets metadata. Acceptance criterion 1: a PDF of a saved layout within 2 minutes, with a page count that matches the preview. WeasyPrint is the named fallback.
- **M7.** The preview, the PDF and the email body share one server-rendered HTML document. The preview paginates with the Paged.js polyfill, and Gotenberg uses Chromium's own paging. Acceptance criterion 4: preview and PDF match in pagination for a 3-page report, within a 1 percent visual-regression tolerance. OpenAPI documents `POST /reports/layouts/{id}/preview` as "Server-rendered HTML identical to the PDF input".
- **Security (8.1).** Gotenberg sits on the internal network with no outbound access. HTML is assembled on the server from validated layouts, and templates contain no user-supplied URLs.
- **R-02: the HTML can come from either renderer.** Puck's `Render` produced HTML in plain Node, and a Jinja2 renderer over the same JSON produced byte-identical output. ECharts SSR rendered charts to SVG in Node. Under Jinja2, charts need a Node step or a Playwright screenshot. ADR-0005 proposes the Node render worker (BL-17), and the Jinja2 path stands until the owner accepts it. The PDF input pipeline is therefore open, pending BL-17.
- **R-04: browser print only at launch.** No Node IPP client passes the license gate, and the server print bridge is deferred (BL-13, BL-15). `outputs.server_print` stays off, and browser printing uses M7's `@media print` CSS.
- **Licenses:**
  - Gotenberg: MIT, verified at v8.39.0 (`3d4f655`). WeasyPrint: BSD-3-Clause, verified at v70.0 (`4d3b7b6`) (R-01 rows 37 and 38).
  - R-01 read Gotenberg's own LICENSE only, not the licenses of the Chromium and LibreOffice builds inside its image.
  - pdfmake and Paged.js have no register rows.
  - The contract image line is `gotenberg/gotenberg:8`.
- **No measurement.** No research item ran Gotenberg. Its render time, memory use, image size and PDF/A output are not established.

## Decision

1. **Gotenberg 8 as the `pdf` sidecar.** The worker task `outputs.render_pdf` calls its Chromium HTML route. The sidecar is internal-only, with no egress (ADR-0001 decision 3); the Compose network enforces this whatever Gotenberg's own settings are.
2. **One self-contained HTML document per report is the PDF input contract.** CSS, fonts, images and chart SVGs are inlined, and there are no external URLs. The same document serves the preview endpoint, browser printing, the email body and Gotenberg. This ADR is neutral on which renderer produces it: Jinja2 in the API (current M7 spec) or Puck's `Render` in a Node render worker (BL-17). R-02 showed that both give the same HTML, and the choice stays with ADR-0005 and BL-17.
3. **Paper output at launch is browser print plus PDF download.** Browser print uses the same HTML with `@media print` rules (R-04). Server-side IPP printing, if BL-15 is scheduled, would send the Gotenberg PDF. It is not built now (BL-47).
4. **Pagination comes from shared CSS paged-media rules**, polyfilled by Paged.js in the preview and applied natively by Chromium in Gotenberg. The M7 criterion 4 visual-regression test is the parity check.
5. **WeasyPrint is the fallback**, running in the worker. Trigger: Gotenberg fails M8 criterion 1, M7 criterion 4 or the M8 security review. WeasyPrint does not run JavaScript, so charts must already be SVG and the preview must use CSS that WeasyPrint supports.

## Alternatives considered

| Option | License | Pros | Cons |
| --- | --- | --- | --- |
| **Gotenberg sidecar on one shared HTML document (chosen)** | MIT (V) | The same Chromium engine as the browser, so screen and PDF match (3.2); runs as an HTTP service; the worker holds no browser for reports | A browser container to patch and isolate; LibreOffice ships in the image unused; size and speed not measured |
| WeasyPrint only | BSD-3 (V) | Pure Python, in process; no browser container | Its own layout engine, so browser print and PDF can differ; no JavaScript; preview parity harder to prove |
| Browser-side pdfmake | not verified (no register row) | No server rendering | Builds PDFs from a separate document definition, not from the HTML (a second rendering path); scheduled and emailed PDFs still need a server |
| Playwright `page.pdf()` in the worker | Apache-2.0 (V) | Already in the register for `render_js` | Puts report rendering in the same Chromium that loads hostile captured pages (8.1); ties output to the capture worker image |

## Consequences

- **Positive:** one HTML document drives four outputs. The renderer decision (BL-17) can be made later without changing M8. Browser print needs no new component.
- **Negative:**
  - Chromium renders HTML that contains captured text, so escaping in the renderer (React escaping or Jinja2 autoescape) and the lack of egress are the controls (8.1).
  - The image bundles components R-01 did not read (BL-52).
  - Whether PDF/A-2b works, and how fast Gotenberg is on the target host, are not established until M8.
  - If Jinja2 stays, charts need a separate SSR or screenshot step (R-02).
- **Follow-up backlog rows:** BL-17 (renderer), BL-15 and BL-47 (server print path and its ADR), BL-52 (image license scan).

## Open questions for the owner

1. Is the PDF/A-2b archival option needed at launch, or can it wait until M8 has verified it?
2. Do you accept the WeasyPrint fallback trigger in decision 5?
3. If BL-17 is declined and Jinja2 stays, should charts be rendered by a small Node SSR step (a second-language sidecar under ADR-0001 decision 5) or by a Playwright screenshot?


## Owner decisions at Gate G0 (2026-11-02)

The owner accepted the recommended default for every open question above:

- Q1: PDF/A-2b is not needed at launch; add it after M8 verifies it.
- Q2 accepted: the WeasyPrint fallback trigger.
- Q3: decided together with BL-17 at the M7 builder spike.
