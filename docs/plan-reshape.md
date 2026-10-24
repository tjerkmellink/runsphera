# Plan reshape — Schedule & race date

> Change an active plan's training days, long-run day, or race date from the plan-settings modal. Every upcoming workout is rebuilt on the new shape; past weeks and completed runs are never touched.

## Purpose

Life moves: a race gets rescheduled, a weekly commitment lands on your quality day, the long run has to move to Saturday. Before this feature the only options were living with a wrong schedule or archiving the plan and starting over — losing adherence history and completed weeks. Reshape keeps the plan (and its history) and rebuilds only the future.

## How it works (user view)

On **/plans**, click **Edit plan** on the active-plan hero → the **Schedule & race date** section of the plan-settings modal.

- **Flexible-schedule methodologies (Daniels):** pick a new race date, days per week, training days, and long-run day — the same picker as the create form, pre-filled with the plan's current schedule, with the same "exactly N days" enforcement.
- **Fixed-schedule methodologies (Pfitzinger, Foppen):** only the race date is offered; the copy explains the methodology owns its weekly pattern. Moving the race re-anchors the whole template (e.g. a Saturday marathon moves the long runs to Saturdays).

Clicking **Reshape future weeks** validates the picks (a wrong day count shows inline under the picker — no popups) and reveals an inline confirm strip explaining what will happen; only **Yes, reshape** actually submits. The page returns to /plans with a banner: how many upcoming workouts were rebuilt, and how many previously-pushed workouts were removed from Garmin (re-push the weeks you want on the watch). Validation problems (race in the past, wrong day count, Foppen's Sunday-only rule, a race date the plan can't stretch to) come back as a red banner with the reason.

**What is never touched:** workouts dated before today, and any workout already matched to a completed activity (even if it's dated today or later). Adherence history, diary links on past rows, and the completed weeks' look all survive.

## How it works (implementation)

- `running_coach/plans/service.py` — `reshape_plan(conn, client, plan_id, *, race_date, days_per_week, long_run_day, workout_days, today_iso)`.
- `running_coach/web/app.py` — `POST /plans/{plan_id}/reshape`; `GET /plans/{plan_id}/edit` now passes `methodology_info` + parsed `plan_workout_days` to the modal.
- `running_coach/web/templates/_plan_settings_modal.html` — the form (replaces the Tier 2c/d stub).
- `running_coach/web/templates/plans.html` — `saved=reshaped` / `reshape_error` banners.

### Regenerate + splice

1. **Effective params.** Args left empty keep the plan's current values. Fixed-schedule methodologies ignore the day picks entirely. Same validation as create (days 3–6, exactly-N picks, long run inside the picks, race date in the future).
2. **Regenerate the whole plan** with the plan's own methodology, anchored to the plan's original week-1 Monday (from the earliest `plan_workouts` row), the plan's `vdot_at_start` (so paces match the recalibrate flow), and the **creation-time baseline** parsed back out of the plan notes (`baseline 35.0 km/wk…`) — so future volumes stay on the plan's original trajectory instead of re-ramping from today's mileage. Falls back to the current 4-week seed if the note was edited away.
3. **Guards.** The splice relies on old and new plans sharing week-1's Monday, which makes week numbers agree by construction. A race date far enough out that a capped-length methodology (Pfitzinger's 18 weeks, Daniels' 30) would start later — or end before the race — is refused with "create a new plan instead".
4. **Splice by date.** Rows with `planned_date < today` are kept. Rows ≥ today with a matched activity are kept (and the regenerated row for that date is dropped). Everything else ≥ today is deleted and replaced by the regenerated rows. Deleted rows that were pushed to Garmin get a best-effort `client.delete_workout` first (auth failures are swallowed; the runner re-pushes per week).
5. **Plans row stays truthful.** `race_date`, `days_per_week`, `long_run_day`, `workout_days` are updated; for fixed-schedule methodologies they're re-derived from the generated workouts (`_derive_fixed_schedule`, shared with `create_plan`).
6. **Strength sessions.** If the plan has optional strength enabled, future sessions are cleared and re-assigned so they land on the *new* rest days.

## Configuration

None. The section appears for every plan; the day pickers only for flexible-schedule methodologies, the race-date field for every goal except Stay fit.

## Known limitations

- **VDOT and goal don't move here.** Paces come from the existing Set-VDOT + Recalibrate flow; switching goal or methodology remains "create a new plan".
- **The transition week can look odd.** Reshaping mid-week splices new days against old ones — e.g. two quality days or two long runs in the same calendar week if the pattern moved across today. Coaching-wise: treat the first spliced week with common sense.
- **Race dates the plan can't reach are refused, not stretched.** Pfitzinger caps at 18 weeks from the plan's start, Daniels at 30 — beyond that the answer is a new plan.
- **Garmin deletes are best-effort.** Offline / expired session means stale workouts may linger on Garmin Connect; the DB pointers are gone either way, so re-pushing produces fresh ones.
- **The reshape error text is English** even in the Dutch UI (it's the raw service message).

## Verification

Automated: `.venv/Scripts/python.exe tests/test_plan_reshape.py` (8 tests: day moves, completed-row preservation, race move, Garmin cleanup, Pfitzinger re-anchor, far-race guard, validation rejections).

Manual (safe to do on a scratch DB: `RUNNING_COACH_DB=/tmp/x.db uvicorn running_coach.web.app:app`):

1. Create a Daniels plan, open **Edit plan** → Schedule & race date shows the current schedule pre-filled.
2. Change training days and move the race a week; confirm. The banner reports N workouts rebuilt; week cards show the new day pattern; the race lands on the new date; the hero line ("X days/week, long run on …") matches.
3. On a Pfitzinger plan the section offers only the race date; moving the race Sunday→Saturday re-anchors long runs and the race-week template to Saturday.
4. Mark a future workout done (or check a past week) — reshaping keeps it byte-for-byte.

## Future improvements

- **Preview before commit** — a recalibrate-style HTMX preview ("32 workouts would move; race +7 days") before the confirm.
- **Translate service-level error messages** so the red banner is Dutch in the Dutch UI.
- **Smart transition week** — merge rather than splice the current week so the first week after a reshape never doubles a quality day.

---

*Last updated: 2026-07-11*
