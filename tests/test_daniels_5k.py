"""Lock-down tests for the Daniels 5K plan (new goal, 2026-07-18).

The 5K is speed-driven: repetition (R-pace) work enters in base already,
build alternates I and R sessions, and the final sharpening session before
the taper is short R work. Long runs cap at min(25% of weekly volume, 12 km).
The R sessions use the title word "Repetitions" — the recalibration zone
mapper reads it as R (a plain "Intervals" title re-zones to I).

Also holds the 15K smoke test: "15k" is in GOAL_TYPES and Daniels has no
goal allow-list, so Daniels + 15k must generate instead of KeyError-ing
(the pre-2026-07-18 latent crash).

Run from repo root:
    .venv/Scripts/python.exe tests/test_daniels_5k.py
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from running_coach.plans.daniels import DanielsVDOT, _paces_for_vdot  # noqa: E402
from running_coach.plans.methodology import PlanParams  # noqa: E402
from running_coach.plans.service import _zone_for_workout  # noqa: E402


def _params(goal: str = "5k") -> PlanParams:
    return PlanParams(
        goal_type=goal,
        start_date=date(2026, 7, 20),  # a Monday
        race_date=None,
        target_time_s=None,
        days_per_week=4,
        long_run_day=6,
        current_vdot=45.0,
        weekly_km_baseline=30.0,
        workout_days=[1, 3, 4, 6],
    )


def _quality(workouts) -> list:
    return [w for w in workouts if w.workout_type in ("tempo", "intervals")]


def test_default_is_8_weeks_2_3_2_1() -> None:
    workouts = DanielsVDOT().generate(_params())
    assert len(workouts) == 56, f"expected 8 weeks × 7 rows, got {len(workouts)}"
    phase_of_week = {w.week_number: w.week_phase for w in workouts}
    assert [phase_of_week[n] for n in range(1, 9)] == (
        ["base"] * 2 + ["build"] * 3 + ["peak"] * 2 + ["taper"]
    ), f"got {phase_of_week}"


def test_quality_progression_mixes_i_and_r() -> None:
    workouts = DanielsVDOT().generate(_params())
    q = _quality(workouts)
    assert len(q) == 8
    titles = [w.title.split()[0] for w in q]
    # base: Tempo, Repetitions · build: I, R, I · peak: I(800s), R · taper: Strides
    assert titles == [
        "Tempo", "Repetitions",
        "Intervals", "Repetitions", "Intervals",
        "Intervals", "Repetitions",
        "Strides",
    ], f"got {titles}"
    assert q[1].title == "Repetitions 8×200 m"
    assert q[5].title == "Intervals 5×800 m"
    assert q[6].title == "Repetitions 6×400 m", "final sharpening should be short R work"


def test_repetition_sessions_run_at_r_pace() -> None:
    workouts = DanielsVDOT().generate(_params())
    paces = _paces_for_vdot(45.0)
    reps = [w for w in workouts if w.title.startswith("Repetitions")]
    assert len(reps) == 3
    for w in reps:
        assert w.target_pace_s_per_km == paces["R"], f"{w.title}: expected R pace"
        steps = w.workout_structure["steps"]
        assert steps[1]["type"] == "repeat"
        assert steps[1]["steps"][0]["pace_s_per_km"] == paces["R"]


def test_repetition_titles_zone_to_r() -> None:
    """Recalibration contract: without the 'repetition' title override these
    sessions would silently re-zone to I and get the wrong pace stamped."""
    zone = _zone_for_workout({"workout_type": "intervals", "title": "Repetitions 8×200 m"})
    assert zone == "R", f"expected R, got {zone}"
    # Plain intervals still map to I.
    assert _zone_for_workout({"workout_type": "intervals", "title": "Intervals 5×800 m"}) == "I"


def test_long_runs_capped_at_12km_and_quarter_of_week() -> None:
    workouts = DanielsVDOT().generate(_params())
    longs = [w for w in workouts if w.workout_type == "long"]
    assert longs, "expected long runs"
    by_week: dict[int, float] = {}
    for w in workouts:
        if w.target_distance_km and w.workout_type != "race":
            by_week[w.week_number] = by_week.get(w.week_number, 0) + w.target_distance_km
    for w in longs:
        assert w.target_distance_km <= 12, f"week {w.week_number}: long {w.target_distance_km} km > 12"
        assert w.target_distance_km <= round(by_week[w.week_number] * 0.30), (
            f"week {w.week_number}: long run out of proportion for a 5K plan"
        )


def test_15k_generates_without_crashing() -> None:
    """The latent KeyError: Daniels + 15k used to crash on _DEFAULT_WEEKS."""
    workouts = DanielsVDOT().generate(_params(goal="15k"))
    assert len(workouts) == 77, f"expected 11 weeks × 7 rows, got {len(workouts)}"
    phases = {w.week_phase for w in workouts}
    assert phases == {"base", "build", "peak", "taper"}, f"got {phases}"
    assert DanielsVDOT().total_weeks("15k", None, date(2026, 7, 20)) == 11


TESTS = [
    test_default_is_8_weeks_2_3_2_1,
    test_quality_progression_mixes_i_and_r,
    test_repetition_sessions_run_at_r_pace,
    test_repetition_titles_zone_to_r,
    test_long_runs_capped_at_12km_and_quarter_of_week,
    test_15k_generates_without_crashing,
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
