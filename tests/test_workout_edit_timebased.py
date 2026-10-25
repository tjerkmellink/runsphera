"""Lock-down tests for time-based manual edits (2026-07-18).

Origin: user bug report — opening "Manual edit" on a Couch to 5K week-1
session showed a distance/pace interval form whose grey placeholders
(2.0 km / 1.0 km / 3:50/km) read as real values, and saving would have
required inventing a distance + pace, converting the paceless run/walk
session into a Daniels-style interval workout. The steps strip likewise
rendered the 1-minute run blocks as "0 km".

The edit path now has time-based branches: run/walk repeats and continuous
runs are edited as durations, the rebuilt structure stays duration-only,
and no distance/pace targets ever appear.

Run from repo root:
    .venv/Scripts/python.exe tests/test_workout_edit_timebased.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runsphera.db import connect  # noqa: E402
from runsphera.plans import service as plan_service  # noqa: E402
from runsphera.plans.service import _derive_title  # noqa: E402


def _fresh_conn():
    tmp = Path(tempfile.mkdtemp()) / "test.db"
    return connect(tmp)


def _create_c25k_plan(conn) -> int:
    return plan_service.create_plan(
        conn,
        goal_type="5k",
        methodology_id="c25k",
        race_date=None,
        target_time_s=None,
        days_per_week=3,
        long_run_day=5,
        workout_days=[1, 3, 5],
    )


def _row(conn, plan_id: int, week: int, wtype: str) -> dict:
    r = conn.execute(
        "SELECT * FROM plan_workouts WHERE plan_id = ? AND week_number = ? "
        "AND workout_type = ? ORDER BY day_of_week LIMIT 1",
        (plan_id, week, wtype),
    ).fetchone()
    assert r, f"no {wtype} row in week {week}"
    return dict(r)


def test_edit_runwalk_repeats_stays_paceless() -> None:
    conn = _fresh_conn()
    plan_id = _create_c25k_plan(conn)
    pw = _row(conn, plan_id, 1, "intervals")

    result = plan_service.edit_workout(
        conn, None, pw["id"],
        workout_type="intervals",
        intervals_iterations=6,
        intervals_work_s=90,
        intervals_recovery_s=60,
        intervals_warmup_s=300,
        intervals_cooldown_s=300,
    )
    to = result["to"]
    assert to["target_distance_km"] is None, "edit must not invent a distance"
    assert to["target_pace_s_per_km"] is None, "edit must not invent a pace"
    assert to["target_duration_s"] == 300 + 6 * (90 + 60) + 300

    structure = json.loads(to["workout_structure"])
    steps = structure["steps"]
    assert steps[0] == {"type": "warmup", "end": {"duration_s": 300}}
    assert steps[-1] == {"type": "cooldown", "end": {"duration_s": 300}}
    repeat = steps[1]
    assert repeat["iterations"] == 6
    assert repeat["steps"][0] == {"type": "active", "end": {"duration_s": 90}}
    assert repeat["steps"][1] == {"type": "recovery", "end": {"duration_s": 60}}
    assert to["title"] == "Run/walk 6×(90 s run / 1 min walk)", to["title"]


def test_edit_continuous_run_stays_paceless() -> None:
    conn = _fresh_conn()
    plan_id = _create_c25k_plan(conn)
    pw = _row(conn, plan_id, 7, "easy")

    result = plan_service.edit_workout(
        conn, None, pw["id"],
        workout_type="easy",
        simple_warmup_s=300,
        simple_run_s=1680,
        simple_cooldown_s=300,
    )
    to = result["to"]
    assert to["target_distance_km"] is None
    assert to["target_pace_s_per_km"] is None
    assert to["target_duration_s"] == 300 + 1680 + 300
    assert to["title"] == "Run 28 min", to["title"]
    steps = json.loads(to["workout_structure"])["steps"]
    assert [s["type"] for s in steps] == ["warmup", "active", "cooldown"]
    assert steps[1]["end"] == {"duration_s": 1680}
    assert all("pace_s_per_km" not in s for s in steps)


def test_km_based_daniels_edit_unchanged() -> None:
    """Regression: the distance/pace edit path is untouched."""
    conn = _fresh_conn()
    plan_id = plan_service.create_plan(
        conn,
        goal_type="10k",
        methodology_id="daniels",
        race_date=None,
        target_time_s=None,
        days_per_week=4,
        long_run_day=6,
        workout_days=[1, 3, 4, 6],
    )
    r = conn.execute(
        "SELECT * FROM plan_workouts WHERE plan_id = ? AND workout_type = 'intervals' "
        "AND workout_structure IS NOT NULL ORDER BY planned_date LIMIT 1",
        (plan_id,),
    ).fetchone()
    assert r, "expected an intervals session in the 10k plan"
    pw = dict(r)
    result = plan_service.edit_workout(
        conn, None, pw["id"],
        workout_type="intervals",
        intervals_warmup_km=2.0,
        intervals_iterations=4,
        intervals_work_km=1.0,
        intervals_work_pace_s=270,
        intervals_recovery_s=120,
        intervals_cooldown_km=2.0,
    )
    to = result["to"]
    # 2 km warm-up + 4x1 km + 2 km cool-down = 8 km of *measured* steps, plus
    # 4x120 s of recovery jogging. The runner covers that ground too, so the
    # headline counts it at an easy default pace: 8 + 4*(120/360) = 9.33 km.
    # Reporting 8.0 understated every interval session's contribution to
    # weekly volume — see the 2026-10-24 review finding.
    assert to["target_distance_km"] == 9.33, to["target_distance_km"]
    assert to["target_pace_s_per_km"] == 270
    assert to["title"] == "Intervals 4×1000 m"
    repeat = json.loads(to["workout_structure"])["steps"][1]
    assert repeat["steps"][0]["end"] == {"distance_m": 1000}
    assert repeat["steps"][0]["pace_s_per_km"] == 270


def test_derive_title_timebased_shapes() -> None:
    rw = {
        "steps": [
            {"type": "warmup", "end": {"duration_s": 300}},
            {"type": "repeat", "iterations": 8, "steps": [
                {"type": "active", "end": {"duration_s": 60}},
                {"type": "recovery", "end": {"duration_s": 90}},
            ]},
            {"type": "cooldown", "end": {"duration_s": 300}},
        ]
    }
    assert _derive_title("intervals", None, rw) == "Run/walk 8×(1 min run / 90 s walk)"
    # No recovery step → no walk suffix.
    rw_norec = {"steps": [{"type": "repeat", "iterations": 4, "steps": [
        {"type": "active", "end": {"duration_s": 120}},
    ]}]}
    assert _derive_title("intervals", None, rw_norec) == "Run/walk 4×2 min"
    cont = {"steps": [
        {"type": "warmup", "end": {"duration_s": 300}},
        {"type": "active", "end": {"duration_s": 1500}},
        {"type": "cooldown", "end": {"duration_s": 300}},
    ]}
    assert _derive_title("easy", None, cont) == "Run 25 min"
    # Distance-based shapes keep their historical titles.
    assert _derive_title("easy", 8.0, None) == "Easy 8 km"


TESTS = [
    test_edit_runwalk_repeats_stays_paceless,
    test_edit_continuous_run_stays_paceless,
    test_km_based_daniels_edit_unchanged,
    test_derive_title_timebased_shapes,
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
