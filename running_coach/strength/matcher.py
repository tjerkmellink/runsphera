"""Link completed Garmin "strength_training" / "mobility" activities to
their scheduled `plan_strength_sessions` row.

Strategy: **strict workout-id echo only.** When we push a strength
session to Garmin, we get back a `workoutId` (stored in
``plan_strength_sessions.garmin_workout_id``). When the runner
completes that session on the watch, Garmin's activity payload echoes
the same `workoutId` field back inside the activity's raw JSON. We
match on that exact ID — no fuzzy date or activity-type fallback,
because:

- Strict matching never misattributes an unrelated gym session to a
  scheduled session — only sessions the runner actually pushed + did
  via the watch's guided flow count.
- Date+type fallback would silently mark a manual gym session as
  "completed" against our prescription. The scheduled session is
  about *doing the prescribed work*; an unrelated strength activity
  shouldn't satisfy it.
- Manual *Mark complete* in the modal is always available as the
  escape hatch when the runner did the session without pushing it.

Runs at the end of `ingest_activities` (same place as the running
matcher). Idempotent — re-running it produces the same links.
"""
from __future__ import annotations

import json
import logging
import sqlite3

log = logging.getLogger(__name__)


# Activity types that *could* match a strength session. The watch
# classifies the completed activity from the pushed sportType, and per
# the Fenix-compatibility quirk we push bodyweight circuits as
# `cardio_training` (id 6) / `hiit` (id 9) / `yoga` (id 7, recovery) —
# Garmin then logs those as "indoor_cardio", "hiit", "yoga", "pilates",
# "mobility" (legacy pushes), etc. depending on its own categorization.
# The matcher
# accepts all of them because the workoutId echo is what actually drives
# the link — the type filter just narrows the candidate pool so we don't
# parse raw_json for every running activity.
_CANDIDATE_TYPES = (
    "strength_training",
    "mobility",
    "yoga",
    "pilates",
    "cardio_training",
    "indoor_cardio",
    "hiit",
)


def match_strength_sessions(conn: sqlite3.Connection) -> dict[str, int]:
    """Iterate strength-flavored activities, parse `workoutId` from each
    raw_json, and link to the matching `plan_strength_sessions` row
    when one exists with that `garmin_workout_id`.

    Returns: `{"matched": int, "skipped_already": int, "scanned": int}`.
    """
    placeholders = ",".join(["?"] * len(_CANDIDATE_TYPES))
    rows = conn.execute(
        f"""SELECT a.activity_id, a.raw_json
            FROM activities a
            WHERE a.activity_type IN ({placeholders})""",
        _CANDIDATE_TYPES,
    ).fetchall()

    matched = 0
    skipped_already = 0
    scanned = 0
    for row in rows:
        scanned += 1
        try:
            payload = json.loads(row["raw_json"]) if row["raw_json"] else {}
        except (TypeError, ValueError):
            continue
        wid = payload.get("workoutId")
        if not wid:
            continue

        # Look up the scheduled session by garmin_workout_id. The unique
        # constraint on (plan_id, planned_date) means at most one
        # session links to one Garmin workoutId.
        sess = conn.execute(
            """SELECT id, actual_activity_id
               FROM plan_strength_sessions
               WHERE garmin_workout_id = ?""",
            (int(wid),),
        ).fetchone()
        if not sess:
            continue

        if sess["actual_activity_id"] == row["activity_id"]:
            skipped_already += 1
            continue

        conn.execute(
            """UPDATE plan_strength_sessions
                  SET actual_activity_id = ?,
                      completed_at       = COALESCE(completed_at, datetime('now'))
                WHERE id = ?""",
            (row["activity_id"], sess["id"]),
        )
        matched += 1
        log.info(
            "matched strength session id=%s with activity %s (garmin workoutId=%s)",
            sess["id"], row["activity_id"], wid,
        )

    conn.commit()
    return {"matched": matched, "skipped_already": skipped_already, "scanned": scanned}
