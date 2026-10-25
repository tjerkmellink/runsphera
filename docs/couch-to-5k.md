# Couch to 5K

> The classic 9-week run/walk on-ramp for absolute beginners — from 8×1-minute runs to a continuous 30-minute (~5 km) graduation run. Time-based, paceless, injury-cautious.

## Purpose

Before this engine, the app's most beginner-friendly path was Higdon Novice 1 — which already assumes you can run continuously. A true first-time runner (or a returner after a long layoff) had nowhere to start, and the goal grid didn't even offer 5 km. Couch to 5K is the globally recognised answer: three run/walk sessions a week whose walk breaks do the tendon-conditioning a new runner's body needs, graduating at 30 minutes of continuous running.

## How it works (user view)

- `/plans/new` → goal **5 km race** → methodology **Couch to 5K** (the tile carries a "Beginner · 5K" badge). The gallery is goal-filtered, so the tile only appears while 5 km is the selected distance; picking it snaps days-per-week to 3, and the runner picks *which* three days and marks the "long run" day — that's where the week's biggest session (and eventually the graduation run) lives. The default day picks are seeded **two days apart** (Wed/Fri/Sun for a Sunday anchor, via `PREFERRED_DAY_OFFSETS` = engine fallback) so a beginner never runs back-to-back — C25K's cardinal rule — instead of the generic Daniels 3-day pattern, which would put an easy run the day before the long run.
- **Race date is optional.** Without one, the plan runs 9 weeks from the start week and the graduation day is synthesized on the final week's long-run day. With one, the plan anchors so week 9 is race week (starting later than the chosen start week when the race is further out). A race **closer than 9 weeks is refused** — the gentle opening weeks are the point.
- Weekly cards show time-based sessions ("Run/walk 8×(1 min run / 90 s walk)", "Run 25 min") with effort cues instead of paces. No distances are shown — a beginner's pace is unknown, so the app doesn't fake them. The plan hero shows **"Pacing — by effort"** instead of a VDOT number (a "calibrated to VDOT" claim would be meaningless here).
- The workout modal's **Steps** strip renders the run/walk blocks as durations ("WU 5:00 → 8× 1:00 + 1:30 recovery → CD 5:00"), and **Manual edit** shows a time-based form (warm-up walk / reps / run time / recovery walk / cool-down walk — no distance or pace fields). Edits stay paceless by construction: the rebuilt structure is duration-only and no pace/distance target is ever written. The uneven "ladder" sessions of weeks 3–6 can't be represented by a reps form and say so instead of guessing.
- The plan-settings modal hides **Recalibrate paces** and **Set VDOT** (nothing to calibrate), and the coach's workout-swap softening declines politely — a week-2 run/walk session is already the gentlest shape there is.

### The programme (NHS canonical)

Every session = 5-min brisk warmup walk + main block + 5-min cooldown walk.

| Week | Sessions (×3 unless noted) | Phase |
|------|----------------------------|-------|
| 1 | 8 × (60 s run / 90 s walk) | base |
| 2 | 6 × (90 s run / 2 min walk) | base |
| 3 | 2 × (90 s run, 90 s walk, 3 min run, 3 min walk) | base |
| 4 | runs of 3-5-3-5 min with 90 s / 2½ min walks | build |
| 5 | S1: 3×5 min runs · S2: 2×8 min runs · S3: **20 min continuous** | build |
| 6 | S1: 5-8-5 min runs · S2: 2×10 min runs · S3: **25 min continuous** | build |
| 7 | 25 min continuous | peak |
| 8 | 28 min continuous | peak |
| 9 | 30 min continuous — S3 = **graduation run (~5 km)** / race day | taper |

## How it works (implementation)

- **Modules**: `runsphera/plans/c25k.py` (engine — programme table + generator), `runsphera/plans/__init__.py` (registry entry `c25k`), `runsphera/plans/methodology.py` (`uses_vdot_paces`, `fixed_days_per_week` fields).
- **Templates**: `plans_new.html` (5K goal tile, `data-fixed-dpw` days-per-week lock), `_plan_settings_modal.html` (recalibrate/VDOT sections hidden via `uses_vdot_paces`).
- **Routes**: none new — everything flows through `POST /plans/new`.
- **DB**: none new.
- **External services**: Garmin push works unchanged — sessions are time-based steps with no pace targets (`{"end": {"duration_s": N}}`, repeat groups), the exact shapes the Foppen engine already pushes.

Data flow: the registry entry declares `force_goal="5k"`, `fixed_days_per_week=3`, `uses_vdot_paces=False`, `fixed_schedule=False`. The engine honours the runner's three picked days; **session 3 pins to `long_run_day`** — load-bearing, because `create_plan` synthesizes the goal date on the final week's long-run day and the race overlay must land on the graduation slot. In the final week session 3 follows the race weekday if a booked race sits elsewhere.

### The paceless contract

Two layers keep recalibration away from this plan:
1. `uses_vdot_paces=False` → `service._require_vdot_paces` refuses `preview_recalibrate_paces` / `recalibrate_paces` / `apply_workout_swap`, the settings modal hides the sections, and the auto-VDOT dashboard banner never surfaces (also fixed for Foppen).
2. Defence in depth: no workout carries `target_pace_s_per_km` or `target_distance_km`, no `pace_s_per_km` keys exist in structures, and no `X:XX/km` idioms appear in any title or description — so even a forced description-refresh is a structural no-op. Locked by `tests/test_c25k.py::test_everything_is_paceless`.

## Configuration

Nothing to configure. Days-per-week is fixed at 3 (form-locked and server-validated); training days and the long-run day are the runner's choice.

## Known limitations

- **Weekly `total_km` shows 0** on plan cards (no distances by design — Foppen precedent).
- **Moving the race date** usually shifts the anchored start week, which the reshape splice guard refuses; create a new plan instead.
- **No variants** (no "Couch to 10K" continuation, no repeat-a-week mechanic when a week proves too hard — the honest manual workaround is creating a new plan starting at the failed week).
- Execution scores stay empty (no pace/distance targets to score against); adherence counts sessions normally.
- Hero art is a programmatic placeholder in the house risograph style — regenerate with the prompt in `docs/methodology-hero-images-brief.md` for a hand-made look.

## Verification

1. `.venv/Scripts/python.exe tests/test_c25k.py` — 14 lockdowns — and `tests/test_workout_edit_timebased.py` for the paceless manual-edit path.
2. `/plans/new` → pick 5 km + Couch to 5K → days-per-week snaps to 3 → generate. Expect 9 weeks, week 1 card "Run/walk 8×(1 min run / 90 s walk)", no paces anywhere, race-day card on the final long-run day.
3. Open a week-1 session: Steps read "WU 5:00 → 8× 1:00 + 1:30 recovery → CD 5:00"; Manual edit shows time fields (5:00 / 8 / 1:00 / 1:30 / 5:00) and no pace/distance inputs. Save a change → title and steps update, still paceless.
4. Plan settings modal: no Recalibrate / Set VDOT sections; plan hero shows "Pacing — by effort" instead of a VDOT stat.
4. Push week 1 to Garmin: lands as a repeat workout (8 × 1 min interval / 90 s recovery) with warmup/cooldown, no pace targets.

## Future improvements

- A "repeat this week" action for runners who need more time at a step (the programme's own advice).
- Couch-to-10K continuation as a follow-up plan suggestion after graduation.
- Auto-suggest creating a Daniels/Higdon 5K plan once a graduation run is completed.

---

*Last updated: 2026-07-18*
