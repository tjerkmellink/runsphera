"""Lock-down tests for per-segment editing of multi-pace long runs (2026-07-22).

Origin: user request — a Daniels peak marathon long run ("First 16 km easy,
last 8 km @ M pace") is stored as a two-segment zone-tagged structure and the
read-only Steps strip shows both paces, but the Manual edit form collapsed it
to a single distance/pace pair. Editing the distance silently dropped the
M-pace finish.

The edit path now has a progression branch: easy/long/recovery workouts with
two or more distance-based active segments are edited one row per segment
(`segments=[{km, pace_s_per_km, zone}, ...]`), the structure is rebuilt, the
zone tags survive (so the pace recalibrator keeps working), and the totals +
title are re-derived from the new shape.

Run from repo root:
    .venv/Scripts/python.exe tests/test_workout_edit_progression.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from running_coach.db import connect  # noqa: E402
from running_coach.plans import service as plan_service  # noqa: E402
from running_coach.plans.service import (  # noqa: E402
    _build_progression_structure,
    _derive_title,
)


def _fresh_conn():
    tmp = Path(tempfile.mkdtemp()) / "test.db"
    return connect(tmp)


def _create_marathon_plan(conn) -> int:
    return plan_service.create_plan(
        conn,
        goal_type="marathon",
        methodology_id="daniels",
        race_date=None,
        target_time_s=None,
        days_per_week=4,
        long_run_day=6,
        workout_days=[1, 3, 4, 6],
    )


def _peak_long_run(conn, plan_id: int) -> dict:
    """The first peak-phase long run carrying a multi-segment (E+M) structure."""
    rows = conn.execute(
        "SELECT * FROM plan_workouts WHERE plan_id = ? AND workout_type = 'long' "
        "AND week_phase = 'peak' AND workout_structure IS NOT NULL "
        "ORDER BY planned_date",
        (plan_id,),
    ).fetchall()
    assert rows, "expected a peak marathon long run with a structure"
    return dict(rows[0])


def test_seed_has_two_zoned_segments() -> None:
    """Sanity: the engine really does emit the two-segment shape this feature
    edits, so the rest of the test is exercising a real workout."""
    conn = _fresh_conn()
    plan_id = _create_marathon_plan(conn)
    pw = _peak_long_run(conn, plan_id)
    steps = json.loads(pw["workout_structure"])["steps"]
    active = [s for s in steps if s["type"] == "active" and s.get("end", {}).get("distance_m")]
    assert len(active) == 2, f"expected 2 active segments, got {len(active)}"
    assert active[0]["zone"] == "E" and active[1]["zone"] == "M"


def test_edit_segments_rebuilds_structure_and_preserves_zones() -> None:
    conn = _fresh_conn()
    plan_id = _create_marathon_plan(conn)
    pw = _peak_long_run(conn, plan_id)

    # Stretch the easy block and the M-pace finish, and nudge the M pace.
    result = plan_service.edit_workout(
        conn, None, pw["id"],
        workout_type="long",
        segments=[
            {"km": 18.0, "pace_s_per_km": 383, "zone": "E"},
            {"km": 10.0, "pace_s_per_km": 320, "zone": "M"},
        ],
    )
    to = result["to"]

    steps = json.loads(to["workout_structure"])["steps"]
    assert len(steps) == 2, steps
    assert steps[0] == {"type": "active", "zone": "E",
                        "end": {"distance_m": 18000}, "pace_s_per_km": 383}
    assert steps[1] == {"type": "active", "zone": "M",
                        "end": {"distance_m": 10000}, "pace_s_per_km": 320}

    # Totals derive from the structure; headline pace is the easy lead-in.
    assert to["target_distance_km"] == 28.0, to["target_distance_km"]
    assert to["target_pace_s_per_km"] == 383
    assert to["target_duration_s"] == int(18 * 383 + 10 * 320)
    # Title keeps the M-pace finish visible.
    assert to["title"] == "Long 28 km incl. 10 km @ M pace", to["title"]


class _DeletesOk:
    """Garmin client double that confirms the delete."""

    def __init__(self):
        self.deleted = []

    def delete_workout(self, wid):
        self.deleted.append(wid)

    def upload_running_workout(self, obj):  # pragma: no cover — re-push path
        return {"workoutId": 1234}

    def schedule_workout(self, wid, date):  # pragma: no cover
        pass


def _pushed_peak_long_run(conn, plan_id):
    pw = _peak_long_run(conn, plan_id)
    conn.execute(
        "UPDATE plan_workouts SET garmin_workout_id = 999, pushed_at = '2026-01-01' WHERE id = ?",
        (pw["id"],),
    )
    conn.commit()
    return pw


_SEGMENTS = [
    {"km": 16.0, "pace_s_per_km": 383, "zone": "E"},
    {"km": 8.0, "pace_s_per_km": 323, "zone": "M"},
]


def test_edit_segments_clears_push_state_once_garmin_confirms() -> None:
    """A segment edit clears the Garmin push state like any other edit —
    but only once the old copy is confirmed off the watch."""
    conn = _fresh_conn()
    plan_id = _create_marathon_plan(conn)
    pw = _pushed_peak_long_run(conn, plan_id)
    client = _DeletesOk()

    result = plan_service.edit_workout(
        conn, client, pw["id"], workout_type="long", segments=_SEGMENTS,
    )

    assert client.deleted == [999], "old Garmin copy was never deleted"
    assert result["garmin_stale"] is False
    # Re-pushed under a new id, so the row is pushed again rather than blank.
    assert result["to"]["garmin_workout_id"] != 999


def test_edit_segments_retains_id_when_garmin_unreachable() -> None:
    """With no authenticated client the old workout is still on the watch.

    Clearing the id here would strand it there permanently — nothing left to
    retry the delete with, and the next push would add a second copy rather
    than replace it. Regression guard for the 2026-10-24 review finding.
    """
    conn = _fresh_conn()
    plan_id = _create_marathon_plan(conn)
    pw = _pushed_peak_long_run(conn, plan_id)

    result = plan_service.edit_workout(
        conn, None, pw["id"], workout_type="long", segments=_SEGMENTS,
    )

    to = result["to"]
    assert to["garmin_workout_id"] == 999, "retry handle was thrown away"
    # pushed_at must NOT survive. The watch holds the *pre-edit* prescription,
    # so a row reading as synchronised is a lie — and once pushes became
    # idempotent (round 4), that lie made every later push a no-op, stranding
    # the old shape on the watch permanently. Keeping the id without
    # pushed_at is what routes the next push through the stranded-upload path,
    # which releases the old copy and uploads the edited one.
    assert to["pushed_at"] is None, "row still claims the edit is on the watch"
    assert result["garmin_stale"] is True
    # The edit itself still applied locally.
    assert to["target_distance_km"] == 24.0, to["target_distance_km"]


def test_single_segment_falls_through_to_simple() -> None:
    """One segment is not a progression — the branch must not swallow it, so a
    plain distance/pace edit still behaves as before."""
    conn = _fresh_conn()
    plan_id = _create_marathon_plan(conn)
    pw = _peak_long_run(conn, plan_id)

    result = plan_service.edit_workout(
        conn, None, pw["id"],
        workout_type="long",
        target_distance_km=20.0,
        target_pace_s_per_km=360,
        segments=[{"km": 20.0, "pace_s_per_km": 360, "zone": "E"}],
    )
    to = result["to"]
    # Simple path: flat long run, structure dropped (E+M shape no longer applies).
    assert to["target_distance_km"] == 20.0
    assert to["target_pace_s_per_km"] == 360
    assert to["workout_structure"] is None
    assert to["title"] == "Long 20 km", to["title"]


def test_build_progression_structure_drops_empty_segments() -> None:
    s = _build_progression_structure([
        {"km": 16.0, "pace_s_per_km": 383, "zone": "E"},
        {"km": None, "pace_s_per_km": 320, "zone": "M"},  # dropped
        {"km": 8.0, "pace_s_per_km": 323, "zone": "M"},
    ])
    assert [st["end"]["distance_m"] for st in s["steps"]] == [16000, 8000]


def test_derive_title_progression_shape() -> None:
    structure = {"steps": [
        {"type": "active", "zone": "E", "end": {"distance_m": 16000}, "pace_s_per_km": 383},
        {"type": "active", "zone": "M", "end": {"distance_m": 8000}, "pace_s_per_km": 323},
    ]}
    assert _derive_title("long", 24.0, structure) == "Long 24 km incl. 8 km @ M pace"


TESTS = [
    test_seed_has_two_zoned_segments,
    test_edit_segments_rebuilds_structure_and_preserves_zones,
    test_edit_segments_clears_push_state_once_garmin_confirms,
    test_edit_segments_retains_id_when_garmin_unreachable,
    test_single_segment_falls_through_to_simple,
    test_build_progression_structure_drops_empty_segments,
    test_derive_title_progression_shape,
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
