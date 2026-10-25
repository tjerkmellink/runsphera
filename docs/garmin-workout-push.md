# Push planned workouts to Garmin

> Send a planned session from the plan to the watch, so the run is guided on the wrist instead of remembered from a screen.

## Purpose

A plan the runner has to memorise is a plan they half-run. Pushing a planned
workout uploads it to Garmin Connect as a structured running workout and
schedules it on its planned date, so the watch counts the warm-up down, beeps
each rep, and holds the pace target for every segment.

The payoff is sharpest on quality sessions — tempo splits, interval reps,
mixed-pace long runs, taper strides — which are precisely the sessions that
need a `workout_structure` to survive the trip. A session the watch can't
receive silently becomes a session the runner has to improvise.

## How it works (user view)

Two surfaces, both gated on a connected Garmin account:

- **Per workout** — the plan-workout modal and the day card each show a
  *Push to watch* button on a pushable, not-yet-pushed workout dated today or
  later. After a successful push the button is replaced by a **✓ on watch**
  pill and the push date.
- **Per week** — the week header shows a bulk push when the week still holds
  at least one pushable, unpushed, not-in-the-past workout
  (`week_has_pushable`). It pushes everything that qualifies and reports
  pushed / skipped / failed counts.

Editing an already-pushed workout turns its save button into **Save &
re-push →**: the old Garmin workout is deleted and the edited one re-uploaded,
so the watch never holds a stale copy. A pace recalibration does the same
across every affected session.

Rest and cross-training days have no button at all — there is nothing to send.

## How it works (implementation)

- **Modules**
  - [runsphera/plans/garmin_sync.py](../runsphera/plans/garmin_sync.py) — the translation layer: the pushability contract (`is_pushable`, `is_pushable_row`, `push_status`), the Garmin shape primitives, and `planned_to_garmin_workout()`.
  - [runsphera/plans/service.py](../runsphera/plans/service.py) — `push_workout_to_garmin()`, `push_week_to_garmin()`, `cleanup_pushed_workouts()`, plus the re-push paths inside `edit_workout()` and `recalibrate_paces()`.
  - [runsphera/plans/daniels.py](../runsphera/plans/daniels.py) and the other engines — build the `workout_structure` JSON at generation time.
- **Templates** — [_day_card.html](../runsphera/web/templates/_day_card.html), [_plan_workout_modal.html](../runsphera/web/templates/_plan_workout_modal.html), [_week_card.html](../runsphera/web/templates/_week_card.html).
- **Routes** — `POST /plan-workouts/{pw_id}/push`, `POST /plans/{plan_id}/weeks/{week_number}/push`. (Strength sessions have their own pair, `/plan-strength/{id}/push` and `/unpush` — see [strength-sessions.md](strength-sessions.md).)
- **DB** — `plan_workouts.workout_structure` (JSON text), `garmin_workout_id`, `pushed_at`.
- **External services** — Garmin Connect via `garminconnect`: `upload_running_workout()` then `schedule_workout()`.

### The pushability contract

`garmin_sync` splits workout types into three buckets, and this split is the
single most load-bearing rule in the push path:

| Bucket | Types | Needs `workout_structure`? |
|---|---|---|
| Simple | `easy`, `long`, `recovery`, `race` | No — one distance step at the headline pace |
| Structured | `tempo`, `intervals` | **Yes** — no structure ⇒ not pushable |
| Never | `rest`, `cross` | n/a |

A type outside all three is not pushable either. The consequence worth
internalising: **typing a row `intervals` is a promise to also hand it a
structure.** Break that promise and the row isn't rejected loudly — the push
button simply never renders and the bulk push counts it as "skipped".

### Structure JSON shape

```jsonc
{"steps": [
  {"type": "warmup",   "zone": "E", "end": {"distance_m": 4500}, "pace_s_per_km": 383},
  {"type": "repeat",   "iterations": 6, "steps": [
    {"type": "active",   "zone": "R", "end": {"distance_m": 100}, "pace_s_per_km": 259},
    {"type": "recovery", "zone": "E", "end": {"duration_s": 60}}
  ]},
  {"type": "cooldown", "zone": "E", "end": {"distance_m": 1000}, "pace_s_per_km": 383}
]}
```

- `type` maps to Garmin's step types (`warmup`/`interval`/`recovery`/`cooldown`/`rest`/`repeat`).
- `end` is either `distance_m` or `duration_s`. Exactly one, or the build raises.
- `pace_s_per_km` becomes a `pace.zone` target (±10 s/km, converted to m/s); omit it for an untargeted step.
- `zone` (E/M/T/I/R) is optional but strongly preferred: `_rewrite_structure_pace()` re-paces a tagged step against *its own* zone on recalibration. An untagged paced step falls back to the row's headline pace — which is wrong for any mixed-pace session, where the headline names only the hardest segment.

Durations: `daniels._structure_duration_s()` returns an exact time when every
step can be timed (distance + pace, or a duration cap, recursing into repeat
blocks). Otherwise it returns `None` and the caller falls back to
distance × headline pace. Classic tempo/interval structures leave warm-up and
cool-down unpaced, so they still take the estimate.

### Data flow

`plan_workouts` row → `planned_to_garmin_workout()` (structure path, or the
single-distance-step fallback) → `RunningWorkout` → `upload_running_workout()`
→ `schedule_workout(workout_id, planned_date)` → `garmin_workout_id` and
`pushed_at` written back. Nothing is cached; the DB columns *are* the push
state.

### The two columns mean different things

Upload and scheduling are **separate Garmin gates**, and they are recorded
separately:

| Column | Asserts | Written when |
|---|---|---|
| `garmin_workout_id` | a copy of this session exists on Garmin | the upload returns an id |
| `pushed_at` | it is on the calendar for `planned_date` | `schedule_workout` is confirmed |

An id with no `pushed_at` is therefore a **stranded upload** — in Garmin's
workout list but not on any date, so it will never reach the watch.
`push_workout_to_garmin` detects that on the next attempt and releases the
stranded copy before uploading again, so a retry replaces rather than
duplicates. If Garmin won't delete it, the push refuses loudly instead of
adding a second copy.

### The headline columns must agree with the structure

`target_distance_km`, `target_pace_s_per_km` and `target_duration_s` are
derived from the structure whenever one exists — at generation time
(`_headline_from_structure` in `plans/daniels.py`) and on edit
(`_totals_from_structure` in `plans/service.py`). Both call the same
`plans/_structure.py` helper.

They used to disagree. `_tempo_structure` is built to a km budget so it
matched, but `_interval_structure` carries Daniels' published rep counts with
a fixed 2 km warm-up and cool-down: a 5 km "budget" prescribed about 10.7 km.
Weekly volume was understated on every interval week.

Two rules the helper encodes, both learned from defects:

* **Timed steps still cover ground.** Interval recoveries and stride jogs are
  expressed in `duration_s`. Counting only their seconds understated a
  6-stride taper run by about a kilometre.
* **A recovery is never priced at the headline pace.** The headline is the
  *work* pace (R / I / T); a jog between 100 m strides is easy by definition.
  Pricing it at R pace inflated the same taper run to 12.53 km.

When a budget and a prescription disagree, **the prescription wins and the
report changes** — never the other way round. Trimming reps to fit a mileage
figure would alter a published training number to protect a display one.

### Three states, two columns

The pair encodes three states, and the middle one is the load-bearing case:

| `garmin_workout_id` | `pushed_at` | Means |
|---|---|---|
| NULL | NULL | never pushed |
| set | NULL | **a copy exists on Garmin; the current prescription is not on it** |
| set | set | the current prescription is confirmed on the watch |

The middle row covers both a stranded upload (schedule failed) and a stale
copy (the workout was edited, moved, swapped or recalibrated while Garmin was
unreachable). Both want the same treatment, and both get it: the next push
releases the old copy and uploads the current shape.

Getting this wrong once produced the nastiest defect in five review rounds.
`pushed_at` used to survive a failed release, so an edit made offline left the
row reading *synchronised* — and once pushes became idempotent, every later
push returned early. The watch kept the pre-edit prescription permanently
while the UI displayed the new one as on-watch. **Keep the id, drop
`pushed_at`**: the id is the handle, `pushed_at` is the claim.

### Pushes are serialised per row

"Push week" and an individual Push run on different threads of the same
process. Without a lock both read the row as unpushed, both upload, both
schedule, and the second write overwrites the first id — leaving a duplicate
on Garmin that no later cleanup can find. `push_lock(kind, row_id)` in
`garmin_state.py` guards it, and the state is re-read inside the lock so the
loser takes the replay no-op. Not a DB-level claim deliberately: holding a
SQLite write lock across a Garmin round-trip would block every other request.

### The rule has to hold at every layer

Four review rounds found the same defect at successive layers, so the rule is
worth stating as a layer checklist rather than a service-level habit:

| Layer | What went wrong |
|---|---|
| Helper | `cleanup_pushed_workouts` cleared ids for deletes that failed |
| Service | `edit`, `move`, `swap`, `recalibrate`, `reshape` each had their own copy |
| Route | the strength unpush route *ignored* the helper's result and cleared state itself, in two branches, then reported success |
| Adjacent service | `clear_future_sessions` deleted whole rows, discarding ids with no Garmin call at all |
| Another module | `event_swap.py` had its own copies of the same clear-then-delete pattern, in both `apply_swap` and `revert_swap` — missed because the audit grepped a list of files instead of the package |

A fix at one layer is invisible if the layer above overrides it. `unpush_session`
was corrected to keep state on a failed delete, and the route above it cleared
that state anyway and flashed "Removed from your watch." — so the fix changed
nothing a runner could see.

**Pushes are idempotent.** A row with both `garmin_workout_id` and `pushed_at`
is already on the watch, so `push_workout_to_garmin` returns it unchanged.
Without that, a replayed POST — a stale tab, a lost response, an individual
push racing the bulk one — uploaded a second copy *and* overwrote the id,
putting the first beyond the reach of any later cleanup.

**Deleting a row deletes the handle.** `clear_future_sessions` takes a client
so pushed sessions come off Garmin before their rows go, keeps any row Garmin
refuses to release, and never deletes a completed session — including one
completed today, which the old `planned_date >= today` predicate erased.

### Never clear push state you did not change

Five paths reshape a pushed workout — `edit_workout`, `move_workout`,
`apply_workout_swap`, `recalibrate_paces`, `reshape_plan` — and all of them go
through `release_garmin_copy(client, garmin_workout_id)` first. It returns
True only when Garmin confirmed the delete (or there was nothing to delete);
`client is None` counts as **not** confirmed, because an unauthenticated run
cannot have removed anything.

Only on True may the caller clear `garmin_workout_id` / `pushed_at`, and only
on True may it upload a replacement. The reasoning is the same every time:

- clearing the id after a failed delete reports "not on watch" for a workout
  that *is* on the watch, and
- it throws away the only handle that could retry the delete, so the next push
  adds a duplicate instead of replacing.

`reshape_plan` is the exception that proves the rule: it deletes the rows
outright, so there is no row left to hold the id. A failed delete there is a
permanent orphan, which is why it counts `garmin_failed` and the route tells
the runner to clean up in Garmin Connect by hand.

## Configuration

Nothing user-tunable. The push surfaces require an authenticated Garmin
session (`is_authenticated()`); without one the buttons don't render. Pace
tolerance (±10 s/km) and the Garmin enum IDs are constants in `garmin_sync`.

## Known limitations

- **Condition-type IDs are empirically derived.** The `garminconnect`
  library's `ConditionType` constants are stale; the verified IDs are
  lap.button=1, time=2, distance=3. Don't "fix" them back to the library's.
- **Likewise `targetValueOne` / `targetValueTwo`** — Garmin uses these, not
  the `Low` / `High` names the library suggests.
- **Unpushable rows fail silently in the UI.** The button is hidden rather
  than disabled-with-a-reason, so a structure-less structured row looks like
  a design choice instead of a bug. `push_status()` returns the explanation,
  but only the direct POST surfaces it. See the strides case below.
- **"Regenerate the plan to enable push"** — what `push_status()` says for a
  structure-less structured row — is only true if the engine would now build
  a structure. When the engine itself emits `None`, regenerating changes
  nothing.
- **Past workouts are never pushed**, by either surface. Bulk push also skips
  anything already pushed.
- **Sport-type and animation gates are separate from pushability.** A
  workout can be FIT-valid, pushable, animated in Connect, and still rejected
  by the watch on *Send to device* — see [strength-sessions.md](strength-sessions.md).

### Case study: taper strides (fixed 2026-10-19)

The Daniels taper session was emitted as `workout_type="intervals"` with
`workout_structure=None`, on the reasoning that strides "aren't a structured
workout". Both halves of the row were defensible; together they were a bug.
`intervals` is a structured type, so every taper strides row was unpushable —
no button, no error, and "Push week" quietly skipping it. A 23-week marathon
block reaches its first strides session only in the taper, so the hole stayed
invisible for 20 weeks.

The session now builds a real structure (easy warm-up at E → N × [100 m @ R +
60 s jog] → easy cool-down at E), which also let it stop lying in two smaller
ways: the description hardcoded "Easy 4–5 km" on rows targeting 7–8 km, and
the duration estimate timed the whole easy run at R pace. Rep count flexes
6 → 4 to fit short taper runs; a run with no room for a real warm-up falls
back to a plain `easy` row, which is pushable by definition.

Regression tests: [tests/test_daniels_taper_strides.py](../tests/test_daniels_taper_strides.py).
Existing plans stuck with structure-less rows:
`scripts/backfill_strides_structure.py` (dry run by default, `--apply` to write).

## Verification

1. Open `/plans`, expand a week containing a future tempo, intervals or
   strides session.
2. The session's day card shows **Push to watch**. Click it — the card should
   flip to a **✓ on watch** pill.
3. In Garmin Connect, open the scheduled workout on that date and check the
   step list matches the plan modal's Steps strip: step types, distances,
   rep count, and a pace range on every step that carries a pace.
4. Edit the workout in the app and save — the button reads **Save & re-push
   →**, and Connect should hold exactly one workout for that date afterwards.
5. Sanity check from a shell: a row is pushable iff

   ```
   .venv/Scripts/python.exe -c "import sys; sys.path.insert(0,'.'); \
     from runsphera.plans.garmin_sync import push_status; \
     print(repr(push_status('intervals', None)))"
   ```

   returns `''`. Anything else is the reason the button is missing.

## Future improvements

- Render `push_status()` as a disabled-button tooltip instead of hiding the
  button — the strides bug would have announced itself on day one.
- A plan-level health check: flag any structured row whose structure is
  missing, or whose steps don't sum to the row's target distance.
- Unpush for running workouts (strength already has it).
- Push cadence / heart-rate targets alongside pace for quality steps.
