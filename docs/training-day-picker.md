# Training-day picker

> Pick exactly which weekdays you train on when generating a plan. The engine
> assigns long / quality / easy slot types around your choice, respecting
> Daniels' recovery rules — you control the *days*, the engine still owns the
> *intensity layout*.

## Purpose

Before this feature, the Daniels engine hard-coded the training days as
offsets from the long-run day. A 3-day week with a Sunday long run always
landed Thursday + Saturday + Sunday — no way to say "I want Tuesday + Thursday
instead". Real-life schedules don't always line up with that template (gym
classes, work patterns, kids' weekends).

The picker keeps Daniels' philosophy intact (no back-to-back hard sessions;
quality 2-4 days before the long run) while letting the runner align training
with their week.

## How it works (user view)

On the **New plan** form (`/plans/new`), the *Schedule* block has:

1. **Days per week** — 3 / 4 / 5 / 6 radio.
2. **Training days** — seven weekday tiles. Click to toggle. The form keeps
   exactly the number you picked above; if you click an 8th day, the oldest
   non-long check is dropped.
3. **Long run** — a small radio inside each tile, visible only when the day is
   checked. Picking long on an unchecked day auto-checks that day.

When you change "Days per week", the picker re-seeds to sensible defaults
anchored to the current long-run day (the same pattern the legacy fixed
templates used). After that you can tweak freely.

Submit fails with a friendly inline error if the count is wrong or the long
run lands on an un-picked day.

## How it works (implementation)

### Slot allocator

[runsphera/plans/daniels.py](../runsphera/plans/daniels.py) — `_slot_map()` was a lookup against `_SLOT_PATTERNS`; now it's a dynamic allocator when `workout_days` is supplied. The algorithm:

1. Put the long run on `long_run_day`.
2. Score each other workout day for the *main quality* slot: forward-gap from
   the long run is rated closer-to-3-is-better, with adjacency (gap of 1)
   rejected outright (Daniels: never two hard days in a row).
3. Pick the best-scored day as quality. 6-day weeks pick a second quality
   (`quality2`) under the same no-adjacency rule, chosen so it sits 2+ days
   from both the long run and the first quality.
4. All other workout days become `easy`. Non-picked weekdays stay `rest`.

If the user picks a tight set where no valid no-adjacency placement exists
(e.g., 3 days = Fri + Sat + Sun, long = Sun) the allocator falls back to
"best score ignoring adjacency" rather than refusing to generate. Rare edge.

### Data flow

```
new-plan form  ──┐
                  └─→ POST /plans/new ──→ plan_service.create_plan ──→ daniels.generate
                                                                          └─→ _slot_map(dpw, long, workout_days)
                                          ↓
                                          plans.workout_days (CSV)
```

`workout_days` is stored as a comma-separated string of day-of-week ints (e.g.,
`"1,3,6"` for Tue/Thu/Sun) on the `plans` row. Foppen and other fixed-pattern
methodologies ignore the field — only Daniels reads it.

### Modules touched

- [runsphera/plans/methodology.py](../runsphera/plans/methodology.py) — `PlanParams.workout_days: list[int] | None`.
- [runsphera/plans/daniels.py](../runsphera/plans/daniels.py) — `_slot_map()` + `_cyclic_gap()`. Legacy `_SLOT_PATTERNS` kept as the fallback when `workout_days is None`.
- [runsphera/plans/service.py](../runsphera/plans/service.py) — `create_plan()` accepts and validates `workout_days`, persists it as CSV.
- [runsphera/db.py](../runsphera/db.py) — `ALTER TABLE plans ADD COLUMN workout_days TEXT`.
- [runsphera/web/app.py](../runsphera/web/app.py) — `POST /plans/new` accepts the repeated form field, validates count + long-in-set, surfaces inline errors.
- [runsphera/web/templates/plans_new.html](../runsphera/web/templates/plans_new.html) — picker UI + the JS that enforces count and keeps long-run-day in sync.
- [runsphera/web/templates/base.html](../runsphera/web/templates/base.html) — `.day-picker.workout-day-picker` styling shared across themes.

## Configuration

No env vars. The defaults the JS seeds when `days_per_week` changes mirror the
legacy `_SLOT_PATTERNS` offsets (Daniels' canonical layout). To change defaults
in one place, edit `SLOT_OFFSETS` in [plans_new.html](../runsphera/web/templates/plans_new.html) and the Python `_SLOT_PATTERNS` in [daniels.py](../runsphera/plans/daniels.py).

## Known limitations

- **Pattern is constant across the plan.** Every week uses the same picked
  weekdays. There's no per-week override (e.g., "this week I'm on holiday,
  shift my long run to Monday"). For one-off changes use the
  [planned-workout modal](design-system.md#editorial-byline-trio-llm-voice-surfaces) → Move section.
- **No client-side warning when adjacency forces a fallback.** If you pick
  Fri/Sat/Sun + Sun long, the allocator picks Fri as quality even though Sat
  would be adjacent to Sun (gap 1). A "your picked days create a back-to-back
  hard situation — proceed?" warning would be a nicer UX.
- **Pre-existing plans have `workout_days = NULL`.** They render fine
  (`_slot_map` falls back to the legacy fixed template) but can't be re-edited
  to switch to the new picker without regenerating the plan.
- **Doesn't apply to imported methodologies.** Foppen's 7Heuvelen plan ignores
  `days_per_week`, `long_run_day`, and the new `workout_days` field — its
  weekday layout is locked.

## Verification

1. Open `/plans/new`. Pick **Stay fit** + **Daniels** + **3 days/week**. The
   picker should auto-fill **Thu + Sat + Sun** (legacy default with Sunday long).
2. Click **Mon** — Sat gets auto-unchecked (count stays at 3).
3. Click the small **"long run"** radio inside the Tuesday tile — Tuesday gets
   auto-checked; long moves to Tuesday.
4. Submit with **Tue + Thu + Sun · long = Sun**. The generated plan should show
   `Tue=easy`, `Thu=quality (tempo)`, `Sun=long`. Hover the tooltip on Thursday
   in the Tempo plans page to confirm.
5. Try submitting with the long-run radio on a day you've unchecked — you
   should land back on the form with a red error banner.

## Future improvements

- **Adjacency warning** — when the user's day choice would force a quality
  next to the long run, show a non-blocking hint and let them confirm.
- **Per-week overrides** — extend `plan_workouts` so individual weeks can
  shift their pattern without re-generating the whole plan.
- **Smart suggestion** — based on diary mood + Garmin readiness over time,
  suggest the runner's "best" training days as defaults (Mon often misses,
  Thu often green).
- **Preset templates** — "Weekend warrior" (Sat/Sun), "Lunchtime runner"
  (Tue/Thu/Sat), "Every other day", etc. as one-click picks.

---

*Last updated: 2026-05-17*
