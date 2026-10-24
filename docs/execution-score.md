# Execution score

> Composite 0–100 score on every completed plan workout — "how well did you execute the prescription?" — rendered as a colored corner ring on the day-cell and the workout modal.

## Purpose

The plans page already shows whether a workout was *done* (status pill, actual stats under the target). What it doesn't show, at a glance, is **how well**. A 6 km tempo executed at 5:00/km vs target 4:59/km is essentially perfect; an "easy" run that drifts into Z4 for half the duration was something else. Both currently look identical on the plan grid — both are just "✓ done." The execution score surfaces the gap between *prescription* and *execution* in a single visual unit you can scan across the week.

## How it works (user view)

### Where it appears

- **Plans page day cells** — a small (~26 px) score ring in the top-right corner of every done workout in the [_week_card.html](../running_coach/web/templates/_week_card.html). Hover for a tooltip with the per-component breakdown.
- **Plan-workout modal** — larger (~52 px) ring in the header alongside the title pills, so the runner sees the score the moment they tap into a session.

### What the colors mean

| Range | Color | Reading |
|---|---|---|
| 85–100 | Green | Nailed it — the session was executed as prescribed. |
| 60–84 | Amber | Mostly there, with a noticeable miss on one component. |
| 0–59 | Red | The session that was executed isn't the session that was prescribed. |

### What the score is composed of

Three sub-scores 0–100 combined with weights that vary by workout type:

- **Pace adherence**: actual pace vs target pace. For structured workouts (tempo / intervals) this uses the *active-block-only* pace (extracted from per-km lap data via [`laps.active_block_summary`](../running_coach/laps.py)), so warmup + cooldown don't drag the comparison. For unstructured runs (easy / long / recovery) it uses the total-run average.
- **Distance adherence**: `actual_km / target_km`, with a grace band 95–110 % (no penalty), a sharp falloff below 95 % (cutting a run short matters), and a linear falloff from 110 % to 150 % (overshooting burns reserves for the rest of the week, so it isn't free either).
- **HR-zone discipline**: percentage of duration spent in the *right* zones for the workout type — easy/recovery rewards Z1–Z2 (with Z3 counted as still-aerobic for easy/long, since amateur HR-zone calibration tends to be conservative), tempo rewards Z3–Z4, intervals rewards Z4–Z5.

If a sub-score can't be computed (no HR data, no target distance, etc.), it's skipped and the remaining sub-scores are re-weighted so the headline number stays meaningful.

### What doesn't get scored

- Rest / cross days — no prescription to score against.
- Workouts without a matched activity (planned days that haven't been run yet, or runs that didn't auto-match).
- Workouts where both target pace and target distance are missing.

## How it works (implementation)

### Modules

- [running_coach/execution_score.py](../running_coach/execution_score.py)
  - `compute(conn, planned, activity)` → `{score, pace_score, distance_score, hr_score, color}` or `None`.
  - Internal sub-score functions `_pace_score`, `_distance_score`, `_hr_score`, plus `_color_for`.
  - All tunables (`_PACE_TOLERANCE_S_PER_KM`, `_WEIGHTS`, `_HR_GOOD_ZONES`) live at the top of the file — adjust them and re-run [tests/test_execution_score.py](../tests/test_execution_score.py).

### Templates

- [_exec_score_ring.html](../running_coach/web/templates/_exec_score_ring.html) — SVG circular-progress badge. Theme-agnostic; included from both Tempo and base layouts (today only Tempo wires it; base falls through to the existing flat layout).
- [_week_card.html](../running_coach/web/templates/_week_card.html) — adds the small ring to each `tp-plan-day` cell.
- [_plan_workout_modal.html](../running_coach/web/templates/_plan_workout_modal.html) — adds the larger ring to the modal header.

### Data path

```
plans/service.get_plan_workouts(plan_id)
    └── JOINs activities, pulls HR-zone columns
        └── for each row, runs execution_score.compute(conn, planned, activity)
            └── attaches `execution_score` dict (or None) to the workout

web/app.plan_workout_modal(pw_id)   # separate route, modal partial
    └── refetches the row + HR-zone columns
        └── same execution_score.compute() call
```

Scores are computed at request time — no caching, no DB column. The math is cheap (a few arithmetic ops + one `active_block_summary` query for structured workouts) and recomputing keeps the score in sync with any lap/activity edits without an invalidation layer.

### Score → color mapping

```python
≥ 85 → green
≥ 60 → amber
otherwise → red
```

In light mode the text inside the ring uses a darker shade of the band color for readability; in dark mode it brightens. See the `.exec-score-num.is-*` rules in [base.html](../running_coach/web/templates/base.html).

## Configuration

| What | Where | Notes |
|---|---|---|
| Pace tolerance bands | `_PACE_TOLERANCE_S_PER_KM` in `execution_score.py` | Per workout type. `under` = ran faster than target; `over` = ran slower. |
| Sub-score weights | `_WEIGHTS` | Per workout type. Tempo/intervals weight pace heaviest; easy/long weight distance heaviest. |
| HR-zone reward sets | `_HR_GOOD_ZONES` | Which zones count as "right" per workout type. |
| Color thresholds | `_color_for` | Green/amber/red cutoffs at 85 and 60. |

## Known limitations

- **No score for runs without a matched plan workout.** The dashboard's recent-runs table and the standalone run-detail modal don't show the ring today — only sessions tied to a plan get scored, because the prescription side of the comparison comes from the plan row.
- **Stale targets aren't healed.** If a plan was recalibrated *after* a workout was completed, the activity row keeps its older `target_pace_s_per_km` snapshot and the score reflects adherence to the old target, not the current one. That's the honest read of what was prescribed at the time, but it can look odd after the table changes (the user ran what we now call the right pace, but against an old number it scores low).
- **HR zones are Garmin's defaults.** We don't recalibrate against the runner's actual LTHR or HRR; the score uses whatever zones Garmin assigned. Amateur runners with conservative defaults can see Z3 drift on what feels like an easy run — that's why `easy` counts Z3 as still-aerobic. If we add per-runner zone calibration later, the rules pick that up automatically.
- **No "perceived effort" axis.** The score is data-driven (pace / distance / HR). Garmin's `directWorkoutFeel` and `directWorkoutRpe` are surfaced elsewhere but not folded in — adding them is straightforward but they're often unfilled.
- **Single-segment workouts only.** Intervals with multiple ACTIVE segments are averaged together for the pace component — a workout that nailed reps 1–4 and blew up reps 5–6 scores the same as one that was uniformly mid-effort across all six. The lap chart shows the detail; the score doesn't.

## Verification

1. **Score appears on the plans page.** Open `/plans`. Each week card's day cells should show a colored ring in the top-right corner for every completed workout. Rest days, missed days, and future days have no ring.
2. **Tempo session lights green.** Today's tempo (3 km @ T-pace inside a 6 km total) should score in the 90s — pace match was tight, distance was on, HR was mostly in T-zone.
3. **Easy run with Z4 drift lands amber.** An "easy" run where the runner pushed into Z4 for a meaningful chunk scores in the 60s–70s — pace and distance fine, HR pulled the composite down.
4. **Modal shows the larger ring.** Click a completed day cell. The plan-workout modal opens with a 52 px ring in the header next to the title pills. Hover the ring → tooltip lists pace / distance / HR sub-scores.
5. **Rest days have no ring.** Verify a rest day cell renders without any score badge — `compute()` returns `None` for `workout_type in ('rest', 'cross')`.
6. **Unmatched-but-past workouts have no ring.** A missed day (planned in the past, no matched activity) shows no ring — same `None` return.

## Future improvements

- **Score on the dashboard's "Today" flagship** when today is done. Same partial, larger size (64 px), placed alongside the workout title.
- **Score history chart** on the plan-hero: a sparkline of weekly average execution scores, so the runner sees consistency trends, not just per-session reads.
- **Recent-runs row indicator** — even for runs not tied to a plan, surface a small ring derived from "did this run fit *some* category cleanly" (e.g. was the easy run actually easy?). Needs a heuristic for what category an unplanned run was *trying* to be.
- **Hover breakdown popover** — replace the bare title-tooltip with a small popover showing each sub-score as its own mini-bar, plus the workout-type-specific weighting.
- **Per-segment scoring for intervals** — instead of averaging all ACTIVE segments together for the pace component, score each rep against target and report the worst (the "bonk lap") alongside the average.
- **Surface in LLM coach context** — feed the score breakdown into the run-reaction prompt so the coach can lead with the headline ("solid 82 — pace was on, but HR drifted late") instead of paraphrasing what the runner can already see.

---

*Last updated: 2026-05-30*
