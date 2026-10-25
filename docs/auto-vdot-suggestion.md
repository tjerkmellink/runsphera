# Auto-VDOT suggestion

> When the runner races a parkrun, 5k tempo, or any standard-distance hard effort, the dashboard offers a one-click recalibration of the plan's VDOT — keeping target paces honest as fitness changes.

## Purpose

The plan's `vdot_at_start` drives every workout's target pace (easy, tempo, intervals, long). When fitness improves, those paces become too soft — the runner overshoots them effortlessly, the plan stops challenging, the prediction widget on the countdown card drifts pessimistic. The classic fix is to manually update VDOT via Settings → Plan → Recalibrate paces, but most runners don't remember to do that on a Tuesday.

The auto-VDOT detector watches for race-pace efforts in the runner's actual activity stream. When one lands that implies a meaningfully different VDOT than the plan is calibrated against, the dashboard surfaces a single non-intrusive banner with two buttons:

- **Apply to plan** — updates `vdot_at_start`, re-runs `recalibrate_paces` (rewrites every future workout's target pace), best-effort re-pushes any previously-pushed Garmin workouts.
- **Dismiss** — won't re-suggest off the same activity.

Closes the loop on "did I get fitter? does the plan know?" without nagging.

## How it works (user view)

### When the banner appears

The runner sees the banner on the dashboard (just above the Today's-workout flagship) when **all** of these hold:

- An active plan exists with `vdot_at_start` set
- A running activity in the last **28 days** has:
  - Distance matching a standard race distance (5k / 10k / 15k / half-marathon / marathon) within tolerance
  - Either ≥ 60% of activity time in HR Zone 4–5, OR an activity name containing a race keyword (`race`, `parkrun`, `wedstrijd`, `time trial`, `tt`, etc.)
- The implied VDOT (back-derived from distance + duration via Daniels' formula) is **at least 1.0 above** the plan's current `vdot_at_start`
- That activity hasn't been dismissed or already applied

Negative deltas are deliberately excluded — a slow run with high HR isn't a credible fitness-*decline* signal off a single activity. The plan-settings UI still allows manual downgrade.

Only **one** suggestion shows at a time (the most recent qualifying activity), to avoid a queue of nags.

### What the runner sees

```
🔔 FITNESS SIGNAL
Your 5K on sun 8 jun 2026 — 22:18 · avg HR 175 — implies
VDOT 46, a +3.0 bump from your plan's 43.
Apply to recalibrate your plan paces?

  [ Apply to plan ]  [ Dismiss ]
```

Clicking **Apply to plan** triggers the same path as Settings → Plan → Recalibrate paces:

1. `plans.vdot_at_start` updated to the implied value
2. `recalibrate_paces` rewrites every future workout's `target_pace_s_per_km`
3. Any previously-pushed Garmin workouts get a best-effort re-push (same as the manual flow)
4. The today's-coach LLM cache invalidates so the next render picks up the new pace context
5. Activity is marked `vdot_suggestion_applied_at` — won't be re-suggested

Clicking **Dismiss** records `vdot_suggestion_dismissed_at` on the activity. Same effect for the detector as applied.

## How it works (implementation)

### Modules

- **`runsphera/plans/vdot_detection.py`** — `detect_vdot_suggestion(conn)` returns the suggestion payload or None. Private helpers `_match_distance` (canonical-distance lookup with tolerance), `_has_race_keyword`, `_high_hr_fraction`, `_is_race_effort`. Public mutators `mark_applied` / `mark_dismissed` flip the per-activity state.
- **`runsphera/plans/service.py`** — reuses the existing `estimate_vdot_from_race(distance_m, time_s)`, `update_plan_vdot`, and `recalibrate_paces` machinery.
- **`runsphera/web/app.py`** — dashboard `index()` route adds `vdot_suggestion` to the context. `POST /plan/vdot/apply/{activity_id}` and `POST /plan/vdot/dismiss/{activity_id}` are the two new routes.

### Templates

- **`index.html`** — banner block rendered between the coach hero and the today's-workout flagship.

### Routes

| Method | Path | Purpose |
| ------ | ---- | ------- |
| `POST` | `/plan/vdot/apply/{activity_id}` | Re-derives the suggestion server-side (avoids races / tampering), calls `update_plan_vdot` + `recalibrate_paces`, marks the activity applied, redirects to `/?vdot=applied&new_vdot=X&n_updated=Y`. |
| `POST` | `/plan/vdot/dismiss/{activity_id}` | Marks `vdot_suggestion_dismissed_at` on the activity, redirects to `/?vdot=dismissed`. |

### DB

Two columns added to `activities`:

- `vdot_suggestion_dismissed_at TEXT` — runner clicked Dismiss
- `vdot_suggestion_applied_at TEXT` — runner clicked Apply

Both nullable. Once either is set, the detector skips this activity forever.

### Heuristic constants

All live at the top of `vdot_detection.py`:

```python
_SCAN_DAYS = 28                       # how far back to look
_HIGH_HR_FRACTION_MIN = 0.60          # 60% of time in Z4+ = race effort
_MIN_VDOT_DELTA = 1.0                 # below this = not actionable
_RACE_DISTANCES = ((..., target, tol), ...)
_RACE_KEYWORDS = (... 'race', 'parkrun', 'wedstrijd', ...)
```

### Data flow

1. **Every dashboard render** — `detect_vdot_suggestion(conn)` runs. Single indexed query against `activities`; iterates in newest-first order; early-exits on the first qualifying activity.
2. **Apply click** — re-derive the suggestion (avoids stale form data), update VDOT, recalibrate paces, mark applied. All in one transaction. Redirect back to dashboard with success params for a future banner (banner UI not yet added; `?vdot=applied` is the hook).
3. **Dismiss click** — single UPDATE, redirect.

No background workers. The detector cost is one indexed range query per page render — negligible.

## Configuration

Nothing user-configurable yet. The five constants in `vdot_detection.py` can be tuned by an operator if the suggestions feel too eager or too quiet:

- Loosen `_HIGH_HR_FRACTION_MIN` → more borderline efforts qualify
- Tighten `_MIN_VDOT_DELTA` (e.g. 0.5) → smaller bumps surface
- Widen `_SCAN_DAYS` → older efforts can trigger

## Known limitations

- **Single-activity calibration.** A great parkrun day could bump VDOT once and turn out to have been a one-off (cool weather, downhill course, fresh legs). The runner can dismiss or manually downgrade later if it doesn't stick. No multi-effort smoothing yet.
- **Negative-delta blind spot.** Fitness decline (injury, illness, layoff) isn't auto-detected. By design — single-activity decline signals are too noisy. Manual downgrade via plan settings remains the path.
- **HR-zone data dependence.** Activities synced from older Garmin firmware or third-party uploads sometimes lack `hr_zone_*_s` values. In that case the high-HR check fails and the suggestion needs a race-keyword in the activity name. Most parkruns are auto-named "Parkrun" so this works in practice; a generic-named hard tempo without HR-zone data would slip through.
- **Whole-activity scope.** If a runner does an interval workout that includes a 5km block at race pace, the average duration over 5km might not be racing-hard. We don't sub-segment.
- **No success banner yet.** After Apply, the dashboard redirects with `?vdot=applied` query params, but no toast/banner picks them up. Add a small "VDOT updated 43 → 46 · N workouts recalibrated" line on next render.

## Verification

1. **Manual smoke**: run `python -c "from runsphera.plans import vdot_detection as v; from runsphera.db import connect; from contextlib import closing; print(v.detect_vdot_suggestion(connect()))"`. With no qualifying activity, prints `None`. With one, prints the payload.
2. **Banner appears**: trigger a fake suggestion by manually crafting one in the DB (`UPDATE activities SET activity_name = 'Test 5K race', distance_m = 5000, duration_s = 1200 WHERE activity_id = …`), then open `/`. The banner should render above the Today's Workout section.
3. **Apply round-trip**: click Apply → `/plans/<id>/edit` should now show the new VDOT; dashboard's countdown card prediction should update on next render; `vdot_suggestion_applied_at` should be set on the activity.
4. **Dismiss persistence**: click Dismiss → banner disappears, never re-shows for that activity even on hard refresh.

## Future improvements

- **Multi-effort smoothing** — require N qualifying efforts in a window (say 2 in 21 days) before suggesting, to dampen one-off PR days. Or weight by recency.
- **Decline detection** — separate logic for sustained slow-pace + high-HR runs over multiple sessions (illness signal, overtraining). Surface as a "consider easing" suggestion rather than a VDOT downgrade.
- **Success banner after Apply** — pick up the `?vdot=applied&new_vdot=…&n_updated=…` query params and render a small confirmation line at the top of the dashboard for one render.
- **Implied-from-race-segment** — for structured workouts (e.g. 5×1km), extract the race-pace block timing from `activity_laps` instead of whole-activity averages. Catches workouts that contain a race-pace effort but average out slower.
- **Coach voice ties in** — when a suggestion lands, the daily coach line should mention it ("you absolutely cooked that parkrun — bump the VDOT and let's see what's next").

---

*Last updated: 2026-06-13*
