"""Build + upload strength workouts to Garmin Connect.

Converts our nested strength-session shape (block → round → exercise,
with supersets) into the flat ``workoutSteps`` payload Garmin's
``POST /gc-api/workout-service/workout`` endpoint expects. Each step
carries the canonical FIT ``category`` + ``exerciseName`` pair (the
library uses them directly as the source of truth) so the watch plays
the right animation during the session.

## Translation rules (block → steps)

- **Rounds are flattened**: a block with 3 rounds × 4 exercises emits
  12 work steps + 2 rest steps (rest between rounds, not after the
  last round). Watch counts up through them like any sequential
  workout.
- **Supersets are sequential**: two consecutive exercises in our model
  with the same ``superset_id`` simply emit as back-to-back steps
  inside the same round (no rest between). Garmin's watch UX for
  strength doesn't have a "superset group" primitive — the watch
  groups by stepOrder.
- **Per-side exercises** emit as TWO consecutive steps with the same
  exercise name. The runner gets a clean "first side / second side"
  beat on the watch instead of a single double-length step.
- **Time-based** (``duration_s``) → ``endCondition: time``,
  ``endConditionValue: seconds``.
- **Rep-based** (``reps``) → ``endCondition: reps``,
  ``endConditionValue: count``.
- **Rest between rounds** → a single ``rest`` step with
  ``endCondition: fixed.rest`` and ``endConditionValue: seconds``.

## Sport type

Sessions with ``category == "recovery"`` use ``mobility`` (sportTypeId
11); everything else uses ``strength_training`` (5). The watch routes
to different post-session summaries based on the sport type, and
mobility sessions shouldn't appear as "strength" in Garmin's stats.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import date
from typing import Any

from . import garmin_catalog, service
from ..garmin_state import push_lock, release_garmin_copy

log = logging.getLogger(__name__)


# ── Garmin enum constants (mirroring the schema payload) ──────────────

# Sport types for the push payload.
#
# We tested ``strength_training`` (id 5) first — workouts uploaded fine
# but did NOT sync to a Fenix 7 Solar. Garmin's own pre-made bodyweight
# sessions (the Plank Challenge, the 10-Minute Body Weight AMRAP) use
# ``cardio_training`` and ``hiit`` respectively, both of which sync to
# the watch. The hypothesis: ``strength_training`` on Fenix expects
# weight/rep tracking metadata that pure-bodyweight time-based
# circuits don't carry, so the device rejects them silently.
#
# The SAME trap caught ``mobility`` (id 11): Recovery & Mobility uploaded
# fine and animated in Connect, but every probe of it — even a single
# pose — was rejected by the Fenix with "incompatible device" on sync
# (probed 2026-06-16; all 12 single-pose mobility workouts failed). The
# runner's own copies of Garmin's stock yoga/pilates workouts (which DO
# sync) use ``yoga`` (id 7) / ``pilates`` (id 8) with the exact same
# POSE/MOVE step enums we already use. Re-pushing the full Recovery &
# Mobility session under ``yoga`` (id 7) + ``subSportType: GENERIC`` synced
# cleanly. So ``mobility`` is NOT a watch-syncable workout sport type;
# ``yoga`` is the right home for our pose/move flow.
#
# Mapping for our library:
#   - ``cardio_training`` (id 6)  for the structured circuits
#     (core_hamstrings, full_body_strength, hip_glute_stability,
#     anti_rotation_core) — same type Garmin uses for the Plank
#     Challenge.
#   - ``hiit`` (id 9) for ``plyo_power`` — semantically right
#     (explosive intervals) and aligned with Garmin's AMRAP shape.
#   - ``yoga`` (id 7) for ``recovery_mobility`` — matches Garmin's own
#     syncable yoga/pilates workouts; ``mobility`` (id 11) does NOT sync.
_SPORT_TYPE_CARDIO   = {"sportTypeId": 6,  "sportTypeKey": "cardio_training"}
_SPORT_TYPE_HIIT     = {"sportTypeId": 9,  "sportTypeKey": "hiit"}
_SPORT_TYPE_YOGA     = {"sportTypeId": 7,  "sportTypeKey": "yoga", "displayOrder": 8}

_STEP_TYPE_INTERVAL = {"stepTypeId": 3, "stepTypeKey": "interval", "displayOrder": 3}
_STEP_TYPE_REST     = {"stepTypeId": 5, "stepTypeKey": "rest",     "displayOrder": 5}
_STEP_TYPE_REPEAT   = {"stepTypeId": 6, "stepTypeKey": "repeat",   "displayOrder": 6}

_END_TIME       = {"conditionTypeId": 2,  "conditionTypeKey": "time",       "displayOrder": 2,  "displayable": True}
_END_REPS       = {"conditionTypeId": 10, "conditionTypeKey": "reps",       "displayOrder": 10, "displayable": True}
_END_FIXED_REST = {"conditionTypeId": 8,  "conditionTypeKey": "fixed.rest", "displayOrder": 8,  "displayable": True}
# `iterations` is the end-condition used inside a fixed-iteration
# RepeatGroupDTO (when numberOfIterations is set). Garmin marks it
# `displayable: False` because the iteration count drives the watch UX
# rather than a separate visible field.
_END_ITERATIONS = {"conditionTypeId": 7,  "conditionTypeKey": "iterations", "displayOrder": 7,  "displayable": False}

_TARGET_NONE = {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target", "displayOrder": 1}
_EMPTY_EQUIPMENT = {"equipmentTypeId": None, "equipmentTypeKey": None, "displayOrder": None}
_WEIGHT_UNIT_KG  = {"unitId": 8, "unitKey": "kilogram", "factor": 1000}


def _pick_sport_type(session: dict) -> dict:
    """Sport type per session category. Drives the watch's post-session
    summary AND determines whether the device will even accept the
    push — see the comment on ``_SPORT_TYPE_CARDIO`` for why we don't
    use ``strength_training`` for pure-bodyweight circuits."""
    cat = session.get("category")
    if cat == "recovery":
        return _SPORT_TYPE_YOGA
    if cat == "plyo":
        return _SPORT_TYPE_HIIT
    return _SPORT_TYPE_CARDIO


def _make_exercise_step(
    step_order: int,
    exercise: dict,
) -> dict:
    """Build one work step from a library exercise dict. Every library
    exercise carries a canonical FIT ``category`` + ``exercise`` pair
    (the library shape is the source of truth — no separate mapping
    table to maintain), so no lookup is required."""
    category = exercise.get("category")
    exercise_name = exercise.get("exercise")

    # End condition: time or reps, depending on what the library specifies.
    if exercise.get("duration_s"):
        end_cond = _END_TIME
        end_val = int(exercise["duration_s"])
    elif exercise.get("reps"):
        end_cond = _END_REPS
        end_val = int(exercise["reps"])
    else:
        end_cond = _END_TIME
        end_val = 30

    # Leave ``description`` None on every step. Garmin's device-
    # compatibility check rejects custom-named steps (description set)
    # for the Fenix-class watches that don't have a custom-label
    # display mode — confirmed by diffing our payload vs Garmin's own
    # AMRAP / Plank Challenge / Pilates Ab Burner, all of which sync
    # with description=None. The canonical ``category`` + ``exerciseName``
    # alone gives the watch enough to render a localized label.
    return {
        "type":                       "ExecutableStepDTO",
        "stepOrder":                  step_order,
        "stepType":                   _STEP_TYPE_INTERVAL,
        "childStepId":                None,
        "description":                None,
        "endCondition":               end_cond,
        "endConditionValue":          end_val,
        "preferredEndConditionUnit":  None,
        "endConditionCompare":        None,
        "targetType":                 _TARGET_NONE,
        "equipmentType":              _EMPTY_EQUIPMENT,
        "category":                   garmin_catalog.to_api_value(category) if category else None,
        "exerciseName":               garmin_catalog.to_api_value(exercise_name) if exercise_name else None,
        "workoutProvider":            None,
        "providerExerciseSourceId":   None,
        "weightValue":                None,
        "weightUnit":                 _WEIGHT_UNIT_KG,
    }


def _make_rest_step(step_order: int, seconds: int) -> dict:
    # ``description`` deliberately None for the same Fenix
    # device-compatibility reason — see _make_exercise_step.
    return {
        "type":                       "ExecutableStepDTO",
        "stepOrder":                  step_order,
        "stepType":                   _STEP_TYPE_REST,
        "childStepId":                None,
        "description":                None,
        "endCondition":               _END_FIXED_REST,
        "endConditionValue":          seconds,
        "preferredEndConditionUnit":  None,
        "endConditionCompare":        None,
        "targetType":                 _TARGET_NONE,
        "equipmentType":              _EMPTY_EQUIPMENT,
        "category":                   None,
        "exerciseName":               None,
        "workoutProvider":            None,
        "providerExerciseSourceId":   None,
        "weightValue":                None,
        "weightUnit":                 _WEIGHT_UNIT_KG,
    }


def build_payload(session: dict) -> dict:
    """Convert a hydrated strength session (the dict returned by
    ``service.get_session``) into the Garmin workout payload.

    Each block becomes a ``RepeatGroupDTO`` step when it has multiple
    rounds, so the watch shows "Round 2 of 3" UX rather than flat
    step numbering. Single-round blocks emit their exercises flat
    (no point wrapping a one-shot pass). Rest-between-rounds lives as
    the LAST step inside the repeat group with ``skipLastRestStep``
    so the watch doesn't fire a useless rest after the final round.
    """
    structure = session.get("structure", {}) or {}
    blocks = structure.get("blocks", []) or []
    sport_type = _pick_sport_type(session)
    sport_for_segment = {**sport_type, "displayOrder": sport_type["sportTypeId"]}

    steps: list[dict] = []
    step_order = 1          # global, flat, includes both group + inner step orders
    child_step_id = 1       # increments per RepeatGroup so multiple blocks stay distinct
    total_seconds = 0

    def _exercise_seconds(ex: dict) -> int:
        if ex.get("duration_s"):
            return int(ex["duration_s"])
        # Rough rep-time estimate at 3s/rep — only used for the headline total.
        return int(ex.get("reps", 0) or 0) * 3

    for block in blocks:
        rounds = max(int(block.get("rounds", 1)), 1)
        rest_s = int(block.get("rest_between_rounds_s", 0) or 0)
        exercises = block.get("exercises", [])

        if rounds == 1:
            # Single-pass block — no repeat group; emit exercises flat.
            for ex in exercises:
                emissions = 2 if ex.get("per_side") else 1
                for _ in range(emissions):
                    steps.append(_make_exercise_step(step_order, ex))
                    step_order += 1
                    total_seconds += _exercise_seconds(ex)
            continue

        # Multi-round → wrap in RepeatGroupDTO so the watch shows
        # "Round N of M". Reserve a stepOrder for the group itself
        # before numbering the inner steps.
        group_order = step_order
        step_order += 1
        inner: list[dict] = []
        for ex in exercises:
            emissions = 2 if ex.get("per_side") else 1
            for _ in range(emissions):
                inner_step = _make_exercise_step(step_order, ex)
                inner_step["childStepId"] = child_step_id
                inner.append(inner_step)
                step_order += 1
                total_seconds += _exercise_seconds(ex)
        if rest_s > 0:
            # Rest as the final inner step. With `skipLastRestStep: True`
            # on the group, the watch fires this rest between rounds
            # but skips it after the last round — same UX as our
            # previous flat-emission "insert rest between rounds".
            rest_step = _make_rest_step(step_order, rest_s)
            rest_step["childStepId"] = child_step_id
            inner.append(rest_step)
            step_order += 1

        steps.append({
            "type":                       "RepeatGroupDTO",
            "stepOrder":                  group_order,
            "stepType":                   _STEP_TYPE_REPEAT,
            "childStepId":                child_step_id,
            "numberOfIterations":         rounds,
            "endCondition":               _END_ITERATIONS,
            "endConditionValue":          float(rounds),
            "skipLastRestStep":           True if rest_s > 0 else None,
            "smartRepeat":                False,
            "workoutSteps":               inner,
        })
        child_step_id += 1

        # The inner-step seconds we summed above were for ONE round —
        # multiply by rounds, then add rest * (rounds-1) for the rests
        # that actually fire between rounds.
        round_seconds = sum(_exercise_seconds(ex) * (2 if ex.get("per_side") else 1)
                            for ex in exercises)
        # We already added one round to total_seconds inside the loop above —
        # add the remaining (rounds - 1) passes plus the inter-round rests.
        total_seconds += round_seconds * (rounds - 1)
        total_seconds += rest_s * (rounds - 1)

    # Best-guess duration: ranges from the library are nicer for the
    # estimate. Use the midpoint when summed steps exceed it (gives the
    # runner a realistic ETA).
    est_from_range = (
        ((session.get("duration_min_lo") or 0) + (session.get("duration_min_hi") or 0)) // 2 * 60
    )
    estimated = max(total_seconds, est_from_range)

    return {
        "workoutName":                  session.get("title", "Strength session"),
        "description":                  (session.get("notes") or "")[:1000],
        "locale":                       "en-US",
        "sportType":                    sport_type,
        # Garmin's own syncable yoga/pilates workouts carry
        # ``subSportType: "GENERIC"``; the yoga push was verified with it
        # set. Cardio/hiit circuits sync fine with None, so only the yoga
        # (recovery) path needs it.
        "subSportType":                 "GENERIC" if sport_type is _SPORT_TYPE_YOGA else None,
        # Garmin's device-compatibility validator on Fenix-class watches
        # rejects non-running workouts where ``workoutProvider`` is null.
        # Setting it to "Garmin" matches the working reference shape
        # (Plank Challenge, AMRAP clones, Ab Burner clones — all
        # provider="Garmin", all sync to Fenix 7). The field is opaque
        # provenance metadata; using "Garmin" here doesn't actually
        # attribute the workout to them — it just satisfies the check.
        "workoutProvider":              "Garmin",
        "estimatedDurationInSecs":      int(estimated),
        "estimatedDistanceInMeters":    None,
        "workoutSegments": [
            {
                "segmentOrder": 1,
                "sportType":    sport_for_segment,
                "workoutSteps": steps,
            },
        ],
    }


# ── Push / unpush wiring ──────────────────────────────────────────────

def push_session(
    conn: sqlite3.Connection,
    client,
    session_id: int,
) -> dict:
    """Upload a strength session to Garmin and schedule it on its
    ``planned_date``. Mirrors the running-side ``push_workout_to_garmin``
    flow in plans/service.py: delete any prior Garmin copy first, upload
    fresh, schedule, then stamp our row.

    Upload and scheduling are two separate gates, and they are recorded
    separately:

    * ``garmin_workout_id`` is stamped as soon as the upload succeeds, so a
      retry deletes and replaces that copy instead of uploading a duplicate.
    * ``pushed_at`` is stamped **only** once Garmin confirms the schedule,
      because it means "this is on the watch's calendar on the planned date".

    Returns ``{"workout_id", "session_id", "scheduled", "schedule_error"}``.
    A failed schedule is reported via ``scheduled=False`` rather than raised:
    the upload did happen and must not be rolled back silently. The caller is
    expected to tell the runner, who would otherwise see "Pushed to your
    watch" for a session that never reached the calendar.

    Raises on any Garmin *upload* error so the caller can surface the message.
    """
    # Same race as the running path: serialise per session.
    with push_lock("strength", session_id):
        return _push_session_locked(conn, client, session_id)


def _push_session_locked(conn: sqlite3.Connection, client, session_id: int) -> dict:
    session = service.get_session(conn, session_id)
    if not session:
        raise ValueError("strength session not found")

    payload = build_payload(session)

    # If there's a stale prior push, delete it on Garmin first so we
    # don't accumulate duplicates in the runner's workout library.
    prior = conn.execute(
        "SELECT garmin_workout_id FROM plan_strength_sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    if prior and prior["garmin_workout_id"]:
        # Refuse rather than stack a second copy on the same day. The id stays
        # on the row so a later attempt can still clear it.
        if not release_garmin_copy(client, prior["garmin_workout_id"]):
            raise RuntimeError(
                f"the previous copy of this session (Garmin id "
                f"{prior['garmin_workout_id']}) could not be removed — remove "
                f"it in Garmin Connect, then push again"
            )

    # Generic upload — the `garminconnect` package's helper for
    # sport-typed workouts hits the same endpoint underneath.
    resp = client.upload_workout(payload)
    workout_id = resp.get("workoutId") if isinstance(resp, dict) else None
    if not workout_id:
        raise RuntimeError(
            f"Garmin upload returned no workoutId (keys: "
            f"{list(resp.keys()) if isinstance(resp, dict) else type(resp).__name__})"
        )

    # Schedule on the planned date so it appears on the watch's calendar.
    # Upload and schedule are separate gates; record them separately.
    schedule_error: str | None = None
    try:
        client.schedule_workout(workout_id, session["planned_date"])
    except Exception as exc:  # noqa: BLE001 — report, but don't roll back the upload
        log.warning("schedule failed for workout %s: %s", workout_id, exc)
        schedule_error = str(exc)

    scheduled = schedule_error is None
    if scheduled:
        conn.execute(
            """UPDATE plan_strength_sessions
               SET garmin_workout_id = ?, pushed_at = datetime('now')
               WHERE id = ?""",
            (workout_id, session_id),
        )
    else:
        # pushed_at stays NULL: the session is not on the calendar, and
        # claiming otherwise is exactly the silent failure this guards against.
        # garmin_workout_id is still stamped so a retry replaces this upload
        # rather than adding a second copy.
        conn.execute(
            """UPDATE plan_strength_sessions
               SET garmin_workout_id = ?, pushed_at = NULL
               WHERE id = ?""",
            (workout_id, session_id),
        )
    conn.commit()
    return {
        "workout_id": workout_id,
        "session_id": session_id,
        "scheduled": scheduled,
        "schedule_error": schedule_error,
    }


def unpush_session(
    conn: sqlite3.Connection,
    client,
    session_id: int,
) -> bool:
    """Remove from Garmin and clear our push state.

    Returns True only when the workout is confirmed gone from Garmin. False
    means either there was nothing to remove, or the delete failed — in which
    case ``garmin_workout_id`` and ``pushed_at`` are deliberately left intact.

    Clearing them on a failed delete would report "removed from your watch"
    for a session still sitting on the watch, and discard the only handle left
    to retry; the next push would then add a duplicate instead of replacing.
    """
    row = conn.execute(
        "SELECT garmin_workout_id FROM plan_strength_sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    if not row or not row["garmin_workout_id"]:
        return False
    if not release_garmin_copy(client, row["garmin_workout_id"]):
        log.warning("delete strength workout %s failed; keeping push state",
                    row["garmin_workout_id"])
        return False
    conn.execute(
        "UPDATE plan_strength_sessions SET garmin_workout_id = NULL, "
        "pushed_at = NULL WHERE id = ?",
        (session_id,),
    )
    conn.commit()
    return True
