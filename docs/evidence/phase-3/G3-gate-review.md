# Gate G3 review: Phase 3 Interface (M6, M9)

**Prepared by:** lead session · **Build under review:** `feat/M9-preferences` (top of the Phase 3 stack, on `feat/M6-shell`) at the commit that adds this record · **Date:** 2026-11-20 · **Decision:** **pending the owner**. Mirror it as the comment `approved` on the `Gate G3` issue (docs/06-process.md 6.1).

**Exit criterion (6.1):**
- the map shows live changes;
- the keyboard and screen-reader journeys pass;
- three themes;
- use testing round 1.

## Exit criterion

| Part | Status | Evidence |
| --- | --- | --- |
| Map shows live changes | **Met** | The activity is asked for again every minute while the page is visible, as passive requests that never keep an idle session alive (`MapPage.test.tsx` "shows live changes"; `test_auth.py::test_passive_requests_never_renew_an_idle_session`). The map is drawn in the real app, checked by the e2e keyboard journey after use-testing finding U-M6-1. |
| Keyboard journey | **Met up to printing** | `web/e2e/keyboard.spec.ts` uses Tab, arrow keys, Enter and Escape only. It goes: sign in; Region view and Europe's panel; Germany; its latest item; the Diff tab. Printing a stock report needs M7 and M8. |
| Screen-reader journey | **Pending the owner** | Structure: the jurisdiction listbox and the table view carry the map's data, the live regions are checked, and axe passes. The manual run with a screen reader needs a person. |
| Three themes | **Met** | axe finds no serious or critical issue on eight routes plus the table view in the light, dark and high-contrast themes, each set through the user's preferences and confirmed on `<html>` (`web/e2e/accessibility.spec.ts`; the canary shows the check is real). High-contrast hatching is checked in a browser. |
| Use testing round 1 | **Done, with findings** | `docs/evidence/phase-3/use-testing/M6.md` and `M9.md`, an independent tester session with 59 screenshots: 12 of 16 journeys passed. The blocker U-M6-1, the majors U-M6-2 and U-M9-1, and the minor U-M6-6 are fixed (`ab03c92`, `061e090`). The rest are BL-127 to BL-129. |

## Checklist (docs/07-testing-quality.md 7.8)

| Item | Status | Evidence |
| --- | --- | --- |
| Module definitions of done complete and linked | **M9 yes. M6 mostly.** | `M6-module-summary.md`: acceptance 2, 4 and 5 met; 1 partly (timing); 3 up to printing; open items listed. `M9-module-summary.md`: 1 to 3 met. |
| CI green on the release branch; coverage report attached | **Pending the owner:** local only, until the stack is pushed and the PRs opened | `make lint` clean. `make test-api`: 1,465 unit and 394 database tests, 94.85% coverage. `make test-web`: 185 tests. `make e2e`: 5 of 5 on the QA stack. |
| Contract tests pass against the committed OpenAPI | **Yes** | No contract change in P3. `/me/preferences` became real to the existing schema. The `X-Regwatch-Passive` header is BL-126. |
| End-to-end suite green in three themes; accessibility report | **Yes** | `M6-e2e.md`. |
| Performance results within budgets | **Partly** | The main bundle is about 120 KB gzip and the map chunk about 306 KB, inside the 600 KB budget. The first-paint and 500 ms timings need the Lighthouse run against a production build (U-M6-12). |
| Security scans attached; no high or critical open | **Yes** | `make security` passes. The license scan has 602 allowed, 0 failing. Every M6 and M9 slice is signed off by the independent web reviewer, with fixes re-verified (the commits are in `M6-module-summary.md`). |
| Peer, security, use and adversarial records for every module | **Security and use: yes. Peer and adversarial: not yet.** | The adversarial session is the owner's (since G1). Peer review is due on each PR. |
| License scan clean; register and notices updated | **Yes** | Register rows for lucide-react, Inter, MapLibre and its packages, and Playwright and axe. `web/THIRD_PARTY_NOTICES.md`. Shipping it with the bundle is BL-124. |
| CHANGELOG release section cut; BACKLOG decisions recorded; CP issues summarised | **At the gate** | CP proposals BL-125 (view lists for `items.read`) and BL-126 (the passive header); the ADR-0004 amendment 1 for the build-time Equal Earth. |
| Questioning-period issues closed or assumptions recorded | **Recorded** | The M6 and M9 bank defaults, approved 2026-11-19, and the P3 rows in ASSUMPTIONS. The issues are still to open on GitHub. |
| Owner comment `approved` | **Pending** | |

## Owner actions before approval

1. **Push the stack:**
   ```
   git push origin feat/M5-map
   git push origin feat/M6-shell
   git push -u origin feat/M9-preferences
   ```
   Then open the PRs so CI runs.
2. **Run the screen-reader journey** (NVDA or VoiceOver):
   - sign in;
   - on the map, the list and the table: does each jurisdiction read with its count, last change and severity?
   - the side panel;
   - an item's tabs;
   - the user tab;
   - the idle warning's announcement.
3. **Run the adversarial session,** or record a decision to defer it to G5, as at G1.
4. **Decide on:**
   - the CP proposals BL-125 and BL-126;
   - BL-127 (search in the item text);
   - whether the BL-128 gaps (items filter panel, item actions) block G3 or move to the next phase.
5. **Comment `approved` on the `Gate G3` issue,** or list what must change.
