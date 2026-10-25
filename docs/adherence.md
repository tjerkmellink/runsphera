# Per-week adherence stats

> A small `X/Y done` pill on each plan week card showing how many of that week's quality sessions have been completed. Color-coded by state. Hides until a week has at least one session that has reached its planned date.

## Purpose

The plan hero already shows an overall completion percentage. The per-week stats fill in the middle zoom level: at a glance, you see "this week I'm on track, last week I was behind, week 3 was perfect." Builds visual feedback on top of the existing matcher (which links completed activities to planned workouts) without any new pipeline.

## How it works (user view)

On the active plan page (`/plans`) and the archived plan detail page (`/plans/{id}`), each week card shows a compact pill in the header next to the existing `N km · M sessions` summary:

```
Week 3 · [Build]        15.2 km · 4 sessions  [3/4 done]
starting Mon 8 Jun 2026
```

Three pill states with distinct colors:

| State | When | Color |
|---|---|---|
| **complete** | All planned non-rest sessions done | Solid green |
| **on-track** | All sessions that have reached their planned date are done, more still upcoming | Subtle green |
| **behind** | At least one due session was missed (planned_date strictly before today, no matched activity) | Amber |

Future weeks (no session has reached its planned date yet) hide the pill entirely — the existing `M sessions` count tells you what's coming.

Hover the pill for a tooltip: `"3 done · 1 missed · 0 upcoming"`.

## How it works (implementation)

### Modules

- [runsphera/plans/service.py](../runsphera/plans/service.py) — `week_adherence(week, today_iso)`. Pure function: takes a week dict (already populated with workouts by `get_plan_weeks`) and today's ISO date string, returns `{planned, done, due, missed}`. No DB access — uses what's already loaded.

### Templates

- [_week_card.html](../runsphera/web/templates/_week_card.html) — calls `week_adherence(week, today_iso)` and renders the pill when `adh.due > 0`.
- [base.html](../runsphera/web/templates/base.html) — CSS for the `.week-adherence` pill + the three state classes (`.adh-complete`, `.adh-on-track`, `.adh-behind`).

### Jinja global

`week_adherence` is registered as a Jinja global in [app.py](../runsphera/web/app.py) alongside `week_has_pushable` and `workout_status`. Templates can call it without explicit passing.

### Definitions

The function matches the same conventions used in `plan_adherence` and `workout_status` so all three agree:

- **planned** — count of workouts in the week with `workout_type` not in `{rest, cross}`.
- **done** — subset of the above that have `actual_activity_id` set (matched to a completed activity).
- **due** — subset of planned where `planned_date <= today_iso`.
- **missed** — strictly past dates without a match: `planned_date < today_iso` AND no `actual_activity_id`. Today's not-yet-done workout is *not* missed yet.

The display logic:

```jinja
{% if adh.due > 0 %}                              {# hide on future weeks #}
    {% if adh.missed > 0 %}    behind             {# amber                  #}
    {% elif adh.done == adh.planned %} complete   {# solid green            #}
    {% else %}                  on-track          {# subtle green           #}
    {% endif %}
{% endif %}
```

### Where the `done` flag actually comes from

`actual_activity_id` is set by [plans/matcher.py](../runsphera/plans/matcher.py) on every Garmin sync. It looks at completed running activities and tries to match each to a planned workout based on `planned_date` and workout shape. Re-runnable manually via the "Re-match" button on the plan detail page.

## Configuration

None — the behavior is deterministic from the plan + activity data.

## Known limitations

- **Doesn't distinguish "swapped" from "missed".** When `apply_workout_swap` softens today's quality session into an easy run, the workout type changes but the row stays. If you then complete the easy run, it's counted as done. Correct outcome — but the badge can't tell the user "you swapped and recovered" vs "you nailed the original plan".
- **Rest/cross days are ignored entirely.** A user who deliberately walks on a rest day doesn't get credit. This matches the rules elsewhere but means the badge under-represents actual training effort.
- **"On-track" and "complete" are both green.** Subtle visual difference (background opacity). Could be more distinct.
- **No drilldown.** The pill tells you the count, not which day was missed. The day-cards within the week card already show that via their status pills, so this is fine for now — but could be linked.
- **Tooltip uses HTML title attribute.** Mobile users don't see it. Not a regression — same pattern used elsewhere on the dashboard.
- **No "ahead of schedule" state.** If you do tomorrow's session today (sometimes happens with travel), the matcher matches by date so it'd show as undone on tomorrow's count. Could be addressed in the matcher with a tolerance window.

## Verification

1. With the active plan in a past week with mixed completion: visit `/plans`, scroll to the week. The pill should be visible.
2. **Behind state.** Simulate by being in week N+1 with no syncs done on week N: pill is amber, tooltip says "0 done · M missed · 0 upcoming".
3. **On-track state.** Mid-week, all due sessions matched, some upcoming: pill is subtle green.
4. **Complete state.** Past week with everything matched: pill is solid green.
5. **Future weeks.** Before plan start (or weeks further out): no pill, just the existing `N sessions` summary.
6. Archived plan view (`/plans/{id}` for an inactive plan): same behavior — past weeks show their final state.

## Future improvements

- **Distinguish swapped-and-completed from missed.** Add a `swapped_at` column on `plan_workouts` (set by `apply_workout_swap`) and reflect it as a fourth state ("swapped" — different shape, maybe blue).
- **Cumulative week-over-week sparkline.** A tiny inline sparkline next to the plan hero showing the completion ratio for the last N weeks. Spot trends.
- **Adherence in the LLM prompt.** Once the plan has been running for 2+ weeks, surface the week adherence numbers in the request block so Claude can reference them ("You hit 4/4 last week — Monday's tempo should land well.").
- **Per-day status indicator within the pill.** A row of 4 colored dots inside the pill, one per session, color = status (done / today / future / missed). Higher information density without losing the at-a-glance read.
- **Manual override.** A "Mark week as planned" button that pretends the week's done — useful for runners coming back from a non-Garmin trip.

---

*Last updated: 2026-05-16*
