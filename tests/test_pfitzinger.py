"""Lock-down tests for the Pfitzinger 18/55 marathon engine.

Asserts the plan's non-negotiable shape: 18 weeks, four mesocycles in order,
paces pulled straight from the VDOT table, Pfitzinger's volume ceilings (long
run ≤ 32 km, ~88 km peak), the two tune-up races, the marathon-pace long runs,
and the marathon overlaid on the final week's long-run slot.

Run from repo root:
    .venv/Scripts/python.exe tests/test_pfitzinger.py
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runsphera.plans.methodology import PlanParams  # noqa: E402
from runsphera.plans.pfitzinger import (  # noqa: E402
    Pfitzinger18_55,
    TOTAL_WEEKS,
    _LONG_CAP_KM,
    _PEAK_KM,
)
from runsphera.plans.daniels import _paces_for_vdot  # noqa: E402

# Kept in sync with service.ALLOWED_WORKOUT_TYPES, duplicated here so the test
# doesn't pull in service.py (which imports the optional garminconnect dep).
_ALLOWED_TYPES = frozenset(
    {"easy", "tempo", "intervals", "long", "recovery", "rest", "cross", "race"}
)

_RACE = date(2026, 11, 1)  # a Sunday
_START_18WK = date(2026, 6, 22)  # Monday, 18+ weeks before the race
_START_16WK = date(2026, 7, 13)  # Monday, 16 weeks before the race


def _params(
    vdot: float = 49.0,
    baseline: float = 35.0,
    target_s: int | None = 4 * 3600,
    start: date = _START_18WK,
) -> PlanParams:
    return PlanParams(
        goal_type="marathon",
        start_date=start,
        race_date=_RACE,
        target_time_s=target_s,
        days_per_week=5,
        long_run_day=_RACE.weekday(),
        current_vdot=vdot,
        weekly_km_baseline=baseline,
    )


def _generate(**kw):
    return Pfitzinger18_55().generate(_params(**kw))


def _by_week(workouts):
    weeks: dict[int, list] = {}
    for w in workouts:
        weeks.setdefault(w.week_number, []).append(w)
    return weeks


def test_span_is_18_full_weeks() -> None:
    ws = _generate()
    assert Pfitzinger18_55().total_weeks("marathon", _RACE, _START_18WK) == 18
    weeks = _by_week(ws)
    assert sorted(weeks) == list(range(1, TOTAL_WEEKS + 1)), f"weeks: {sorted(weeks)}"
    assert all(len(v) == 7 for v in weeks.values()), "every week must have 7 day rows"
    assert len(ws) == TOTAL_WEEKS * 7


def test_race_lands_on_race_date_final_week() -> None:
    ws = _generate()
    race_rows = [w for w in ws if w.planned_date == _RACE]
    assert len(race_rows) == 1, "exactly one row on race day"
    r = race_rows[0]
    assert r.workout_type == "race"
    assert r.week_number == TOTAL_WEEKS, "race must be in week 18"
    assert abs((r.target_distance_km or 0) - 42.195) < 0.01, "marathon distance"
    assert r.target_duration_s == 4 * 3600, "target time flows through"
    # Plan ends on race day; starts 17 weeks earlier on the same weekday cycle.
    assert ws[-1].planned_date == _RACE


def test_phase_badges_in_order() -> None:
    """Weeks map to base(6) → build(5) → peak(4) → taper(3)."""
    weeks = _by_week(_generate())
    badges = [weeks[w][0].week_phase for w in sorted(weeks)]
    expected = ["base"] * 6 + ["build"] * 5 + ["peak"] * 4 + ["taper"] * 3
    assert badges == expected, f"phase badges: {badges}"


def test_only_allowed_workout_types() -> None:
    used = {w.workout_type for w in _generate()}
    illegal = used - _ALLOWED_TYPES
    assert not illegal, f"illegal workout types: {illegal}"


def test_paces_match_vdot_table() -> None:
    """Every prescribed pace is one of the runner's VDOT zone paces — the
    engine never invents a pace outside the Daniels table."""
    paces = _paces_for_vdot(49.0)
    zone_values = set(paces.values())
    for w in _generate():
        if w.target_pace_s_per_km is None:
            continue
        if w.workout_type == "race":
            continue  # race pace is derived from target time, not a zone
        assert w.target_pace_s_per_km in zone_values, (
            f"{w.title}: pace {w.target_pace_s_per_km} not in VDOT zones {sorted(zone_values)}"
        )


def test_lactate_threshold_uses_T_pace() -> None:
    paces = _paces_for_vdot(49.0)
    lts = [w for w in _generate() if w.title.startswith("Lactate threshold")]
    assert lts, "expected lactate-threshold sessions"
    assert all(w.target_pace_s_per_km == paces["T"] for w in lts)
    assert all(w.workout_type == "tempo" for w in lts)


def test_vo2max_uses_I_pace_and_intervals() -> None:
    paces = _paces_for_vdot(49.0)
    vo2 = [w for w in _generate() if "VO" in w.title and "max" in w.title]
    assert vo2, "expected VO2max sessions"
    assert all(w.target_pace_s_per_km == paces["I"] for w in vo2)
    assert all(w.workout_type == "intervals" for w in vo2)


def test_long_run_cap_respected_and_reached() -> None:
    """The signature 20-miler: the biggest plain long run must hit the 32 km
    ceiling exactly — never exceed it, and never fall short of it either."""
    longs = [w for w in _generate() if w.workout_type == "long"]
    biggest = max((w.target_distance_km or 0) for w in longs)
    assert biggest == _LONG_CAP_KM, f"biggest long run {biggest} km != cap {_LONG_CAP_KM}"


def test_peak_weekly_volume_near_target() -> None:
    """Some week peaks close to the ~88 km ceiling; none blows past it (the
    race-week total is excluded — it's dominated by the 42 km marathon)."""
    weeks = _by_week(_generate())
    totals = {
        wn: sum(w.target_distance_km or 0 for w in rows)
        for wn, rows in weeks.items()
        if wn != TOTAL_WEEKS
    }
    peak = max(totals.values())
    assert peak <= _PEAK_KM + 6, f"peak week {peak} km overshoots ceiling"
    assert peak >= _PEAK_KM - 12, f"peak week {peak} km never approaches target"


def test_two_tuneup_races_before_the_marathon() -> None:
    ws = _generate()
    tuneups = [w for w in ws if w.workout_type == "race" and w.planned_date != _RACE]
    assert len(tuneups) == 2, f"expected 2 tune-up races, got {len(tuneups)}"
    assert all(w.planned_date < _RACE for w in tuneups)
    assert all("Tune-up" in w.title for w in tuneups)


def test_marathon_pace_long_runs_have_E_and_M_structure() -> None:
    """MP long runs carry the two-step zone-tagged structure so the M-pace
    finish reaches the watch and survives recalibration."""
    paces = _paces_for_vdot(49.0)
    mp_longs = [w for w in _generate() if w.workout_type == "long" and "@ MP" in w.title]
    assert mp_longs, "expected marathon-pace long runs"
    for w in mp_longs:
        steps = (w.workout_structure or {}).get("steps", [])
        zones = [s.get("zone") for s in steps]
        assert zones == ["E", "M"], f"{w.title}: zones {zones}"
        assert steps[1]["pace_s_per_km"] == paces["M"]


def test_baseline_mismatch_note_only_when_far_below() -> None:
    """A low base attaches the ramp-conservatively caution to week 1's long
    run; a base near the plan's opening volume does not."""
    def week1_long_desc(baseline: float) -> str:
        ws = Pfitzinger18_55().generate(_params(baseline=baseline))
        # The weekend long run, not the mid-week medium-long (both are "long"
        # workout_type; only the real long run carries the caution).
        w1 = [
            w for w in ws
            if w.week_number == 1 and w.title.startswith("Long ")
        ][0]
        return w1.description

    assert "Heads up" in week1_long_desc(18.0), "low base should get the caution"
    assert "Heads up" not in week1_long_desc(60.0), "high base should not"


def test_mp_blocks_progress_toward_race() -> None:
    """The marathon-pace block grows through the plan (book: 8 mi → 14 mi @ MP)
    and the final rehearsal covers at least ~two-thirds of its run."""
    mp_longs = sorted(
        (w for w in _generate() if w.workout_type == "long" and "@ MP" in w.title),
        key=lambda w: w.planned_date,
    )
    assert len(mp_longs) >= 3, "expected an MP rehearsal + race-prep MP long runs"
    mp_kms = [w.workout_structure["steps"][1]["end"]["distance_m"] / 1000 for w in mp_longs]
    assert mp_kms == sorted(mp_kms) and mp_kms[0] < mp_kms[-1], f"MP blocks not progressive: {mp_kms}"
    assert mp_kms[-1] >= 0.65 * mp_longs[-1].target_distance_km, (
        f"final MP block {mp_kms[-1]} km too small for {mp_longs[-1].target_distance_km} km run"
    )


def test_tuneup_race_precedes_a_long_run() -> None:
    """Book-style tune-up weekends: race one day, long run the next morning."""
    ws = _generate()
    by_date = {w.planned_date: w for w in ws}
    tuneups = [w for w in ws if w.workout_type == "race" and w.planned_date != _RACE]
    assert len(tuneups) == 2
    for r in tuneups:
        next_day = by_date[r.planned_date + timedelta(days=1)]
        assert next_day.workout_type == "long", (
            f"expected a long run the day after the {r.planned_date} tune-up, "
            f"got {next_day.workout_type}"
        )


def test_taper_has_no_threshold_work() -> None:
    """Pfitzinger's taper sharpens with short VO₂max touches only — a sustained
    LT tempo 10-12 days out is exactly what the taper exists to avoid."""
    weeks = _by_week(_generate())
    for wn in (16, 17):
        types = {w.workout_type for w in weeks[wn]}
        assert "tempo" not in types, f"week {wn} contains an LT tempo"
        assert "intervals" in types, f"week {wn} should keep a VO₂max touch"


def test_vo2max_distance_matches_structure() -> None:
    """The card distance is derived from the structure (WU + reps + jogs + CD),
    not from the weekly quality allocation."""
    for w in _generate():
        if w.workout_type != "intervals":
            continue
        steps = w.workout_structure["steps"]
        reps = steps[1]["iterations"]
        floor_km = 4.0 + reps * 1.0            # WU 2 + CD 2 + reps, jogs excluded
        assert floor_km <= w.target_distance_km <= floor_km + reps * 0.6, (
            f"{w.title}: distance {w.target_distance_km} km vs structure floor {floor_km} km"
        )


def test_taper_sheds_volume_even_on_high_baseline() -> None:
    """A runner already at/above the 88 km peak still gets a real taper."""
    weeks = _by_week(Pfitzinger18_55().generate(_params(baseline=95.0)))
    peak = max(
        sum(w.target_distance_km or 0 for w in rows)
        for wn, rows in weeks.items() if wn <= 15
    )
    wk17 = sum(w.target_distance_km or 0 for w in weeks[17])
    assert wk17 <= 0.65 * peak, f"taper week 17 = {wk17} km vs peak {peak} km"


def test_short_window_compresses_instead_of_backdating() -> None:
    """A race 16 weeks out drops two endurance weeks; nothing lands before the
    start date and the race anchors stay tied to the race."""
    eng = Pfitzinger18_55()
    assert eng.total_weeks("marathon", _RACE, _START_16WK) == 16
    ws = eng.generate(_params(start=_START_16WK))
    weeks = _by_week(ws)
    assert sorted(weeks) == list(range(1, 17)), f"weeks: {sorted(weeks)}"
    assert min(w.planned_date for w in ws) >= _START_16WK, "workouts back-dated before start"
    badges = [weeks[w][0].week_phase for w in sorted(weeks)]
    assert badges == ["base"] * 4 + ["build"] * 5 + ["peak"] * 4 + ["taper"] * 3
    assert [w for w in ws if w.planned_date == _RACE][0].workout_type == "race"
    tuneups = [w for w in ws if w.workout_type == "race" and w.planned_date != _RACE]
    assert len(tuneups) == 2, "compressed plan must keep both tune-up races"


def test_too_short_window_raises() -> None:
    _raises(
        lambda: Pfitzinger18_55().generate(_params(start=date(2026, 9, 1))),
        "at least 12 weeks",
    )


def test_requires_marathon_goal_and_race_date() -> None:
    eng = Pfitzinger18_55()
    bad_goal = _params()
    bad_goal.goal_type = "half_marathon"
    _raises(lambda: eng.generate(bad_goal), "marathon")

    no_race = _params()
    no_race.race_date = None
    _raises(lambda: eng.generate(no_race), "race date")


def _raises(fn, needle: str) -> None:
    try:
        fn()
    except ValueError as exc:
        assert needle.lower() in str(exc).lower(), f"wrong error: {exc}"
    else:
        raise AssertionError(f"expected ValueError mentioning {needle!r}")


# ──────────────────────────────────────────────────────────────────────────

TESTS = [
    test_span_is_18_full_weeks,
    test_race_lands_on_race_date_final_week,
    test_phase_badges_in_order,
    test_only_allowed_workout_types,
    test_paces_match_vdot_table,
    test_lactate_threshold_uses_T_pace,
    test_vo2max_uses_I_pace_and_intervals,
    test_long_run_cap_respected_and_reached,
    test_peak_weekly_volume_near_target,
    test_two_tuneup_races_before_the_marathon,
    test_marathon_pace_long_runs_have_E_and_M_structure,
    test_baseline_mismatch_note_only_when_far_below,
    test_mp_blocks_progress_toward_race,
    test_tuneup_race_precedes_a_long_run,
    test_taper_has_no_threshold_work,
    test_vo2max_distance_matches_structure,
    test_taper_sheds_volume_even_on_high_baseline,
    test_short_window_compresses_instead_of_backdating,
    test_too_short_window_raises,
    test_requires_marathon_goal_and_race_date,
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
