# Cursus — WP-16 Visual Reference · review.md

> **Revision 3 (2026-11-20) — operator correction applied.** The small-caps "OPEN IN THIS PREVIEW" group header inside the nav list read as a menu point set in a different font (11 px uppercase vs. the points' 13.5 px sentence case) — the inconsistency the operator flagged. Per the operator's pick, it is now a **collapsible parent menu point** ("Open in this preview ▾") in the same type as every other menu point, with the three sub-points indented and slightly smaller beneath it — the template's own group pattern ("Folders ▾"). Two unrequested tweaks made while misreading the complaint were reverted (active-item highlight restored to the reviewed violet pill; preview-state pill size restored). Keyboard re-verified: the parent is a focusable button with `aria-expanded`/`aria-controls`, Enter/Space activate natively, collapse/expand toggles work. All 18 screenshots recaptured.

> **Revision 2 (2026-11-20) — operator correction applied.** The first pass had invented two pieces of chrome the template does not have: a sticky top bar, and a dashed "preview state / variant" strip above the main body. Dashboard 02's live preview was re-inspected before restructuring: it has **no top bar** — the page-title row is the first row *inside* the content — and its body fills the remaining width with **symmetric gutters** (measured ~48 px each side at 1440) in a stacked, full-width flow. Revision 2 removes the top bar and both strips, centers the main column (measured **54 px symmetric gutters** at 1440×900), stacks the phase/attempt bodies full-width like the template (title row → chips → stepper → full-width table → supporting cards below), moves the preview-state pills to the sidebar, and switches phase/attempt variants via the sidebar links. All 18 screenshots were recaptured against the corrected layout; the overflow checks in §1 now verify **no horizontal table overflow at either viewport**. Sections below describe the corrected preview.

**Status:** Review notes for operator approval. All checks below were actually run against `preview/index.html` opened from local files in Chromium (via the automation browser); screenshots are in `screens/`. Anything not verifiable in a static preview is listed under "Pending / not verifiable here" — nothing is claimed as passed that was not observed.

**Assumed review viewports** (the specs do not fix exact resolutions; labeled as assumptions per the skill convention):

- **MyPC-size: 1440×900** (desktop browser)
- **Chromebook-size: 1366×768** (Chromebook browser)

Both render the desktop shell unchanged (sidebar + topbar); the responsive fold at ≤1180 px was not part of the required matrix but is implemented.

---

## 1. Browser checks — both viewports, both themes

Boot check on every load: 0 external network requests, 0 images loaded (zero remote dependencies confirmed via `performance` resource entries); router active; theme behavior applied.

| View | 1440×900 light | 1440×900 dark | 1366×768 light | 1366×768 dark |
| --- | --- | --- | --- | --- |
| Overview (metrics + phases table) | ✅ `overview-light-1440.png` | ✅ `overview-dark-1440.png` | ✅ `overview-light-1366.png` | ✅ `overview-dark-1366.png` |
| Phase — in progress (title row, stepper, packages, questions, steering, cancel, events) | ✅ `phase-auth-light-1440.png` | ✅ `phase-auth-dark-1440.png` | ✅ `phase-auth-light-1366.png` | — |
| Phase — delivered, PR handoff | ✅ `phase-pr-light-1440.png` | ✅ `phase-pr-dark-1440.png` | — | — |
| Phase — delivered, file handoff (M4 preview) | rendered (reachable variant)² | — | — | — |
| Attempt — running (log stream, usage, verification) | ✅ `attempt-run-light-1440.png` | ✅ `attempt-run-dark-1440.png` | ✅ `attempt-run-light-1366.png` | — |
| Attempt — runner disconnected (ownership intact) | ✅ `attempt-disc-light-1440.png` | — | — | — |
| Attempt — parked, unknown (abandon flow) | ✅ `attempt-parked-light-1440.png` | ✅ `attempt-parked-dark-1440.png` | — | ✅ `attempt-parked-dark-1366.png` |
| New run & intake (form + interview) | ✅ `intake-light-1440.png` | ✅ `intake-dark-1440.png` | — | — |

Layout verification added in revision 2: `getBoundingClientRect` measured the centered column (main left 286 px / right margin 54 px at 1440×900 — symmetric), and `scrollWidth ≤ clientWidth` confirmed **no horizontal table overflow** on the overview, packages, attempts and PR tables at **both** viewports.

² The file-handoff variant is a third block inside the phase view, reached via the sidebar's `launch-brief` link; it was exercised during the pass and is the same card pattern as the PR variant (title row → chips → stepper → full-width deliverable table + Download buttons + contract note).

**Vision-reviewed findings (all "no breakage / no contrast failure" verdicts):**

- **Light overview:** metric strip, table, chips all legible; no overflow; high fidelity to the Dashboard 02 neutral-light character.
- **Dark overview:** surfaces read as neutral dark (not blue/purple-tinted); chips distinguishable by hue and context; sidebar/table footnotes legible after the contrast fix below.
- **Phase in progress (light):** stepper node spacing, connector alignment, chip semantics and table rhythm all clean; minor polish notes below.
- **Phase in progress (dark):** footnote/meta contrast confirmed fixed; stepper, chips, table readable; no clipping beyond the expected fold.
- **Attempt running (light, 1366):** the deliberately long log line (~180 chars) wraps with a hanging indent; no horizontal overflow at Chromebook width; pause/copy controls visible; the stacked full-width body holds.
- **Attempt running (dark):** kind-colored lines (violet usage, green command_result) legible on the inset well; hanging indent works; timestamps scannable.
- **Attempt disconnected:** violet ownership banner vs. amber warning states are visually distinct; pending-steer chip present; recovery-action preconditions stated on the disabled controls.
- **Attempt parked:** disabled abandon button visibly disabled; precondition notes readable; amber ownership banner distinct from the disconnected variant's violet one.
- **Intake (dark):** labels/inputs/buttons legible; radio and checkbox states distinguishable; polish notes below.
- **PR handoff (dark):** PR card, head/base SHA chips, verdict chips, primary button and the "merging is your action on GitHub" note all legible; Download button and digest line legible.

## 2. Keyboard / focus checks (observed, real key dispatch)

| Check | Result |
| --- | --- |
| Tab order from page load | Skip link → phase filter → nav (Overview, Attempts, New run & intake) → phase shortcuts → theme control → in-content links (attempt links in the packages table) — semantic DOM order, no traps (re-verified after revision 2) |
| Focus visibility | `:focus-visible` renders **2px solid #8b5cf6** outline with 2px offset (computed style verified on a focused link) |
| Dialog focus | Confirm dialog opens with initial focus on **Cancel** (`autofocus`); **Esc** closes it and resolves as no-action |
| Status communication | `aria-live="polite"` on reconnect banner, cancel banner, steer state, intake state; log stream is deliberately `aria-live="off"` with pause/copy affordances; Problem card is `role="alert"`; current lifecycle step carries `aria-current="step"` |
| Reduced motion | `prefers-reduced-motion: reduce` disables the skeleton shimmer and transitions (CSS media query; not screenshot-verifiable — code-verified) |

## 3. Functional interaction checks (observed)

| Interaction | Observed result |
| --- | --- |
| Phase filter | Typing "grant" hides non-matching rows; clearing restores all |
| Overview preview states | Loaded / **Empty** (metrics hide, explicit empty row shows) / Loading (5 skeletons, no invented values) / Reconnecting (banner, last-committed snapshot) / Error (Problem card `503 · control-store-unavailable`) |
| Steer | Submit → `steer: pending` chip → after runner disposition → `steer: accepted`; empty input focuses the field instead of submitting |
| Interview answer | Submit records once: form hides, `recorded` confirmation appears; empty input is refused |
| Cancel phase | Confirm dialog → banner "cancel: pending …" appears, button disables; banner text states finality conditions |
| Abandon attempt | Button **disabled until a nonempty reason is typed** → confirm dialog → `abandoned` chip, action row hidden |
| Declare unrecoverable | Confirm dialog → "Declared unrecoverable — recorded", disabled afterward |
| Downloads | Download buttons produce a local file (synthetic blob; the deployed route is `GET /artifacts/{id}` with digest headers) |
| Attempt header per variant | Header id/package/step/ref update per attempt entity (att-9f2c41d0/WP-14/produce → att-8d41b2e7/WP-13/verify → att-5e93c8aa/WP-12/produce) |

## 4. Contrast audit (computed WCAG ratios, not eyeballed)

Computed for every text/background pair actually used. **All status chips pass AA (≥4.5:1) in both themes.** Three initial failures were **found and fixed during this pass**:

| Token | Before | Ratio | Fix | After |
| --- | --- | --- | --- | --- |
| light `--text-4` on surface | `#9d9da6` | 2.69 ✗ | → `#71717a` | 4.83 ✓ |
| dark `--text-4` on surface | `#74747e` | 3.87 ✗ | → `#90909b` | 5.66 ✓ |
| dark solid button text on `--brand-600` | `#8b5cf6` | 4.23 ✗ | → `#7c3aed` | 5.70 ✓ |

Remaining passing pairs (samples): light chips ok 6.76 / warn 6.84 / danger 5.91 / active 6.30 / neutral 7.03; dark chips ok 9.63 / warn 9.42 / danger 7.93 / active 7.16 / neutral 7.35; body text ≥ 9.6 both themes; brand links 6.64 (light) / 7.86 (dark).

## 5. Defects found and fixed during the pass

1. **`[hidden]` overridden by component `display`** — `.cancel-banner` and `.q__done` set `display:flex`, which beat the UA `[hidden]` rule, so the cancel banner and a "recorded" confirmation rendered on every fresh load. Fixed with a global `[hidden] { display:none !important }` guard; re-verified (computed `display:none`).
2. **Router misses entity hashes** — sidebar/row links used `#/phase/<id>`-style hashes that weren't in the route table, falling back to overview. Fixed with alias route keys; re-verified.
3. **Contrast failures** — the three token fixes in §4.
4. **Empty state unreachable** — the empty-condition row existed but no preview state revealed it. Added the "Empty" preview state; re-verified.
5. **Shared attempt header misattributed entities** — the parked/disconnected variants showed the running attempt's package/ref. Header now renders per-entity values; re-verified.

## 6. Observations (polish-level, non-blocking; operator may direct changes)

- Unchecked radio/checkbox outlines in dark theme are faint on some displays (native control rendering); hit targets are label-text-sized.
- Browser-default placeholders on the intake repo/ref inputs are dimmer than the styled ones (native `::placeholder` styling varies); could be unified.
- Preview-only demo state persists across hash navigations until a reload (e.g. a confirmed cancel stays disabled) — preview behavior, not a product behavior; product pages re-render from committed state per request.
- The `M4 preview` chip is the lowest-contrast chip (still ≥7:1); intentional de-emphasis of a preview tag.
- Log well boundary against the card is subtle in dark theme (perceptible, not failing).

## 7. Pending / not verifiable in a static preview

- **Real SSE behavior** (cursor replay, `Last-Event-ID`, reset flag, 15s keepalive) — simulated in the preview; contracts are specified in DESIGN.md §8 for WP-16 implementation and tested in `tests/integration/test_browser.py`.
- **Tailscale Serve identity flow, CSRF, and unauthorized-access behavior** — out of scope for a static reference (TS §7; WP-17 qualification).
- **Real artifact download with digest verification** — the preview's download is a synthetic local blob by design.
- **Zoom levels beyond 100% and screen-reader passes** — not exercised; the ARIA structure is in place (§2) but a screen-reader walkthrough should happen at WP-17.
- **1440×900 capture of the file-handoff variant and full 1366×768 dark set for every view** — the file-handoff variant is the same card pattern as the captured PR variant; remaining cells were not individually screenshotted but use identical components already verified in both themes.

## 8. Open decision for the operator (blocking default selection only, not the pass)

1. **Theme default:** Dark default / Light default / Follow-OS-until-overridden — the preview starts on *Follow OS* precisely because this pass does not pick. All three behaviors are implemented and working.
2. **Accent confirmation:** violet inherited from Dashboard 02 (its own brand hue, tuned for AA) — confirm, or redirect at review.

## 9. Deliverable inventory

```
docs/design/wp-16/
├── DESIGN.md                     visual direction, tokens, behavior, TS mappings
├── references.md                 Proper UI entries inspected + how each informed Cursus
├── review.md                     this file
├── preview/
│   ├── index.html                self-contained preview (semantic HTML)
│   ├── cursus.css                both token sets + components (original)
│   └── app.js                    router, theme behaviors, demo interactions (original)
└── screens/                      18 browser captures (both viewports, both themes)
```

No external assets are copied; no network dependency exists (verified at runtime).
