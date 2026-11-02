# ADR-0005: Puck for the report builder, with a project-owned keyboard layer and server rendering through Puck's Render

**Status:** accepted at Gate G0 on 2026-11-02, except decision 3 (Node render worker), deferred to the M7 builder spike with BL-17 · **Date:** 2026-11-01 · **Requirements:** REQ-12, REQ-13, REQ-18 (also REQ-19, REQ-20)
**Research:** R-02, `docs/research/R-02-puck-report-builder.md` (#4); license verified in R-01 E3

## Context

M7 needs four things:
- A drag-and-drop editor that places whitelisted fields and blocks on a page (REQ-12).
- Saved layouts that each user can select (REQ-13).
- A builder that works by keyboard alone (REQ-18; WCAG 2.2 AA, notably 2.1.1 Keyboard and 2.5.7 Dragging Movements).
- One server-rendered HTML shared by the preview, the Gotenberg PDF and the email body.

The license policy (3.5) allows MIT and BSD-3.

R-02 tested Puck `@puckeditor/core` 0.24.0 at commit `d14401c`:
- It has **no keyboard drag and drop**. Only dnd-kit's `PointerSensor` is registered, and its plugin rail is mouse-only. axe-core reports 3 serious or critical violations.
- Keyboard alternatives built on its public overrides (`actionBar`, `drawerItem`, `iframe`, `useGetPuck().dispatch`) passed every keyboard check.
- `Render` turns saved data into escaped HTML in plain Node, and a Jinja2 renderer produced byte-identical output.
- Puck drops unknown top-level keys from its data on edit, so `data_source` must stay beside `layout`, as the OpenAPI `ReportLayout` already has it.

## Decision

1. **Use Puck as the M7 editor.** Pin `@puckeditor/core` at exactly `0.24.0` (no caret range); upgrades go through a reviewed PR that runs `migrate()` on stored layouts. Import `@puckeditor/core/no-external.css`, not `puck.css`.
2. **Adoption is conditional on a project-owned accessibility layer (BL-16).** It provides:
   - keyboard selection;
   - Move up and Move down actions;
   - keyboard insertion;
   - polite live announcements;
   - keyboard access to the panel switcher;
   - an iframe title and labels for unlabelled controls.

   The layer is held to zero serious or critical axe violations and a recorded keyboard-only walkthrough. Fixes are offered upstream.
3. **Render on the server with Puck's `Render`** from `@puckeditor/core/rsc`, inside an internal Node render worker. The worker receives validated layout JSON plus rows the API has already resolved, returns HTML, and has no database access and no egress. Charts use ECharts SSR in the same worker. Report components may not use `dangerouslySetInnerHTML` or Puck `richtext` for untrusted text. This needs a contract change to `M0-tooling.md` and updates to 3.2 and 3.3 (BL-17). Until the owner accepts that change, the Jinja2 path in the M7 spec stands.
4. **Fallback trigger (BL-19).** Build the editor on dnd-kit (`@dnd-kit/react`, MIT) if the M7 builder spike cannot meet the bar in point 2 with Puck 0.24.x.

## Alternatives considered

| Option | License | Pros | Cons |
| --- | --- | --- | --- |
| Puck 0.24.0 plus accessibility layer (chosen) | MIT | Covers REQ-12 and REQ-13: typed fields, slots, overrides, saved JSON, `Render` and `resolveAllData` in Node; active (11 releases in 12 months) | No keyboard drag and drop; mouse-only plugin rail; 3 axe violations; 384 KB gzip editor bundle; 0.x data model can change |
| Custom builder on dnd-kit `@dnd-kit/react` 0.5.3 | MIT | Keyboard sorting verified out of the box; about 39 KB gzip; full control of accessibility | Palette, canvas, properties panel, undo, nesting and data model all to build: 15 to 25 extra developer-days |
| react-grid-layout 2.3.0 | MIT | Small (about 24 KB gzip); mature | No keyboard support at all; absolute x/y/w/h grid does not fit paginated print |
| GrapesJS 0.23.8 | BSD-3-Clause | Full page builder with keyboard selection keymaps | Not React; HTML/CSS document model with no typed field binding; no keyboard move; about 301 KB gzip |
| Jinja2 template per component in the API (server rendering only) | BSD-3-Clause | Python-only server; fits current contracts; output identical in R-02 | Every component written twice (React and Jinja2) with a parity test; charts still need JavaScript or a screenshot step |

## Consequences

- **Positive:**
  - M7 starts from a maintained editor, not from scratch.
  - The canvas, preview, PDF and email share one set of components.
  - The keyboard path is something we own and test, not an assumption. The M7 test plan's "Puck supports keyboard sensors; verified" is withdrawn (BL-18).
- **Negative:**
  - An accessibility layer must be maintained across Puck upgrades.
  - A Node render worker adds a container and a second server-side runtime, if accepted.
  - The editor bundle is large, so the builder route must be lazy-loaded.
  - Puck bundles `@dnd-kit/*` 0.4.0, so a separate dnd-kit 0.5.x for list ordering ships a second copy.
- **Follow-up backlog rows:** BL-16 (accessibility layer and upstream fixes), BL-17 (render worker contract change), BL-18 (M7 spec and 3.2 corrections), BL-19 (fallback trigger).


## Owner decisions at Gate G0 (2026-11-02)

- Accepted, except decision 3, which follows BL-17 and is decided at the M7 builder spike in Phase 4. Until then the server render path is Jinja2 per the contracts.
- The keyboard assumption (keyboard alternatives satisfy WCAG 2.1.1 and 2.5.7) is accepted; confirm it with an accessibility check during M7 use testing.
