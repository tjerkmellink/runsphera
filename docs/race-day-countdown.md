# Race-day countdown

> The flagship-aside card that turns the runner's A-race into a daily signal — days remaining, projected finish time, and a 0-100 readiness score saying whether the build-up is on plan.

## Purpose

A training plan's A-race is the gravitational center of months of work — but the rest of the dashboard surfaces today, this week, recent runs. Race day itself was a static line in the calendar. The countdown card pulls it forward into the daily-check-in surface and answers three "where am I?" questions at a glance:

1. **How long?** — days until the race, with phase-driven urgency styling (amber → red → "GO" → recap).
2. **How fast?** — a predicted finish time, sourced from Garmin's race predictor where available and Daniels' VDOT formula otherwise.
3. **Am I ready?** — a 0-100 score blending plan adherence, recent quality work, VDOT trend, ACWR band, and long-run base. Calls out gaps honestly (e.g. "long-run base is light for a marathon" without spelling those words out).

Together they replace the static "Bonus Mobility" tip in the flagship aside whenever the active plan has a linked A-race.

## How it works (user view)

### Where it lives

Top of the **flagship aside** on the dashboard (`/`) — the right-hand column next to "Today's workout" / strength session. It only appears when:

- An **active plan** exists (`plans.status = 'active'`)
- That plan has a **race linked to it** via `runner_races.plan_id` (set when the runner clicks "Plan {distance}" on an event in `/calendar`)
- The race's `race_date` is **between today and 2 days ago** (after that, the daily Bonus tip returns)

When all three are true, the card replaces the daily tip. When they're not (stay-fit plan, no race attached, race long past), the daily tip stays.

### What the runner sees

```
COUNTDOWN
142
DAYS UNTIL
City Marathon
sun 5 apr 2026 · 42 km · Rotterdam
─────────────
ON PACE FOR  3:58:12  VIA GARMIN

RACE READINESS                        82/100
█████████████████████████████░░░░░
ON TRACK                                why?
```

Clicking the card body opens the event detail modal (same as the saved-races carousel below). Clicking the **readiness bar** pops up the score breakdown instead — see below.

### Five phases (urgency styling)

The flag-banner kicker and color treatment shift as the race approaches:

| `days_until` | Phase          | Flag label       | Big number | Color  |
| ---: | -------------- | ---------------- | ---------- | ------ |
|  > 7 | `future`       | `COUNTDOWN`      | days       | amber  |
|  2-7 | `final-week`   | `RACE WEEK`      | days       | red    |
|    1 | `tomorrow`     | `RACE TOMORROW`  | `1`        | red    |
|    0 | `today`        | `RACE DAY`       | `GO`       | red    |
| -1/-2| `recap`        | `RACE RECAP`     | `✓`        | grey   |

The prediction line and readiness bar **suppress in the recap phase** — the actual race time becomes the headline by then.

### Predicted finish time — two sources

The "ON PACE FOR" line picks the most honest available source for the race's distance:

1. **Garmin's race predictor** (preferred at canonical distances). Available for **5k / 10k / half-marathon / marathon**, with a ±0.5 km tolerance. Surfaced as `via Garmin`.
2. **Daniels' VDOT formula** (fallback for non-canonical distances like 15k). Inverted numerically from the runner's calibrated VDOT. Surfaced as `VDOT 43`.

The VDOT in path #2 comes from `plans.vdot_at_start` (the runner's manually-calibrated value, set when they noticed Garmin's reading was optimistically high), falling back to `training_status.vo2max_precise` only when no plan-level VDOT exists.

### Race-readiness score — 0-100

Five components, each capped at its own ceiling, summed:

| Component             | Max | What it measures                                                                |
| --------------------- | --: | ------------------------------------------------------------------------------- |
| **Plan adherence**    |  40 | `done / due` ratio of quality workouts in the last 4 weeks                      |
| **Recent quality**    |  20 | Completed quality activities in the last 3 weeks (target: 3, full at 3+)        |
| **VDOT trend**        |  15 | Today vs 4 weeks ago: ≥ +1 → 15, 0 → 10, -2 or worse → 0                        |
| **ACWR sweet spot**   |  15 | Today's `acwr_ratio` in `[0.8, 1.5]` → 15; outside band tapers to 0             |
| **Long-run base**     |  10 | Longest run in last 6 weeks, blended against what the plan asked for lately and what the race needs — see below |

Three bands → headline verdict shown beneath the bar:

- **75-100** → `ON TRACK` (green)
- **55-74**  → `BUILDING` (amber)
- **< 55**   → `BEHIND`   (red)

Components that need data the DB doesn't have yet (e.g. no VDOT reading 4 weeks back, no ACWR row) score **half their max** rather than 0 — early-plan runners shouldn't see a misleading "behind" red bar just because Garmin hasn't synced enough history yet.

#### Long-run base: two yardsticks, weighted by plan progress

This component answers two different questions, and which one matters depends on where the runner is in the plan:

- **Plan-relative** — *did you run what the plan asked for lately?* The longest run in the last 6 weeks against the longest **already-due** `target_distance_km` in that same window. Workouts scheduled for later this week don't count against the runner yet.
- **Absolute** — *is that enough for the race itself?* The same longest run against the race-day benchmark: race distance for 5k/10k/15k, 18 km for a half, **30 km for a marathon**.

Both use the same ramp shape: **zero at or below 60 % of the target**, full marks at the target, linear between (`_LONGRUN_FLOOR_FRACTION`). The final score is the two blended by **plan progress** — 0.0 at the plan's first workout, 1.0 on race day:

```
pts = (1 - progress) × plan_relative + progress × absolute
```

So week 3 isn't marked down for not having run week 19's long run, while race week is judged on race terms. When nothing distance-based has come due in the window there's nothing to be relative to, and the absolute ramp is used alone.

Keeping the absolute half in the blend is deliberate. Daniels caps the long run at ~25 % of weekly volume, so a marathon plan can top out around 24 km — a runner who completes such a plan to the letter still reaches race day without a 30 km run in the bank, and this component is the only place that gap is visible. It scores ~5/10 at race day rather than full marks, which is the honest answer.

The row's note prints all three numbers (`longest · plan asked · race needs`) precisely so the score is reconstructible. In the absolute-only case it names the zero point instead (`race needs 30 km, under 18 km scores zero`) — otherwise "16.1 of 30" looks like it should be worth half the points when the floor makes it zero.

### "Where does 80/100 come from?" — the breakdown popup

The readiness bar is a button with a `why?` affordance on its right. Click it (or tab to it and hit Enter) and a small popup opens with one row per component:

```
        WEDSTRIJD-GEREEDHEID          80/100
        ─────────────────────────────────────
        Plan-opvolging                  40/40
        ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
        8 van 8 kwaliteitstrainingen in 4 weken

        VDOT-trend                       5/15
        ▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░░░░░░░░░░░░
        -1.0 VDOT t.o.v. 4 weken terug
        …
        ─────────────────────────────────────
        75+ op schema · 55-74 opbouwen · onder 55 achter
```

320 px wide, anchored under the bar with the right edges flush, flipping above the bar when the viewport runs out below. The header doubles as the total the five rows add up to — no separate "Total" row at this size.

Each row shows three things: **points earned / that component's ceiling**, a **mini-bar** of the earned fraction, and the **raw numbers** the points came from (sessions done vs due, VDOT delta, ACWR ratio, longest run vs target). The runner can see at a glance which lever is dragging the score.

Rows are coloured by earned fraction using the same green/amber/red vocabulary as the headline band — ≥ 80 % green, ≥ 50 % amber, below that red — so a `0/10` long-run base doesn't sit there in on-track green. Rows that fell back to **half marks** (the DB couldn't answer) are greyed with a dashed mini-bar; a second footnote explaining that only appears when at least one row actually fell back.

Every number in the popup comes from the scorer's `components` payload — including each ceiling and the band thresholds in the footnote. The template computes nothing, so re-weighting a component in `readiness.py` can't leave the explainer lying.

### When the readiness bar hides

- Plan is **younger than 14 days** (not enough signal to score honestly)
- Race is **more than 2 days past** (recap phase or beyond)
- No A-race linked to the active plan (then the whole card is hidden anyway)
- Any scoring exception (silent fallback — card still renders without the bar)

## How it works (implementation)

### Modules

- **`runsphera/plans/readiness.py`** — `race_readiness(conn, plan, race, today=None)` returns the score payload `{score, band, thresholds, components: {...}}` or `None`. Helper-private functions `_adherence_pts` / `_quality_recency_pts` / `_vdot_trend_pts` / `_acwr_band_pts` / `_longrun_base_pts` each compute one component and return it as a dict: `pts`, its `max` (from the `_MAX_*` constants), the raw numbers behind it, and `estimated` (True when the DB couldn't answer and we fell back to half marks). That dict *is* what the breakdown popup renders. The `total` is summed at full precision before the per-component values are rounded for display. `_longrun_ramp` / `_plan_progress` back the long-run blend; **`today` is a parameter throughout** (defaulting to the real date) so the windows and the progress weighting are reproducible in tests.
- **`runsphera/plans/service.py`** — `predict_race_time(distance_m, vdot)` (bisection inverter for Daniels' formula) + `garmin_race_prediction(distance_km, training_status)` (picks the right `race_pred_*` column by distance with tolerance, returns None outside canonical distances).
- **`runsphera/race_calendar.py`** — `race_for_active_plan(conn, plan_id)` joins `runner_races` → `race_events` to find the linked A-race.
- **`runsphera/web/app.py`** — `index()` route builds the `countdown` context dict (phase, days_until, predicted_time_s, predicted_source/vdot, readiness).
- **`runsphera/ingest.py`** — `_race_predictions_row(payload)` + a dedicated upsert in `_ingest_day` pull Garmin's `time5K / time10K / timeHalfMarathon / timeMarathon` and store them on `training_status` once per day.

### Templates

- **`runsphera/web/templates/_flagship_aside.html`** — the countdown card markup. Includes the prediction line, the readiness bar, and its breakdown popup. The `readiness_row(label, comp, note)` macro at the top of the file renders one breakdown row.

The card is a plain `<div class="tp-side-card race-countdown">` wrapping **two sibling controls**: a `<button class="tp-countdown-open">` (the whole body → event detail modal) and a `<button class="tp-countdown-readiness-trigger">` (the bar → breakdown popup). They can't nest — a button inside a button is invalid HTML and swallows its own clicks — which is why the card element itself is no longer the button. The hover lift moved to `.race-countdown:has(.tp-countdown-open:hover)` so it still reads as one clickable card. Everything inside the trigger is a `<span>`, since a `<button>` takes phrasing content only.

The panel is a **native `[popover]`** wired up with `popovertarget`. That buys three things no CSS-only panel gets: it renders in the **top layer**, so the card's `overflow: hidden` (which the flag banner and edge stripe need) can't clip it and the card doesn't grow when it opens; plus light-dismiss on outside click, Esc to close, and focus handling — all with **zero JS**.

Placement uses **CSS anchor positioning** (`anchor-name` on the trigger, `top: anchor(bottom)` / `right: anchor(right)` on the panel, `position-try-fallbacks: flip-block`), wrapped in `@supports (anchor-name: --tp-rdy)`. Where that isn't supported the UA's own `inset: 0; margin: auto` centers the popup on screen — a plain popup rather than a broken one. Entry animation is `@starting-style` + `transition-behavior: allow-discrete`, disabled under `prefers-reduced-motion`.

### Routes

No new routes. The card is part of the dashboard `GET /` render.

### DB

Columns added to `training_status` (all `INTEGER`, nullable):

- `race_pred_5k_s`
- `race_pred_10k_s`
- `race_pred_half_s`
- `race_pred_marathon_s`

All existing tables consumed read-only by the readiness scorer: `plan_workouts`, `activities`, `training_status`.

### External services

- **Garmin Connect** — `client.get_race_predictions()` (called once per sync in `_ingest_day`, only on today's date — endpoint always returns today's snapshot regardless of date arg).

### Data flow

1. **Sync time** — Garmin's race-predictor endpoint returns the 4 canonical times; they upsert into `training_status` for today via a dedicated SQL (not the generic `_upsert`) so we can supply `raw_json` on INSERT without clobbering the real training_status raw_json on UPDATE.
2. **Dashboard render** — `index()` checks for an active plan with race_date, calls `race_for_active_plan`, builds the countdown dict with phase + days_until. Then computes `race_readiness(...)` and merges `predicted_time_s` / `predicted_source` / `predicted_vdot` into the same dict.
3. **Template** — renders three sub-blocks (header/phase, prediction line, readiness bar) all keyed off the same `countdown` context. Each suppresses independently when its data is missing.

No caching. The score recomputes on every dashboard render — every component is a single indexed query, cost is negligible.

## Configuration

Nothing user-configurable yet. The score weights, band thresholds, and minimum plan age are constants at the top of `plans/readiness.py`:

```python
_ADHERENCE_WEEKS = 4
_QUALITY_WEEKS  = 3
_VDOT_WEEKS     = 4
_LONGRUN_WEEKS  = 6
_MIN_PLAN_AGE_DAYS = 14
_BAND_THRESHOLDS = ((75, "on_track"), (55, "building"), (0, "behind"))
```

Long-run targets (`30 km` for marathon, `18 km` for half, race distance otherwise) live inside `_longrun_base_pts` since they're tied to the formula, not user preference.

## Known limitations

- **Garmin's race predictor only covers 4 distances.** A runner targeting a 15 km, 20 km, or anything non-standard falls back to Daniels' formula. That's fine for 10-15 km (Daniels matches reality closely there) but optimistic for half-marathon and marathon if no Garmin data is available.
- **Daniels' formula assumes distance-specific training.** A runner with VDOT 48 but only 15 km long-runs in the bank can't actually hit Daniels' marathon prediction. The readiness score's long-run-base component flags this gap as a visible scoring penalty rather than a separate warning — the breakdown popup is where the runner sees which component it was.
- **The long-run blend has one date-shaped edge.** Plan progress is measured from `MIN(planned_date)` for the plan, so a plan whose early workouts were deleted rather than left in place would read as having started later, weighting the score too far toward the plan-relative half. Reshapes only touch future workouts today, so this doesn't bite in practice.
- **The breakdown popup needs a modern engine.** Native `popover` (Chromium 114+, Safari 17+, Firefox 125+) for the top-layer panel, CSS anchor positioning (Chromium 125+, Safari 26+) for the placement. The desktop launcher runs pywebview → WebView2 → evergreen Edge, so both are there; other browsers without anchor support fall back to a viewport-centered popup, and a browser without `popover` at all would show the panel inline as a plain block.
- **VDOT trend penalizes early-plan dips.** Aerobic-base weeks can show VDOT drift down before tempo work pulls it back up. The trend window (4 weeks) is short enough to be twitchy on slow weeks.
- **No re-calibration of plan VDOT from race-pace efforts yet.** A parkrun or time-trial implying a new VDOT would be a strong signal for both the prediction widget and the readiness scorer; the roadmap "auto-detect VDOT-implying efforts" item picks this up.

## Verification

1. Open `/` on the dashboard while a plan with a linked race is active and the race is in the future. The Race-day card should render with the day count, race title, predicted finish, and readiness bar.
2. The day count should match `(race_date - today).days` exactly. Off-by-one means timezone drift — check `_date.today()` in `app.py:index()`.
3. The "ON PACE FOR" time should equal `(race_pred_*_s for the race distance)` from `training_status` for today (canonical distance), or the Daniels prediction off `plans.vdot_at_start` (non-canonical). The "via Garmin" / "VDOT 43" suffix flags the source.
4. The readiness score is reproducible: run `python -c "from runsphera.db import connect; from runsphera.plans import readiness, service; from runsphera import race_calendar; from contextlib import closing; conn=connect(); plan = service.get_active_plan(conn); race = race_calendar.race_for_active_plan(conn, plan['id']); print(readiness.race_readiness(conn, plan, race))"` to print the score and component breakdown.
5. Hide-conditions: deactivate the plan, set `plans.race_date = NULL`, or wait until 3+ days after race day — the card should fall back to the daily Bonus tip.
6. Click the readiness bar. The breakdown popup opens **without** opening the event detail modal (they're sibling controls, not nested), the five rows' points sum to the header score within rounding, and each row's note matches the raw numbers in step 4's `components` output. Clicking the card body above it still opens the modal.
7. With the popup open: Esc closes it, a click anywhere outside closes it, and the card underneath does **not** get taller (top layer, not inline flow). Scroll the bar near the bottom of the viewport and reopen — the popup flips above it instead of hanging off-screen.
8. `.venv/Scripts/python.exe tests/test_race_readiness.py` covers the scoring itself — the long-run blend at both ends of the plan, the 60 % floor, the plan-peaks-short case, and that the components sum to the headline score. All fixtures pass an explicit `today` and build their own temp DB.

## Future improvements

- **Auto-detect VDOT-implying efforts** — scan recent activities for race-pace efforts (parkrun, 5k time-trial), back-derive VDOT via `estimate_vdot_from_race`, and surface a "your effort implies VDOT 46 — apply to plan?" banner. Keeps both the prediction widget and the readiness scorer calibrated to current fitness without manual intervention. (See [roadmap.md](roadmap.md) — auto-VDOT idea.)
- **Course profile + projected splits** — if we can scrape elevation profile from the event organiser site (or the runner uploads a GPX), generate suggested splits accounting for hills. Pairs naturally with the predicted finish.
- **Cross-link to plan view** — a "see week" link on the readiness bar that jumps to the active plan's current week so the runner can act on the verdict.

---

*Last updated: 2026-08-12*
