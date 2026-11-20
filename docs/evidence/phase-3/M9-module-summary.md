# M9 User tab, preferences and session controls: module status record

**Branch:** `feat/M9-preferences` (stacked on `feat/M6-shell`) · **Date:** 2026-11-20 · **Status:**
- **Acceptance:** 1, 2 and 3 are met by tests.
- **Security:** each slice is signed off by an independent reviewer; the idle-watch fixes are re-verified (signed off at `64a9bc1`).

## Acceptance criteria (`docs/modules/M9-user-preferences.md`)

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Changing theme, font scale and density applies immediately, persists across devices after re-login, and never flashes the wrong theme on load | **Met** | `api/tests/integration/test_preferences.py` (a second session sees the same preferences). `MePage.test.tsx` (applies to `<html>` at once). `appearance.test.ts` (the stored copy applied before the first render, tampering ignored). |
| 2 | An idle timeout of 20 minutes signs the user out after 20 minutes of inactivity, with a 60-second warning dialog that screen readers announce | **Met** | `IdleWatch.test.tsx` with fake timers covers: the warning, focus, the inert page, announcements at 60, 30 and 10 seconds, sign-out at zero (local even when the logout request fails), activity in other tabs, and Stay checked against `/auth/me`. The server enforces the timeout on its own. |
| 3 | Revoking another session from the list makes that session's next request return 401 | **Met** | `api/tests/integration/test_auth.py::test_sessions_list_and_revoke`; the `/me` sessions table (`MePage.test.tsx`). |

## Built

- **API:** `GET` and `PATCH /me/preferences`. Values are merged and checked, and invalid stored values fall back field by field.
- **`/me` page:**
  - profile and a password link;
  - appearance: accessibility preset, theme, text size, density, motion, labels;
  - language and time zone;
  - the session: idle timeout, remember-me default, and active sessions with revoke;
  - the landing view.
- **Appearance:** applied through tokens on `<html>`, and mirrored for the first paint.
- **Idle warning:** `IdleWatch`.

## Open

- **Landing view:** done: `/` opens with the chosen saved view (period, colour, view, first facet term); a view the user can no longer see leaves the map as it is.
- **i18n:** `react-i18next` (spec), deferred while English is the only locale (backlog E10).
- **The manual check of the warning dialog with a screen reader.**
