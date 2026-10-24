# Methodology picker

> The illustrated gallery of training methodologies on `/plans/new` — pick *how* you'll train, at a glance.

> See also [plan-recommendation.md](plan-recommendation.md): one tile can carry a "★ Recommended for you" ribbon + reason line, and the recommended methodology / goal / Higdon tier are pre-checked from the runner's fitness baseline.

## Purpose

Choosing a methodology is the emotional centre of plan creation: it commits the runner to a coaching philosophy for the next 8–23 weeks. The old picker was a flat 2-column grid of bordered text boxes — functional but joyless, with the key facts (weeks, days/week, peak volume, whether the schedule is fixed) buried in prose. This redesign turns each methodology into a **plan tile**: an illustrated hero header, title, one-line hook, scannable fact-chips, a clamped description, and a "Best for" footer — so the choice reads like picking a product off a shelf.

## How it works (user view)

On **`/plans/new`**, the *Methodology* step renders a responsive grid of tiles (2-up on desktop, 1-up ≤820px). Each tile shows:

- A **hero image** unique to the methodology, with a small badge (e.g. "All distances", "Race-specific · Marathon") whose colour dot is keyed to the plan's dominant training phase.
- The **title** (Archivo Black italic) and a short **hook**.
- **Fact chips** — weeks, days/week, peak volume, an intensity chip (green/amber/red), and an amber "Fixed schedule" chip where applicable.
- A **description** clamped to 3 lines with an inline **Read more / Show less** toggle (only shown when the text actually overflows — no native popup).
- A **"Best for:"** footer.

Selecting a tile fills a checkmark and rings it in accent. Behaviour is unchanged from before:
- Race-specific methodologies (**Foppen**, **Pfitzinger**) **lock the Goal picker** to their distance.
- Fixed-schedule methodologies **dim the Schedule pickers** and show the "owns its own schedule" note — the day pickers are kept in the DOM (functionality intact), just neutralised.
- **Coming-soon** methodologies (Higdon, Hybrid) render desaturated with a "Coming soon" ribbon and a `disabled` radio.

### Schedule step: start week + optional race date (2026-07-18)

- **Start picker** — "Next week · ‹date›" (default) or "This week": the plan's start Monday, passed to `create_plan(start_date=…)`. "This week" starts the plan on the current week's Monday, so a mid-week signup still gets this weekend's long run (earlier weekdays simply read as past).
- **Race date is optional** for every methodology except race-specific imported plans (Foppen, which sets the new `MethodologyInfo.requires_race_date` flag — the form marks the field required via `data-requires-race`, and both the route and `create_plan` enforce it server-side). Without a date, `create_plan` runs the methodology's full default length (`total_weeks(goal, None, start)` — Daniels' per-goal default, Higdon 12/18, Pfitzinger 18) from the start week and **synthesizes a goal date on the final week's long-run day**; the race-shaped finale (taper + race-day workout) stays, the default title becomes "‹Goal› · N-week build", and the runner can swap in a real event later via event-swap.
- The **subhead is source-honest**: it labels the seed VDOT/volume as measured (Garmin), "what you told us" (manual baseline, with the race-result note), or a cautious default with a link to `/settings#fitness`. See [onboarding.md](onboarding.md) for the seed-precedence ladder.

## How it works (implementation)

- **Modules**:
  - [`running_coach/plans/methodology.py`](../running_coach/plans/methodology.py) — `MethodologyInfo` gained tile-presentation fields: `hook`, `badge`, `badge_phase`, `intensity`, `stat_chips` (list of `(value, label)` pairs). All optional with sensible defaults.
  - [`running_coach/plans/__init__.py`](../running_coach/plans/__init__.py) — `_REGISTRY` populates those fields per methodology.
- **Templates**: [`plans_new.html`](../running_coach/web/templates/plans_new.html) — the *Methodology* `form-block` renders the `.method-tile` gallery + the Read-more JS. The hidden radio still carries `name="methodology_id"`, `data-force-goal`, `data-supported-goals`, `data-fixed-schedule`, `disabled`, and `required`. **Browsing is goal-first**: the distance tiles are never disabled; selecting a goal filters the gallery to methodologies that offer it (`force_goal` = exactly one, `supported_goals` = a subset, neither = all), and a selected tile that no longer fits is deselected in favour of the recommended-or-first visible one. The filter is also server-rendered for the initial goal so the gallery is correct before JS runs.
- **CSS**: [`app.css`](../running_coach/web/static/app.css) — a `/* Methodology picker tiles */` section, scoped entirely to `.method-*`. It reuses the TEMPO tokens (`--card`, `--text`, `--muted`, `--line`, `--chip`, `--accent`) and defines the phase tokens (`--base`…`--maintain`) and `--tint` locally since they're only needed here. The shared `.pick` class (also used by the compact Goal tiles) is deliberately **not** restructured; `.method-tile` overrides its box model.
- **Assets**: [`running_coach/web/static/heroes/`](../running_coach/web/static/heroes/) — one PNG pair per methodology, `‹id›-light.png` / `‹id›-dark.png` (16:9). File names match the methodology `id` (`daniels`, `foppen_7heuvelen`, `pfitzinger`, `higdon`, `hybrid`). The layer matching the active theme is shown via `html.is-light` / `html.is-dark`.
- **Routes**: none changed. `/plans/new` already passes `list_methodologies()` to the template; the new fields flow through automatically.
- **i18n**: new tile strings (hooks, badges, chip labels, intensity phrases, "Fixed schedule", "Read more", "Show less") added to `_NL` in [`i18n.py`](../running_coach/i18n.py).

**Data flow:** `list_methodologies()` → `MethodologyInfo` objects → template loop → per-tile markup. Intensity level maps to a phase colour in-template (`low→base`, `moderate→race`, `high→peak`); the "Fixed schedule" chip and the goal-first tile filter derive from the pre-existing `fixed_schedule` / `force_goal` / `supported_goals` fields.

## Configuration

Tile content is authored in `_REGISTRY`. To add a methodology tile: set `hook`, `badge`, `badge_phase`, `intensity`, and `stat_chips` on its `MethodologyInfo`, and drop a `‹id›-light.png` / `‹id›-dark.png` pair into `static/heroes/`. To swap art, replace those PNGs at the same names/aspect ratio.

## Known limitations

- **Hero art is per-id PNGs**, not generated — a new methodology needs its two images before its tile looks finished (it will otherwise show a broken/empty hero band). The original handoff included a token-driven SVG fallback generator; it was not ported (PNG art is higher fidelity).
- **Fact chips are authored, not derived** from the engine — if a plan's real length/volume changes, the `stat_chips` copy must be updated by hand.
- Chip/badge strings are individually translated; a brand-new copy string renders in English until added to `_NL`.

## Verification

1. Run the app and open **`/plans/new`** (create a plan from `/plans` → "+ New plan").
2. Confirm five tiles render with hero images: Daniels, Foppen, Pfitzinger (live) + Higdon, Hybrid ("Coming soon", desaturated, ribbon, not selectable).
3. Select **Pfitzinger** → the Goal picker locks to Marathon and the Schedule pickers dim with the fixed-schedule note. Select **Daniels** → both unlock.
4. Toggle the app theme (Settings → Tempo) between light and dark → hero art swaps to the matching layer; chips/borders stay legible.
5. On a tile with a long description, confirm **Read more** appears and expands/collapses in place; on short ones it stays hidden.
6. Keyboard: Tab to a tile → focus ring shows; arrow keys move selection within the radio group.

## Future improvements

- Port the SVG hero fallback so new methodologies render before bespoke art exists.
- Derive `stat_chips` from the engine (weeks/peak) so copy can't drift from the generated plan.

---

*Last updated: 2026-07-15*
