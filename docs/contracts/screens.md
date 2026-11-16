# Screen inventory and design brief

## Design brief

Corporate, quiet, dense enough for analysts. One accent colour; status colours only for meaning. Everything works with keyboard alone and in three themes.

| Token group | Values (light theme; dark and high-contrast override in `tokens.css`) |
| --- | --- |
| Colour | `--bg: #F7F8FA`, `--surface: #FFFFFF`, `--border: #D9DEE5`, `--text: #1B2430`, `--text-muted: #5B6675`, `--accent: #1F5AA6` (replaceable by `branding.primary_color`), `--accent-contrast: #FFFFFF`, `--good: #1E7F4F`, `--warning: #B7791F`, `--critical: #B23A3A`, `--focus: #B45309` in light (4.73:1 on `--bg`), `#FFB400` in dark and high contrast (3 px outline, 2 px offset; CP-09) |
| Map scale (recency) | 5 steps from `--map-0: #E6ECF3` (no change in period) to `--map-4: #123E7A`; high-contrast theme adds diagonal hatch patterns per step |
| Type | Inter; scale 12 / 13 / 14 (body) / 16 / 20 / 24 px; line height 1.45; weights 400 and 600 only |
| Spacing | 4 px base: 4, 8, 12, 16, 24, 32, 48. Density setting multiplies paddings by 0.85 (compact), 1 (default), 1.2 (comfortable) |
| Radius and elevation | 6 px radius; borders instead of shadows; one shadow level for menus and dialogs |
| Hit targets | 32 px default, 44 px in accessibility preset |
| Motion | 150 ms ease for panels and menus; none when `prefers-reduced-motion` |

Dark theme: `--bg: #0F141A`, `--surface: #171E26`, `--border: #2A3440`, `--text: #E6EBF0`, `--text-muted: #9AA7B5`, accent lightened to `#6FA3E8`, map scale from `#1C2733` to `#8FC1FF`. High contrast: pure black and white backgrounds and text, 7:1 minimum, 2 px borders, no muted text below 4.5:1.

## Layout grid

- Header 56 px: logo and title (from branding), global search box (centre, 480 px max), user menu (right).
- Left rail 64 px: icon buttons with tooltips; labels always visible at 160 px width in accessibility preset or when pinned. Order: Map, Items, Reports, Outputs, User, Settings (settings only with `settings.manage`).
- Main area: fills remaining width; at widths under 1024 px the right panel becomes a sheet over the main area; under 768 px the rail collapses to a menu button.
- Right panel 400 px: contextual details; closable; focus moves into it when opened and returns on close.
- Footer 32 px: legal link, version, required markings text from settings.

## Screens

| Route | Screen | Regions and components | Primary commands (toolbar) | Module |
| --- | --- | --- | --- | --- |
| `/login` | Sign in | Centered card: logo and site title from `GET /branding/public` (CP-08), email, password, sign-in button, error live region; link to legal page | none | M1 |
| `/change-password` | Change password | Card with current, new, confirm; policy hints; forced after temporary password | none | M1, M9 |
| `/` | Map | Toolbar row: period selector (7, 30, 90, 365, custom), view selector (country, region, regulation, facets flagged in M2), colour encoding (recency, count, severity), filter button with active-filter chips, saved view picker, export menu, print menu. Main: MapLibre choropleth with legend; beside it a collapsible jurisdiction listbox (keyboard equivalent) sorted by last change. Right panel on selection: jurisdiction name, counts by severity, latest 10 change events, link to items filtered by that jurisdiction. Status bar: result count announced in a live region | Display, Filter, Search, Change view, Print stock report, Print custom report, Export CSV | M6 |
| `/items` | Items table | Same toolbar as map minus view selector; TanStack table with columns title (translated title when present), jurisdictions, topics, source, published, last changed, severity; column chooser; sort; pagination; row click opens detail panel | Filter, Search, Export CSV, Print | M6, M5 |
| `/items/:id` | Item detail | Header: title, original title, source link, jurisdictions, status, severity. Tabs: Summary (summary, attributes, tags with confidence and feedback buttons), Content (sanitized text, original or translated toggle), Versions (list with changed percent), Diff (side-by-side or unified, text only). Actions: reprocess, edit tags, add to report | Print, Reprocess | M6, M4 |
| `/jurisdictions/:code` | Jurisdiction profile | Header with name, region, parent; timeline strip of change events; items table filtered; regulations list | Print jurisdiction profile | M6 |
| `/reports` | Reports | Left list: stock reports (cards with thumbnail), my layouts, shared layouts. Right: preview pane. New layout button opens builder | New layout, Print, Email, Download PDF | M7 |
| `/reports/builder/:id` | Report builder | Puck editor: left palette (components), centre page canvas, right properties (component props, data source binding: saved view or query, limit). Top bar: name, page size, orientation, save, preview, share | Save, Preview, Share | M7 |
| `/outputs` | Outputs | Table of output jobs (kind, source, destination, status, created, actions); filters mine or all (`outputs.read_all`); retry and cancel; download artifact; scheduled outputs tab with next run | New output, Retry, Cancel | M8 |
| `/me` | User tab | Sections: Profile (name, email read-only), Password (change form), Appearance (theme, contrast, font scale, density, accessibility preset toggle), Locale (language, time zone), Session (idle timeout within admin bounds, remember me, active sessions with revoke), Defaults (landing view, default saved view), Sign out button | Sign out | M9 |
| `/admin` | Settings home | Cards linking to each admin area; health summary (sources unhealthy, queue depth, last backup) | none | M1, M10 |
| `/admin/users` | Users | Table, create and edit dialog (email, name, roles, status, temporary password), reset password action | Create user | M1 |
| `/admin/roles` | Roles | Role list, permission matrix (checkboxes grouped by module from registries) | Create role | M1 |
| `/admin/taxonomy` | Taxonomy | Facet list with reorder; term tree per facet with synonyms and match rules editor and "test against sample text"; import and export | Create facet, Import, Export | M2 |
| `/admin/jurisdictions` | Jurisdictions | Table with code, name, kind, region, active; edit dialog | Create jurisdiction | M2 |
| `/admin/sources` | Sources | Table with kind, health, last run, next run; source editor with connector form generated from `connectors.yaml`; capture job settings (schedule, limits, render JS, extraction rules with selector tester); test run (first 5 candidates); run history table | Create source, Run now, Test | M3 |
| `/admin/settings` | Settings | Form grouped by prefix from registries; validation per type | Save | M1 |
| `/admin/branding` | Branding and legal | Logo upload with preview, title, company fields, primary colour, legal page Markdown editor with preview, required markings text | Save | M1 |
| `/admin/flags` | Feature flags | Toggle list with descriptions and dependencies (hosted providers require data-processing basis) | none | M1 |
| `/admin/printers` | Printers | Table, create dialog (name, IPP URL, media), test page | Create printer, Test page | M8 |
| `/admin/audit` | Audit log | Filterable table (actor, action, entity, date range) with before and after diff viewer; CSV export | Export | M1 |
| `/legal` | Legal page | Rendered legal Markdown and required markings; public, outside the signed-in shell, with the public branding (CP-08) | none | M1 |

## Component conventions

- Every page has one `h1`, landmarks `header`, `nav`, `main`, `aside`, `footer`, and a skip link to `main`.
- Tables use `aria-sort`, keyboard row navigation, and a caption with the result count.
- Dialogs trap focus, close on Escape, and return focus to the opener.
- The map exposes `aria-label` with the view description and relies on the jurisdiction listbox for keyboard and screen-reader access.
- Toasts are polite live regions; errors use `role="alert"`.
- Icons from lucide-react with `aria-hidden` and an adjacent visible or visually hidden label.
