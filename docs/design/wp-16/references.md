# Cursus — WP-16 Reference Notes (references.md)

Record of the Proper UI catalog entries actually inspected for this pass, what each contributed, and asset/licensing notes. The lookup connector is design tooling; **no Proper UI installer, React/JSX, Tailwind, npm project, or hosted runtime was used in or shipped with Cursus** — registry content and any install commands were treated strictly as reference material.

## 1. Catalog searches performed

Generic vocabulary only — no private project text, URLs, logs, repo paths or data entered any catalog query.

| Query (`search_screens`, `platform=app`) | Matches | Purpose |
| --- | --- | --- |
| `dashboard with sidebar navigation` (limit 6) | 40 screens; returned dashboard-01…06 | Locate the approved style base and confirm its composition |
| `settings` (limit 6) | 21 screens; returned settings-01…06 | Supporting form/tab patterns for intake/interview surfaces |

Supporting component vocabulary (`compare_screens`, `get_component_docs`) was read on the three entries below. `search_components` was not needed further: the composition lists returned by the screen searches (below) already covered the supporting patterns used (badges, buttons, input, metrics, progress-indicators, table, tabs).

## 2. Style base of record — Proper UI `dashboard-02`

| Field | Value |
| --- | --- |
| Name / title | `dashboard-02` · "Dashboard 02" |
| Layer / type / group | `app-examples` · app screen · `dashboards` |
| Description | "Dashboards with sidebar navigation: Dashboard 02 variant." |
| Live preview | https://properui.dev/preview/variant/app-examples/dashboards/dashboard-02 |
| Docs | https://properui.dev/components/dashboards/dashboard-02 |
| Thumbnail inspected | https://properui.dev/thumbs/app-examples/dashboards/dashboard-02.webp (light theme) |
| Composes | app-navigation, avatar, badges, buttons, charts, cx, demo-assets, dropdown, input, metrics, progress-indicators, table, tabs |
| Token contract | `bg-primary`, `border-secondary`, `text-primary`, `text-tertiary`, `text-quaternary`, `text-fg-quaternary`, `text-utility-brand-400`, `text-utility-brand-600`, `text-utility-neutral-100`, `text-utility-neutral-200`, `text-utility-neutral-400` |

### How it inspired Cursus, per part

- **Sidebar navigation shell → Cursus console shell.** White sidebar on a gray canvas, brand block, search/filter field, primary nav, operator identity at the foot; sticky topbar with title + actions. Adapted: nav lists the operator's real surfaces (Overview, Attempts, New run & intake + phase shortcuts); the identity foot states Tailscale-header identity instead of an account card, and shows no sign-out control (no separate login exists — D2 §7).
- **Metric/stat strip → observability cards.** Three KPI cards in the template became the four D2 §10 projection cards (slot occupancy with mini-meters, queue counts, runner contact, reported usage), each with a contract-grounded footnote ("readiness shown separately from reachability"; unreported usage shows *unknown*, never zero).
- **Table-first content → phases/packages/attempts tables.** Compact ~40 px rows, uppercase micro column heads, hairline separators, row links, kebab-free rows (no destructive row actions), and contract footnotes under each table. Adapted: columns carry Cursus's real dimensions (state chips, package progress meter, open questions, event cursor; ownership / runner / outcome for attempts).
- **Progress indicators → verification & slot meters.** Thin rounded bars on inset tracks, violet fill. Adapted: fill reflects integrated/verified counts, not analytics values.
- **Tabs (pill) → theme behavior segmented control and preview variant switchers.** The pill-tab treatment hosts the three theme behaviors (Dark default / Light default / Follow OS) and the preview-only variant chips.
- **Buttons → action hierarchy.** Violet solid primary (submit, record answer), bordered secondary (send steer, download), red solid danger reserved for exceptional recovery (cancel phase, declare unrecoverable, abandon attempt), ghost for preview utilities.
- **Badges/chips → status vocabulary chips.** Pill chips render contract states verbatim (`integrated`, `verification`, `active`, `parked · unknown`, `claim held`, …); color encodes the D2 §8.3 semantics documented in DESIGN.md §3.1.
- **Charts → reduced to signal-bearing meters.** The template's sparkline/KPI charting is not copied; charts survive only as slot-occupancy and verification meters. (Approved constraint: charts remain only where they carry operator-relevant signal.)
- **Token system → Cursus token sets.** The semantic spine (surface layers, one hairline border strength, four-step text ramp, one brand accent used sparingly, neutral utility steps) is carried over as CSS custom properties, with values re-tuned for legibility and the light/dark toggle (DESIGN.md §3). The brand accent stays the template's violet — *not* blue-dominant — and is shifted lighter on dark surfaces for contrast.
- **Density rhythm & radius character** (8–10 px cards, soft controls, comfortable-medium spacing) carried over directly.

## 3. Other entries inspected

### `dashboard-04` — "Dashboard 04" (compared against dashboard-02)
https://properui.dev/preview/variant/app-examples/dashboards/dashboard-04 · docs: https://properui.dev/components/dashboards/dashboard-04
Composes adds **breadcrumbs** to the dashboard-02 set. Shared the same token spine (comparison showed identical shared tokens; no unique tokens). Informed: **breadcrumb treatment** for phase/attempt detail pages (`Overview / phases / {id}`), confirming that detail-page composition in this visual family uses breadcrumbs over the same shell. Not adopted: its extra date-picker/filters surface (no operator need).

### `settings-02` — "Settings 02" (compared against dashboard-02)
https://properui.dev/preview/variant/app-examples/settings-pages/settings-02 · docs: https://properui.dev/components/settings-pages/settings-02
Composes: app-navigation, avatar, badges, button-group, buttons, checkbox, countries, cx, demo-assets, featured-icon, file-upload, form, input, select, tabs, textarea, timezones, toggle. Adds two tokens to the shared spine (`text-secondary`, `bg-border-secondary`) — evidence the text ramp continues to a fifth role. Informed: **form language for intake and interview** (labeled selects, radios, checkbox groups, textareas with field hints, sectioned field groups in cards). Adapted: Cursus's workflow/form/source fields and the interview question cards reuse this treatment.

## 4. Why no further catalog entries were used

Cursus's remaining surfaces have no faithful catalog match — live log streams, lifecycle steppers, ownership/liveness banners, confirmation dialogs, and problem cards are control-plane concepts the catalog (marketing/app dashboards, settings, auth, email) does not model. Per the task contract, they were designed **from the Cursus contracts** (D2 §§5.1, 6.2, 8.3, 9, 10) in the same visual language: tokens, radii, chip treatment, card/table rhythm and type ramp all come from the approved base; structure comes from the specifications.

## 5. Copied external assets and licenses

- **None.** All preview code is original: `preview/index.html`, `preview/cursus.css`, `preview/app.js` were written for this pass. No CSS/JS was copied from Proper UI, no React source was translated line-for-line, and no installer output is present.
- **Fonts:** none loaded — system font stacks only (DESIGN.md §2).
- **Icons:** inline text glyphs (✓) and CSS shapes only; no icon font, no SVG sprite from external sources.
- **Images:** none shipped; the Proper UI thumbnail/preview URLs in this file are documentation links only and are never fetched by the preview.
- **Proper UI registry content** (composition lists, token names, docs pages) is MIT-cataloged reference material used as *descriptive reference*, not code. No `npx @properui/cli` add command was executed, and no registry file was vendored. The htmx vendoring that WP-16 will do is out of scope for this design pass (it ships with license per D2 §2).
