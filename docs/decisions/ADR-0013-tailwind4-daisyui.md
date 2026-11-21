# ADR-0013: Tailwind CSS 4 and daisyUI 5 for the look of the web app

**Status:** accepted 2026-11-21 at the owner's request ("upgrade to Tailwind 4 with daisyUI 5"). · **Requirements:** REQ-20 (accessibility), REQ-21 (themes) · **Contract change:** CP-39 (`docs/contracts/M0-tooling.md`, styling) · **Backlog:** BL-149

## Context
The owner asked how to add an open-source UI library such as daisyUI to change how the application looks, and chose the upgrade to Tailwind 4 with daisyUI 5. daisyUI 5 needs Tailwind 4.

The web app had Tailwind 3.4 with every colour, size and radius from `src/styles/tokens.css`, three themes on `html[data-theme]` (light, dark, high-contrast), and shadcn/ui components on Radix primitives for behaviour and accessibility.

## Decision
1. **Tailwind 4.3.5 through `@tailwindcss/vite`.** The theme moves from `tailwind.config.ts` to an `@theme inline reference` block in `src/styles/index.css`. Each utility uses the token directly, and Tailwind emits no `--color-*` or `--text-*` variables that would shadow the tokens.
   - The generated CSS was compared class by class with Tailwind 3's. The remaining differences are equivalent rewrites, such as `margin-inline` for `margin-left` with `margin-right`, or the spacing multiplier.
   - `--default-border-width` keeps `border` at the token's width, 2 px in high contrast.
   - The two defaults Tailwind 4 changed, the placeholder colour and the button cursor, are restored.
2. **daisyUI 5.8.2 as a Tailwind plugin, with its own themes off.**
   - The three daisyUI themes take the app's theme names, so `data-theme` switches them too. Their variables point at the app's tokens:
     - colours, radius and border width;
     - field height as the hit target (32 px, or 44 px in the accessibility preset);
     - no depth or noise, since the design uses borders instead of shadows.
3. **The token `--border` becomes `--line`**, because daisyUI uses `--border` for the border width.
4. **The app keeps its accessibility choices over daisyUI's defaults:**
   - the amber focus ring (CP-09);
   - fields in the app's border colour (white in high contrast);
   - disabled buttons in high contrast in the muted text with a dashed border, rather than 20 % text.
5. **Radix stays** for dialogs, menus and comboboxes. daisyUI provides how components look, not keyboard and screen-reader behaviour.
6. **The screens move over one at a time.** The login page is the first, and the rest follow in use testing (BL-149).

## Alternatives
- **daisyUI 4 on Tailwind 3:** a smaller step, but behind the current daisyUI. The owner chose 5.
- **A class prefix for daisyUI (`d-btn`):** not needed. No class the app uses collides, except `prose`, which daisyUI uses only to scope buttons.
- **Keeping daisyUI's own themes:** they would replace the tested colours (contrast ratios, CP-09) and break high contrast.

## Consequences
- The app's CSS grows from 5 KB to 15 KB compressed while all of daisyUI's components are included. An `include` list can trim it once the screens settle.
- Every restyled screen is checked in the three themes, by the axe journey and by the print journeys.
- Licences: Tailwind CSS, `@tailwindcss/vite` and daisyUI are MIT. daisyUI's CSS ships in the bundle, with its notice.
