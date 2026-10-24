"""Tests for running_coach.plans.readiness — the 0-100 race-readiness score
behind the countdown card's breakdown popup (2026-08-04).

Focus is the long-run-base component, the only one with non-trivial logic:
it blends "did you run what the plan asked for lately?" against "is that
enough for the race itself?", weighted by how far through the plan we are.
The other four components are single linear interpolations already covered
by their own assertions here at the payload level.

Every test builds a synthetic plan in a temp DB and passes an explicit
`today`, so nothing depends on the real database or the real date.

Run from repo root:
    .venv/Scripts/python.exe tests/test_race_readiness.py
"""
from __future__ import annotations

import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from running_coach.db import connect  # noqa: E402
from running_coach.plans import readiness  # noqa: E402

# A 24-week marathon build: first workout 2026-05-25, race 2026-11-01.
PLAN_START = date(2026, 5, 25)
RACE_DAY   = date(2026, 11, 1)
MARATHON_KM = 42.2

# Mid-plan (~49% in) and race week — the two ends of the progress weighting.
MID_PLAN  = date(2026, 8, 4)
RACE_WEEK = date(2026, 10, 28)


def _fresh_conn():
    tmp = Path(tempfile.mkdtemp()) / "test.db"
    return connect(tmp)


def _make_plan(conn) -> dict:
    cur = conn.execute(
        """INSERT INTO plans (goal_type, methodology, days_per_week, long_run_day,
                              title, race_date, status, created_at)
           VALUES ('marathon', 'daniels', 4, 6, 'Test build', ?, 'active', ?)""",
        (RACE_DAY.isoformat(), f"{PLAN_START.isoformat()} 08:00:00"),
    )
    conn.commit()
    return {"id": cur.lastrowid, "race_date": RACE_DAY.isoformat(),
            "created_at": f"{PLAN_START.isoformat()} 08:00:00"}


def _seed_schedule(conn, plan_id: int, ask_km: float = 12.0) -> None:
    """A weekly long run from the plan's start to race week, none of them
    run. Plan progress is measured from `MIN(planned_date)`, so a plan needs
    its real span in the DB for the weighting to mean anything — a fixture
    with a single workout would look like it started in week 10.
    """
    when = PLAN_START
    while when < RACE_DAY:
        _add_long_run(conn, plan_id, when, asked_km=ask_km)
        when += timedelta(days=7)


def _add_long_run(conn, plan_id: int, when: date, *, asked_km: float,
                  ran_km: float | None = None) -> None:
    """One planned long run, optionally with a matched activity of `ran_km`."""
    actual = None
    if ran_km is not None:
        actual = int(when.strftime("%Y%m%d"))
        conn.execute(
            """INSERT INTO activities
               (activity_id, activity_type, start_time_local, start_time_gmt,
                duration_s, distance_m, raw_json)
               VALUES (?, 'running', ?, ?, 7200, ?, '{}')""",
            (actual, f"{when.isoformat()}T08:00:00", f"{when.isoformat()}T06:00:00",
             ran_km * 1000.0),
        )
    conn.execute(
        """INSERT INTO plan_workouts
           (plan_id, week_number, week_phase, day_of_week, planned_date,
            workout_type, title, target_distance_km, actual_activity_id)
           VALUES (?, 1, 'build', 6, ?, 'long', 'Long run', ?, ?)""",
        (plan_id, when.isoformat(), asked_km, actual),
    )
    conn.commit()


def _longrun(conn, plan, today: date):
    """The long-run-base component only, at a fixed `today`."""
    return readiness._longrun_base_pts(
        conn, MARATHON_KM, plan["id"], today, RACE_DAY)


# ── the absolute ramp (what the race itself demands) ─────────────────────

def test_marathon_target_is_30km() -> None:
    conn = _fresh_conn()
    plan = _make_plan(conn)
    c = _longrun(conn, plan, MID_PLAN)
    assert c["target_km"] == 30.0, c
    # 60% of 30 km — the point below which the absolute half scores zero.
    assert c["floor_km"] == 18.0, c


def test_no_plan_ask_falls_back_to_absolute_ramp() -> None:
    """Nothing due lately → nothing to be relative to → race terms alone."""
    conn = _fresh_conn()
    plan = _make_plan(conn)
    # A 24 km run, but no planned workout in the window to compare against.
    conn.execute(
        """INSERT INTO activities
           (activity_id, activity_type, start_time_local, start_time_gmt,
            duration_s, distance_m, raw_json)
           VALUES (1, 'running', '2026-07-20T08:00:00', '2026-07-20T06:00:00',
                   9000, 24000, '{}')""")
    conn.commit()
    c = _longrun(conn, plan, MID_PLAN)
    assert c["asked_km"] is None, c
    assert c["progress"] is None, c
    # 24 km on the 18→30 ramp = half marks.
    assert abs(c["pts"] - 5.0) < 0.01, c


def test_below_the_floor_scores_zero_on_the_absolute_half() -> None:
    conn = _fresh_conn()
    plan = _make_plan(conn)
    conn.execute(
        """INSERT INTO activities
           (activity_id, activity_type, start_time_local, start_time_gmt,
            duration_s, distance_m, raw_json)
           VALUES (1, 'running', '2026-07-20T08:00:00', '2026-07-20T06:00:00',
                   6000, 16100, '{}')""")
    conn.commit()
    c = _longrun(conn, plan, MID_PLAN)
    assert c["pts"] == 0.0, c


# ── the plan-relative half, and the progress weighting ───────────────────

def test_midplan_credits_keeping_up_with_the_plan() -> None:
    """The reported bug: 16.1 km with the plan asking 17 km read 0/10,
    because it was judged against week 19's 30 km target in week 11."""
    conn = _fresh_conn()
    plan = _make_plan(conn)
    _seed_schedule(conn, plan["id"])
    _add_long_run(conn, plan["id"], date(2026, 7, 26), asked_km=17.0, ran_km=16.1)
    c = _longrun(conn, plan, MID_PLAN)
    assert c["asked_km"] == 17.0, c
    # Relative: 16.1 on the 10.2→17 ramp ≈ 8.7. Absolute: 0 (below 18 km).
    # Mid-plan progress ≈ 0.44 → roughly 4-5 points, not zero.
    assert 4.0 < c["pts"] < 5.0, c
    assert 0.4 < c["progress"] < 0.5, c


def test_race_week_judges_on_race_terms() -> None:
    """Same runner, same 16.1 km, but now it's race week — the absolute
    half dominates and the shortfall shows."""
    conn = _fresh_conn()
    plan = _make_plan(conn)
    _seed_schedule(conn, plan["id"])
    _add_long_run(conn, plan["id"], date(2026, 10, 18), asked_km=17.0, ran_km=16.1)
    c = _longrun(conn, plan, RACE_WEEK)
    assert c["progress"] > 0.9, c
    assert c["pts"] < 1.0, c


def test_plan_that_peaks_short_cannot_score_full_marks() -> None:
    """A plan topping out at 24 km still leaves a visible race-day gap —
    the whole point of keeping the absolute half in the blend."""
    conn = _fresh_conn()
    plan = _make_plan(conn)
    _seed_schedule(conn, plan["id"])
    _add_long_run(conn, plan["id"], date(2026, 10, 4), asked_km=24.0, ran_km=24.0)
    c = _longrun(conn, plan, date(2026, 10, 11))
    assert c["pts"] < 7.0, c  # met the plan in full, still not 10/10


def test_full_marks_when_the_race_target_is_actually_met() -> None:
    conn = _fresh_conn()
    plan = _make_plan(conn)
    _seed_schedule(conn, plan["id"])
    _add_long_run(conn, plan["id"], date(2026, 10, 4), asked_km=30.0, ran_km=31.0)
    c = _longrun(conn, plan, date(2026, 10, 11))
    assert c["pts"] == 10.0, c


def test_future_workouts_do_not_count_as_asked() -> None:
    """A long run scheduled for Sunday shouldn't set the bar on Friday."""
    conn = _fresh_conn()
    plan = _make_plan(conn)
    _add_long_run(conn, plan["id"], MID_PLAN + timedelta(days=2), asked_km=28.0)
    c = _longrun(conn, plan, MID_PLAN)
    assert c["asked_km"] is None, c


def test_no_race_distance_scores_neutral_half_marks() -> None:
    conn = _fresh_conn()
    plan = _make_plan(conn)
    c = readiness._longrun_base_pts(conn, None, plan["id"], MID_PLAN, RACE_DAY)
    assert c["pts"] == 5.0 and c["estimated"] is True, c


# ── the assembled payload ────────────────────────────────────────────────

def test_payload_components_sum_to_the_score() -> None:
    conn = _fresh_conn()
    plan = _make_plan(conn)
    _seed_schedule(conn, plan["id"])
    _add_long_run(conn, plan["id"], date(2026, 7, 26), asked_km=17.0, ran_km=16.1)
    r = readiness.race_readiness(
        conn, plan, {"chosen_distance_km": MARATHON_KM}, today=MID_PLAN)
    assert r is not None
    total = sum(c["pts"] for c in r["components"].values())
    assert abs(total - r["score"]) <= 0.5, (total, r["score"])
    assert set(r["thresholds"]) == {"on_track", "building", "behind"}, r["thresholds"]
    for name, c in r["components"].items():
        assert 0 <= c["pts"] <= c["max"], (name, c)


def test_hidden_while_the_plan_is_too_young() -> None:
    conn = _fresh_conn()
    plan = _make_plan(conn)
    just_started = PLAN_START + timedelta(days=3)
    assert readiness.race_readiness(
        conn, plan, {"chosen_distance_km": MARATHON_KM}, today=just_started) is None


def test_hidden_once_the_race_is_past_the_recap_window() -> None:
    conn = _fresh_conn()
    plan = _make_plan(conn)
    assert readiness.race_readiness(
        conn, plan, {"chosen_distance_km": MARATHON_KM},
        today=RACE_DAY + timedelta(days=3)) is None


TESTS = [
    test_marathon_target_is_30km,
    test_no_plan_ask_falls_back_to_absolute_ramp,
    test_below_the_floor_scores_zero_on_the_absolute_half,
    test_midplan_credits_keeping_up_with_the_plan,
    test_race_week_judges_on_race_terms,
    test_plan_that_peaks_short_cannot_score_full_marks,
    test_full_marks_when_the_race_target_is_actually_met,
    test_future_workouts_do_not_count_as_asked,
    test_no_race_distance_scores_neutral_half_marks,
    test_payload_components_sum_to_the_score,
    test_hidden_while_the_plan_is_too_young,
    test_hidden_once_the_race_is_past_the_recap_window,
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
