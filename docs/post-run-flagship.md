# Post-run flagship card

> Once today's run is synced and matched to the plan, the dashboard's "Today" flagship stops showing the prescription and flips to a post-run summary — actual distance / pace / time / HR, with the original target demoted to a subline.

## Purpose

The dashboard hero (Tempo: `tp-flagship`; Base: `today-card`) is the first thing the runner sees. Before today's session it answers *"what am I doing today?"*. But it used to keep answering that **after** the run too — still reading "Today · Easy 9 km" with the target pace and prescription text, hours after the run was done and synced. Stale, and it buried the thing the runner actually wants post-run: *how did I do against the plan?*

This flips the card to a summary the moment the run is matched, so the hero stays truthful all day: prescription → actuals.

## How it works (user view)

On the dashboard (`/`), the "Today" flagship has two states for the same planned workout:

**Before the run is matched** — unchanged. Target distance, target pace, target time, plan name; full prescription description.

**After the run is matched** (its activity is linked to today's plan workout on a Garmin sync):

```
① Today · easy · Done ✓
Easy 9 km

  DISTANCE        PACE            TIME            AVG HR
  9.2 km          5:15 /km        48:00           142 bpm
  vs 9.0 km       vs 5:30/km      vs 47:00
  target          target          target

Planned: 9 km easy @ 5:30/km, relaxed.   (italic, dimmed)
```

- Eyebrow gains a `· Done ✓` marker.
- The stat tiles switch from **target** values to **actual** values; each carries a small `vs {target} target` subline so the prescription is still visible, just demoted.
- Avg HR is added (it has no target counterpart, so no subline).
- The description text is kept but rendered muted/italic with a `Planned:` prefix.
- The workout-type accent color (green easy / red tempo / etc.) is unchanged.

Works in both themes. Tempo uses `t()`-translated labels (English / Nederlands); Base uses plain English literals, matching each theme's existing convention.

## How it works (implementation)

### Modules

- [runsphera/plans/service.py](../runsphera/plans/service.py) — `todays_workout(conn)`. The query gained a `LEFT JOIN activities ON a.activity_id = pw.actual_activity_id`, surfacing `actual_distance_m`, `actual_duration_s`, `actual_avg_hr` on the returned row when (and only when) the day's run is matched. Unmatched → those columns are `NULL` and the template renders the prescription as before.

### Templates

- [index.html](../runsphera/web/templates/index.html) — `tp-flagship-main` block branches on `todays_workout.actual_activity_id`. Actual pace is derived in-template: `actual_duration_s / (actual_distance_m / 1000)`.
- [index.html](../runsphera/web/templates/index.html) — same branch for the Base `today-card`.

### Styles

- [static/app.css](../runsphera/web/static/app.css) — `.tp-flagship-stat-sub` (the `vs target` subline) and `.tp-flagship-desc.is-planned` (dimmed/italic prescription).
- [base.html](../runsphera/web/templates/base.html) — `.today-card .stats .sub` and `.today-card .desc.is-planned`.

### i18n

New keys in [i18n.py](../runsphera/i18n.py) under the flagship section: `Done ✓`, `Time`, `Avg HR`, `Planned:`, `vs {target} km target`, `vs {target} target` (Dutch translations included). `{target}` is a `.format()` placeholder filled by the template — survives the lookup.

### Data flow

Nothing new in the pipeline. `actual_activity_id` is set by [plans/matcher.py](../runsphera/plans/matcher.py) on every Garmin sync (also re-runnable via the plan "Re-match" button). The flagship just reads it and joins the matched activity's headline stats. No caching — recomputed per dashboard render.

## Configuration

None. The flip is deterministic from whether today's plan workout has a matched activity.

## Known limitations

- **Only after a match (by design).** The card flips when the matcher links the activity to today's plan workout, which happens on sync. A run done but not yet synced — or a manual run that the strict matcher never links — won't flip the card. This was the deliberate choice over "any running activity dated today" to avoid false positives.
- **Rest-day and no-plan runs aren't covered.** A run on a planned rest day still shows "Rest day."; a runner with no active plan sees no flagship at all. Those are the option-C cases we explicitly deferred.
- **No execution score or coach line here.** The richer post-run debrief (execution-score ring, LLM run reaction) lives in the run-detail modal, not the flagship. This card is the minimal "stop lying + show actuals" version.
- **Derived pace, not Garmin's.** Actual pace is `duration / distance` from the activity headline, so it matches the recent-runs table but not necessarily Garmin's moving-time pace.

## Verification

1. Find a day where the active plan has a workout **and** that day's run is already synced + matched (`actual_activity_id` set). Visit `/` — the flagship shows `· Done ✓`, actual stats, `vs … target` sublines, and the dimmed `Planned:` description.
2. A planned day whose run is **not** yet matched: the flagship shows the normal prescription (target stats, plain description).
3. Switch theme (Settings → Theme) and switch language to Nederlands — confirm both the Base and Tempo cards flip correctly and the Dutch labels (`Klaar ✓`, `Gepland:`, `t.o.v. doel …`) render.

Quick non-UI check of the query:

```python
from runsphera.plans import service
r = service.todays_workout(conn)
# matched → r["actual_distance_m"] etc. are populated; unmatched → None
```

## Future improvements

- **Surface the execution score** here too (corner ring), reusing `execution_score.compute` as the plan-detail cells do — see [execution-score.md](execution-score.md).
- **One-line coach reaction** pulled from the cached `run_reaction:<id>` so the hero says *why* it went well, not just the numbers.
- **Cover rest-day / no-plan runs** (the deferred option C) so any run today reflects in the hero, not just matched plan workouts.

---

*Last updated: 2026-06-02*
