# Pfitzinger 18/55 — Marathon

> An 18-week, ~55-mile-peak marathon build in Pete Pfitzinger's methodology, calibrated to your VDOT. Medium-long runs, lactate-threshold tempos, marathon-pace long runs, and tune-up races.

## Purpose

Gives the app a true **marathon** engine to sit alongside Daniels (all-distance, pace-zone) and Foppen (race-specific 15 km). Pfitzinger's *Advanced Marathoning* is a gold-standard marathon methodology; the "18/55" is its most accessible plan — 18 weeks peaking near 55 miles (~88 km) per week. The payoff for the runner: a structured, progression-driven marathon plan whose signature mid-week **medium-long run** and **lactate-threshold** work build the specific fatigue-resistance a marathon demands, with every pace anchored to their own fitness.

It is a **methodology engine**, not a transcription of the book's copyrighted week-by-week schedule. It reproduces Pfitzinger's documented *framework* — the four mesocycles, his workout vocabulary, the 18-week / ~88 km-peak shape — and generates the concrete week-by-week prescriptions itself, scaled to the runner. This mirrors how the Daniels engine implements Daniels' *method* (plus a cited pace table) rather than copying his sample schedules.

## How it works (user view)

At **`/plans/new`**, pick the **Pfitzinger 18/55 — Marathon** methodology. Because it declares `force_goal="marathon"`, the goal picker locks to Marathon automatically, and because it declares `fixed_schedule=True` the days-per-week / training-day pickers are visibly neutralised — this plan owns its own 5-day/week schedule anchored to the race weekday, and the plans row records the schedule the engine actually generated.

Set a **race date** and (optionally) a target time. With the race **18+ weeks out** you get the full build; **12–17 weeks out** the plan compresses by dropping opening endurance weeks (nothing is ever back-dated into the past); under 12 weeks the form explains there is no honest 18/55 build left.

The full 18-week plan, rendered on the plan-detail page like any other:

- **Weeks 1–6 — Endurance (base badge):** general-aerobic runs, the mid-week medium-long run, recovery runs, a weekend long run. Lactate-threshold tempos enter around week 3.
- **Weeks 7–11 — Lactate threshold + endurance (build badge):** a weekly LT tempo, growing medium-long and long runs up to the signature **32 km**; week 11's long run rehearses marathon pace (~50% at MP).
- **Weeks 12–15 — Race preparation (peak badge):** VO₂max intervals, marathon-pace long runs with a growing MP block (**~60% → ~70%**, up to ~20 km at MP), and **2 tune-up races** (weeks 12 & 14) — raced the day *before* a shortened long run, book-style.
- **Weeks 16–18 — Taper (taper badge):** volume sheds to ~80% then ~58% of peak; sharpening is short VO₂max touches only (no threshold work). Week 18 is race week — short freshening runs and the **marathon** on the final long-run slot.

Every workout carries a target pace derived from your VDOT, a description, and (for tempos/intervals/MP long runs) a structured step list that can be pushed to Garmin.

## How it works (implementation)

- **Modules**
  - `runsphera/plans/pfitzinger.py` — the engine. `class Pfitzinger18_55(Methodology)` with `total_weeks()` (always 18) and `generate()`.
  - `runsphera/plans/daniels.py` — reused for pace calibration and structure builders (`_paces_for_vdot`, `_tempo_structure`, `_interval_structure`, `_structure_duration_s`, formatters).
  - `runsphera/plans/__init__.py` — registry entry (`available=True`, `force_goal="marathon"`).
- **Templates / Routes / DB:** none new. Reuses the existing plan-creation form, plan-detail rendering, `plans` / `plan_workouts` tables, and all downstream machinery (adherence, recalibration, swap, Garmin push).
- **External services:** none directly; workouts flow into the existing Garmin-push path unchanged.

### Data flow

`PlanParams` (goal, race date, target time, VDOT, weekly-km baseline) → `generate()`:

1. **Paces.** `daniels._paces_for_vdot(current_vdot)` yields the E/M/T/I/R table. Pfitzinger's effort prescriptions map onto it directly:

   | Pfitzinger workout | Effort reference | Daniels zone | App `workout_type` |
   |---|---|---|---|
   | Recovery | slower than easy | E | `recovery` |
   | General aerobic | easy/steady | E | `easy` |
   | Medium-long run | endurance | E | `long` (titled "Medium-long") |
   | Long run | endurance | E | `long` |
   | Marathon-pace long run | marathon pace | E + **M** | `long` (two-step E+M structure) |
   | Lactate threshold | 15K–half pace | **T** | `tempo` |
   | VO₂max | ~5K pace | **I** | `intervals` |
   | Tune-up race | race effort | (T guidance) | `race` |

2. **Phases.** `_PHASE_LAYOUT` = endurance 6 → lt_endurance 5 → race_prep 4 → taper 3 (= 18). Internal names map to the UI's `base/build/peak/taper` badges via `_BADGE`.

3. **Window fitting.** `_effective_weeks(race_date, start_date)` counts the Monday-aligned weeks available. Under 18, the plan drops opening **endurance** weeks (the sharpening phases are never trimmed) and week indices stay in the 18-week frame so tune-ups, MP runs, and the taper keep their distance-to-race anchoring. Under 12 (`_MIN_WEEKS`) `generate()` raises a friendly `ValueError`.

4. **Volume.** `_weekly_km(week_idx, baseline)` places each week on a baseline→peak line using the `_LOAD_POS` ladder (step-backs every ~3rd week). Peak ≈ 88 km (`_PEAK_KM`); the opening weeks are floored at 40 km (`_BASE_FLOOR_KM`) and the baseline is capped at the peak. **Taper weeks are a fraction of the peak** (`_TAPER_FRACS` = 80% / 58%) rather than a point on the baseline line, so even a 95 km/week runner sheds real volume. `_sizes()` splits each week across the session roles: the long run takes 38% (hitting the 32 km cap at peak volume — the signature 20-miler), medium-long capped at 24 km.

5. **Weekly template.** Anchored to the long-run day (= race weekday). Day roles are keyed by position `(day_of_week - long_run_day) % 7`: long / rest / quality / medium-long / recovery / general-aerobic+strides / rest. `_role_for()` resolves the quality slot and the weekend per phase; in tune-up weeks the race takes the day **before** the long run (which shortens to ~85%) and the GA day rests. Marathon-pace long runs cap at 29 km (`_MP_LONG_CAP_KM`) with the MP block growing 50% → 60% → 70% (`_MP_FRACTION`). Taper quality is short VO₂max only. VO₂max headline distances are derived from the structure (WU + reps + jog recoveries + CD) so cards, weekly totals, and the pushed workout agree.

6. **Race day.** The marathon overlays the final week's long-run slot (distance 42.195 km, pace from `target_time_s` if given). Race week's other days are hand-built freshening runs (`_race_week_day`).

7. **Baseline mismatch caution.** When the runner's 4-week base sits more than 12 km below the plan's week-1 volume, a "ramp conservatively" note is appended to **week 1's long run** description. The plan stays faithful to 18/55's prescribed volume rather than silently capping — the runner keeps control.

Because paces are plain VDOT zones and MP long runs reuse the same zone-tagged two-step structure as Daniels' peak long run, **pace recalibration, the soft-swap, and Garmin push all work end-to-end**. The recalibrator knows the engine's vocabulary: descriptions use the `(Z, X:XX/km)` idiom which `_refresh_description_paces` rewrites zone-correctly, the "Race-pace tune" tempo maps to M pace, and `race` rows (the marathon and both tune-ups) are never rezoned — their paces come from the goal time / race effort, not a zone.

## Configuration

- **Race date** (required) — anchors the 18-week window; the marathon lands here.
- **Target time** (optional) — sets race-day target pace.
- **VDOT** — read from `training_status` at creation (seeded into `plans.vdot_at_start`); drives all paces and is editable + recalibratable per the existing flow.
- **Weekly-km baseline** — 4-week running average; sets the ramp's starting volume and triggers the mismatch caution.
- Peak (88 km), base floor (40 km), long-run cap (32 km), and tune-up weeks (12, 14) are constants at the top of `pfitzinger.py`.

## Known limitations

- **Fixed 5-day pattern.** Like the Foppen plan, the schedule ignores the day pickers (they're neutralised in the form via `fixed_schedule=True`); there is no 4-day or 6-day variant yet. The persisted plans row records the engine's real schedule, not the picker values.
- **Faithful to 18/55's volume, not fitness-capped.** The peak targets ~88 km/week regardless of the runner's base; the mismatch note warns but doesn't cap. Lower-mileage runners should treat the numbers as aspirational and back off as needed. A fitness-scaled peak (Daniels-style multiplier) was considered and deliberately not chosen for v1. (A base *above* the peak is capped at the peak — that runner wants the 18/70.)
- **Tune-up races assume a real race exists.** Weeks 12 & 14 schedule `race`-type tune-ups (the day before the long run); if the runner has no race those weekends, the description tells them to run a solo time trial or move the day. They are not auto-linked to `race_events`. Since they're `race` rows, recalibration deliberately leaves their pace alone.
- **Only the 18/55 plan.** The 18/70, 18/85, and Faster Road Racing variants are not implemented. The engine is structured to grow into them (adjust `_PEAK_KM`, `_PHASE_LAYOUT`, and volume ladder). Short windows compress down to 12 weeks by trimming endurance.
- **`_derive_title` drift on manual edit.** Editing a VO₂max session in the workout modal re-derives its title as generic "Intervals N×M m" (loses the "VO₂max" label) — shared behavior with Daniels intervals, cosmetic only.

## Verification

1. Sync so `training_status` has a VDOT, then go to **`/plans/new`**.
2. Select the **Marathon** goal (the Pfitzinger tile only shows for it), then **Pfitzinger 18/55 — Marathon**; confirm the day pickers grey out with the fixed-schedule note.
3. Set a race date ≥ 18 weeks out and a target time; **Generate plan**. (With a 12–17-week race date, confirm the plan compresses — fewer base weeks, nothing dated in the past.)
4. On the plan-detail page confirm: 18 weeks; base×6 → build×5 → peak×4 → taper×3 badges; a medium-long **and** a long run each week; LT tempos from ~week 3; a 32 km long run near the peak; VO₂max intervals in weeks 12–15; tune-up races in weeks 12 & 14 with a long run the day after; marathon-pace long runs whose M-block grows toward ~20 km; taper with VO₂max touches only; the marathon on the final week.
5. Open a lactate-threshold day and a marathon-pace long run — confirm the structured steps and that "Push to watch" is offered.
6. Recalibrate paces: confirm tune-up races and the race-week "Race-pace tune" keep their intent (no zone flips), and quality-workout descriptions still show the right zone paces.

Automated lock-down: `.venv/Scripts/python.exe tests/test_pfitzinger.py` (also runs under `pytest tests/`).

## Future improvements

- **More Pfitzinger plans** — 18/70 & 18/85 (higher volume) and *Faster Road Racing* (8K–half). Mostly new constants + ladders on the same engine.
- **Honor days-per-week** — offer a 4-day or 6-day variant by adding/removing the recovery/GA slots.
- **Link tune-ups to the event calendar** — surface nearby `race_events` for the tune-up weekends.
- **Share plan plumbing with Daniels** — the race-day overlay, dict→PlannedWorkout assembly, and E+M structure builder are near-duplicates of daniels.py internals; promote them to a shared module before the next methodology lands.

---

*Last updated: 2026-07-11*
