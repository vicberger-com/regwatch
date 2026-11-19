# M6 shell security review (0c90347)

**Reviewer:** independent session (not the author) · **Date:** 2026-11-19 · **Sign-off: yes**, with no blocking finding.

The review was static. It covered the command registry, the left rail, the header, the `/admin` settings home and its route guard, the self-hosted fonts and lucide-react. The reviewer also ran the Node half of the license policy.

## Findings and what was done

| # | Severity | Finding | Done |
| --- | --- | --- | --- |
| 1 | Low | The vendored Inter fonts had no notices entry, and the production build drops `OFL-1.1.txt` | `web/THIRD_PARTY_NOTICES.md` now lists both woff2 files with their sha256, sources and the OFL text. Shipping the notices with the bundle is BL-124 (M10). |
| 2 | Low | lucide-react is ISC AND MIT (Feather-derived icons), not ISC alone | The register row is corrected, and both texts are in the web notices. |
| 3 | Low | The admin permissions were listed in two places | `ADMIN_PERMISSIONS` is now derived from `ADMIN_AREAS` in `commands.ts`. |
| 4 | Info | A command registered again under a taken id silently replaced the first | A different command under a taken id now throws; an identical re-registration is harmless (tested). |
| 5 | Info | screens.md says Settings shows only with `settings.manage`, and the future health summary needs per-figure gating | Recorded in ASSUMPTIONS for the owner. The gating is noted for M10. |
| 6 | Info | `safeNext` accepted `/\host` (existing code) | Backslashes and control characters are now refused (tested). |
| 7 | Info | A long display name could push Sign out out of view | The name is truncated, and the button no longer shrinks. |

## Checked and found fine

- **Route guards:** every `/admin/*` guard is unchanged, and `/admin` refuses users without an admin permission.
- **Rendering:** labels and brand values are rendered as text only.
- **Storage:** the stored pin flag is safe.
- **Navigation:** navigation targets are constants.
- **lucide-react:** pinned with integrity, no install scripts.
- **Fonts:** CSP `font-src 'self'` holds.
- **Accessibility:** the skip link, accessible names, `aria-current` and `aria-pressed` are all in place.
