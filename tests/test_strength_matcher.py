"""Tests for the strength-session activity matcher.

The matcher is strict: an activity matches a scheduled session only
when Garmin's raw activity payload echoes back the same `workoutId`
we stored on the session at push time. No fuzzy date/type fallback —
manual *Mark complete* in the modal is the escape hatch for sessions
the runner did without pushing.

Run with:
    .venv/Scripts/python.exe tests/test_strength_matcher.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _fresh_db():
    """Spin up a fresh SQLite DB in a temp file so we don't touch the
    real one. Returns (conn, path)."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.environ["RUNNING_COACH_DB"] = path
    from running_coach.db import connect
    return connect(), path


def _make_plan(conn) -> int:
    cur = conn.execute(
        """INSERT INTO plans
           (goal_type, methodology, days_per_week, long_run_day, status, title)
           VALUES ('marathon', 'daniels', 5, 6, 'active', 'test plan')"""
    )
    return cur.lastrowid


def _make_strength_session(
    conn, plan_id: int, planned_date: str, garmin_workout_id: int | None = None
) -> int:
    """Create a plan_strength_sessions row keyed to the first library
    workout. Optionally seed `garmin_workout_id` to simulate a pushed
    session."""
    sw_id = conn.execute(
        "SELECT id FROM strength_workouts ORDER BY id LIMIT 1"
    ).fetchone()["id"]
    cur = conn.execute(
        """INSERT INTO plan_strength_sessions
           (plan_id, strength_workout_id, planned_date, garmin_workout_id, pushed_at)
           VALUES (?, ?, ?, ?, CASE WHEN ? IS NOT NULL THEN datetime('now') END)""",
        (plan_id, sw_id, planned_date, garmin_workout_id, garmin_workout_id),
    )
    return cur.lastrowid


def _make_activity(
    conn,
    activity_id: int,
    activity_type: str,
    raw: dict,
    start_local: str = "2030-01-06 10:00:00",
) -> None:
    """Stamp a synthetic activity row with the given raw_json. The
    matcher reads `workoutId` from this column."""
    conn.execute(
        """INSERT INTO activities
           (activity_id, activity_type, start_time_local, start_time_gmt, raw_json)
           VALUES (?, ?, ?, ?, ?)""",
        (activity_id, activity_type, start_local, start_local, json.dumps(raw)),
    )
    conn.commit()


def _link(conn, session_id: int):
    return conn.execute(
        "SELECT actual_activity_id, completed_at "
        "FROM plan_strength_sessions WHERE id = ?", (session_id,)
    ).fetchone()


# ── Tests ─────────────────────────────────────────────────────────

def test_matches_via_workout_id_echo():
    """Activity with workoutId == session.garmin_workout_id → linked."""
    conn, _ = _fresh_db()
    plan = _make_plan(conn)
    sess = _make_strength_session(conn, plan, "2030-01-06", garmin_workout_id=999111)
    _make_activity(conn, 1234, "strength_training",
                   {"workoutId": 999111, "activityId": 1234})

    from running_coach.strength import matcher
    result = matcher.match_strength_sessions(conn)
    assert result["matched"] == 1, f"expected 1 match, got {result}"
    row = _link(conn, sess)
    assert row["actual_activity_id"] == 1234
    assert row["completed_at"] is not None, "completed_at should be auto-stamped"


def test_ignores_unrelated_strength_activity():
    """Activity with a different workoutId → not linked, even on same date."""
    conn, _ = _fresh_db()
    plan = _make_plan(conn)
    sess = _make_strength_session(conn, plan, "2030-01-06", garmin_workout_id=999111)
    _make_activity(conn, 5678, "strength_training",
                   {"workoutId": 222222, "activityId": 5678})

    from running_coach.strength import matcher
    result = matcher.match_strength_sessions(conn)
    assert result["matched"] == 0, f"expected 0 matches, got {result}"
    assert _link(conn, sess)["actual_activity_id"] is None


def test_ignores_activity_with_no_workout_id():
    """Manual gym session (no workoutId) → not linked."""
    conn, _ = _fresh_db()
    plan = _make_plan(conn)
    sess = _make_strength_session(conn, plan, "2030-01-06", garmin_workout_id=999111)
    # Note: workoutId absent from the raw payload
    _make_activity(conn, 9999, "strength_training", {"activityId": 9999})

    from running_coach.strength import matcher
    result = matcher.match_strength_sessions(conn)
    assert result["matched"] == 0
    assert _link(conn, sess)["actual_activity_id"] is None


def test_skips_already_matched():
    """Re-running the matcher with the same data → no new matches,
    counts the existing link as skipped_already, no re-stamp."""
    conn, _ = _fresh_db()
    plan = _make_plan(conn)
    sess = _make_strength_session(conn, plan, "2030-01-06", garmin_workout_id=999111)
    _make_activity(conn, 1234, "strength_training",
                   {"workoutId": 999111, "activityId": 1234})

    from running_coach.strength import matcher
    first = matcher.match_strength_sessions(conn)
    assert first["matched"] == 1

    second = matcher.match_strength_sessions(conn)
    assert second["matched"] == 0
    assert second["skipped_already"] == 1


def test_unscheduled_session_session_no_op():
    """Activity with a workoutId that doesn't match any scheduled
    session → not an error, just not linked."""
    conn, _ = _fresh_db()
    _make_plan(conn)  # plan exists but no session
    _make_activity(conn, 7777, "strength_training",
                   {"workoutId": 11111111, "activityId": 7777})

    from running_coach.strength import matcher
    result = matcher.match_strength_sessions(conn)
    assert result["matched"] == 0


def test_picks_up_mobility_activity_type():
    """Recovery sessions push as `sportType: mobility`, so the watch
    may classify them as 'mobility' instead of 'strength_training'.
    The matcher needs to scan both."""
    conn, _ = _fresh_db()
    plan = _make_plan(conn)
    sess = _make_strength_session(conn, plan, "2030-01-06", garmin_workout_id=999111)
    _make_activity(conn, 8888, "mobility", {"workoutId": 999111, "activityId": 8888})

    from running_coach.strength import matcher
    result = matcher.match_strength_sessions(conn)
    assert result["matched"] == 1, f"mobility type should match too, got {result}"
    assert _link(conn, sess)["actual_activity_id"] == 8888


def test_preserves_manual_completed_at():
    """If the runner manually marked the session done BEFORE the
    activity synced, the matcher links the activity but doesn't
    overwrite the existing completed_at timestamp."""
    conn, _ = _fresh_db()
    plan = _make_plan(conn)
    sess = _make_strength_session(conn, plan, "2030-01-06", garmin_workout_id=999111)
    # Simulate a manual mark-complete that ran earlier in the day.
    conn.execute(
        "UPDATE plan_strength_sessions SET completed_at = '2030-01-06 08:00:00' WHERE id = ?",
        (sess,),
    )
    conn.commit()
    _make_activity(conn, 1234, "strength_training",
                   {"workoutId": 999111, "activityId": 1234})

    from running_coach.strength import matcher
    matcher.match_strength_sessions(conn)
    row = _link(conn, sess)
    assert row["actual_activity_id"] == 1234
    # Manual timestamp preserved via COALESCE in the UPDATE.
    assert row["completed_at"] == "2030-01-06 08:00:00"


# ──────────────────────────────────────────────────────────────────

TESTS = [
    test_matches_via_workout_id_echo,
    test_ignores_unrelated_strength_activity,
    test_ignores_activity_with_no_workout_id,
    test_skips_already_matched,
    test_unscheduled_session_session_no_op,
    test_picks_up_mobility_activity_type,
    test_preserves_manual_completed_at,
]


def main() -> int:
    failed = 0
    for fn in TESTS:
        try:
            fn()
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL  {fn.__name__}\n        {exc}")
        else:
            print(f"  ok    {fn.__name__}")
    print()
    if failed:
        print(f"{failed} / {len(TESTS)} failed")
        return 1
    print(f"{len(TESTS)} / {len(TESTS)} passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
