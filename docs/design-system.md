# Design system

> The single visual language for the app. Editorial-performance magazine feel — Inter / JetBrains Mono / Archivo Black, paper-cream + ink + tempo-orange accent. Light / Dark / Auto modes; no other theme.

Previously this doc described a multi-theme system (Base / Tempo / Redline). That was consolidated into Tempo on 2026-06-14 — keeping two themes meant every new feature shipped twice. This page is now the reference for *the* design system, not for a theme menu.

## Purpose

A consistent visual identity that:

- Feels like a real coach in your pocket (warm, observant, specific) rather than a stats dashboard
- Treats LLM voice surfaces as pull-quotes with editorial attribution, not chatty alerts
- Uses color semantically (workout types, severity, status) not decoratively
- Respects light/dark mode preference (auto by default; explicit choice always wins over OS)

## Typography

| Use | Family | Weight / Style |
|---|---|---|
| Body | Inter | 400-500 |
| Display headlines | Archivo Black | italic |
| Captions / labels / numeric data | JetBrains Mono | 400-500 |
| Pull-quote (LLM voice) | Archivo Black | italic, oversized |

Self-hosted in [running_coach/web/static/fonts/](../running_coach/web/static/fonts/) — woff2 files + an `@font-face` CSS shim. No external font CDN, keeps the app local-first. Re-fetched with [scripts/fetch_theme_fonts.py](../scripts/fetch_theme_fonts.py).

## Color tokens

Defined as CSS custom properties in [base.html](../running_coach/web/templates/base.html) on `:root` (light) and overridden under `html.is-dark` for dark.

### Surface palette

| Token | Light | Dark | Used for |
|---|---|---|---|
| `--bg` | `#f6f4ef` (paper cream) | `#0a0a0a` (ink) | Body background |
| `--card` | `#ffffff` | `#171717` | Card surfaces |
| `--card-alt` | `#f0ede5` | `#1f1f1f` | Striped tables, recessed cards |
| `--text` | `#0a0a0a` | `#f6f4ef` | Body copy |
| `--muted` | `#666666` | `#999999` | Secondary labels |
| `--rule` | `#e6e2d7` | `#2a2a2a` | Hairlines, borders |
| `--accent` | `#ff3b1f` (tempo orange) | `#ff3b1f` | Brand voice: call-outs, pull-quote glyphs, byline attributions, links/hover, and the *current* item ("today") |

**`--accent` is not a status color.** It is the brand voice and the current-item
marker. It carries no verdict. Because it reads as red-orange, anything that
signals *state* through it looks like an error — which is exactly how an
"Active" integration pill and an "✓ on watch" pill ended up looking like
failures. State goes through the status palette below.

### Status palette (good / worrying / bad)

The single answer to "is this good, worrying, or bad?". Defined on `:root` and
flipped under `html.is-dark` in [base.html](../running_coach/web/templates/base.html).
Two variants per status:

| Token | Light | Dark | Used for |
|---|---|---|---|
| `--ok` | `#15803d` | `#4ade80` | Ink: text, borders, dots, `color-mix()` tints on a card |
| `--ok-solid` | `#16a34a` | `#16a34a` | Filled chip carrying white text |
| `--warn` | `#d97706` | `#fbbf24` | Ink |
| `--warn-solid` | `#d97706` | `#d97706` | Filled chip |
| `--bad` | `#b91c1c` | `#f87171` | Ink |
| `--bad-solid` | `#b91c1c` | `#b91c1c` | Filled chip |
| `--info` | `#1d4ed8` | `#93c5fd` | Ink — neutral information (e.g. rain in the weather strip) |
| `--info-solid` | `#2563eb` | `#2563eb` | Filled chip |

Why two variants: the ink variant must flip per mode to stay legible on the
card surface, but a mode-flipped bright green (`#4ade80`) under white text is
unreadable — so filled chips get a `-solid` value that stays put in both modes.

Rules:

- **Never hardcode a green/amber/red hex.** Every state-signalling rule reads a
  token. This is what keeps one meaning to one color: before this was enforced,
  "positive" was spelled `#15803d`, `#16a34a`, `#4ade80` *and* `#86efac`
  depending on which surface you were looking at.
- **No per-rule `html.is-dark` colour overrides.** The token already flipped.
  Only override when the *mix ratio* needs to change (a 8% tint of a bright
  green on charcoal barely registers — see `.weather-hour-col.is-best`).
- Positive outcomes (done, on watch, linked, active, on-plan, complete) → `--ok`.
  Worrying-but-not-failed (caution, behind, over-target) → `--warn`.
  Negative or destructive (missed, delete, A-race warning) → `--bad`.
  Current/today → `--accent`.

### Semantic palettes (preserved regardless of mode)

These encode meaning — color *is* the message. They render the same in light and dark, with one deliberate exception: the severity palette is muted in dark mode (see its note below).

**Workout-type stripes** (used on plan-week cards, recent-runs row, today-flagship card, run-detail modal kicker, calendar chips):

| Workout type | Color | Hex |
|---|---|---|
| Easy | green | `--w-easy` |
| Long | blue | `--w-long` |
| Tempo | orange | `--w-tempo` |
| Intervals | red | `--w-intervals` |
| Race | amber | `--w-race` |
| Rest | grey | `--w-rest` |

**Training-phase palette** (block-map segments + their legend on `/plans` and `/plans/{id}`, and the phase pill on every week row):

| Phase | Color | Token |
|---|---|---|
| Base | green | `--phase-base` |
| Build | blue | `--phase-build` |
| Peak | red | `--phase-peak` |
| Taper | purple | `--phase-taper` |
| Race | amber | `--phase-race` |
| Maintain | grey | `--phase-maintain` |

Consumers set `--phase-c` via a `.phase-<name>` class and read it from there, so the block-map segment and the week-row pill are the same colour by construction. The pill tints to 20% against the card and keeps its label in `--text` — several of these hues are tuned for filled blocks and fail contrast as micro-type.

**Coach-status palette** (daily readiness banner — GO / CAUTION / EASY / REST):

| Status | Color |
|---|---|
| GO | green |
| CAUTION | amber |
| EASY | softer amber |
| REST | muted grey |

**Severity / wellbeing palette** (body-map regions, active-issue cards, and any "how is the runner doing" surface — see [body-wellbeing-checkin.md](body-wellbeing-checkin.md)):

| Severity | Color | Token | `-ink` variant |
|---|---|---|---|
| 1–3 | muted green | `--sev-mild` | `--sev-mild-ink` |
| 4–6 | amber | `--sev-mod` | `--sev-mod-ink` |
| 7–10 | red | `--sev-severe` | `--sev-severe-ink` |

Plus `--sev-cleared` (a closed issue) and `--sev-inactive` (no issue — a subtle outline). The `-ink` variants are darker and exist for legibility when the value is set as a large numeral rather than a fill.

**This is the one semantic palette that theme-shifts.** Every token above has an `html.is-dark` override, deliberately muted so a bright severity fill doesn't glow on charcoal. So unlike a `wtype-tempo` stripe, a severity green is *not* the same green in both modes — check both when touching it. (`--sev-severe` is `#ef4444` in light and dark; its override is redundant and can go.)

**Calendar distance bands** (race chips on `/calendar`):

| Band | Used for |
|---|---|
| short | 5k / 10k |
| mid | 15k |
| long | half |
| marathon | marathon |

## Light / Dark / Auto

Three values stored in `app_settings.theme_mode`: `auto` (default) / `light` / `dark`.

How it works:

1. Server renders `<html data-mode="{{ theme_mode }}">` based on the DB value
2. A tiny inline `<head>` script combines `data-mode` + `matchMedia('(prefers-color-scheme: dark)')` and applies `html.is-dark` or `html.is-light` synchronously, before the body paints
3. All dark-mode CSS rules target `html.is-dark`, **not** `@media (prefers-color-scheme: dark)` — so an explicit Light or Dark choice always wins over the OS setting

User-facing surface: `/settings` → *Appearance* card → 3-button mode toggle (Auto · Light · Dark).

## CSS architecture

Two layers cooperate to make the cascade behave:

1. **Inline base `<style>`** in [base.html](../running_coach/web/templates/base.html) — light tokens on `:root`, dark tokens on `html.is-dark`, all baseline component rules.
2. **`<link>` to [static/app.css](../running_coach/web/static/app.css)** loaded *after* the inline `<style>` — page-level component classes (the `.tp-*` family) and feature-specific overrides. Wins on equal specificity through source order.

### Class-name conventions

- `.tp-*` prefix for editorial / page-level layout classes (`.tp-dash-hero`, `.tp-coach-message`, `.tp-card`, `.tp-section-eyebrow`, etc.) — this is a vestigial prefix from the multi-theme era, kept because renaming ~800 selectors offers no functional benefit. Treat `tp-` as "page-layout" and proceed normally.
- `.wtype-easy`, `.wtype-long`, `.wtype-tempo`, etc. — workout-type semantic classes
- `.is-dark`, `.is-light` — `<html>` mode classes; toggled by the inline script
- `.is-active`, `.is-loading`, `.is-disabled` — state classes; never standalone selectors

## Editorial byline trio (LLM voice surfaces)

Three LLM-generated voice surfaces share a consistent attribution footer: `— Coach · HH:MM · ↻ Regenerate`.

- **Daily coach** ([_coach_message.html](../running_coach/web/templates/_coach_message.html)) — hero pull-quote, time pulled from `daily_coach_generated_at(conn)`
- **Weekly recap** ([_weekly_recap.html](../running_coach/web/templates/_weekly_recap.html)) — pull-quote card, time from `weekly_recap_generated_at(conn)`
- **Run reaction** ([_run_reaction.html](../running_coach/web/templates/_run_reaction.html)) — the run-detail modal's coach pull-quote (`.tprd-coach-quote` + `.tprd-coach-by`), time from `run_reaction_generated_at(conn, activity_id)`. One partial for all states, included inline by `_run_detail.html` and returned by the lazy/refresh endpoints, so the inline and swapped-in renders are the same markup.

All three helpers in [commentary.py](../running_coach/llm/commentary.py) share the `_cache_row_local_hhmm` parser that converts SQLite's UTC `created_at` to local HH:MM.

The HTMX swap targets (`#coach-head`, `#weekly-recap`, `#run-reaction-<id>`) wrap both body and byline so regeneration preserves the editorial structure.

## Component conventions

### Cards
Default `--card` background, `--rule` 1px border, 18px border-radius, 1.5rem-1.75rem padding. Drop shadows are rare — the `--rule` hairline does the lifting.

### Section eyebrows
`.tp-section-eyebrow` — JetBrains Mono, 0.62rem, `--muted` color, 0.16em letter-spacing, uppercase, often prefixed with a circled number (`①`, `②`, etc.) for the dashboard's reading order.

### Pull-quote bodies
Inter italic, 1.3rem-2rem, sat hard against the left edge. Accent-colored quote glyph (only on daily coach + weekly recap, not run reaction).

### Status pills
Small uppercase JetBrains Mono with a leading colored dot. `.tp-status-pill status-go` / `status-caution` / `status-easy` / `status-rest`. Filled, so they use the `-solid` tokens. The colored dot pulses on GO; should respect `prefers-reduced-motion` (todo).

### State pills and badges
Tinted-background + ink-colored-text chips, drawn from the status palette. The same meaning must land on the same color no matter which surface renders it:

| Pill | Meaning | Token |
|---|---|---|
| `.tp-card-corner-pill pill-ok` / `pill-on` | integration linked / active | `--ok` |
| `.tp-card-corner-pill pill-off` | offline / idle | `--muted` |
| `.tp-pw-pill on-watch`, `.watch-pill on` | pushed to the watch | `--ok` |
| `.tp-pw-pill status-done`, `.status-pill done` | session completed | `--ok` |
| `.tp-pw-pill status-missed`, `.status-pill missed` | session missed | `--bad` |
| `.tp-pw-pill status-today`, `.status-pill today` | current day | `--accent` |
| `.week-adherence adh-complete` / `adh-on-track` | on plan | `--ok` |
| `.week-adherence adh-behind` | behind | `--warn` |
| `.tprd-verdict`, `.tprd-glow-badge` | ran on plan / over target | `--ok` / `--warn` |

`pill-ok` and `pill-on` are deliberate aliases of one green rule — both say "this integration is live", and having them differ was the original inconsistency.

Two layers render some of these concepts twice (base `.status-pill` for `_day_card.html`, Tempo `.tp-pw-pill` for the workout modal). When you touch one, check the other — a day cell and the modal it opens must not disagree about what "today" or "done" looks like.

### Buttons
| Class | Role | Fill |
|---|---|---|
| `.tp-btn` | default / secondary | transparent, `--muted` text, `--rule` border |
| `.tp-btn.primary` | main action | `--text` fill, `--accent` on hover |
| `.tp-btn.danger` | destructive (delete, reset) | `--bad` text + border, `--bad-solid` fill on hover |

`.danger` must not share `--accent` with `.primary`'s hover state — a Delete button that looked like a normal call-to-action was the second half of the same problem.

### Inline confirm strips

**No native `confirm()` or `alert()` anywhere in the UI.** Actions worth a second thought ask inline: the first submit reveals a `.tp-confirm` strip under the button, and only the strip's own button posts.

A form opts in declaratively — no per-instance script:

```html
<form method="post" action="/plans/7/delete"
      data-confirm="Delete this plan permanently? This removes the plan and all its workouts."
      data-confirm-yes="Yes, delete">
```

| Attribute | Purpose |
|---|---|
| `data-confirm` | the question. Required — its presence is what arms the strip |
| `data-confirm-yes` | confirm-button label. Defaults to *Yes, continue* |
| `data-confirm-tone` | `primary` for cautionary actions (accent tint, `.tp-btn.primary`). Default is destructive (`--bad` tint, `.tp-btn.danger`) |
| `data-confirm-field` | name of a field whose live value replaces `{value}` in the question, so it can quote back what the runner just typed ("Set plan VDOT to 46.2?") |
| `data-confirm-into` | selector of an ancestor (via `closest()`) to mount the strip on, for forms sitting in a container too narrow to read in |

The handler lives once in [base.html](../running_coach/web/templates/base.html), delegated from `document` — so partials HTMX swaps in later (plan-settings modal, recalibrate preview) are covered without shipping their own copy.

Behaviour that matters:

- **Cancel takes focus**, so a reflexive Enter or Space backs out rather than confirming something destructive. Escape cancels too, and cancelling returns focus to the button that opened the strip.
- **One strip at a time**; opening a second releases the first.
- The originating form gets `.is-confirming` (dimmed, `pointer-events: none`) so its button can't be double-fired.
- Confirming calls `form.submit()`, *not* `requestSubmit()` — `submit()` doesn't re-fire the submit event, so the handler can't loop. Constraint validation still applies, because the browser validates before the submit event that armed the strip ever fires: an out-of-range VDOT never reaches a confirm strip at all.

**Mounting.** The strip carries both `flex: 1 0 100%` and `grid-column: 1 / -1`; each is inert in the wrong context, so one rule gives it a full-width line in a flex button row, a full-column span in a grid row, and a plain stacked block elsewhere. **A flex container hosting a strip needs `flex-wrap: wrap`** — without it the strip can't wrap to its own line and squeezes the buttons instead. That is why `.archive-row` wraps.

## Configuration

| Setting | Storage | UI surface |
|---|---|---|
| Light/dark mode | `app_settings.theme_mode` | `/settings` → Appearance → Mode toggle |
| Fonts | [running_coach/web/static/fonts/*.woff2](../running_coach/web/static/fonts/) | re-fetch with `python scripts/fetch_theme_fonts.py` |

No env-var escape hatches — mode is a UI choice, not an operator decision.

## Known limitations

- **No reduced-motion handling.** The status-pill dot pulses unconditionally. Should respect `prefers-reduced-motion`.
- **Plotly charts use fixed hex colors.** Don't read tokens from the design system, so dark mode looks subtly off. Could pass theme tokens into the chart renderer.
- **The `tp-` prefix is a vestige** from the multi-theme era. Cosmetic, not load-bearing. Renaming would be a sweep with no functional benefit; treat as legacy class-naming convention.
- **Two layers render some state pills twice.** Base `.status-pill` / `.watch-pill` and Tempo `.tp-pw-pill` express the same done/missed/on-watch/today concepts in different markup. Both now read the same tokens, so they agree on color, but the duplication itself remains — a change to one needs a matching change to the other.
- **The mood and distance-band palettes still hold raw hexes.** They are separate semantic dimensions (not good/bad verdicts), so they were left alone when the status and phase palettes were tokenised. Distance-band has already started drifting — `.tp-cal-race-band.band-short` is `#16a34a` while the filter pill, chip and list row for the same band are `#4ade80`. Deliberate contrast tweak or copy-paste slip is no longer knowable from the code, which is the argument for tokenising it.
- **Severity is tokenised but theme-shifts.** `--sev-*` is properly named — its open item is different from mood/distance-band: its eight `html.is-dark` overrides mean the same severity is two different colors depending on mode. That's intentional (glow control), but it makes severity the one semantic palette you can't verify in a single theme.
- **`.error` keeps its own paired background/foreground** (`#fee2e2` / `#991b1b`) rather than using `--bad`. It is a block alert, not a chip.

## Verification

1. **Mode toggle.** `/settings` → Appearance → click Light · Dark · Auto. Light: paper-cream `#f6f4ef`. Dark: charcoal `#0a0a0a`. Auto: matches OS — toggle your OS appearance to verify.
2. **CSS cascade.** Inline `<style>` rules should lose to `static/app.css` rules on equal specificity (source order). Inspect any `.tp-card` rule in DevTools — the app.css declaration should win.
3. **Semantic colors render the same in both modes.** A `wtype-tempo` stripe should be orange in both light and dark — workout-type colors are load-bearing for plan readability and don't theme-shift. Same for the phase palette: a *build* week's pill and its block-map segment are the same blue in either mode. Severity is the documented exception and is expected to differ.
4. **Status colors agree across surfaces.** On `/settings`, the Garmin card's *Linked* pill and the Coach-voice card's *Active* pill must be the same green — neither may be red. On a plan detail page, a pushed workout's *✓ on watch* pill is green, a missed session's pill is red, and today's is accent. Flip to dark mode and check that each still reads as one color per meaning (one green, one amber, one red) — that's the regression this palette exists to prevent.
5. **No stray semantic hexes.** `grep -nE '#(4ade80|16a34a|15803d|86efac|b91c1c|ef4444|dc2626|f87171|d97706|fcd34d)' running_coach/web/static/app.css running_coach/web/templates/base.html` should only return the token definitions (status, workout-type, phase, severity) plus the raw-hex mood / distance-band rules. A hit inside a pill, badge, button or banner rule is a bug. The phase hexes now live only in the `--phase-*` block in `base.html`; a raw phase hex anywhere else (a legend, a segment rule) means the pill and the block map can drift apart.
6. **Editorial byline trio.** On `/`, the hero pull-quote and weekly-recap card should both show `— Coach · HH:MM · ↻ Regenerate` under the body. Open any run from Recent runs — the modal's reaction strip shows the same byline pattern.
7. **Mode invalid value.** `curl -X POST -d 'mode=nonsense' /settings/theme-mode` should `ValueError` server-side without writing the row.
8. **No native popups.** `grep -rn 'confirm(\|alert(' running_coach/web/templates/` should return nothing outside the documentation comment in `base.html`. Then exercise a strip: `/settings` → *Disconnect* shows an inline red strip and stays connected; Escape and *Cancel* both dismiss it and return focus to the button. `/calendar` → an event's `×` shows a strip spanning the row that names the event, and clicking inside the strip must not open the event modal (the row is itself clickable).
9. **Confirm strips survive an HTMX swap.** Open the plan-settings modal (`/plans` → *Edit plan*, loaded on demand) and submit *Save VDOT* — a strip must appear quoting the value in the field. The handler is delegated from `document`; if it were bound per page load, swapped-in partials would submit unconfirmed.

## Future improvements

- **Reduced-motion guard** — wrap the status-pill pulse animation in `@media (prefers-reduced-motion: no-preference)`.
- **Theme-aware Plotly charts** — pass design-system tokens into the chart renderer so dark mode reads cleanly.
- **`tp-` rename sweep** — replace with a plain `.dash-*`, `.coach-*`, etc. prefix system. Low priority; mechanical.
- **Tokenise mood + distance-band** — both still carry raw hexes repeated across several rule blocks (distance-band four times over, and already inconsistent). Same treatment as the status and phase palettes. Severity is *not* part of this — it's already named; see the separate note under Known limitations.
- **Collapse the duplicated state pills** — one `.status-pill` vocabulary shared by `_day_card.html` and the workout modal, instead of base + Tempo versions of done/missed/on-watch/today.
- **Fold the reshape confirm into `.tp-confirm`** — the plan-reshape strip in `_plan_settings_modal.html` predates the shared component and hand-rolls the same pattern with its own IDs, inline styles and script. It's compliant (no native popup), so this is de-duplication, not a fix. It needs a guard hook first: its trigger validates the day-count picks *before* revealing the strip, which the declarative version has no way to express.
- **Per-feature severity color reuse** — body-map has shipped and consumes `--sev-*` in ~43 rules (regions, entry chips, big numerals, heatmap). Worth an audit that the mapping reads consistently across those surfaces, and that the `-ink` variants are used everywhere a severity appears as type rather than fill.

---

*Last updated: 2026-07-29*
