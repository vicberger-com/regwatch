# R-02: Does Puck fit the report builder?

**Issue:** #4 · **Module:** M7 · **Requirements:** REQ-12, REQ-13, REQ-18 (also REQ-19, REQ-20) · **Date:** 2026-11-01
**Decision record:** `docs/decisions/ADR-0005-report-builder.md` (proposed) · **Protocol:** `docs/03-architecture.md` 3.8

## Question

Does Puck meet the M7 report builder's needs?
- (a) Keyboard-only drag and drop that satisfies WCAG 2.2 AA.
- (b) Rendering its saved data model on the server, so the preview, the PDF (Gotenberg) and the email body come from one server-rendered HTML.

If not, plan the fallback (dnd-kit or react-grid-layout) and state what it costs.

## Answer

- **(a) No, not as shipped.** Puck 0.24.0 has no keyboard drag and drop. Its three drag providers register only dnd-kit's `PointerSensor`, which removes dnd-kit's default `KeyboardSensor`. Canvas items take focus and tell screen-reader users to "press the space bar" to pick them up, but nothing reacts to the key. The plugin rail cannot be reached by keyboard. axe-core finds 3 serious or critical violations.
  - WCAG 2.2 AA does not require keyboard *dragging*. It requires every function to work from the keyboard (2.1.1) and a non-drag alternative for drag operations (2.5.7).
  - The proof of concept built that alternative from Puck's public override API: Enter selects, "Move up" and "Move down" buttons reorder, and an "Add" button inserts. All five keyboard checks passed.
  - The remaining defects need about 3 to 5 days of project-owned accessibility work plus small upstream fixes.
- **(b) Yes.** `Render`, from either `@puckeditor/core` or `@puckeditor/core/rsc`, turned saved Puck JSON into clean HTML in plain Node with no browser and no DOM. User text was escaped. A Jinja2 renderer over the same JSON produced byte-identical HTML.
- **Recommendation:** keep Puck, pinned exactly at `0.24.0`, on condition that the accessibility layer (BL-16) is built. Render on the server with Puck's `Render` in a small Node render worker (BL-17), so the canvas, preview, PDF and email share one set of components. Jinja2 per component remains the documented alternative if the owner wants no server-side Node.
- **Fallback trigger:** the M7 builder spike cannot reach zero serious or critical axe violations plus a recorded keyboard walkthrough (BL-19). The fallback is a builder written on dnd-kit, at about 15 to 25 extra developer-days.

## Method

1. Read Puck at tag `v0.24.0`, commit `d14401c3a47947543e9de733ef1a20fb85140d52`, the same commit R-01 used for the LICENSE. The npm `latest` tag is `0.24.0`, published 2026-10-29. Code read: `packages/core` (drag and drop, sensors, action bar, drawer, plugin rail, server render, reducer actions, override types) and `apps/docs` (server components, data model, accessibility mentions). The installed dependency `@dnd-kit/dom@0.4.0` was read to confirm how sensors resolve.
2. Searched Puck's open issues for keyboard, accessibility, a11y, screen reader and server rendering.
3. Built a proof of concept with pnpm in a scratch directory outside the repository and ran it with Playwright and axe-core. The commands are in the appendix. The proof of concept is not committed.
4. Read the alternatives at their release tags (treeless clones): test files, CI workflows, LICENSE head, keyboard handlers in the built package, bundle size, `pnpm audit`.

## Findings from the source (Puck v0.24.0)

| # | Finding | Evidence |
| --- | --- | --- |
| S1 | Only a pointer sensor is registered. `useSensors()` returns `[PointerSensor.configure(...)]` and nothing else. | `packages/core/lib/dnd/use-sensors.ts` |
| S2 | Every drag surface uses that list: the canvas, array-field sorting and the outline (layer tree). | `components/DragDropContext/index.tsx` (`sensors={sensors}`), `components/Sortable/index.tsx`, `components/LayerTree/components/outline-dnd-provider/index.tsx` |
| S3 | Passing `sensors` replaces dnd-kit's defaults, so the default `KeyboardSensor` is dropped. The `Accessibility` plugin (announcements and the "press the space bar" description) is kept, which makes it misleading. | `@dnd-kit/dom@0.4.0` `index.js`: `defaultPreset.sensors = [PointerSensor, KeyboardSensor]`; `resolveCustomizable(value, defaults)` returns `value` when one is given |
| S4 | The action-bar "Drag to reorder" handle is a focusable `<button>` whose only handler is `onClick={e => e.stopPropagation()}`. There is no move-up or move-down action; the defaults are select parent, drag, duplicate and delete. | `components/ActionBar/index.tsx`, `lib/dictionary.ts` |
| S5 | The plugin rail (Blocks, Outline, Fields) renders `<div onClick>` with no `tabindex`, role or key handler. | `components/Puck/components/Nav/index.tsx` |
| S6 | The public API is enough to add keyboard alternatives: `overrides.actionBar`, `overrides.drawerItem`, `overrides.iframe`, `useGetPuck()` (`dispatch`, `getSelectorForId`) and the reducer actions `move`, `reorder` and `insert`. | `types/API/Overrides.ts`, `reducer/actions.tsx`, `lib/use-puck.ts` |
| S7 | Server rendering: the `react-server` export condition and `./rsc` export `Render`, `resolveAllData`, `migrate`, `transformProps` and `walkTree`. `Render` walks `content` and slots and calls each component's `render` with `isEditing: false` and `dragRef: null`. | `packages/core/package.json` `exports`, `bundle/rsc.tsx`, `components/ServerRender/index.tsx` |
| S8 | Data model: `{ root: { props }, content: [{ type, props: { id, ... } }], zones }`. `zones` belongs to the legacy `DropZone`; the docs recommend `slot` fields. Puck is 0.x: the docs say major releases may change `Data`, and `migrate()` upgrades old payloads. | `apps/docs/pages/docs/api-reference/data-model/data.mdx`, `integrating-puck/data-migration.mdx`, `integrating-puck/server-components.mdx` |
| S9 | The default `puck.css` loads `@import "https://rsms.me/inter/inter.css"`. `@puckeditor/core/no-external.css` has no `@import`. | `dist/index.css`, `dist/no-external.css` |
| S10 | Puck's docs claim no keyboard drag and drop. The M7 test-plan line "Puck supports keyboard sensors; verified" has no support in the docs or the code. | docs search for "keyboard"; S1 to S3 |

Upstream issues found by search (2026-11-01):
- Open: #1443 "Add move up and down hotkeys" and #668 "Adding up/down and add buttons in Action Bar", whose reporter built them with the `actionBar` override.
- Open: #1807 "Three icon-only editor controls have no accessible name", which includes the zoom `<select>` that axe flags below.
- Open: #269 "Accessibility, markup & CSS improvements", whose "Keyboard support" audit item is unchecked.
- Open: #327, #328 and #329 (a11y of `ExternalInput`, `HeadingAnalyzer` and `ArrayField`).
- Closed: #1580 "RichText renders plain HTML when rendered in the server (RSC)", which affected `DropZone` content. Use `slot` fields, not `DropZone`.

## Proof of concept and test evidence

Setup: Node 22.23.4, pnpm 10.28.0, `@puckeditor/core@0.24.0`, React and React DOM 19.3.1, esbuild 0.28.2, Playwright 1.63.0 (Chromium, headless), `@axe-core/playwright` 4.14.0 with axe-core 4.14.0, tags `wcag2a wcag2aa wcag21a wcag21aa wcag22aa`.

The editor has two components, `Heading` and `ItemsTable` (a table with caption and `th scope`), and three saved items in the order `Heading-a, ItemsTable-b, Heading-c`.
- Variant `default` is plain Puck.
- Variant `a11y` adds about 70 lines of overrides: `iframe` (Enter on a focused canvas item dispatches `setUi` with `getSelectorForId`), `actionBar` ("Move up" and "Move down" dispatch `move`, keep the selection and write to a polite live region) and `drawerItem` (an "Add" button dispatches `insert` at the end of the page).

Order is read from `onChange`.

### (a) Keyboard and axe-core: `node kbd-a11y.mjs` (7 of 15 checks passed, as expected for the default editor)

| Check | Result | Observed |
| --- | --- | --- |
| D1 Canvas items and drawer items reachable by Tab | PASS | Both take focus: `role="button"`, `aria-roledescription="draggable"`, `tabindex="0"` |
| D1b Plugin rail (Blocks, Outline, Fields) reachable by Tab | FAIL | Not reached in 30 presses; the Tab cycle repeats every 14 stops |
| D1c "Publish" reachable by Tab | FAIL | Not reached in 30 presses (cause not investigated; M7 replaces the header with its own Save) |
| D2 Keyboard drag on canvas: Space, ArrowDown ×3, Space | FAIL | Order unchanged |
| D2 Same with Enter | FAIL | Order unchanged |
| D3 Enter on a focused canvas item selects it | FAIL | Fields panel did not change |
| D4 Keyboard insert from drawer: Space, arrows, Space | FAIL | Items 3 → 3 |
| D5 **Positive control:** pointer drag of `Heading-a` below `Heading-c` | PASS | `ItemsTable-b, Heading-c, Heading-a`; the harness detects reorders |
| D6 axe on default editor, zero serious or critical | FAIL | `aria-prohibited-attr` (serious, loader `<span aria-label>`), `frame-title` (serious, `#preview-frame`), `select-name` (critical, zoom `<select>`, upstream #1807) |
| A1 a11y variant: Enter selects focused canvas item | PASS | Selected |
| A2 "Move down" reachable by Tab after selection | PASS | 4 Tab presses |
| A3 "Move down" reorders | PASS | `ItemsTable-b, Heading-a, Heading-c`; live region "Moved to position 2 of 3" |
| A4 Focus stays on "Move down" for a second press | PASS | `ItemsTable-b, Heading-c, Heading-a` |
| A5 Keyboard insert with "Add ItemsTable to end of page" | PASS | 4 items; new `ItemsTable-<uuid>` last |
| A6 axe on a11y variant, zero serious or critical | FAIL | The D6 three, plus `nested-interactive` ×2 and `target-size` ×2, both caused by the proof of concept placing its Add button inside the drawer item's `role="button"` element |

Fallback probe, `node dndkit-test.mjs`: `@dnd-kit/react@0.5.3` `useSortable` with default sensors.
- **K1 PASS.** Tab, Space, ArrowDown, Space reordered `Heading-a, ItemsTable-b, Heading-c` to `ItemsTable-b, Heading-a, Heading-c`.
- The default announcement read "Draggable item Heading-a was dropped over droppable target Heading-a", so the wording needs customising.
- axe found `list` (serious), caused by the probe's `role="button"` on an `<li>`.

Data-model probe, `node ds-test.mjs`:
- An extra top-level `dataSource` key in the data given to `<Puck>` is **dropped**. After one edit, `onChange` returned only `root, content, zones`.
- The OpenAPI contract already stores `data_source` beside `layout` (`ReportLayout`), so the contract is right. The M7 design note "Puck's data format plus a `dataSource` block" is misleading (BL-18).

### (b) Server rendering in Node, no browser: `NODE_ENV=production node dist/server-render.mjs`

Fixture: the three items, plus a `Heading` whose text is `<script>alert(1)</script>`, plus an item of unknown type `Unknown`.

| Check | Result |
| --- | --- |
| `typeof window` during the render | `undefined` (plain Node 22, no jsdom) |
| `renderToStaticMarkup(<Render config data/>)` | `<div><h2>First</h2><table><caption>Second</caption>…</table><h2>Third</h2><h2>&lt;script&gt;alert(1)&lt;/script&gt;</h2></div>` |
| `/rsc` `Render` | The same markup without the wrapping `<div>` |
| User text escaped, unknown type dropped, no `data-puck-*` attributes | yes, yes, 0 attributes |
| `resolveAllData()` on the server | 5 items resolved |
| Render time | 0.174 ms average over 200 renders (first render 7.9 ms) |
| Jinja2 3.x over the same JSON (`uv run --with jinja2`, autoescape on) | **Byte-identical** to the `/rsc` output; 0.046 ms average |
| ECharts 6.1.0 SSR in Node (`renderer: "svg", ssr: true`) | 3,262-byte `<svg>`, no `window` |

### Choosing the server renderer: Puck `Render` in Node versus Jinja2 in the API

| Aspect | Puck `Render` (Node render worker) | Jinja2 per component (FastAPI) |
| --- | --- | --- |
| Single source of components | Yes. The canvas, preview, PDF and email all use the same React `render` | No. Each of about 12 components exists twice and needs a parity test (feasible: identical output above) |
| Charts (BarChart, LineChart) | ECharts SSR to SVG runs in the same process | Needs a Node step or a Playwright screenshot from Python |
| Fit with current contracts | Needs a Node runtime service; `M0-tooling.md` and 3.2 rejected a second backend language. Needs a `CP-nn` (BL-17) | Fits as written (M7 spec) |
| Escaping and injection | React escapes text; forbid `dangerouslySetInnerHTML` (ESLint `react/no-danger`) and Puck `richtext` for untrusted text | Autoescape on; forbid `|safe` |
| Input | Validated layout JSON plus rows the API already resolved; no database access, no egress | The same |

Puck `Render` fits better technically. Jinja2 is cheaper only while the component palette stays small. The decision belongs to the owner, through ADR-0005.

## Scored evaluation (protocol 3.8: 1 to 5, higher is better)

Extra R-02 rows: **Keyboard** means keyboard operability as shipped. **Server render** means rendering the saved model on the server.

| Criterion | Puck `@puckeditor/core` 0.24.0 | dnd-kit `@dnd-kit/react` 0.5.3 (custom builder) | react-grid-layout 2.3.0 | GrapesJS 0.23.8 |
| --- | --- | --- | --- | --- |
| License fit | 5. MIT, `LICENSE` at `d14401c` | 5. MIT, `LICENSE` at `3910e27` | 5. MIT, `LICENSE` at `9b01a61` | 5. BSD-3-Clause, `packages/core/LICENSE` at `3b2c671` |
| Activity, last 12 months | 5. 11 releases; last 2026-10-29; 176 open issues | 5. 13 releases; last 2026-10-31; 91 open issues | 4. 11 releases; last 2026-10-05; 22 open issues | 4. 11 releases; last 2026-10-15; 31 open issues |
| Tests and CI | 4. 67 test files; `ci.yml` | 4. 43 test files; Playwright and Chromatic workflows | 4. 59 test files; `test.yml`, `lint.yml` | 4. 151 test files; `test.yml`, `quality.yml` |
| Documentation | 4. Full API, RSC and migration guides | 3. Pre-1.0 API, separate docs site | 3. README and examples | 4. Full docs site |
| Open security advisories | 5. `pnpm audit --prod`: none | 5. None | 5. None | 5. None |
| API fit for M7 | 5. Typed fields, slots, overrides, `Render`, `resolveData` | 2. Primitives only; palette, canvas, properties panel, undo and model all to build | 2. Absolute x/y/w/h grid, not flowing print pages | 2. HTML/CSS document editor, not React; typed field binding is custom |
| Size (min+gzip, React 19 included where used) | 2. 384 KB (React 69 KB; includes Tiptap) | 5. 108 KB (about 39 KB above React) | 4. 93 KB (about 24 KB above React) | 2. 301 KB (no React) |
| Keyboard (R-02) | 2. Focusable, but no keyboard move, insert or select; fixable with overrides (A1 to A5) | 5. `KeyboardSensor` verified (K1) | 1. No `keydown` handler in `dist/` | 2. Keymaps select (`s`, `w`, `d`, `a`) and delete; no keyboard move |
| Server render (R-02) | 5. `Render` in Node verified | 3. Own model, own renderer | 3. Own model, own renderer | 2. Editor exports HTML/CSS; server-side model rendering not evaluated |
| **Total (45)** | **37** | **37** | **31** | **30** |

dnd-kit ties Puck on points, but its 2 for API fit hides the cost: the whole builder must be written. Puck's two low scores (size, keyboard) are each recoverable: the builder route is lazy-loaded, and the accessibility layer is about 3 to 5 days of work.

### Component evaluation records

**Puck.** Capability: drag-and-drop layout editor and server renderer · Module: M7 · Repository: https://github.com/puckeditor/puck · Version: 0.24.0 (`d14401c`) · License: MIT · Policy: allowed. **Decision:** dependency, pinned exactly; adopted on condition of BL-16. **Reasoning:** it covers REQ-12 and REQ-13 and renders on the server; its keyboard gaps can be fixed with public overrides. **Notices required:** yes (MIT; entry drafted when M7 adds the dependency).

**dnd-kit (`@dnd-kit/react`).** Capability: drag-and-drop primitives with keyboard sensor · Module: M7 · Repository: https://github.com/clauderic/dnd-kit · Version: 0.5.3 (`3910e27`) · License: MIT · Policy: allowed. **Decision:** dependency for the fallback, and for list ordering outside Puck. **Reasoning:** keyboard sorting works out of the box, but a builder on it is about 15 to 25 extra developer-days. **Notices required:** yes. Note: Puck pins `@dnd-kit/*` at exactly `0.4.0`, so a separate 0.5.x install ships a second copy (about 39 KB gzip).

**react-grid-layout.** Capability: grid layout · Repository: https://github.com/react-grid-layout/react-grid-layout · Version: 2.3.0 (`9b01a61`) · License: MIT · Policy: allowed. **Decision:** reject for M7. **Reasoning:** it has no keyboard support, and its absolute grid model does not map to paginated print. **Notices required:** no.

**GrapesJS.** Capability: HTML page builder · Repository: https://github.com/GrapesJS/grapesjs · Version: 0.23.8 (`3b2c671`) · License: BSD-3-Clause · Policy: allowed. **Decision:** reject. **Reasoning:** it is a non-React HTML/CSS editor with no keyboard move and no typed data binding, at a similar bundle size to Puck. **Notices required:** no.

## Cost of each route (estimates, not measured)

| Route | Work | Estimate |
| --- | --- | --- |
| Puck plus accessibility layer (recommended) | Keyboard select; Move up and Move down; Add with a position picker; live-region wording; plugin-rail keyboard access (own panel switcher in `overrides.header`, or an upstream fix); iframe `title`; zoom select label; 24 px targets; drawer "Add" outside the `role=button` element; Playwright keyboard walkthrough; upstream PRs for #1807, #1443 and S5 | 3 to 5 developer-days, plus about 2 days of upstream work |
| Puck `Render` render worker | Node service (validated JSON plus rows in, HTML out), ECharts SSR, contract tests, container | 3 to 4 developer-days, plus CP and ADR updates |
| Jinja2 instead | About 12 templates, plus a React↔Jinja2 parity test in CI | 4 to 6 developer-days, growing with each component |
| Fallback: dnd-kit builder | Palette, canvas, selection, properties forms from `/reports/fields`, undo and redo, nesting, persistence format, migration, accessibility | 15 to 25 developer-days beyond the Puck route |

## Appendix: commands used (the proof of concept lives outside the repository; not committed)

```
git clone --depth 1 --branch v0.24.0 https://github.com/puckeditor/puck   # HEAD d14401c3a47947543e9de733ef1a20fb85140d52
pnpm add @puckeditor/core@0.24.0 react@19 react-dom@19 && pnpm add -D esbuild @axe-core/playwright
pnpm add @dnd-kit/react@0.5.3 @dnd-kit/helpers@0.5.3 echarts@6
npx esbuild src/editor.tsx --bundle --format=esm --outdir=dist --jsx=automatic --loader:.css=css --define:process.env.NODE_ENV='"production"'
node kbd-a11y.mjs          # D1-D6, A1-A6 (Playwright + axe, served by a local Node static server)
node ds-test.mjs           # dataSource key retention
node dndkit-test.mjs       # K1 + axe
npx esbuild src/server-render.tsx --bundle --platform=node --format=esm --packages=external --jsx=automatic --outfile=dist/server-render.mjs
NODE_ENV=production node dist/server-render.mjs
uv run --no-project --python 3.12 --with jinja2 python -I jinja/render.py saved.json
node echarts-ssr.mjs
pnpm audit --prod          # PoC tree and alternatives tree: "No known vulnerabilities found"
git clone --depth 1 --filter=blob:none --no-checkout --branch <tag> <repo>   # alternatives: tests, CI, LICENSE
```

Puck's CSS requests `rsms.me` at runtime; the sandbox refused that host and the tests aborted the request. This did not affect the results; use `no-external.css` (S9).
