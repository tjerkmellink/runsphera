# Daily tips

> A "Today's bonus" card on the dashboard suggesting one supplementary activity (mobility, strides, core, walk, etc.) calibrated to today's planned workout and yesterday's intensity. Rules-only, no LLM.

## Purpose

A real coach doesn't only program runs — they also tell you when to do strides, when an active-recovery walk is better than nothing, when to spend 10 minutes on hip mobility. The daily tip card brings that bonus layer to the dashboard. Lightweight, deterministic, and visible even on days without a scheduled run (which is exactly when supplementary work matters most).

## How it works (user view)

A small card on the dashboard (below the today's-workout card, above the status tiles). Shows:

- **Category label + duration pill** (e.g. "Today's bonus · Core · 20 min")
- **Title** (e.g. "Bonus core + mobility")
- **Body** — concrete description of what to do
- **Rationale** (muted italic) — *why* this fits today

Color-coded swatch on the left edge matches the category (cyan for mobility, purple for core/strength, green for walk, amber for strides, teal for stretch, slate for off).

The card always renders unless the rules return `None` (currently never — there's always a tip).

## How it works (implementation)

### Modules

- [runsphera/tips.py](../runsphera/tips.py) — single function `daily_tip(conn, today=None)`. Pure: reads today's planned workout, yesterday's planned workout, and yesterday's actual run, then walks a decision tree. Plus the `CATEGORY_LABELS` dict used by the template for human-readable names.

### Templates

- [_daily_tip.html](../runsphera/web/templates/_daily_tip.html) — the card. Mirrors `today-card` HTML structure (swatch + grow body) with its own CSS class prefix `tip-card` / `tip-cat-*`.

### Routes

- `GET /` — calls `tips.daily_tip(conn)`, passes the result + `CATEGORY_LABELS` to the template.

### DB

Read-only:
- `plan_workouts` (today + yesterday, via `plan_service.todays_workout` and a direct query)
- `activities` (yesterday, for the `training_load` and `duration_s` fallback)

No writes. No cache table — the decision is cheap (~one or two SQL queries) and recomputes on every page load.

### Decision tree

The function classifies based on today's workout type first, then falls through to a yesterday-aware branch if there's no workout today:

| Today's workout | Tip category | Title | Duration |
|---|---|---|---|
| `tempo` / `intervals` / `race` | strides | Bookend your quality session | 15 min |
| `long` | mobility | Post-long-run reset | 10 min |
| `easy` | strides | Optional strides | 5 min |
| `recovery` | mobility | Light mobility | 10 min |
| `cross` | core | Pair with runner core | 15 min |
| `rest` or none, **and yesterday was hard/long** | walk | Active recovery walk | 30 min |
| `rest` or none, quiet stretch | core | Bonus core + mobility | 20 min |

"Hard/long" yesterday is determined by:
1. Planned workout type in `{tempo, intervals, race, long}`, OR
2. Garmin `training_load >= 100` on the actual run, OR
3. Actual run duration `≥ 75 min`.

Internal helpers: `_yesterdays_planned`, `_yesterdays_run`, `_was_hard_yesterday`. Constants `_HARD_TYPES` and `_MODERATE_TYPES` mirror the same sets in [plan_coach](../runsphera/plans/coach.py).

## Configuration

None. The tip is fully deterministic from the data.

## Known limitations

- **No LLM voicing.** The rationale is fixed-string. Decent for v1; would benefit from per-runner personalization (e.g. "Your knee niggle from the About-you note means we'll skip the strides today.").
- **Can't be dismissed.** Always renders. Some runners may not want a daily nudge; needs a "Skip today's bonus" or a global "Hide daily tips" toggle eventually.
- **No category preference.** A runner who hates core work gets the core suggestion just as often as a runner who lives for it. A preference dial in Settings (later) could weight categories.
- **No diary signal.** If the diary says "ankle felt off today", the tip still tells you to do strides. The LLM coach picks up on the diary; the tip rules don't yet.
- **No "completed the bonus" tracking.** No checkbox, no streak, no historical record of which tips were actually done. Intentional — keeps the card unobtrusive — but a future "Mark done" affordance could feed adherence.
- **Yesterday's run is the only past-day signal.** A grueling tempo two days ago doesn't influence today's tip. The ACWR ratio is available but not consulted.

## Verification

1. Open `/`. The tip card should be visible below the today's-workout area.
2. Today's behavior (pre-plan-start example): no workout, no run yesterday → "Bonus core + mobility · 20 min".
3. Once the plan kicks in:
   - Monday (easy day) → "Optional strides · 5 min".
   - Wednesday (tempo/intervals) → "Bookend your quality session · 15 min".
   - Sunday (long run) → "Post-long-run reset · 10 min".
   - Rest day after a long run → "Active recovery walk · 30 min".
4. The swatch color should match the category (check the [CSS rules](../runsphera/web/templates/base.html) section for `.tip-cat-*`).
5. Hover the duration pill — no tooltip needed; the number plus the category label tell the story.

## Future improvements

- **LLM voicing.** Wrap the structured tip in the same prompt-caching layer as the coach banner. Same persona, but constrained to one paragraph describing the bonus in the runner's context.
- **Dismissal + history.** A small ✕ on the card writes to a `daily_tips_log` table (date, category, dismissed). Lets us track "how often does the runner actually do core?" — and feeds the LLM context: "You've skipped strides 4 out of 5 times this week."
- **Preference dial.** A Settings card (or part of a future "Coach preferences" card) where the runner can mute categories ("never recommend strength") or boost them.
- **Multi-tip days.** Some days warrant two suggestions (pre-run drill + post-run cool-down). Currently we collapse into one. Could surface a primary + secondary.
- **Cross-link with the diary.** If today's tip is "active recovery walk", offer a one-click "Log this in your diary" button after the user does it.
- **Per-category templates.** A small library of mobility flows / core circuits with timed steps, opened from the card body.

---

*Last updated: 2026-05-16*
