# Event swap — race a calendar event inside your plan

> Swap a training day in your active plan for a race from the `/calendar` — and swap it back with one click.

## Purpose

Mid-plan tune-up races are normal (and healthy) — a 15 km event seven weeks
before the marathon is a better long-run stimulus than another solo Saturday.
Before this feature the calendar and the plan were only loosely linked: an
event could start a *new* plan, but there was no way to say "I'll run this
race *instead of* my 24 km long run that weekend". Event swap is that bridge.
It places the race on the plan day it falls on, optionally converts the
session you're giving up (typically the long run) into a rest day, and keeps
the originals around so the whole thing is reversible.

## How it works (user view)

1. **Calendar → event modal.** Open `/calendar`, click an event. When an
   active plan covers the event's date, the modal shows *"Run this event as
   part of "{plan title}""* with a **⇄ Swap into plan** button per distance.
2. **Confirm strip.** Clicking a distance loads an inline confirm (no native
   popups): *"Add "100 Bruggenloop" (15 km) to your plan? It replaces "Long
   24 km" on Sunday 27 September."* When the race doesn't land on the session
   you want to give up, a dropdown offers the week's other sessions —
   defaulting to that week's long run — to convert into a rest day
   ("swap my long run for this event").
3. **Confirm → plan.** On confirm you land on `/plans`: the day now shows a
   `race`-typed cell titled `🏁 {event name} — {label}`. The event is also
   saved to "Your races" on the calendar, and the event modal now shows
   *"🏁 In your plan"*.
4. **Undo.** Click the race day → the workout modal shows a **Race event**
   section with *"Remove race & restore training"* behind an inline confirm.
   Reverting restores the original workout **and** the freed-up session,
   exactly as they were. The freed-up rest day's modal explains what happened
   and points back to the race day.

## How it works (implementation)

- **Modules**
  - `running_coach/plans/event_swap.py` — the whole feature:
    `swap_context()` (eligibility + candidates + proposed long run),
    `apply_swap()`, `revert_swap()`, `get_swap_for_event()`,
    `get_swap_for_workout()`.
  - `running_coach/race_calendar.py` — reused reads (`get_event`) and
    favorite bookkeeping.
- **Templates**
  - `_event_detail_modal.html` — swap buttons / "in your plan" state.
  - `_event_swap_confirm.html` — the inline confirm strip (HTMX-loaded into
    `#event-swap-zone`).
  - `_plan_workout_modal.html` — "Race event" section + revert confirm.
- **Routes** (`running_coach/web/app.py`)
  - `GET  /calendar/events/{id}/swap-preview` — renders the confirm strip.
  - `POST /calendar/events/{id}/swap-into-plan` — applies; answers HTMX with
    `HX-Redirect: /plans`.
  - `POST /plan-workouts/{id}/revert-event-swap` — reverts; 303 → `/plans`.
- **DB** — new table `plan_event_swaps` (in `db.py` SCHEMA): one row per
  swap with `race_workout_id`, optional `displaced_workout_id`, and JSON
  snapshots (`race_original_json`, `displaced_original_json`) of the seven
  mutable fields (`workout_type, title, description, target_distance_km,
  target_duration_s, target_pace_s_per_km, workout_structure`). FK cascades:
  deleting the plan or event removes the swap record.
- **External services** — Garmin: pushed copies of overwritten/restored rows
  are deleted best-effort (`client` tolerated as `None`); nothing is
  auto-re-pushed.

**Data flow.** Every plan day has a `plan_workouts` row (rest days included),
so the race always lands **on the event's date**: that row is updated
in-place to `workout_type='race'` with the chosen distance and the event name
as title. If the runner picks an additional session to give up, that row
becomes a plain rest day. Both pre-images go into `plan_event_swaps`; revert
is a field-for-field restore plus deletion of the swap row. The event is
favorited into `runner_races` *without* `plan_id` — that column stays
reserved for the A-race that drives the dashboard countdown.

Eligibility guards (`swap_context` / re-checked in `apply_swap`): active plan
exists, event date is today-or-later and inside the plan window, not the
plan's goal race day, the target day isn't completed and isn't already a
race, and the event isn't already swapped in. Displaced candidates are
same-week, future, uncompleted `easy/tempo/intervals/long/recovery` rows not
involved in another swap.

## Configuration

Nothing to configure. Behavior follows the active plan; all copy is
translated (EN/NL) via `i18n.py`.

## Known limitations

- **One event per day / per plan-week granularity.** A day already holding a
  race (goal race or another swap) is refused; there's no multi-race day.
- **No pace target on the swapped race.** The race row gets distance + title
  only — no auto-estimated race pace (VDOT-based estimate is a nice v2).
  Manual edit can add one; "Send to watch" works after that.
- **Editing/moving a swapped race is allowed** but revert restores the row
  *where it now lives* — if you moved the race to another date first, the
  restored workout lands on that date too.
- **Weekly recalibration** treats the race row like any other `race` type
  (never soft-swapped); it doesn't taper the surrounding week for the
  tune-up race.
- If the displaced (rest) row gets a matched activity before revert, only
  the race row is restored — completed rows are never rewritten.

## Verification

Manual smoke test (~1 min):

1. With an active plan, open `/calendar`, click an event dated inside the
   plan (add a manual event on your long-run date if needed).
2. Click **⇄ Swap into plan · {distance}** → confirm strip appears naming the
   workout it replaces → **Yes, add to plan** → you land on `/plans` with a
   🏁 race cell on that date.
3. Click the race cell → "Race event" section → **Remove race & restore
   training** → **Yes, restore** → the original workout (and the freed-up
   session, if any) are back.

Automated: `.venv/Scripts/python.exe tests/test_event_swap.py` (6 tests).

## Future improvements

- VDOT-estimated race pace + duration on the swapped race (feeds watch push
  and the fuel engine).
- Coach-aware surrounding week: ease the 2 days before a swapped tune-up
  race, recovery day after.
- Surface swapped races on the dashboard race-day countdown as B-races.
- Offer the swap from the plan side too (workout modal → "race an event this
  day instead").

---

*Last updated: 2026-07-17*
