"""Tests for the Garmin-less onboarding contracts.

Contract under test: plan seeding follows the precedence ladder
Garmin-measured → manually entered → default, and reports where each value
came from (`vdot_source` / `weekly_km_source`); race goals no longer need a
race date (a goal date is synthesized on the final week's long-run day);
race-specific imported plans (Foppen) still require one; `start_date` lets
a plan start in the current week.

Run from repo root:
    .venv/Scripts/python.exe tests/test_garmin_less_onboarding.py
"""
from __future__ import annotations

import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from running_coach import settings as app_settings  # noqa: E402
from running_coach.db import connect  # noqa: E402
from running_coach.plans import service as plan_service  # noqa: E402


def _fresh_conn():
    tmp = Path(tempfile.mkdtemp()) / "test.db"
    return connect(tmp)


def _this_monday() -> date:
    today = date.today()
    return today - timedelta(days=today.weekday())


def _insert_garmin_vdot(conn, vdot: float):
    conn.execute(
        "INSERT INTO training_status (calendar_date, vo2max_precise, raw_json) "
        "VALUES (?, ?, '{}')",
        (date.today().isoformat(), vdot),
    )
    conn.commit()


def _insert_recent_runs(conn, total_km: float):
    """Spread `total_km` of running over the last 4 complete weeks."""
    monday = _this_monday()
    per_run = total_km / 4
    for i in range(4):
        day = monday - timedelta(weeks=i + 1)
        conn.execute(
            "INSERT INTO activities (activity_id, activity_type, start_time_local, "
            "start_time_gmt, distance_m, raw_json) VALUES (?, 'running', ?, ?, ?, '{}')",
            (9000 + i, f"{day.isoformat()}T08:00:00", f"{day.isoformat()}T07:00:00",
             per_run * 1000),
        )
    conn.commit()


# ── Seed precedence ────────────────────────────────────────────────────

def test_seed_defaults_on_fresh_db():
    conn = _fresh_conn()
    seed = plan_service.get_plan_seed(conn)
    assert seed["current_vdot"] == 45.0, seed
    assert seed["vdot_source"] == "default", seed
    assert seed["weekly_km_baseline"] == 25.0, seed
    assert seed["weekly_km_source"] == "default", seed
    assert seed["vdot_note"] is None, seed


def test_seed_uses_manual_baseline():
    conn = _fresh_conn()
    app_settings.set_manual_vdot(conn, 48.3, note="10 km in 47:30")
    app_settings.set_manual_weekly_km(conn, 32)
    seed = plan_service.get_plan_seed(conn)
    assert seed["current_vdot"] == 48.3, seed
    assert seed["vdot_source"] == "manual", seed
    assert seed["vdot_note"] == "10 km in 47:30", seed
    assert seed["weekly_km_baseline"] == 32.0, seed
    assert seed["weekly_km_source"] == "manual", seed


def test_garmin_outranks_manual():
    conn = _fresh_conn()
    app_settings.set_manual_vdot(conn, 48.3, note="10 km in 47:30")
    app_settings.set_manual_weekly_km(conn, 32)
    _insert_garmin_vdot(conn, 51.2)
    _insert_recent_runs(conn, total_km=160)  # 40 km/week measured
    seed = plan_service.get_plan_seed(conn)
    assert seed["current_vdot"] == 51.2, seed
    assert seed["vdot_source"] == "garmin", seed
    assert seed["vdot_note"] is None, seed
    assert seed["weekly_km_baseline"] == 40.0, seed
    assert seed["weekly_km_source"] == "garmin", seed


def test_manual_setters_validate_ranges():
    conn = _fresh_conn()
    for bad in (19, 86):
        try:
            app_settings.set_manual_vdot(conn, bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"set_manual_vdot({bad}) should raise")
    try:
        app_settings.set_manual_weekly_km(conn, 301)
    except ValueError:
        pass
    else:
        raise AssertionError("set_manual_weekly_km(301) should raise")


def test_race_estimator_matches_known_point():
    # Daniels' tables: 10k in ~50:00 ≈ VDOT 40 (±1).
    vdot = plan_service.estimate_vdot_from_race(10000, 50 * 60)
    assert 39 <= vdot <= 41, vdot


# ── Optional race date ────────────────────────────────────────────────

def test_daniels_plan_without_race_date():
    conn = _fresh_conn()
    plan_id = plan_service.create_plan(
        conn,
        goal_type="half_marathon",
        methodology_id="daniels",
        race_date=None,
        target_time_s=None,
        days_per_week=4,
        long_run_day=6,
        workout_days=[1, 3, 5, 6],
    )
    plan = plan_service.get_plan(conn, plan_id)
    assert plan["race_date"] is not None, "goal date should be synthesized"
    assert "-week build" in plan["title"], plan["title"]
    rows = conn.execute(
        "SELECT MAX(week_number) AS weeks FROM plan_workouts WHERE plan_id = ?",
        (plan_id,),
    ).fetchone()
    assert rows["weeks"] >= 8, rows["weeks"]
    # The synthesized goal date is the final week's long-run day (Sunday).
    assert date.fromisoformat(plan["race_date"]).weekday() == 6, plan["race_date"]
    race_row = conn.execute(
        "SELECT COUNT(*) AS n FROM plan_workouts "
        "WHERE plan_id = ? AND workout_type = 'race'",
        (plan_id,),
    ).fetchone()
    assert race_row["n"] == 1, "the synthesized goal date should carry the race-day finale"


def test_higdon_plan_without_race_date_runs_full_length():
    conn = _fresh_conn()
    plan_id = plan_service.create_plan(
        conn,
        goal_type="marathon",
        methodology_id="higdon",
        race_date=None,
        target_time_s=None,
        days_per_week=4,
        long_run_day=6,
        variant="novice_1",
    )
    rows = conn.execute(
        "SELECT MAX(week_number) AS weeks FROM plan_workouts WHERE plan_id = ?",
        (plan_id,),
    ).fetchone()
    assert rows["weeks"] == 18, f"full Higdon marathon frame expected, got {rows['weeks']}"


def test_foppen_still_requires_race_date():
    conn = _fresh_conn()
    try:
        plan_service.create_plan(
            conn,
            goal_type="15k",
            methodology_id="foppen_7heuvelen",
            race_date=None,
            target_time_s=None,
            days_per_week=3,
            long_run_day=6,
        )
    except ValueError as exc:
        assert "race date" in str(exc).lower(), exc
    else:
        raise AssertionError("Foppen without a race date should raise")


def test_start_date_this_week():
    conn = _fresh_conn()
    monday = _this_monday()
    plan_id = plan_service.create_plan(
        conn,
        goal_type="10k",
        methodology_id="daniels",
        race_date=None,
        target_time_s=None,
        days_per_week=3,
        long_run_day=6,
        workout_days=[1, 4, 6],
        start_date=monday,
    )
    first = conn.execute(
        "SELECT MIN(planned_date) AS d FROM plan_workouts WHERE plan_id = ?",
        (plan_id,),
    ).fetchone()
    assert first["d"] == monday.isoformat(), (first["d"], monday.isoformat())


def test_can_run_10min_round_trip():
    """Tri-state self-assessment: NULL on a fresh DB, then True/False."""
    conn = _fresh_conn()
    assert app_settings.get_can_run_10min(conn) is None
    app_settings.set_can_run_10min(conn, False)
    assert app_settings.get_can_run_10min(conn) is False
    app_settings.set_can_run_10min(conn, True)
    assert app_settings.get_can_run_10min(conn) is True


def test_c25k_plan_creates_via_service():
    """End-to-end create_plan: c25k + 5k, no race date → 9 weeks, goal date
    synthesized on the final week's long-run day (the graduation slot)."""
    conn = _fresh_conn()
    plan_id = plan_service.create_plan(
        conn,
        goal_type="5k",
        methodology_id="c25k",
        race_date=None,
        target_time_s=None,
        days_per_week=3,
        long_run_day=5,
        workout_days=[1, 3, 5],
    )
    weeks = conn.execute(
        "SELECT MAX(week_number) AS n FROM plan_workouts WHERE plan_id = ?",
        (plan_id,),
    ).fetchone()
    assert weeks["n"] == 9, weeks["n"]
    race = conn.execute(
        "SELECT planned_date, target_distance_km FROM plan_workouts "
        "WHERE plan_id = ? AND workout_type = 'race'",
        (plan_id,),
    ).fetchone()
    assert race is not None, "synthesized goal date should overlay the graduation run"
    assert race["target_distance_km"] == 5.0
    assert date.fromisoformat(race["planned_date"]).weekday() == 5  # long-run day
    # Paceless invariant survives persistence.
    paced = conn.execute(
        "SELECT COUNT(*) AS n FROM plan_workouts "
        "WHERE plan_id = ? AND target_pace_s_per_km IS NOT NULL",
        (plan_id,),
    ).fetchone()
    assert paced["n"] == 0, f"{paced['n']} workouts carry a pace"


TESTS = [
    test_seed_defaults_on_fresh_db,
    test_seed_uses_manual_baseline,
    test_garmin_outranks_manual,
    test_manual_setters_validate_ranges,
    test_race_estimator_matches_known_point,
    test_daniels_plan_without_race_date,
    test_higdon_plan_without_race_date_runs_full_length,
    test_foppen_still_requires_race_date,
    test_start_date_this_week,
    test_can_run_10min_round_trip,
    test_c25k_plan_creates_via_service,
]


def main() -> int:
    failed = 0
    for fn in TESTS:
        try:
            fn()
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL  {fn.__name__}\n        {exc}")
        except Exception as exc:  # noqa: BLE001 — surface hard errors too
            failed += 1
            print(f"  ERROR {fn.__name__}\n        {type(exc).__name__}: {exc}")
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
