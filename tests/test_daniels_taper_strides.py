"""Lock-down tests for Daniels taper strides (bug fixed 2026-10-19).

THE BUG: the taper strides session was emitted as workout_type "intervals"
with workout_structure None. "intervals" is a *structured* type, so
is_pushable() refused it — the Garmin push button silently disappeared and
"Push week" skipped the session. Regenerating the plan could never help: the
engine always returned None. A 23-week marathon plan only reaches its first
strides session in the taper, so the hole stayed invisible for 20 weeks.

The session now carries a real structure (easy warm-up at E, N x [100 m @ R +
jog], easy cool-down at E), which also makes it narratable and stops the
duration estimate pretending the whole run happens at R pace.

Run from repo root:
    .venv/Scripts/python.exe tests/test_daniels_taper_strides.py
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from running_coach.plans.daniels import (  # noqa: E402
    DanielsVDOT,
    _interval_structure,
    _paces_for_vdot,
    _quality_workout,
    _strides_structure,
    _structure_duration_s,
    _tempo_structure,
)
from running_coach.plans.garmin_sync import is_pushable  # noqa: E402
from running_coach.plans.methodology import PlanParams  # noqa: E402
from running_coach.plans.service import (  # noqa: E402
    _rewrite_structure_pace,
    _zone_for_workout,
)

VDOT = 49.0


def _params(goal: str = "marathon", weeks: int = 23) -> PlanParams:
    """A marathon block long enough to own a real multi-week taper."""
    start = date(2026, 5, 25)  # a Monday
    return PlanParams(
        goal_type=goal,
        start_date=start,
        race_date=start + timedelta(weeks=weeks) - timedelta(days=1),
        target_time_s=None,
        days_per_week=4,
        long_run_day=6,
        current_vdot=VDOT,
        weekly_km_baseline=45.0,
        workout_days=[1, 3, 4, 6],
    )


def _strides(workouts) -> list:
    return [w for w in workouts if w.title.startswith("Strides")]


def test_taper_strides_are_pushable() -> None:
    """THE BUG: every taper strides row used to be unpushable."""
    strides = _strides(DanielsVDOT().generate(_params()))
    assert strides, "a marathon plan should produce taper strides sessions"
    for w in strides:
        assert w.workout_structure, f"{w.planned_date} {w.title}: no structure"
        assert is_pushable(w.workout_type, w.workout_structure), (
            f"{w.planned_date} {w.title} ({w.workout_type}) is not pushable"
        )


def test_strides_structure_shape() -> None:
    """Easy warm-up, repeat of short R reps with jog recovery, easy finish."""
    paces = _paces_for_vdot(VDOT)
    reps, structure = _strides_structure(8.0, paces)
    assert reps == 6, f"8 km should hold 6 reps, got {reps}"
    wu, block, cd = structure["steps"]

    assert wu["type"] == "warmup" and wu["pace_s_per_km"] == paces["E"]
    assert cd["type"] == "cooldown" and cd["pace_s_per_km"] == paces["E"]
    assert block["type"] == "repeat" and block["iterations"] == reps

    rep, rec = block["steps"]
    assert rep["end"]["distance_m"] == 100
    assert rep["pace_s_per_km"] == paces["R"], "strides run at R pace, not I"
    assert rec["type"] == "recovery" and rec["end"]["duration_s"] == 60

    running_m = wu["end"]["distance_m"] + reps * 100 + cd["end"]["distance_m"]
    assert 6000 <= running_m <= 8000, f"steps miss the 8 km target: {running_m} m"


def test_strides_steps_carry_zone_tags() -> None:
    """Zone tags are what let the recalibrator rewrite each segment correctly.

    The headline pace of a strides row is R, so an untagged easy warm-up
    would be rewritten to R — a 5 km warm-up at rep pace."""
    paces = _paces_for_vdot(VDOT)
    _, structure = _strides_structure(8.0, paces)
    wu, block, cd = structure["steps"]
    assert wu["zone"] == "E" and cd["zone"] == "E"
    assert block["steps"][0]["zone"] == "R"

    faster = _paces_for_vdot(53.0)
    r_wu, r_block, r_cd = _rewrite_structure_pace(
        structure, faster["R"], faster
    )["steps"]
    assert r_wu["pace_s_per_km"] == faster["E"], "warm-up must follow E, not R"
    assert r_cd["pace_s_per_km"] == faster["E"], "cool-down must follow E, not R"
    assert r_block["steps"][0]["pace_s_per_km"] == faster["R"]


def test_duration_no_longer_times_the_whole_run_at_r_pace() -> None:
    """Structureless strides fell back to distance x R pace, billing an 8 km
    easy run as half an hour. A fully-paced structure times itself."""
    paces = _paces_for_vdot(VDOT)
    _, structure = _strides_structure(8.0, paces)
    duration = _structure_duration_s(structure)
    assert duration is not None, "a fully-paced structure must time itself"
    naive_r = int(8.0 * paces["R"])
    assert duration > naive_r * 1.2, (
        f"duration {duration}s is still near the R-pace fiction ({naive_r}s)"
    )
    # Sanity: an 8 km mostly-easy run sits near 8 x E pace.
    assert abs(duration - int(8.0 * paces["E"])) < 600


def test_repeat_blocks_do_not_break_existing_estimates() -> None:
    """Tempo/interval structures leave warm-up and cool-down unpaced, so they
    must still return None and keep the historical distance x pace estimate."""
    paces = _paces_for_vdot(VDOT)
    assert _structure_duration_s(_interval_structure(5, 1000, 120, paces["I"])) is None
    assert _structure_duration_s(_tempo_structure(12.0, paces["T"])) is None


def test_strides_still_zone_as_r() -> None:
    """The recalibrator reads "Strides" in the title as R — renaming the
    session to a concrete rep count must not break that."""
    paces = _paces_for_vdot(VDOT)
    for w in _strides(DanielsVDOT().generate(_params())):
        zone = _zone_for_workout({"workout_type": w.workout_type, "title": w.title})
        assert zone == "R", f"{w.title} re-zoned to {zone}"
        assert w.target_pace_s_per_km == paces["R"]


def test_short_taper_run_falls_back_to_a_pushable_easy_run() -> None:
    """A run too short to hold a strides block must not regress into an
    unpushable structureless "intervals" row."""
    paces = _paces_for_vdot(VDOT)
    assert _strides_structure(3.0, paces) is None
    wtype, _title, _desc, _pace, structure = _quality_workout(
        "taper", 0, "5k", 3.0, paces
    )
    assert wtype == "easy", f"expected an easy fallback, got {wtype}"
    assert is_pushable(wtype, structure), "the fallback must be pushable"


def test_description_names_the_real_distance_and_reps() -> None:
    """The old copy hardcoded "Easy 4-5 km with 4-6x100 m" on rows whose target
    was 7-8 km, and the pushed structure matched neither."""
    for w in _strides(DanielsVDOT().generate(_params())):
        km = w.target_distance_km
        assert f"{km:g} km" in w.description, (
            f"description does not name the {km} km target: {w.description}"
        )
        reps = w.workout_structure["steps"][1]["iterations"]
        assert f"{reps}×100 m" in w.description
        assert f"{reps}×100 m" in w.title
        # Pace idioms the description refresher rewrites must survive.
        assert "E pace (" in w.description and "R pace (" in w.description


TESTS = [
    test_taper_strides_are_pushable,
    test_strides_structure_shape,
    test_strides_steps_carry_zone_tags,
    test_duration_no_longer_times_the_whole_run_at_r_pace,
    test_repeat_blocks_do_not_break_existing_estimates,
    test_strides_still_zone_as_r,
    test_short_taper_run_falls_back_to_a_pushable_easy_run,
    test_description_names_the_real_distance_and_reps,
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
