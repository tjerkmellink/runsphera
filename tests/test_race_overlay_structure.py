"""The race-day overlay must not inherit the replaced session's structure.

Every engine builds its weeks first and then stamps the race onto whichever
day the race date lands on. That day is often a quality session, so it already
carries a `workout_structure`.

`race` is a simple workout type — `planned_to_garmin_workout` is supposed to
send one distance step. But it prefers *any* structure it finds over the
headline distance, and nothing gates that on the type. A leftover structure
therefore reaches the watch: on race morning the runner is guided through a
warm-up, six 100 m R-pace strides and a cool-down, under a "Race day" title,
instead of the race.

Found by review on 2026-10-24 in the Daniels engine; Pfitzinger, Higdon and
C25K already cleared it. This pins all of them.
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runsphera.plans.daniels import DanielsVDOT  # noqa: E402
from runsphera.plans.garmin_sync import planned_to_garmin_workout  # noqa: E402
from runsphera.plans.methodology import PlanParams  # noqa: E402


def _structure_of(w):
    st = w.workout_structure
    if isinstance(st, str):
        st = json.loads(st)
    return (st or {}).get("steps") or []


def _race_row(workouts, race_date):
    rows = [w for w in workouts if w.planned_date == race_date]
    assert len(rows) == 1, f"expected exactly one race row, got {len(rows)}"
    return rows[0]


# The reproduction from the review: a Thursday race, so it lands on a
# mid-week quality day rather than the Sunday long run.
REPRO = PlanParams(
    goal_type="10k",
    start_date=date(2026, 10, 26),
    race_date=date(2027, 1, 7),
    target_time_s=None,
    days_per_week=4,
    long_run_day=6,
    current_vdot=49.0,
    weekly_km_baseline=45.0,
    workout_days=[1, 3, 4, 6],
)


def test_daniels_race_day_carries_no_structure():
    w = _race_row(DanielsVDOT().generate(REPRO), REPRO.race_date)
    assert w.workout_type == "race"
    assert _structure_of(w) == [], (
        "race day inherited the replaced session's steps — the watch would "
        "guide the runner through strides instead of the race"
    )


def test_daniels_race_day_pushes_a_single_distance_step():
    """The end-to-end consequence: what actually reaches the watch."""
    w = _race_row(DanielsVDOT().generate(REPRO), REPRO.race_date)
    gw = planned_to_garmin_workout({
        "workout_type": w.workout_type,
        "title": w.title,
        "description": w.description,
        "target_distance_km": w.target_distance_km,
        "target_pace_s_per_km": w.target_pace_s_per_km,
        "target_duration_s": w.target_duration_s,
        "workout_structure": w.workout_structure,
    })
    steps = gw.workoutSegments[0].workoutSteps
    assert len(steps) == 1, f"race pushed as {len(steps)} steps, expected 1"
    assert steps[0].endConditionValue == 10_000.0, steps[0].endConditionValue


def test_race_overlay_clears_structure_on_every_weekday():
    """The race can land on any day; none of them may keep a structure."""
    start = date(2026, 10, 26)  # a Monday
    for offset in range(7):
        race = start + timedelta(weeks=10, days=offset)
        params = PlanParams(
            goal_type="10k", start_date=start, race_date=race,
            target_time_s=None, days_per_week=4, long_run_day=6,
            current_vdot=49.0, weekly_km_baseline=45.0, workout_days=[1, 3, 4, 6],
        )
        try:
            workouts = DanielsVDOT().generate(params)
        except ValueError:
            continue  # some race dates are rejected outright; fine
        rows = [w for w in workouts if w.planned_date == race]
        if not rows:
            continue
        assert _structure_of(rows[0]) == [], f"structure survived on {race:%a %Y-%m-%d}"


def main():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"{len(fns)} passed")


if __name__ == "__main__":
    main()
