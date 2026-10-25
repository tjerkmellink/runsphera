"""Moving a workout across a week boundary must re-file it.

`move_workout` updated `planned_date` and `day_of_week` but left
`week_number` alone, while `get_plan_weeks` groups by `week_number`. Moving
Sunday's long run to Monday therefore left it filed under the *previous*
week — where, once that week had elapsed, it rendered behind the "Show N
previous weeks" collapse and looked to the runner like it had vanished.

The swap case was worse: the row already on the destination date moved back
to the vacated one and kept its own week number, so both rows were mis-filed.
Week N ended up spanning eight days with two Mondays, and week N+1 with two
Sundays.

Found by manual testing on 2026-10-24, not by any review round — it needs
someone to actually move a workout and look at the page.
"""
from __future__ import annotations

import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runsphera.db import connect  # noqa: E402
from runsphera.plans import service as plan_service  # noqa: E402
from runsphera.plans.daniels import DanielsVDOT  # noqa: E402
from runsphera.plans.methodology import PlanParams  # noqa: E402

START = date(2026, 11, 2)  # a Monday


def _plan():
    """A real generated Daniels plan in a temp DB."""
    conn = connect(Path(tempfile.mkdtemp()) / "test.db")
    params = PlanParams(
        goal_type="10k", start_date=START,
        race_date=START + timedelta(weeks=10) - timedelta(days=1),
        target_time_s=None, days_per_week=4, long_run_day=6,
        current_vdot=45.0, weekly_km_baseline=30.0, workout_days=[1, 3, 4, 6],
    )
    plan_id = conn.execute(
        "INSERT INTO plans (goal_type, methodology, days_per_week, long_run_day, "
        "title, status) VALUES ('10k','daniels',4,6,'test','active')"
    ).lastrowid
    for w in DanielsVDOT().generate(params):
        conn.execute(
            "INSERT INTO plan_workouts (plan_id, week_number, week_phase, day_of_week,"
            " planned_date, workout_type, title, target_distance_km, target_pace_s_per_km)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (plan_id, w.week_number, w.week_phase, w.day_of_week,
             w.planned_date.isoformat(), w.workout_type, w.title,
             w.target_distance_km, w.target_pace_s_per_km),
        )
    conn.commit()
    return conn, plan_id


def _row(conn, wid):
    return conn.execute(
        "SELECT planned_date, day_of_week, week_number, week_phase "
        "FROM plan_workouts WHERE id = ?", (wid,)
    ).fetchone()


def _sunday_long_run(conn, plan_id, week=1):
    return conn.execute(
        "SELECT id, planned_date, title FROM plan_workouts "
        "WHERE plan_id = ? AND week_number = ? AND day_of_week = 6",
        (plan_id, week),
    ).fetchone()


def test_moving_sunday_to_monday_refiles_into_the_next_week():
    conn, plan_id = _plan()
    sun = _sunday_long_run(conn, plan_id)
    monday = (date.fromisoformat(sun["planned_date"]) + timedelta(days=1)).isoformat()

    plan_service.move_workout(conn, None, sun["id"], monday)

    r = _row(conn, sun["id"])
    assert r["planned_date"] == monday
    assert r["day_of_week"] == 0
    assert r["week_number"] == 2, (
        f"still filed under week {r['week_number']} — it would render behind "
        f"the previous-weeks collapse"
    )


def test_the_swap_partner_refiles_too():
    """Both rows exchange dates, so both must exchange weeks."""
    conn, plan_id = _plan()
    sun = _sunday_long_run(conn, plan_id)
    monday = (date.fromisoformat(sun["planned_date"]) + timedelta(days=1)).isoformat()
    partner = conn.execute(
        "SELECT id FROM plan_workouts WHERE plan_id = ? AND planned_date = ?",
        (plan_id, monday),
    ).fetchone()
    assert partner, "expected a workout already on that Monday"

    plan_service.move_workout(conn, None, sun["id"], monday)

    p = _row(conn, partner["id"])
    assert p["planned_date"] == sun["planned_date"]
    assert p["week_number"] == 1, f"partner left in week {p['week_number']}"


def test_every_week_still_spans_exactly_seven_days():
    """The structural invariant the bug broke."""
    conn, plan_id = _plan()
    sun = _sunday_long_run(conn, plan_id)
    monday = (date.fromisoformat(sun["planned_date"]) + timedelta(days=1)).isoformat()

    plan_service.move_workout(conn, None, sun["id"], monday)

    for wk in plan_service.get_plan_weeks(conn, plan_id):
        dates = sorted(w["planned_date"] for w in wk["workouts"])
        span = (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[0])).days + 1
        assert span == 7, f"week {wk['week_number']} spans {span} days"


def test_no_week_gets_a_duplicate_weekday():
    conn, plan_id = _plan()
    sun = _sunday_long_run(conn, plan_id)
    monday = (date.fromisoformat(sun["planned_date"]) + timedelta(days=1)).isoformat()

    plan_service.move_workout(conn, None, sun["id"], monday)

    for wk in plan_service.get_plan_weeks(conn, plan_id):
        dows = [w["day_of_week"] for w in wk["workouts"]]
        assert len(dows) == len(set(dows)), (
            f"week {wk['week_number']} has duplicate weekdays: {sorted(dows)}"
        )


def test_the_moved_row_adopts_the_destination_week_phase():
    """A row tagged 'base' sitting among 'build' rows misreports the block."""
    conn, plan_id = _plan()
    # Find a Sunday whose following Monday belongs to a different phase.
    for week in range(1, 9):
        sun = _sunday_long_run(conn, plan_id, week=week)
        if not sun:
            continue
        monday = (date.fromisoformat(sun["planned_date"]) + timedelta(days=1)).isoformat()
        nxt = conn.execute(
            "SELECT week_phase FROM plan_workouts WHERE plan_id = ? AND planned_date = ?",
            (plan_id, monday),
        ).fetchone()
        before = _row(conn, sun["id"])
        if nxt and nxt["week_phase"] != before["week_phase"]:
            plan_service.move_workout(conn, None, sun["id"], monday)
            assert _row(conn, sun["id"])["week_phase"] == nxt["week_phase"]
            return
    # No phase boundary in this plan shape — nothing to assert, not a failure.


def test_a_move_within_the_same_week_is_unchanged():
    """The fix must not disturb the ordinary case."""
    conn, plan_id = _plan()
    row = conn.execute(
        "SELECT id, planned_date, week_number FROM plan_workouts "
        "WHERE plan_id = ? AND week_number = 2 AND day_of_week = 1",
        (plan_id,),
    ).fetchone()
    target = (date.fromisoformat(row["planned_date"]) + timedelta(days=1)).isoformat()

    plan_service.move_workout(conn, None, row["id"], target)

    r = _row(conn, row["id"])
    assert r["planned_date"] == target
    assert r["week_number"] == row["week_number"], "same-week move changed the week"


def main():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"{len(fns)} passed")


if __name__ == "__main__":
    main()
