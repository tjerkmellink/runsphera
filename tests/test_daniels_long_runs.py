"""Lock-down tests for marathon long-run sizing and the mixed-pace structure.

Origin (2026-07-02): a 23-week marathon plan at 61 km/wk peak topped out at a
20 km long run — the flat 32%-of-weekly split never let the long run approach
Daniels' 2.5-hour ceiling, and the "last X km @ M pace" instruction lived only
in the description text (never reached the watch). Peak marathon long runs now
size toward min(40% of weekly volume, the 2.5 h ceiling) and carry a two-step
zone-tagged workout_structure (E segment + M segment).

Run from repo root:
    .venv/Scripts/python.exe tests/test_daniels_long_runs.py
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runsphera.plans.daniels import (  # noqa: E402
    DanielsVDOT,
    _LONG_RUN_CAP_S,
    _PEAK_LONG_M_FRACTION,
    _paces_for_vdot,
    _structure_duration_s,
    _time_capped_long_km,
)
from runsphera.plans.methodology import PlanParams  # noqa: E402
from runsphera.plans.service import _rewrite_structure_pace  # noqa: E402


# Mirrors the live plan this work was verified against (plan 41):
# VDOT 43, 4 days/week, Sunday long run, ~34 km baseline, 23 weeks.
def _marathon_params() -> PlanParams:
    return PlanParams(
        goal_type="marathon",
        start_date=date(2026, 5, 25),
        race_date=date(2026, 11, 1),
        target_time_s=None,
        days_per_week=4,
        long_run_day=6,
        current_vdot=43.0,
        weekly_km_baseline=34.0,
        workout_days=[1, 3, 4, 6],
    )


def _long_runs(workouts) -> list:
    return [w for w in workouts if w.workout_type == "long"]


def test_time_capped_long_km() -> None:
    paces = _paces_for_vdot(43.0)  # E=383, M=323
    assert _time_capped_long_km(paces) == 23, "fully-easy cap at VDOT 43 should be 23 km"
    assert _time_capped_long_km(paces, _PEAK_LONG_M_FRACTION) == 24, (
        "cap with a 35% M-pace finish should be 24 km (M pace is faster)"
    )


def test_peak_long_runs_approach_the_ceiling() -> None:
    workouts = DanielsVDOT().generate(_marathon_params())
    peak_longs = [w for w in _long_runs(workouts) if w.week_phase == "peak"]
    assert len(peak_longs) == 3, f"expected 3 peak long runs, got {len(peak_longs)}"
    kms = [w.target_distance_km for w in peak_longs]
    assert kms[0] == 24 and kms[1] == 24, f"first two peak long runs should be 24 km, got {kms}"
    assert kms[2] == 22, f"final peak week should step down ~10%, got {kms[2]}"


def test_no_long_run_exceeds_2h30() -> None:
    workouts = DanielsVDOT().generate(_marathon_params())
    for w in _long_runs(workouts):
        duration = w.target_duration_s
        assert duration is not None
        assert duration <= _LONG_RUN_CAP_S, (
            f"{w.planned_date} '{w.title}': {duration}s exceeds the 2.5h ceiling"
        )


def test_build_bridges_into_peak_without_a_big_jump() -> None:
    """The last build-week long run stretches toward the easy-pace ceiling so
    the step into the first peak week stays ≤ 2 km."""
    workouts = DanielsVDOT().generate(_marathon_params())
    longs = _long_runs(workouts)
    build_longs = [w for w in longs if w.week_phase == "build"]
    first_peak = next(w for w in longs if w.week_phase == "peak")
    bridge = build_longs[-1]
    assert bridge.target_distance_km == 22, f"bridge week should be 22 km, got {bridge.target_distance_km}"
    assert first_peak.target_distance_km - bridge.target_distance_km <= 2


def test_peak_long_run_structure_has_zoned_e_and_m_steps() -> None:
    workouts = DanielsVDOT().generate(_marathon_params())
    paces = _paces_for_vdot(43.0)
    peak_longs = [w for w in _long_runs(workouts) if w.week_phase == "peak"]
    for w in peak_longs:
        s = w.workout_structure
        assert s and len(s["steps"]) == 2, f"{w.title}: expected a 2-step structure"
        e_step, m_step = s["steps"]
        assert e_step["zone"] == "E" and e_step["pace_s_per_km"] == paces["E"]
        assert m_step["zone"] == "M" and m_step["pace_s_per_km"] == paces["M"]
        total_m = e_step["end"]["distance_m"] + m_step["end"]["distance_m"]
        assert total_m == int(w.target_distance_km * 1000), (
            f"{w.title}: structure distances ({total_m} m) don't sum to the target"
        )
        # Duration must come from the structure (E×E-pace + M×M-pace), not
        # distance × headline pace, which would overestimate.
        assert w.target_duration_s == _structure_duration_s(s)
        # Title and description carry the M-pace part for the calendar view.
        assert "@ M pace" in w.title


def test_non_peak_long_runs_stay_simple() -> None:
    workouts = DanielsVDOT().generate(_marathon_params())
    for w in _long_runs(workouts):
        if w.week_phase != "peak":
            assert w.workout_structure is None, f"{w.week_phase} long run should have no structure"


def test_weekly_totals_are_conserved() -> None:
    """Raising the long run redistributes within the week — the easy days
    shrink; the weekly total must not balloon."""
    workouts = DanielsVDOT().generate(_marathon_params())
    by_week: dict[int, float] = {}
    for w in workouts:
        if w.target_distance_km and w.workout_type != "race":
            by_week[w.week_number] = by_week.get(w.week_number, 0) + w.target_distance_km
    peak_weeks = {w.week_number for w in workouts if w.week_phase == "peak"}
    for wk in peak_weeks:
        assert 58 <= by_week[wk] <= 64, f"week {wk}: total {by_week[wk]} km drifted from ~61"


def test_recalibrate_rewrites_zone_tagged_steps_per_zone() -> None:
    """A VDOT bump must move the M step to the new M pace — before the zone
    tags, _rewrite_structure_pace flattened every step to E pace."""
    old = _paces_for_vdot(43.0)
    new = _paces_for_vdot(46.0)
    structure = {
        "steps": [
            {"type": "active", "zone": "E", "end": {"distance_m": 16000}, "pace_s_per_km": old["E"]},
            {"type": "active", "zone": "M", "end": {"distance_m": 8000}, "pace_s_per_km": old["M"]},
        ]
    }
    out = _rewrite_structure_pace(structure, new["E"], new)
    assert out["steps"][0]["pace_s_per_km"] == new["E"]
    assert out["steps"][1]["pace_s_per_km"] == new["M"]
    # Original dict untouched.
    assert structure["steps"][1]["pace_s_per_km"] == old["M"]


def test_recalibrate_untagged_steps_use_workout_pace() -> None:
    """Pre-tag structures (tempo/intervals already in the DB) keep the old
    behaviour: every active step gets the workout-level pace."""
    new = _paces_for_vdot(46.0)
    structure = {
        "steps": [
            {"type": "warmup", "end": {"distance_m": 2000}},
            {"type": "active", "end": {"distance_m": 7000}, "pace_s_per_km": 300},
            {"type": "cooldown", "end": {"distance_m": 2000}},
        ]
    }
    out = _rewrite_structure_pace(structure, new["T"], new)
    assert out["steps"][1]["pace_s_per_km"] == new["T"]


def test_structure_duration_bails_on_paceless_steps() -> None:
    """Tempo structures have paceless warmup/cooldown steps — duration must
    fall back to the historical distance × headline-pace estimate."""
    tempo_like = {
        "steps": [
            {"type": "warmup", "end": {"distance_m": 2000}},
            {"type": "active", "end": {"distance_m": 7000}, "pace_s_per_km": 300},
        ]
    }
    assert _structure_duration_s(tempo_like) is None


TESTS = [
    test_time_capped_long_km,
    test_peak_long_runs_approach_the_ceiling,
    test_no_long_run_exceeds_2h30,
    test_build_bridges_into_peak_without_a_big_jump,
    test_peak_long_run_structure_has_zoned_e_and_m_steps,
    test_non_peak_long_runs_stay_simple,
    test_weekly_totals_are_conserved,
    test_recalibrate_rewrites_zone_tagged_steps_per_zone,
    test_recalibrate_untagged_steps_use_workout_pace,
    test_structure_duration_bails_on_paceless_steps,
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
