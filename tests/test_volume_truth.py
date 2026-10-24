"""Headline numbers must agree with what the structure prescribes.

`workout_structure` is the contract with the watch, so it is the authority on
what a session asks of the runner. When the headline columns disagree, the
plan reports one volume and the watch prescribes another.

Two defects found by review on 2026-10-24:

* Quality sessions carried the *budget* distance (`q1_km`) while
  `_interval_structure` built a fixed 2 km warm-up + N reps + recoveries +
  2 km cool-down. A 5 km headline prescribed ~10.7 km, so every interval week
  understated weekly volume.
* The half-marathon peak long run promised "5 km @ ~T pace" in its description
  but returned no structure, so the watch received one flat E-pace step.

The fix reports the truth rather than trimming the prescription: Daniels'
rep counts are published numbers, and shrinking them to protect a display
figure would corrupt the methodology.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from running_coach.plans._structure import totals_from_structure  # noqa: E402
from running_coach.plans.daniels import DanielsVDOT  # noqa: E402
from running_coach.plans.garmin_sync import planned_to_garmin_workout  # noqa: E402
from running_coach.plans.methodology import PlanParams  # noqa: E402


def _params(goal="10k", weeks=12, baseline=25.0, vdot=45.0):
    start = date(2026, 10, 26)
    return PlanParams(
        goal_type=goal, start_date=start,
        race_date=start + timedelta(weeks=weeks) - timedelta(days=1),
        target_time_s=None, days_per_week=4, long_run_day=6,
        current_vdot=vdot, weekly_km_baseline=baseline, workout_days=[1, 3, 4, 6],
    )


# ── totals_from_structure itself ─────────────────────────────────────────

def test_totals_count_repeat_iterations():
    st = {"steps": [
        {"type": "warmup", "end": {"distance_m": 2000}, "pace_s_per_km": 360},
        {"type": "repeat", "iterations": 5, "steps": [
            {"type": "active", "end": {"distance_m": 1000}, "pace_s_per_km": 270},
        ]},
        {"type": "cooldown", "end": {"distance_m": 2000}, "pace_s_per_km": 360},
    ]}
    assert totals_from_structure(st)["total_km"] == 9.0


def test_totals_count_timed_recoveries_as_distance():
    """A jog between reps covers ground; omitting it understates the session."""
    st = {"steps": [
        {"type": "repeat", "iterations": 4, "steps": [
            {"type": "active", "end": {"distance_m": 1000}, "pace_s_per_km": 270},
            {"type": "recovery", "end": {"duration_s": 120}},
        ]},
    ]}
    # 4 km of reps + 4x120 s jogged at the 360 s/km easy default = 1.33 km.
    assert totals_from_structure(st)["total_km"] == 5.33


def test_recovery_is_never_priced_at_the_work_pace():
    """The headline pace is the *work* pace; a recovery jog is easy.

    Pricing a 60 s stride-jog at R pace rather than easy inflated a taper
    strides run from 12 km to 12.53 km.
    """
    st = {"steps": [
        {"type": "repeat", "iterations": 6, "steps": [
            {"type": "active", "end": {"distance_m": 100}, "pace_s_per_km": 236},
            {"type": "recovery", "end": {"duration_s": 60}},
        ]},
    ]}
    # 0.6 km of strides + 6x60 s at the easy default (not at R pace).
    assert totals_from_structure(st, fallback_pace=236)["total_km"] == 1.6


def test_totals_of_an_empty_structure_are_zero():
    assert totals_from_structure(None)["total_km"] == 0.0
    assert totals_from_structure({})["total_km"] == 0.0


# ── generation: headline agrees with structure ───────────────────────────

def test_every_structured_session_headline_matches_its_structure():
    """The defect in one assertion, across a whole generated plan."""
    for w in DanielsVDOT().generate(_params()):
        st = w.workout_structure
        if not st or not st.get("steps"):
            continue
        expected = totals_from_structure(st, fallback_pace=w.target_pace_s_per_km)
        assert abs(w.target_distance_km - expected["total_km"]) < 0.02, (
            f"wk{w.week_number} {w.workout_type}: headline "
            f"{w.target_distance_km} km vs structure {expected['total_km']} km"
        )


def test_interval_session_reports_more_than_its_budget():
    """Specifically the reproduced case: a 5 km budget, ~10 km prescribed."""
    intervals = [w for w in DanielsVDOT().generate(_params())
                 if w.workout_type == "intervals" and w.workout_structure]
    assert intervals, "expected an interval session"
    w = intervals[0]
    assert w.target_distance_km > 8.0, (
        f"interval headline {w.target_distance_km} km looks like the old budget"
    )


def test_interval_duration_is_not_billed_at_the_work_pace():
    """distance x headline pace would price the whole session at I pace.

    I pace is the *fastest* pace in the session — warm-up, recoveries and
    cool-down are all easy — so the honest duration is longer than the naive
    product, not shorter.
    """
    intervals = [w for w in DanielsVDOT().generate(_params())
                 if w.workout_type == "intervals" and w.workout_structure]
    w = intervals[0]
    naive = int((w.target_distance_km or 0) * (w.target_pace_s_per_km or 0))
    assert w.target_duration_s > naive, (
        f"duration {w.target_duration_s}s prices the whole session at I pace "
        f"({naive}s); the easy portions should make it longer"
    )


# ── the half-marathon peak long run ──────────────────────────────────────

def _hm_peak_long():
    for w in DanielsVDOT().generate(_params("half_marathon", weeks=16, baseline=40.0)):
        if w.workout_type == "long" and "HM pace" in (w.title or ""):
            return w
    raise AssertionError("no half-marathon peak long run generated")


def test_hm_peak_long_run_has_a_structure():
    w = _hm_peak_long()
    steps = (w.workout_structure or {}).get("steps") or []
    assert steps, "description promises a T-pace finish with no structure to deliver it"


def test_hm_peak_long_run_pushes_the_t_pace_finish():
    w = _hm_peak_long()
    gw = planned_to_garmin_workout({
        "workout_type": w.workout_type, "title": w.title,
        "description": w.description, "target_distance_km": w.target_distance_km,
        "target_pace_s_per_km": w.target_pace_s_per_km,
        "target_duration_s": w.target_duration_s,
        "workout_structure": w.workout_structure,
    })
    steps = gw.workoutSegments[0].workoutSteps
    assert len(steps) == 3, f"expected easy + T + cooldown, got {len(steps)} steps"
    assert steps[1].endConditionValue == 5000.0, "the 5 km T-pace block is missing"


def test_hm_peak_long_run_steps_carry_zone_tags():
    """Zone tags are what let a recalibration rewrite each segment correctly."""
    steps = _hm_peak_long().workout_structure["steps"]
    assert [s.get("zone") for s in steps] == ["E", "T", "E"]


# ── editing must not change a session's pace zone ────────────────────────

def test_editing_repetitions_keeps_them_at_R_pace():
    """`_zone_for_workout` reads R vs I off the title token.

    Re-deriving a generic "Intervals N x M m" on save demoted a VDOT-50
    6x400 m repetition session from R (232 s/km) to I (250 s/km) on the next
    recalibrate — a silent change to the prescribed stimulus.
    """
    from running_coach.plans.service import _derive_title, _zone_for_workout

    structure = {"steps": [
        {"type": "warmup", "zone": "E", "end": {"distance_m": 2000}},
        {"type": "repeat", "iterations": 6, "steps": [
            {"type": "active", "zone": "R", "end": {"distance_m": 400},
             "pace_s_per_km": 232},
            {"type": "recovery", "zone": "E", "end": {"duration_s": 90}},
        ]},
        {"type": "cooldown", "zone": "E", "end": {"distance_m": 2000}},
    ]}
    title = _derive_title("intervals", 6.4, structure,
                          current_title="Repetitions 6x400 m")
    assert _zone_for_workout({"workout_type": "intervals", "title": title}) == "R", title


def test_editing_strides_keeps_the_strides_identity():
    from running_coach.plans.service import _derive_title, _zone_for_workout

    structure = {"steps": [
        {"type": "repeat", "iterations": 6, "steps": [
            {"type": "active", "zone": "R", "end": {"distance_m": 100},
             "pace_s_per_km": 232},
            {"type": "recovery", "zone": "E", "end": {"duration_s": 60}},
        ]},
    ]}
    title = _derive_title("intervals", 0.6, structure,
                          current_title="Easy 12 km with 6x100 m strides")
    assert "Strides" in title, title
    assert _zone_for_workout({"workout_type": "intervals", "title": title}) == "R"


def test_editing_a_real_interval_session_stays_at_I_pace():
    """The fix must not promote genuine I-pace intervals to R."""
    from running_coach.plans.service import _derive_title, _zone_for_workout

    structure = {"steps": [
        {"type": "warmup", "zone": "E", "end": {"distance_m": 2000}},
        {"type": "repeat", "iterations": 5, "steps": [
            {"type": "active", "zone": "I", "end": {"distance_m": 1000},
             "pace_s_per_km": 250},
            {"type": "recovery", "zone": "E", "end": {"duration_s": 120}},
        ]},
        {"type": "cooldown", "zone": "E", "end": {"distance_m": 2000}},
    ]}
    title = _derive_title("intervals", 9.0, structure,
                          current_title="Intervals 5x1000 m")
    assert _zone_for_workout({"workout_type": "intervals", "title": title}) == "I", title


def main():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"{len(fns)} passed")


if __name__ == "__main__":
    main()
