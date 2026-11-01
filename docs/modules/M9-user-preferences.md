# M9 User tab, preferences and session controls

**Phase:** P3 · **Size:** S · **Parallelism:** one session.
**Requirements:** REQ-14, REQ-18

## Purpose
The user tab: password change, environmental controls (theme, contrast, font scale, density, language, time zone, landing view), session settings (idle timeout within admin bounds, remember-me, active sessions list with revoke), and logout.

## Interfaces
- `GET|PATCH /me/preferences`, `GET /me/sessions`, `DELETE /me/sessions/{id}`, `POST /auth/password` (M1), `POST /auth/logout` (M1).
- Preferences applied on login and pushed to the SPA store; theme applied before first paint to avoid flashing (inline script reading a cookie mirror of the preference).

## Data
`user.preferences`, `session`.

## Open-source components
Radix primitives for switches and selects, `date-fns-tz` (MIT) for time zones.

## Design notes
- Accessibility mode is a preset: high-contrast theme, font scale 125 percent, always-visible toolbar labels, reduced motion, larger hit targets (44 px); any element can still be changed individually.
- Language setting covers UI strings only (i18n framework `react-i18next`, MIT) with English shipped; other locales are backlog E10.

## Acceptance criteria
1. Changing theme, font scale and density applies immediately, persists across devices after re-login, and never flashes the wrong theme on load.
2. Idle timeout set to 20 minutes logs the user out after 20 minutes of inactivity with a 60-second warning dialog that is announced to screen readers.
3. Revoking another session from the list makes that session's next request return 401.

## Test plan
- Unit: preference validation and bounds.
- E2E: each control in all three themes; idle timeout with mocked timers.
- Accessibility: axe plus manual check of the warning dialog focus trap.

## Question bank
1. Which languages for the UI? Default: English.
2. Are per-user default filters and landing view wanted? Default: yes (landing view is a saved view).
3. Should admins be able to force a theme or accessibility settings organisation-wide? Default: no, only defaults.

## Enhancements to propose
Per-user API tokens; notification preferences for E1 digests.
