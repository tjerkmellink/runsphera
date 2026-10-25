# Optional strength sessions

> Bodyweight core / strength sessions auto-scheduled on rest days, opt-in per plan. A small chip on each rest-day cell opens the session detail with blocks, exercises, and supersets — same shape as the example screenshots from Runna's strength tab. Push to your Garmin watch in one click; the watch plays the right animation for every exercise.

## Purpose

Runners benefit from twice-a-week bodyweight strength + mobility work, but the running plan is the centerpiece — the strength layer can't get in the way of the running. This feature adds an *optional* parallel schedule that lives alongside the existing rest days: turn it on per plan, and every rest day picks up one of six canonical bodyweight sessions on rotation. Push the session to your watch and the watch guides you through it with built-in exercise animations. Turn it off and the rest days go back to being plain rest. Zero impact on the running prescription either way.

## How it works (user view)

### Enabling

Two entry points:

- **At plan creation** (`/plans/new`) — a checkbox under "Extras": *Add optional core / strength sessions on rest days.*
- **On an existing plan** — open Plan Settings (the Edit button on the plan hero); same checkbox sits inside the Name & notes form. Toggling it ON seeds sessions across every future rest day; toggling it OFF clears all future sessions (past ones stay for the historical record).

### Where it shows up

On the plans page, every rest day that has a session attached gains a small **💪 chip in the top-left corner** of the day cell — opposite the execution-score ring on the right. Clicking the chip opens the strength detail modal: blocks, exercises, supersets, plus *Mark complete* and *Push to watch* actions at the bottom. Once marked done, the chip flips to **✓** in a green tint. Once pushed, an *on watch* pill appears in the modal header.

### On the dashboard (rest-day flagship)

When today is a rest day **and** a strength session is scheduled, the session is promoted from a corner chip to the **dashboard flagship** (`tp-flagship-main`), replacing the generic "Rest day." card — because on a rest day the strength session *is* the day's training. The card shows the session title, a violet strength accent, and stat tiles (duration range · block count · exercise count). It mirrors the post-run flagship: the eyebrow turns **green "· Done ✓"** once completed, and if the session was pushed + matched, the tiles flip to **actual** duration / avg HR / calories. The stats body opens the same detail modal as the plan chip (`GET /plan-strength/{id}`). For sessions done *without* pushing to the watch, an inline **"Mark done ✓"** button on the card closes the loop without a trip to `/plans`. The daily coach banner is also aware of today's session (scheduled or done) so it can acknowledge it. See [dashboard.md](dashboard.md) for where it sits in the render order.

### The rotation

Six canonical sessions, all bodyweight:

| # | Slug | Title | Duration | Used in rotation? |
|---|---|---|---|---|
| 1 | `core_hamstrings` | Core & Hamstrings | 20–25 min | Yes |
| 2 | `full_body_strength` | Full-Body Strength | 30–40 min | Yes |
| 3 | `hip_glute_stability` | Hip & Glute Stability | 20–25 min | Yes |
| 4 | `plyo_power` | Plyometric Power | 15–20 min | Yes |
| 5 | `anti_rotation_core` | Anti-Rotation Core | 18–22 min | Yes |
| 6 | `recovery_mobility` | Recovery & Mobility | 15–20 min | Pulled forward, not in rotation |

The scheduler walks future rest days and assigns sessions in this order: **#1 → #2 → #3 → #4 → #5 → #1 → …**, looping. Whenever a rest day immediately follows a **tempo, intervals, long, or race** day, `recovery_mobility` is assigned instead — the "hard day → light day after" coaching rule. The rotation cursor doesn't advance on those days, so the next non-recovery rest day picks up the rotation where it would have been.

### Pushing to Garmin

Each session can be sent to Garmin Connect (and from there to your watch) with the **↗ Push to watch** button in the modal. We construct a Garmin strength-workout payload using the watch's canonical `(category, exerciseName)` enums so each step plays the right animation during the session. Garmin Connect localizes the labels into your language automatically and renders a muscle-group diagram for the workout's overview. Pushing schedules the workout on its `planned_date` so it appears in your Garmin Connect calendar alongside the watch syncs.

To remove it from Garmin Connect, click **↺ Unpush** in the same place — we delete the Garmin workout and clear the local push state.

### Activity matching (auto-mark complete)

When the runner completes a pushed strength session on the watch and the activity syncs back, the matcher in `runsphera/strength/matcher.py` links it to the scheduled `plan_strength_sessions` row. The chip on the rest-day cell flips to ✓ without any manual click, and the modal grows an **Actual** stats panel showing the real duration, average / max HR, calories, and Garmin training load.

The match is **strict**: it relies on Garmin echoing the pushed `workoutId` back inside the activity payload. Any strength-flavored activity that doesn't carry our pushed `workoutId` is left alone — manual gym sessions never get misattributed to a scheduled session. *Mark complete* in the modal stays available as the manual escape hatch for sessions the runner did without pushing.

> **Candidate-type gotcha (fixed 2026-06-03).** The matcher narrows its scan to a set of `activity_type` values before parsing `workoutId`. Because we push bodyweight circuits as the `cardio_training` sportType (a Fenix-compatibility requirement — see below), Garmin logs the *completed* activity as **`indoor_cardio`**, which was missing from the candidate list — so pushed-and-completed sessions silently failed to auto-link until `indoor_cardio` was added. The exact-`workoutId` match is still the real guard, so the type filter is only a performance narrowing; if a future sportType maps to yet another returned type, add it to `_CANDIDATE_TYPES`. Symptom to watch for: a session pushed + done on the watch whose dashboard/plan chip never flips to ✓.

### Session structure

Each session is built from one or more **blocks** (Runna's "Deel 1 / Deel 2 / Deel 3" pattern). A block has a name, a rounds count, rest-between-rounds, and an ordered list of **exercises**. An exercise references Garmin's canonical FIT exercise enum via a `(category, exercise)` pair, a `description` (one-sentence form cue), and either `duration_s` or `reps` plus an optional `per_side: true`. Two consecutive exercises sharing the same `superset_id` render as a paired card. The displayed label is the title-cased FIT enum (`single_leg_hip_raise` → "Single leg hip raise") — we deliberately don't override it, so the in-app modal, the Garmin Connect list, and the Fenix watch screen all show the same name.

### Exercise explanations

Every exercise in the library carries a short hand-written `description` (one form-cue sentence) rendered directly under the exercise name in the modal. For a richer breakdown — setup, key cue, common mistake — a small **"· Explain more"** link sits below the description. Clicking it triggers an HTMX call to `/strength/explain?id=<fit_enum>&name=<friendly>` which:

1. Looks up `strength_explain:<fit_enum>` in `llm_cache` (keyed by the canonical FIT enum so the cache survives display-name tweaks).
2. On miss, calls Claude with a tight system prompt ("3 bullets: Setup / Cue / Mistake — ~12-18 words each") and stores the result.
3. Returns the rendered prose, which HTMX swaps in place of the link.

The cache is global (not per-user). Switching language re-keys the cache because `invalidate_all_coach()` clears the whole `llm_cache` table — so a Dutch user gets Dutch bullets, an English user gets English ones.

### Garmin canonical exercise catalog

[runsphera/strength/garmin_catalog.py](../runsphera/strength/garmin_catalog.py) surfaces Garmin's full exercise enum table via the `garmin-fit-sdk` dependency. That gives us the 53 canonical categories and per-category exercise lists (e.g. 61 plank variants, 43 squat variants of bodyweight type) that the watch firmware knows by name — `category` + `exerciseName` is what triggers the watch's built-in animations during a session. The library above references those enum values **directly** in every exercise dict.

### Animation allowlist + import-time validator

Two sources of truth coexist in `garmin_catalog.py`:

1. **FIT-SDK enum catalog.** `categories()`, `exercises_in()`, `is_known()` — the watch firmware's vocabulary. Every pair here is a valid payload step; the watch will accept and run it.
2. **Empirical animation allowlist.** `KNOWN_ANIMATED` (explicit `(category, exercise)` pairs) + `OPEN_CATEGORIES` (`pose`, `move` — whole categories where every enum tested animated) + `KNOWN_EMPTY` (edge cases inside open categories). `is_animated(c, e)` is the single function that combines them.

These are not the same set. Garmin Connect's **exercise-info database** has narrower coverage than the FIT catalog — many FIT-valid enums (every `warm_up/stretch_*`, most plyo / hip_stability variants, every specialized squat / push_up / lunge) accept the payload but show "Er is een fout opgetreden" when the runner taps the step in Garmin Connect. The workout still runs on the watch, but the in-app UX is broken.

`library.py` calls `_validate_library()` at module-import time — it walks every exercise in every session and asserts `is_animated(c, e)` is True. A typo or unverified enum raises immediately, so we can't silently ship a session with broken steps. The error message names the session, block, and offending pair, plus points to the probe procedure.

### Animation probe procedure

The allowlist is empirical — built from 5 probe workouts across 75 candidate exercises on 2026-05-31. To extend it (e.g. to add a new exercise to a session):

1. Pick a candidate `(category, exercise)` pair from the FIT catalog (use `garmin_catalog.exercises_in("category")` to browse).
2. Push a probe workout containing the candidate. Quickest path: an ad-hoc Python script that calls `garmin_push.build_payload(session_dict)` with the candidate as one exercise step, then `client.upload_workout(payload)`, then optionally `client.schedule_workout(wid, today)` so it shows up in your Connect agenda.
3. Open the workout in the Garmin Connect mobile app (phone is fastest — same exercise-info DB as the watch firmware, no need to mess with the watch).
4. Tap each exercise step. The popup either renders with animation + info text **or** errors "Er is een fout opgetreden".
5. For the ones that render, append the pair to `KNOWN_ANIMATED` in `garmin_catalog.py`. For pose / move enums, no addition is needed (they're already covered by `OPEN_CATEGORIES`); but if one renders **empty**, add it to `KNOWN_EMPTY`.
6. Delete the probe workout via `client.delete_workout(wid)` so it doesn't clutter the workout library.

**Patterns we know from the empirical sweep:**

- **Basic moves animate, variants don't.** `squat/squat` works; `sumo_squat` / `pistol_squat` / `air_squat` / `box_step_squat` all fail. Same pattern in `lunge`, `push_up`, `squat`, `plyo`, `hip_stability`. Rule of thumb: if Garmin's stock workouts use it, it's animated; specialized variants almost never are.
- **`pose/*` and `move/*` are default-animated.** Garmin's stock yoga / pilates / mobility workouts cover these categories thoroughly — every enum we tested in either category animated cleanly (one exception: `pose/seated_cat_cow` renders empty; use `pose/cat` + `pose/cow` separately).
- **`warm_up/*` is dead for animations.** Every `warm_up/stretch_*` and every active-warmup variant (`walking_high_knees`, `ankle_circles`, `cat_camel`, `bear_crawl`, `marching_in_place`) is FIT-valid but un-animated. For stretches, **use `pose/*` instead** — `pose/childs` works where `warm_up/stretch_childs_pose` doesn't, same names same meaning, different table.
- **No API to ask.** We probed every plausible `/exercise-service/*` / `/exercise-info-service/*` / static CDN URL and got 404 everywhere. The Connect SPA likely inlines the exercise dictionary in its JS bundle. Manual probe-and-record is the only ground truth.

## How it works (implementation)

### Modules

- [runsphera/strength/library.py](../runsphera/strength/library.py) — the six canonical sessions as Python data. Edit / extend by appending more entries to `LIBRARY`.
- [runsphera/strength/service.py](../runsphera/strength/service.py) — read/write helpers for `plan_strength_sessions`, the seeder, and small library-fetch utilities. `todays_strength_session(conn)` powers the dashboard flagship (active plan's session for today, with matched-activity actuals joined).
- [runsphera/strength/scheduler.py](../runsphera/strength/scheduler.py) — `assign_for_plan()` does the rotation walk with the recovery-after-quality override.
- [runsphera/strength/garmin_catalog.py](../runsphera/strength/garmin_catalog.py) — wrapper around the FIT SDK exercise enum tables; powers the catalog browse + the push payload builder.
- [runsphera/strength/garmin_push.py](../runsphera/strength/garmin_push.py) — `build_payload(session)` constructs the Garmin POST JSON; `push_session(conn, client, id)` uploads + schedules + records the IDs; `unpush_session(conn, client, id)` cleans up.
- [runsphera/strength/matcher.py](../runsphera/strength/matcher.py) — `match_strength_sessions(conn)` walks every strength-flavored activity, reads `workoutId` from `raw_json`, links to the matching `plan_strength_sessions` row, stamps `actual_activity_id` + (if not already set) `completed_at`. Idempotent — re-running yields the same links. Wired into `ingest.ingest_activities` and the `/ingest` web route so it runs after each sync.

### Templates

- [_week_card.html](../runsphera/web/templates/_week_card.html) — adds the strength chip alongside each day cell.
- [_plan_strength_modal.html](../runsphera/web/templates/_plan_strength_modal.html) — detail modal body, including the block / exercise / superset rendering and the push/unpush + complete/undo controls.
- [index.html](../runsphera/web/templates/index.html) — the rest-day strength flagship branch (`{% elif todays_strength %}`) + the `#plan-strength-modal` dialog mounted on the dashboard.
- [_flagship_aside.html](../runsphera/web/templates/_flagship_aside.html) — bonus-tip + next-race aside, extracted so both the running and strength flagships share it.
- [_strength_explain.html](../runsphera/web/templates/_strength_explain.html) — "Explain more" link partial.
- [_plan_settings_modal.html](../runsphera/web/templates/_plan_settings_modal.html) — toggle checkbox inside the Name & notes form.
- [plans_new.html](../runsphera/web/templates/plans_new.html) — toggle checkbox in the Extras block.

### Routes

| Method | Path | Purpose |
|---|---|---|
| `GET`  | `/plan-strength/{session_id}` | Render the strength detail modal body. |
| `POST` | `/plan-strength/{session_id}/complete` | Mark session done; re-renders modal body. |
| `POST` | `/plan-strength/{session_id}/undo` | Flip a completed session back to pending. |
| `POST` | `/plan-strength/{session_id}/push` | Upload + schedule on Garmin; stamps `garmin_workout_id` + `pushed_at`. |
| `POST` | `/plan-strength/{session_id}/unpush` | Delete from Garmin (best effort) + clear local push state. |
| `GET`  | `/strength/explain?id&name` | LLM-generated 3-bullet breakdown for one exercise, cached. |

The plan-creation (`POST /plans/new`) and plan-edit (`POST /plans/{id}/edit`) handlers both accept the `include_optional_strength` checkbox and call the scheduler / cleaner accordingly.

### DB

```sql
ALTER TABLE plans
    ADD COLUMN include_optional_strength INTEGER NOT NULL DEFAULT 0;

CREATE TABLE strength_workouts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    slug            TEXT UNIQUE NOT NULL,
    title           TEXT NOT NULL,
    category        TEXT NOT NULL,
    duration_min_lo INTEGER NOT NULL,
    duration_min_hi INTEGER NOT NULL,
    equipment       TEXT NOT NULL DEFAULT 'bodyweight',
    notes           TEXT,
    structure       TEXT NOT NULL,        -- JSON: {"blocks": [...]} with FIT pairs
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE plan_strength_sessions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id             INTEGER NOT NULL,
    strength_workout_id INTEGER NOT NULL,
    planned_date        TEXT NOT NULL,
    completed_at        TEXT,
    notes               TEXT,
    garmin_workout_id   INTEGER,           -- set when pushed; cleared on unpush
    pushed_at           TEXT,              -- ditto
    actual_activity_id  INTEGER,           -- matched Garmin activity (workoutId echo)
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(plan_id, planned_date),
    FOREIGN KEY (plan_id) REFERENCES plans(id) ON DELETE CASCADE,
    FOREIGN KEY (strength_workout_id) REFERENCES strength_workouts(id)
);
```

`UNIQUE(plan_id, planned_date)` is what lets the scheduler use `INSERT … ON CONFLICT DO UPDATE` to stay idempotent: re-running the same scheduler call on the same plan produces the same assignments.

### Library shape (Python)

```python
{
    "slug": "core_hamstrings",
    "title": "Core & Hamstrings",
    "category": "core+hamstrings",
    "duration_min_lo": 20,
    "duration_min_hi": 25,
    "notes": "Easy paced. Hold each position; don't rush.",
    "blocks": [
        {
            "name": "Warm-up",
            "rounds": 2,
            "rest_between_rounds_s": 60,
            "exercises": [
                {
                    "category": "hip_raise",
                    "exercise": "single_leg_hip_raise",
                    "duration_s": 30,
                    "description": "Bridge up on one leg with the other extended. Drive through the planted heel, squeeze the glute.",
                },
                {
                    "category": "plank",
                    "exercise": "side_plank",
                    "duration_s": 40,
                    "per_side": True,
                    "superset_id": "B",
                    "description": "On one elbow, body straight from ankles to shoulder. Hips up, don't sag.",
                },
                # …
            ],
        },
    ],
}
```

Two exercises in a row sharing the same `superset_id` render as a paired card in the UI. The `(category, exercise)` pair is also what gets emitted in the Garmin push payload, so every library exercise is animation-mapped by construction.

### Push payload shape

Each push hits `POST /gc-api/workout-service/workout` via the `garminconnect` client's `upload_workout()` and produces a payload like:

```json
{
  "workoutName": "Core & Hamstrings",
  "description": "…",
  "sportType": {"sportTypeId": 5, "sportTypeKey": "strength_training"},
  "estimatedDurationInSecs": 1320,
  "workoutSegments": [
    {
      "segmentOrder": 1,
      "sportType": {"sportTypeId": 5, "sportTypeKey": "strength_training", "displayOrder": 5},
      "workoutSteps": [
        {
          "type": "ExecutableStepDTO",
          "stepOrder": 1,
          "stepType": {"stepTypeId": 3, "stepTypeKey": "interval"},
          "endCondition": {"conditionTypeId": 2, "conditionTypeKey": "time"},
          "endConditionValue": 30,
          "category": "HIP_RAISE",
          "exerciseName": "BRIDGE_WITH_LEG_EXTENSION",
          "description": "Glute bridge walkout"
        },
        ...
      ]
    }
  ]
}
```

Translation rules:

- **Multi-round blocks are wrapped in a ``RepeatGroupDTO``** so the watch shows "Round N of M" while the runner is doing the workout, instead of a flat step counter. The group carries ``numberOfIterations`` + ``endCondition: iterations`` + ``skipLastRestStep: True`` (so the inter-round rest doesn't fire after the final round). Single-round blocks emit their exercises flat (no point wrapping a one-shot pass).
- **Per-side exercises** emit as two consecutive steps so the watch beats out "first side / second side."
- **Recovery & Mobility sessions** use `sportType: "yoga"` (id 7) instead of strength so Garmin's post-session categorization treats them right. (We originally used `mobility` (id 11) — it uploaded and animated fine but the Fenix rejected it on sync; see the device-compatibility quirks below.)

After a successful upload, we call `client.schedule_workout(workout_id, planned_date)` to put it on the runner's Garmin Connect calendar.

### Fenix-class device-compatibility quirks

Four details in the payload control whether the watch will actually accept the workout when the runner hits *Send to device*. None of them are documented; all were found by diffing our payload against Garmin's pre-made workouts (Plank Challenge, AMRAP, Pilates Ab Burner, stock yoga/pilates flows) until ours matched the shape that syncs on a Fenix 7. Anyone porting this to another wearable should know:

- **`sportType` must NOT be `strength_training` (id 5) for bodyweight circuits.** Garmin reserves that profile for weighted gym work. Use `cardio_training` (id 6) for general bodyweight and `hiit` (id 9) for explosive plyo-style work. Our `_pick_sport_type` does this routing.
- **`sportType` for recovery flows must be `yoga` (id 7), NOT `mobility` (id 11).** This one bit us late (probed 2026-06-16): `mobility` uploads cleanly and every pose *animates* in Connect, but the Fenix refuses to sync it — "incompatible device". A by-pose probe (12 single-pose mobility workouts, [scripts/probe_recovery_sync.py](../scripts/probe_recovery_sync.py)) showed **all 12 failed**, ruling out any individual enum. The runner's own copies of Garmin's stock yoga/pilates workouts — which *do* sync — turned out to use `yoga` (id 7) / `pilates` (id 8) with the **exact same POSE/MOVE step enums** we already use. Re-pushing the full session under `yoga` synced first try. Lesson: *animatable ≠ syncable*, and they're gated independently — a sport type can pass the animation/upload path and still be rejected by the device-compatibility validator. The reference yoga workouts also set **`subSportType: "GENERIC"`** (we leave it `None` for cardio/hiit, which sync fine without it), so the yoga path sets it to match.
- **`description` on each step must be `None`.** Setting a custom label there (e.g. our friendly name "Glute bridge walkout") flags the step as a custom-named exercise and the validator rejects it. Leave it None; Garmin localizes the canonical `(category, exerciseName)` enum into the runner's language on the watch.
- **`workoutProvider` at the top level must be non-null.** For non-running sport types the validator requires it set. We use `"Garmin"` (matching the working reference shapes) — the value is opaque provenance metadata that doesn't change anything user-visible, it just clears the check.

> **Probe procedure for sync rejections.** When a session uploads but won't *Send to device*, `scripts/probe_recovery_sync.py` is the reusable harness: `push` uploads one single-exercise workout per step (isolates a bad enum), `yoga` re-pushes the real session under a candidate sport type (isolates a bad sport type), `clean` deletes every probe it created. Test each on the phone and note which throw "incompatible device". Always probe the sport type *and* the enums — they're separate gates.

## Configuration

| What | Where | Notes |
|---|---|---|
| Enable per plan | Plan creation form / Plan settings modal | Persisted on `plans.include_optional_strength`. |
| Rotation order | `runsphera/strength/library.py` → `LIBRARY` | Walks the list top-to-bottom, minus `recovery_mobility` (which is auto-pulled). |
| Quality types that trigger recovery override | `runsphera/strength/scheduler.py` → `_QUALITY_TYPES` | `{"tempo", "intervals", "long", "race"}`. |
| Add a new session | Append a dict to `library.LIBRARY` | Schema seeder picks it up on next DB connect when the table is empty. For an existing DB, see "Re-seeding the library" below. |

### Re-seeding the library

The seeder runs only when `strength_workouts` is empty (the safe, idempotent default). Adding a new session to `library.LIBRARY` after the table is populated won't automatically insert it. Two options:

1. **Per-row insert** with a one-off script using `service.seed_library_if_empty` after clearing the table — destructive, drops user customization.
2. **Hand-insert** the new row via SQL and update existing rows via `UPDATE strength_workouts SET structure = ... WHERE slug = ...` — non-destructive, keeps foreign-key links intact.

Auto-migration of library additions is a follow-up; see "Future improvements" below.

## Known limitations

- **Per-side count from Garmin** — when emitting per-side exercises as two consecutive watch steps, the runner does each side independently. If they only do one side, the second step still counts down on the watch.
- **Bodyweight only.** The library skips kettlebells, bands, and gym work. The schema has an `equipment` column so the library can extend later; the UI doesn't yet expose a filter.
- **Library edits aren't auto-migrated.** Adding a new session to `library.py` after first run doesn't seed it into an existing DB without a manual SQL insert/update. Fine while the library is shaped by the author; not great for multi-device shared libraries.
- **No per-session swap.** The scheduler picks the session for each rest day; the runner can't pick a different one for a specific day from the UI yet.
- **No completion stats / streaks.** Marking sessions done writes the timestamp but nothing surfaces it as a weekly/yearly summary.
- **Tempo-themed only.** The Base theme's plan view doesn't render strength chips. Falls back gracefully — no error, just no chip until the Base layout gets the same partial.
- **No per-side count from Garmin.** When emitting per-side exercises as two consecutive watch steps, the runner does each side independently. If they only do one side, the second step still counts down on the watch.

## Verification

1. **Toggle on a plan.** Open the active plan's settings modal (Edit button on the hero). Check *Include optional core / strength sessions on rest days*. Save. Reload /plans — every future rest day cell shows a small 💪 chip in the top-left corner.
2. **Recovery-after-quality.** Confirm the rest day immediately after the most recent tempo / intervals / long run got `recovery_mobility` (hover the chip; the title should read "Recovery & Mobility").
3. **Open a session.** Click any 💪 chip — the strength modal opens with the workout title, duration range, "Strength" pill, "Bodyweight" pill, and the structured blocks below.
4. **Superset rendering.** Open the *Core & Hamstrings* session. The Strength Block and Core Finisher both have a "Superset" tag with two exercises rendered side-by-side, separated by a small accent stripe down the left.
5. **Mark complete + undo.** Click *Mark complete* — modal re-renders with the green "✓ done" pill and the button flips to "Mark not done". Reload /plans — the chip on that day is now ✓ in a green tint.
6. **Push to Garmin.** With Garmin connected, click *↗ Push to watch* on a future session. The modal re-renders with a flash "Pushed to your watch." and an *on watch* pill. Open Garmin Connect → calendar — the workout appears on the planned date with localized exercise names, animations, and a muscle diagram.
7. **Explain more.** Click the small *· Explain more* link below an exercise's description. After a short pause, three Claude-written bullets appear (Setup / Cue / Mistake). Second click on a different session with the same exercise is instant (cached).
8. **Toggle off.** Open plan settings, uncheck the box, save. Reload /plans — the chips on future rest days are gone. Past days that had a session completed before the toggle-off keep their assignment (visible if you scroll back).

## Future improvements

- **Per-session swap** — small "↻ swap" affordance inside the modal that picks the next library session for *just* that day.
- **Library editor / import** — UI to clone-and-edit a canonical session, or to import a paste of JSON.
- **Library auto-migration** — when `library.py` grows a new entry, detect missing slugs at connect time and insert / update them automatically.
- **Equipment filter** — add bands / dumbbells / kettlebells to the library with an equipment chip set, and let the runner say "show me only bodyweight" or "I have a kettlebell at home."
- **Streaks + adherence on strength** — small weekly count next to the running adherence pill on the plan hero.
- **Base-theme port** — render the chip + modal in the calm/neutral layout (the dashboard flagship is also Tempo-only for now).
- ~~**LLM coach awareness**~~ — *shipped:* today's scheduled / completed strength session now feeds the daily-coach request context ([context.py](../runsphera/llm/context.py) → [prompts.py](../runsphera/llm/prompts.py)).
- ~~**Dashboard surfacing**~~ — *shipped:* rest-day strength flagship with done-flip + inline mark-done (see "On the dashboard" above).

---

*Last updated: 2026-06-03*
