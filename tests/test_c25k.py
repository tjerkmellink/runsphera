"""Lock-down tests for the Couch to 5K engine (2026-07-18).

The invariants that matter:
- The canonical NHS 9-week shape: 3 sessions/week on the runner's picked
  days, session 3 (the week's biggest) pinned to long_run_day — that anchor
  is load-bearing because create_plan synthesizes the goal date on the
  final week's long-run day.
- Everything is paceless: no pace targets, no pace idioms in text, no
  pace_s_per_km keys in structures. Recalibration must be a structural
  no-op on top of the uses_vdot_paces=False service guard.
- The full 9 weeks are sacred: windows shorter than 9 weeks raise.

Run from repo root:
    .venv/Scripts/python.exe tests/test_c25k.py
"""
from __future__ import annotations

import re
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from running_coach.plans.c25k import C25KPlan  # noqa: E402
from running_coach.plans.methodology import PlanParams  # noqa: E402

# Mirrors plans/service.py _ALLOWED_TYPES-adjacent vocabulary.
_ALLOWED_TYPES = {"easy", "long", "tempo", "intervals", "recovery", "rest", "race", "cross"}

_MONDAY = date(2026, 7, 20)
_PACE_IDIOM = re.compile(r"\d+:\d{2}\s*/\s*km")


def _params(
    race_date: date | None = None,
    goal: str = "5k",
    days_per_week: int = 3,
    workout_days: list[int] | None = None,
    long_run_day: int = 5,
) -> PlanParams:
    return PlanParams(
        goal_type=goal,
        start_date=_MONDAY,
        race_date=race_date,
        target_time_s=None,
        days_per_week=days_per_week,
        long_run_day=long_run_day,
        current_vdot=45.0,
        weekly_km_baseline=25.0,
        workout_days=workout_days if workout_days is not None else [1, 3, 5],
    )


def _sessions(workouts) -> list:
    return [w for w in workouts if w.workout_type not in ("rest", "cross")]


def test_nine_weeks_seven_rows_each() -> None:
    workouts = C25KPlan().generate(_params())
    assert len(workouts) == 63, f"expected 9×7 rows, got {len(workouts)}"
    assert {w.week_number for w in workouts} == set(range(1, 10))


def test_three_sessions_on_picked_days_biggest_on_long_run_day() -> None:
    workouts = C25KPlan().generate(_params())
    for week in range(1, 10):
        week_sessions = [w for w in _sessions(workouts) if w.week_number == week]
        assert len(week_sessions) == 3, f"week {week}: {len(week_sessions)} sessions"
        assert sorted(w.day_of_week for w in week_sessions) == [1, 3, 5]
        s3 = max(week_sessions, key=lambda w: w.day_of_week)
        assert s3.day_of_week == 5, f"week {week}: session 3 not on long-run day"


def test_week1_structure_and_duration() -> None:
    workouts = C25KPlan().generate(_params())
    w1 = [w for w in _sessions(workouts) if w.week_number == 1]
    for w in w1:
        assert w.workout_type == "intervals"
        assert w.title == "Run/walk 8×(1 min run / 90 s walk)"
        steps = w.workout_structure["steps"]
        assert steps[0] == {"type": "warmup", "end": {"duration_s": 300}}
        assert steps[-1] == {"type": "cooldown", "end": {"duration_s": 300}}
        repeat = steps[1]
        assert repeat["type"] == "repeat" and repeat["iterations"] == 8
        assert repeat["steps"][0] == {"type": "active", "end": {"duration_s": 60}}
        assert repeat["steps"][1] == {"type": "recovery", "end": {"duration_s": 90}}
        assert w.target_duration_s == 300 + 8 * (60 + 90) + 300


def test_week5_has_three_distinct_sessions() -> None:
    workouts = C25KPlan().generate(_params())
    w5 = sorted(
        [w for w in _sessions(workouts) if w.week_number == 5],
        key=lambda w: w.day_of_week,
    )
    assert w5[0].workout_type == "intervals" and "3×5 min" in w5[0].title
    assert w5[1].workout_type == "intervals" and "2×8 min" in w5[1].title
    assert w5[2].workout_type == "easy" and w5[2].title == "Run 20 min"
    assert w5[2].target_duration_s == 300 + 1200 + 300


def test_final_weeks_are_continuous_runs() -> None:
    workouts = C25KPlan().generate(_params())
    for week, run_s in ((7, 1500), (8, 1680), (9, 1800)):
        sessions = [w for w in _sessions(workouts) if w.week_number == week]
        for w in sessions:
            assert w.workout_type == "easy", f"week {week}: {w.title}"
            assert w.target_duration_s == 300 + run_s + 300
    grad = [w for w in _sessions(workouts) if w.week_number == 9][-1]
    assert grad.title == "Graduation run 30 min (~5 km)"


def test_everything_is_paceless() -> None:
    """The recalibration-no-op guarantee: no pace anywhere, in any form."""
    workouts = C25KPlan().generate(_params())
    for w in workouts:
        assert w.target_pace_s_per_km is None, w.title
        assert w.target_distance_km is None, f"{w.title}: no fake distances"
        assert not _PACE_IDIOM.search(w.title or ""), w.title
        assert not _PACE_IDIOM.search(w.description or ""), w.title
        if w.workout_structure:
            def walk(steps):
                for s in steps:
                    assert "pace_s_per_km" not in s, f"{w.title}: pace in structure"
                    if s.get("steps"):
                        walk(s["steps"])
            walk(w.workout_structure["steps"])


def test_workout_types_within_vocabulary() -> None:
    workouts = C25KPlan().generate(_params())
    assert {w.workout_type for w in workouts} <= _ALLOWED_TYPES


def test_race_overlay_on_race_date() -> None:
    race = _MONDAY + timedelta(weeks=8, days=5)  # Saturday of week 9
    workouts = C25KPlan().generate(_params(race_date=race))
    race_days = [w for w in workouts if w.workout_type == "race"]
    assert len(race_days) == 1
    r = race_days[0]
    assert r.planned_date == race and r.week_number == 9
    assert r.target_distance_km == 5.0
    assert r.workout_structure is None


def test_longer_window_anchors_week9_to_race_week() -> None:
    race = date(2026, 11, 14)  # a Saturday ~17 weeks out
    workouts = C25KPlan().generate(_params(race_date=race))
    assert len(workouts) == 63
    first = min(w.planned_date for w in workouts)
    assert first == date(2026, 9, 14), f"plan should start 8 weeks before race week, got {first}"
    assert max(w.planned_date for w in workouts) >= race


def test_short_window_raises() -> None:
    race = date(2026, 8, 22)  # ~5 weeks out
    try:
        C25KPlan().generate(_params(race_date=race))
    except ValueError as exc:
        assert "9 weeks" in str(exc)
    else:
        raise AssertionError("a <9-week window must raise")


def test_wrong_goal_raises() -> None:
    try:
        C25KPlan().generate(_params(goal="10k"))
    except ValueError as exc:
        assert "5k" in str(exc)
    else:
        raise AssertionError("goal != 5k must raise")


def test_wrong_days_per_week_raises() -> None:
    try:
        C25KPlan().generate(_params(days_per_week=4, workout_days=[1, 3, 4, 5]))
    except ValueError as exc:
        assert "3" in str(exc)
    else:
        raise AssertionError("days_per_week != 3 must raise")


def test_no_workout_days_falls_back_to_spaced_days() -> None:
    p = _params(workout_days=None, long_run_day=6)
    p.workout_days = None
    workouts = C25KPlan().generate(p)
    week1 = [w for w in _sessions(workouts) if w.week_number == 1]
    # long_run_day 6 (Sun) → fallback others (6-4)%7=2 (Wed), (6-2)%7=4 (Fri)
    assert sorted(w.day_of_week for w in week1) == [2, 4, 6]


def test_registry_day_offsets_match_engine_and_never_run_back_to_back() -> None:
    """The form seeds its default day picks from the registry's
    preferred_day_offsets; those must be exactly the engine's own fallback
    spacing, and must never put two sessions on consecutive days — a
    beginner's rest day between runs is C25K's cardinal rule."""
    from running_coach.plans import get_methodology_info
    from running_coach.plans.c25k import PREFERRED_DAY_OFFSETS

    info = get_methodology_info("c25k")
    assert info.preferred_day_offsets == PREFERRED_DAY_OFFSETS
    assert len(PREFERRED_DAY_OFFSETS) == info.fixed_days_per_week == 3

    for anchor in range(7):
        days = sorted((anchor + o) % 7 for o in PREFERRED_DAY_OFFSETS)
        assert len(set(days)) == 3
        for i in range(3):
            gap = (days[(i + 1) % 3] - days[i]) % 7
            assert gap >= 2, (
                f"anchor {anchor}: days {days} put sessions on consecutive days"
            )


def test_phases_follow_the_programme_arc() -> None:
    workouts = C25KPlan().generate(_params())
    phase_of_week = {w.week_number: w.week_phase for w in workouts}
    assert [phase_of_week[n] for n in range(1, 10)] == (
        ["base"] * 3 + ["build"] * 3 + ["peak"] * 2 + ["taper"]
    )


TESTS = [
    test_nine_weeks_seven_rows_each,
    test_three_sessions_on_picked_days_biggest_on_long_run_day,
    test_week1_structure_and_duration,
    test_week5_has_three_distinct_sessions,
    test_final_weeks_are_continuous_runs,
    test_everything_is_paceless,
    test_workout_types_within_vocabulary,
    test_race_overlay_on_race_date,
    test_longer_window_anchors_week9_to_race_week,
    test_short_window_raises,
    test_wrong_goal_raises,
    test_wrong_days_per_week_raises,
    test_no_workout_days_falls_back_to_spaced_days,
    test_registry_day_offsets_match_engine_and_never_run_back_to_back,
    test_phases_follow_the_programme_arc,
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
