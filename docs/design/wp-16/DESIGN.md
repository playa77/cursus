# Cursus — WP-16 Visual Design Reference (DESIGN.md)

**Status:** Draft for operator review — no implementation decisions are final until this pass is approved.
**Version:** 1.0 · 2026-11-20
**Inputs honored:** Project Brief v1.2.1 · Design Document v0.1.1 · Technical Specification v0.1.2 · Implementation Roadmap v0.1.1
**Visual-language baseline:** Proper UI **`dashboard-02`** (app-examples · dashboards) — inspiration and starting point, **not** a pixel-exact specification. Preview: https://properui.dev/preview/variant/app-examples/dashboards/dashboard-02 · Docs: https://properui.dev/components/dashboards/dashboard-02

The preview is at `docs/design/wp-16/preview/index.html` (local `cursus.css` + `app.js`, zero remote dependencies, synthetic data). It opens directly from the filesystem in any browser.

---

## 1. Visual direction

The console adopts Dashboard 02's application shell and content rhythm and adapts it to Cursus's operator reality: a private, single-operator control surface where **tables carry the primary content**, live event streams need long-session legibility, and every status must be readable as contract vocabulary at a glance.

From Dashboard 02 the pass carries over:

- **Sidebar navigation shell** — fixed 232 px sidebar (brand, filter input, primary nav, operator identity at the foot) on a distinct surface tone; the **main body is a centered column** in the remaining width (max 1100 px, symmetric gutters — measured 54 px each side at 1440×900, matching the template's ~48 px balanced gutters), and **there is no top bar**: dashboard-02 keeps its page-title row *inside* the content, so each view opens with that row (entity title left; "synthetic data" tag + theme behavior control right) as the first row of the body. No banner, strip or control bar sits above the body. The nav uses the template's group pattern: a collapsible parent point ("Open in this preview ▾") set in the **same type as every other menu point**, with its three shortcut children indented and slightly smaller — no small-caps group headers inside the nav list.
- **Stacked full-width body** — like the template (title row → metric cards → one full-width table card), content is single-column: overview = title row → metric strip → full-width phases table; phase = title row → metadata chips → lifecycle stepper → full-width packages table → supporting cards stacked below; attempt = title row → chips → status row → full-width cards.
- **Metric/stat strip** — four compact KPI cards above the phases table (the template's three-KPI row, adapted), carrying the D2 §10 observability projection: slot occupancy with small meters, queue counts, runner contact (readiness shown separately from reachability), and reported usage.
- **Table-first content** — Dashboard 02's compact ~40 px rows, uppercase micro-label column heads, hairline row separators, row-level links, and a sub-caption under each table explaining the governing contract.
- **Density rhythm** — comfortable card padding (12–16 px) with tight data rows; 13–14 px body text; a small step ramp for type.
- **Component treatments** — pill status chips, soft 8–10 px card radii, thin rounded progress meters, pill segmented control for the theme behavior.
- **Token character** — a small semantic set (surface layers, one hairline border strength, a four-step text ramp, one brand accent used sparingly, neutral utility steps), not a large palette.

Adapted for Cursus (surfaces Dashboard 02 does not contain, designed in the same language):

- **Lifecycle stepper** — intake → planning → execution → delivery → delivered, rendered as a connected horizontal step rail with done/current/pending dot states (current step carries `aria-current="step"`).
- **Live log stream** — a monospace, inset-well log panel with kind-colored lines, hanging-indent wrapping for long lines (proven with a ~180-char ref line), pause/resume autoscroll, copy, and scroll-up-pauses behavior. Text is inserted with `textContent` only — payloads are data, never markup (TS §10 sanitization).
- **Ownership / liveness banners** — full-width informational banners distinct from error cards: *runner disconnected — attempt still owns the work* (brand-tinted) and *parked, unknown outcome — ownership held* (warning-tinted).
- **Confirmation dialog** — native `<dialog>` for destructive exceptional actions (cancel phase, declare unrecoverable, abandon attempt).
- **Problem page card** — stable code + safe message rendering of the D2 §5.1 `Problem` contract.
- **Intake form + interview pane** — Dashboard-02-language form controls (labeled selects, radios, textareas with hints) and a numbered-question interview card where recorded answers lock.
- **Handoff cards** — reviewed-PR card (head/base SHAs, checks, review verdict, explicit "merging is your action on GitHub" note) and deliverable-file rows with digest and download.

Charts are reduced to where they carry operator signal: the slot-occupancy meters and per-package verification meters. No decorative charting is included.

## 2. Typography

| Role | Face | Size / weight | Notes |
| --- | --- | --- | --- |
| Page title (content title row) | system sans | 20 px / 680 | `-0.015em` — dashboard-02 places the title inside the content, first row of the body |
| Sidebar menu points (incl. group parent) | system sans | 13.5 px / 500 | **one type for every menu point**; sub-points 13 px, indent only |
| Card & table titles | system sans | 13.5 px / 650 | |
| Phase title | system sans | 20 px / 680 | `-0.015em` |
| Body / table cells | system sans | 13–14 px / 400–560 | |
| Micro-labels (column heads, metric labels) | system sans | 11–11.5 px / 600, uppercase, `0.04em` | Dashboard 02 convention |
| Chips | system sans | 11.5 px / 600 | contract vocabulary verbatim |
| Log / IDs / digests | system mono | 12.25 px log, 0.92 em inline | `ui-monospace` stack |

Font stacks are system-only (no webfonts, no CDN):

- Sans: `ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif`
- Mono: `ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace`

## 3. Color and theme

Two complete token sets, both defined as CSS custom properties: light on `:root`, dark on `html[data-theme="dark"]`. Derived from Dashboard 02's token character (`bg-primary`, `border-secondary`, the `text-primary/…/quaternary` ramp, `utility-brand-*`, `utility-neutral-*`), with values tuned for legibility and toggle behavior rather than copied.

**Palette constraints honored:** the scheme is neutral-first with a violet brand accent — Dashboard 02's own brand hue, not blue-dominant (constraint: the operator reads with blue-light-filtering glasses). Status colors are reserved for chips/banners/buttons and never used decoratively. Both sets were checked for text contrast: body text ≥ 7:1, secondary/meta ≥ 4.5:1, chip text on chip backgrounds ≥ 4.5:1 (verified samples in review.md).

### Light token set (summary)

| Token | Value | Use |
| --- | --- | --- |
| `--bg-page` | `#f7f7f8` | canvas |
| `--bg-surface` | `#ffffff` | cards, tables, sidebar |
| `--bg-inset` | `#f2f2f4` | log well, inline code |
| `--border` / `--border-strong` | `#e4e4e7` / `#d4d4d8` | hairlines, control borders |
| `--text-1…4` | `#1b1b1f` `#44444a` `#6e6e76` `#71717a` | headings/values → muted |
| `--brand-600` / `--brand-text` | `#6d28d9` / `#6d28d9` | solid buttons / links & active accents |
| `--brand-soft` | `#f4effe` | active chip + banner tint |
| `--ok/warn/danger/neutral` | text on tinted bg + border (see §3.1) | status chips, banners |
| `--focus-ring` | `#8b5cf6` | focus outlines |

### Dark token set (summary)

| Token | Value | Use |
| --- | --- | --- |
| `--bg-page` | `#101013` | neutral dark, minimal blue cast |
| `--bg-surface` | `#17171b` | cards, tables, sidebar `#131317` |
| `--bg-inset` | `#121215` | log well, code |
| `--border` / `--border-strong` | `#2b2b31` / `#3b3b43` | |
| `--text-1…4` | `#f4f4f6` `#d6d6db` `#a3a3ad` `#90909b` | |
| `--brand-600` / `--brand-text` | `#7c3aed` / `#b79dfb` | solid buttons / links on dark |
| `--brand-soft` | `#241b38` | active chip + banner tint |
| `--ok/warn/danger/neutral` | desaturated-bright variants | status chips, banners |

### 3.1 Status chip mapping (labels are contract vocabulary — colors may be tuned, labels may not)

| Contract states (D2 §8.3) | Chip color | Rationale |
| --- | --- | --- |
| `delivered`, `integrated`, `accepted`, `reachable`, `completed` | green (`ok`) | positive, terminal-good |
| `execution`, `active`, `running`, `claim held`, `verification-in-progress accents` | violet (`active`) | work in flight — uses the brand hue, stays in the template's vocabulary |
| `intake` w/ open questions, `parked · unknown`, `ownership held`, `unreachable`, `pending`, `open questions`, `warn` states | amber (`warn`) | attention, unresolved |
| `failed`, `canceled`, `abandoned`, `stopped`, `rejected` | red (`danger`) | terminal-bad |
| `ready`, `blocked`, `review`, `integration`, `neutral-info`, `preview` tags | neutral gray | structural states |

### 3.2 Theme toggle — three behaviors (preview ships a working control)

The topbar segmented control offers exactly the three behaviors, as **preview-only selectable options**:

1. **Dark default** — sets `data-theme="dark"` unconditionally.
2. **Light default** — sets `data-theme="light"` unconditionally.
3. **Follow OS until overridden** — clears the explicit override and tracks `prefers-color-scheme`, updating live on OS changes (`matchMedia` listener). **This is the preview's initial state** because it asserts no default.

> **The shipped default is an operator decision to confirm at review** — this pass does not pick it. Options for the operator: make *dark default* or *light default* the initial token set, or ship *follow-OS* as the default behavior. Listed as the open item in review.md.

Implementation notes for WP-16: the same mechanism ports to the server-rendered surface as a cookie (`cursus_theme=dark|light|system`) read into the base template's `data-behavior` attribute, with `matchMedia` JS carried in `static/events.js`. Tokens stay as CSS custom properties on `:root` + `[data-theme]`, so templates need no theme branching.

## 4. Density, spacing, responsive behavior

- **Grid:** sidebar 232 px; the main body is a **centered column** (max 1100 px, `margin-inline: auto`) with symmetric gutters — 54 px each side at 1440×900, ≈17 px at 1366×768 — mirroring the template's balanced gutters. Body content is stacked full-width within that column (no side columns).
- **Spacing scale:** 4 px base — card padding 12/16, row padding 9/14 vertical/horizontal, gaps 6/10/14.
- **Row height:** ~38–40 px in data tables (Dashboard 02 rhythm).
- **Radii:** 10 px cards, 8 px controls/inputs, 7 px small buttons, 999 px chips/pills.
- **Responsive:** ≤1180 px the sidebar folds into a horizontal top bar (nav wraps, operator card moves right), metric strip drops to 2 columns, and the intake two-column form grid stacks; ≤720 px the metric strip is single-column and form row pairs stack. The phase/attempt bodies are single-column at every width (template fidelity). Tables fit their card at both review viewports with no horizontal scrolling (verified); `.tablewrap` remains as a safety scroll container. Both review viewports (1440×900, 1366×768) render the desktop shell unchanged.

## 5. State coverage map (preview variants → contracts)

Preview-state pills live in the **sidebar** (shown only on the overview) so the body carries no control strips; phase and attempt variants are reached through the sidebar links.

| Preview state | Where | Contract |
| --- | --- | --- |
| Loaded overview (metrics + phases table) | Overview | `GET /` View projection (D2 §6.2, §10) |
| Loading skeletons | Overview switcher | reads show skeletons, no invented values |
| Reconnecting banner | Overview switcher | SSE resume from committed cursor (D2 §6) |
| Error (Problem card) | Overview switcher | `Problem` code + safe message (D2 §5.1, §11) |
| Phase in progress | Phase → "In progress" | stepper, packages table, interview answer-once, steer pending→accepted, cancel pending banner, committed events w/ cursor |
| Delivered — PR handoff | Phase → "Delivered — PR handoff" | PR ready for operator decision; **no merge control**; evidence; download |
| Delivered — file handoff | Phase → "Delivered — file handoff (M4)" | same download contract; no external distribution |
| Attempt running | Attempt → "Running" | log stream, usage, verification queue, steer accepted |
| Runner disconnected | Attempt → "Runner disconnected" | ownership-intact banner; liveness ≠ ownership (D2 §5, §8.3) |
| Parked — unknown | Attempt → "Parked — unknown" | abandon enabled with required reason + confirm; `declare_unrecoverable` disabled outside its precondition |
| Intake + interview | New run & intake | `submit(Input)`; `answer(phase,question,text)` recorded once; required/optional flags; caps noted |

## 6. Controls, disabled states, and fallbacks (mapped to TS v0.1.2 §§6–7 and 8.3)

| Observable control | Enabled when | Disabled/absent because | Contract |
| --- | --- | --- | --- |
| **Record answer** (interview) | question open, nonempty text | after recording — reply is recorded once; repeated replies return the recorded response | §8.3.1 |
| **Send steer** | attempt eligible (current pi attempt), nonempty text | — (never shown for non-pi or finished attempts) | §6.2, §5.1 `steer` |
| Steer status chip | — | flips pending → accepted only on the runner's actual disposition; never fabricates acceptance | §4.1, §5.1 `CommandResult` |
| **Cancel phase** | nonterminal phase | disabled after request; banner explains cancellation reports final only after live attempts proven stopped + publication intents reconciled | §8.3.8 |
| **Declare unrecoverable…** | operator asserts evidence of permanent loss/missing record on an unresolved *unavailable* attempt | disabled elsewhere with the precondition stated on the control | §8.3.8, §5.1 Action union |
| **Abandon attempt** | attempt already parked with unknown outcome **and** nonempty reason | disabled otherwise; confirm dialog; late results cannot advance the phase afterward | §8.3.8 |
| **Download** | ready FileRef authorized by its phase | — | §6.2 `GET /artifacts/{id}` |
| **Open PR on GitHub** | delivered with PR identity | external to Cursus; no merge control anywhere (target merge is the operator's) | §7, §8.5 |
| Theme radios | always | — | preview-only control |
| Pause autoscroll / Copy | log visible | autoscroll re-engages only at bottom | §10 sanitized stream |

**Fallbacks:** loading → skeletons; empty list → explicit empty row ("no phases yet…"); SSE loss → reconnecting banner + cursor resync; retention/reset → SSE `reset` + resnapshot (server-side); service error → Problem card with stable code, no state change. Unreported usage renders as *unknown*, never zero (§10).

## 7. Keyboard handling, focus, status communication

- **Focus visibility:** every interactive element shows a 2 px `--focus-ring` outline with 2 px offset on `:focus-visible`; small-size controls reduce the offset to fit.
- **Skip link:** "Skip to content" targets `#main` (visible on focus).
- **Tab order:** DOM order is semantic (nav → content); the sidebar's preview-state pills use `aria-pressed` (not tab-stops inside a tablist), so nothing traps focus; phase and attempt **variants are switched with ordinary sidebar links**, so no extra in-body switchers exist; the log panel is `tabindex="0"` with a label so it is reachable and scrollable by keyboard.
- **Dialogs:** native `<dialog>`; the cancel action receives initial focus, focus is trapped by the element, and Esc closes without action.
- **Status communication:** reconnecting banner and steer/cancel/abandon results update `aria-live="polite"` regions; the Problem card is `role="alert"`; the log stream is deliberately `aria-live="off"` (a chatty stream must not interrupt screen-reader output; the pause control and copy affordance provide access).
- **Reduced motion:** `prefers-reduced-motion: reduce` disables the skeleton shimmer and all transitions/animation durations; autoscroll jumps are instant.
- **Keyboard shortcuts:** none invented. The preview has no global hotkeys; filter inputs are plain focusable fields (⌘K-style shortcuts are not part of this reference and would be an implementation decision for WP-16, not implied here).

## 8. Target implementation mapping (for WP-16, not part of this pass)

- **Stack (fixed by D1/D2):** FastAPI + uvicorn, **Jinja2** server-rendered templates, **htmx** (vendored, local) for interaction, **SSE** for event streams. No frontend build, no React, no npm.
- **Template mapping:** `templates/base.html` (shell: sidebar, topbar, theme behavior control, skip link), `templates/index.html` (overview = metric strip + phases table), `templates/phase.html` (stepper, packages table, questions, steering, cancel, events), `templates/attempt.html` (log stream, ownership banners, recovery actions), `templates/problem.html` (Problem card).
- **Assets:** `static/cursus.css` (these tokens/components), `static/events.js` (SSE with cursor replay + theme behavior), vendored `static/htmx.min.js` + license.
- **Forms:** each preview form maps to `POST /operator/actions` with hidden `request_id` + CSRF field; the reply's entity/state/cursor drives htmx swaps; nothing posts anywhere else.
- **SSE:** `GET /phases/{id}/events` with `Last-Event-ID`/cursor; keepalive comments; reset flag handling.
- The preview is design tooling only: **no catalog software, installer output, React/JSX, Tailwind, npm project, or hosted runtime is included or referenced by the deployable.**

## 9. What this pass does *not* decide

- The theme default (dark / light / follow-OS) — operator decision, open in review.md.
- Final accent-hue approval (violet inherited from Dashboard 02, tuned) — confirm at review.
- Exact concurrency/slot-count presentation defaults beyond the D2 §4 defaults shown (2 pi / 1 verifier / 1 frontier / 1 repository).

## Revision history

| Version | Date | Changes |
| --- | --- | --- |
| 1.0 | 2026-11-20 | Initial WP-16 reference built on operator-approved `dashboard-02`; both token sets + three toggle behaviors; default left to operator; Cursus-only surfaces designed in the same visual language. |
| 1.1 | 2026-11-20 | Operator correction applied: removed the invented top bar and the preview-state/variant strips above the body (dashboard-02 has neither); main body is now a centered column with symmetric gutters and a stacked full-width flow matching the template; preview-state pills moved to the sidebar; phase/attempt variants switch via the sidebar links. Screenshots recaptured. |
| 1.2 | 2026-11-20 | Operator correction applied: the small-caps "Open in this preview" group header inside the nav list — read as a menu point in a different font — replaced by a collapsible parent menu point in the same type as all others, with chevron and smaller indented children (the template's "Folders" pattern). Screenshots recaptured. |
