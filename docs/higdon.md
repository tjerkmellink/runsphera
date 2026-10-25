# Hal Higdon — tiered marathon & half-marathon plans

> Beginner-friendly training plans by experience tier (Novice → Intermediate → Advanced). Mostly easy mileage with one long run; minimal quality work at the lower tiers. The plan for someone starting out.

## Purpose

Higdon's plans are the most widely-run beginner marathon and half-marathon plans on the internet, and this is the app's low-complexity, effort-first methodology — the one that speaks to people who are just starting to run. Where Daniels asks you to think in VDOT zones and Pfitzinger assumes a serious mileage base, **Higdon Novice 1 is four short easy runs, one long run, and a cross-training day** — no speedwork, no pace maths. The payoff: a runner with no background can pick a tier, set a race date, and get a schedule they can actually follow.

It is a **methodology engine**, not a transcription of the copyrighted week-by-week tables on halhigdon.com. Like the Pfitzinger engine, it reproduces Higdon's documented *framework* — the six-tier ladder, the mostly-easy-mileage shape, step-back weeks, the 32 km (20-mile) peak long run, the short taper — and generates the concrete prescription itself, metricised and calibrated to the runner's fitness.

## How it works (user view)

At **`/plans/new`**, pick the **Hal Higdon** methodology. Because it declares `supported_goals=["half_marathon", "marathon"]`, the goal picker keeps only **Half marathon** and **Marathon** selectable (the rest grey out). Because it declares `variants`, an **Experience level** picker appears with the six tiers:

- **Novice 1** — new to the distance. Easy runs + one long run + cross-training. No speedwork at all.
- **Novice 2** — a step up: adds a mid-week goal-pace run and goal-pace finishes on the biggest long runs.
- **Intermediate 1** — five running days; a Saturday run stacked before the Sunday long run (back-to-back), a mid-week goal-pace run, two 20-milers.
- **Intermediate 2** — more volume + a weekly tempo; three 20-milers.
- **Advanced 1** — six running days with hill repeats, a goal-pace run, and a tempo.
- **Advanced 2** — highest volume: 800 m speed work, tempo, and goal-pace runs.

Because it declares `fixed_schedule=True`, the days-per-week / training-day pickers are visibly neutralised — each tier owns its own weekly pattern anchored to the race weekday, and the `plans` row records the schedule the engine actually generated. While neutralised, the pickers **mirror the selected tier's real schedule** (Intermediate 1 shows 5 days, Advanced 2 shows 6, laid out around the race weekday) instead of the user's stale picks; each variant carries its run-day offsets (derived from the engine's tier template via `tier_day_offsets`), Pfitzinger/Foppen expose the same via `MethodologyInfo.fixed_day_offsets`, and the form restores the user's own picks when switching back to a free-schedule methodology.

Set a **race date** (and optional target time). The marathon build runs **18 weeks**, the half **12**. With the race closer than that, the plan **compresses** by dropping opening base weeks (nothing is ever back-dated into the past); under 12 weeks (marathon) / 8 weeks (half) the form explains there's no honest build left.

Descriptions read as **effort** ("easy, conversational", "comfortably hard") — true to Higdon — but every run still carries a pace target under the hood, so the workouts push to Garmin, match against your actual runs, and recalibrate exactly like the other engines.

## How it works (implementation)

- **Modules**
  - `runsphera/plans/higdon.py` — the engine. `class HigdonPlan(Methodology)` with `total_weeks()` and `generate()`. Tier profiles in `_TIERS`; long-run ladders in `_MARATHON_LONG_KM` / `_HALF_LONG_KM`.
  - `runsphera/plans/daniels.py` — reused for pace calibration and structure builders (`_paces_for_vdot`, `_tempo_structure`, `_interval_structure`, `_structure_duration_s`, `_fmt_pace`).
  - `runsphera/plans/__init__.py` — registry entry (`available=True`, `supported_goals`, `variants`, `fixed_schedule=True`).
- **Templates**: `web/templates/plans_new.html` — the **Experience level** variant picker (one radio group per methodology with `variants`; JS reveals the selected methodology's group) and the goal allow-list (`data-supported-goals`). `web/templates/base.html` — a `.pick-grid.cols-3` rule for the tier grid.
- **Routes**: `POST /plans/new` reads a new `variant` form field and threads it to `create_plan`.
- **DB**: new nullable column `plans.variant` (migration in `db.py`). NULL ⇒ the engine's default tier (Novice 1).
- **External services**: none directly; workouts flow into the existing Garmin-push path unchanged (cross-training days are in `garmin_sync._NOT_PUSHABLE`, so they're skipped).

### The generic `variant` plumbing

Higdon's identity is the tier, and no methodology before it needed a sub-selection. Rather than special-case Higdon, a small **methodology-agnostic** mechanism was added so future methodologies can reuse it:

- `MethodologyInfo.variants: list[(id, label, short_desc)]` — surfaced as the picker. Empty ⇒ no picker.
- `MethodologyInfo.supported_goals: list[str]` — goal allow-list. Empty ⇒ all goals. (`force_goal` remains the single-goal special case.)
- `PlanParams.variant: str | None` — the chosen tier, threaded through `create_plan` → persisted to `plans.variant` → re-read by `reshape_plan` so a reshape regenerates in the **same** tier.
- **Server-side validation** in `create_plan`: `variant` must be one of the methodology's declared `variants` (missing → the first declared tier, so the persisted label always matches the generated plan; methodologies without variants never persist one), and `goal_type` must be in `supported_goals` when declared — the form's JS pickers can be bypassed, so the allow-lists are enforced where it counts. The engine additionally rejects unknown tier values (`None` still falls back to Novice 1 for legacy rows). A lock-down test asserts the registry's variant list and the engine's `_TIERS` stay in sync.

### Data flow

`PlanParams` (goal, race date, target time, VDOT, baseline, **variant**) → `generate()`:

1. **Tier.** `_tier_for(params.variant)` selects a `_Tier` (default Novice 1). The tier holds the weekly **template** (`position → role`, position 0 = long-run day = race weekday), weekday distances, which quality roles appear, and how many long runs get flattened to the peak / carry a marathon-pace finish.
2. **Paces.** `daniels._paces_for_vdot(current_vdot)` yields the E/M/T/I/R table. Zone map: easy/long/run → **E**; marathon-pace run → **M** (marathon) / half-pace run → **T** (half, since HM pace ≈ threshold); tempo → **T**; hills/speed → **I**; cross → none.
3. **Long-run ladder.** A shared per-distance ladder (`_MARATHON_LONG_KM`, `_HALF_LONG_KM`) — a gentle ramp with a step-back every ~3rd week, the 32 km peak, and a short taper. On **marathon** plans, Intermediate/Advanced raise the biggest `flatten_top` long runs onto the peak (their two/three 20-milers); half plans keep the plain ladder — Higdon's half schedules peak once.
4. **Window fitting.** `_effective_weeks()` counts Monday-aligned weeks to the race; under the full length the plan drops opening base weeks (frame week indices stay anchored to the race so the peak/MP weeks keep their distance-to-race), and under the floor `generate()` raises.
5. **Assembly.** For each day, the template position resolves a role → a workout builder produces `(workout_type, title, description, distance, pace, structure)`. Marathon-pace-finish long runs carry the two-step zone-tagged `E`→`M` structure (same shape as Daniels' peak long run and Pfitzinger's MP long run). Race week strips quality to easy freshening runs; the race overlays the final long-run slot.
6. **Recalibration-safe by construction.** Titles fit `service._zone_for_workout`'s vocabulary ("Marathon-pace run" → M; "Half-pace run"/"Tempo run" → T; "Hill repeats"/"Speed" → I) and descriptions use the recognised `(Z, X:XX/km)` / parenthesised-easy idioms, so pace recalibration, the soft-swap, and Garmin push all work end-to-end. Locked down in `tests/test_description_refresh.py`.

## Configuration

- **Experience tier** (required for Higdon) — the `variant` picker; persisted to `plans.variant`.
- **Goal** — Half marathon or Marathon only.
- **Race date** (required) — anchors the window; the race lands on the final long-run slot.
- **Target time** (optional) — sets race-day target pace.
- **VDOT** — read from `training_status` at creation; drives all paces; editable + recalibratable per the existing flow.
- Plan lengths (18 / 12), floors (12 / 8), long-run ladders, and the per-tier profiles are constants at the top of `higdon.py`.

## Known limitations

- **Framework, not the published tables.** Distances are engine-generated in Higdon's *shape* (metricised, VDOT-calibrated), not copied week-for-week from halhigdon.com. Long-run progressions will differ from the printed plan in the exact numbers.
- **Fixed weekly patterns.** Each tier owns its schedule; the day pickers are ignored (`fixed_schedule=True`). There's no "Novice 1 but on Saturdays" variant beyond the race-weekday anchor.
- **Paces attached even though Novice is effort-only.** By design (so Garmin push / adherence / recalibration work), a Novice 1 run still carries an E pace under the hood. The card copy leads with effort, but the number is there if you look.
- **Half long runs stay plain.** Goal-pace work in the half lives in the dedicated pace run (at T), not in the long run — this sidesteps the marathon-pace (M) vs half-pace (T) zone mismatch on long-run structures.
- **Reshape of a full-length plan.** Like Pfitzinger, moving the race date on an already-full-length plan is refused when it would shift week 1's Monday (create a new plan instead). Reshaping within a stable start week regenerates in the same tier.
- **Two distances only.** Higdon also publishes 5K/10K/8K and multi-race plans; only half + marathon are implemented. The tier/ladder structure extends to them by adding distances to the ladders + floors.

## Verification

1. `.venv/Scripts/python.exe tests/test_higdon.py` and `tests/test_description_refresh.py` (also under `pytest tests/`).
2. `/plans/new` → **Hal Higdon**: confirm the **Experience level** picker appears, the goal picker offers only Half + Marathon, and the day pickers grey out.
3. Generate a **Novice 1 marathon**: 18 weeks; Tue/Wed/Thu easy + one long run + a cross-training day + rest; **no** tempo/intervals; long run peaking at 32 km; taper in the final two weeks; the marathon on the final week. Cards read as effort but each run has a pace.
4. Generate an **Advanced 2 marathon** (six run days, 800 m speed + tempo + goal-pace, three 20-milers) and a **Novice 2 half** (12 weeks). 
5. Open a marathon-pace run and a hill/speed session → confirm structured steps and "Push to watch"; confirm a cross-training day shows no push.
6. Recalibrate paces → easy/long stay E, marathon-pace runs → M, half-pace/tempo → T, hills/speed → I, race day untouched.
7. Reshape the plan within a stable start week → confirm it regenerates in the same tier (variant persisted).

## Future improvements

- **More distances** — Higdon's 5K / 10K / 8K and "multiple race" plans; add ladders + floors on the same engine.
- **Honor the tier's real weekday layout** — offer the runner a choice of long-run weekday beyond the race-weekday anchor.
- **Share plan plumbing with Daniels/Pfitzinger** — the race-day overlay, dict→PlannedWorkout assembly, and the E+M two-step structure builder are near-duplicates across the three engines; promote them to a shared module.

---

*Last updated: 2026-07-17*
