# M6 end-to-end and accessibility results

**Date:** 2026-11-20 · **Stack:** the isolated QA stack (`regwatch-qa`, published on 127.0.0.1 only) at `19a812e` and later, seeded by `web/e2e/setup.ts` (a manual source with two uploaded documents, processed by the stack's own worker) · **Runner:** `make e2e` (`scripts/e2e.sh`, the official Playwright 1.65.1 image pinned by digest)

## Results

| Test | Result |
| --- | --- |
| Acceptance 4: axe (WCAG 2.0, 2.1 and 2.2 A and AA tags) on `/`, the table view, `/items`, an item page, `/admin`, `/admin/sources`, `/admin/taxonomy`, `/admin/users` and `/legal`, in the light, dark and high-contrast themes | **Passed**: no serious or critical violations |
| Canary: axe on a page with an injected unlabelled button and an image without `alt` | Reported serious violations, so the check is not vacuous (run once; not committed) |
| Acceptance 3, keyboard only: sign in, the region view with Europe, Germany from the listbox, the side panel, its latest item, then the item's Diff tab | **Passed** up to the diff. Printing a stock report needs M7 and M8, so that step is open. |

## Open for M6 acceptance

- Acceptance 3: the "print stock report" step (M7, M8), and a diff between two real versions. File uploads create one version each, because items are keyed by content; a URL source in the QA stack would need egress. Component tests cover the diff view.
- The visual regression snapshots per theme, and the Lighthouse budget in CI (test plan).
- The manual screen-reader script (accessibility test plan), which needs a person with a screen reader.
