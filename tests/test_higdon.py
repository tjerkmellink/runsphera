"""Lock-down tests for the Hal Higdon tiered marathon & half engine.

Asserts the plan's non-negotiable shape across all six experience tiers and
both distances: correct week count (18 marathon / 12 half), the race overlaid
on the final long-run slot, paces pulled straight from the VDOT table, the
32 km (20-mile) marathon peak, tier-appropriate quality work (none for Novice
1; marathon-pace / tempo / hills / speed as the tier climbs), goal-pace zones
(M for the marathon, T for the half), short-window compression, and goal
validation.

Run from repo root:
    .venv/Scripts/python.exe tests/test_higdon.py
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runsphera.plans.methodology import PlanParams  # noqa: E402
from runsphera.plans.higdon import (  # noqa: E402
    HigdonPlan,
    _TIERS,
    _MARATHON_WEEKS,
    _HALF_WEEKS,
    _MARATHON_LONG_KM,
)
from runsphera.plans.daniels import _paces_for_vdot  # noqa: E402

# Mirrors service.ALLOWED_WORKOUT_TYPES; duplicated so the test avoids importing
# service.py (which pulls the optional garminconnect dep).
_ALLOWED_TYPES = frozenset(
    {"easy", "tempo", "intervals", "long", "recovery", "rest", "cross", "race"}
)

_MAR_RACE = date(2026, 11, 1)   # Sunday
_MAR_START = date(2026, 6, 22)  # Monday, 18+ weeks before
_MAR_START_15WK = date(2026, 7, 20)  # Monday, 15 weeks before

_HALF_RACE = date(2026, 9, 27)  # Sunday
_HALF_START = date(2026, 7, 6)  # Monday, 12+ weeks before

_PEAK_KM = max(_MARATHON_LONG_KM)  # 32


def _params(goal, variant, race, start, vdot=49.0, target_s=4 * 3600) -> PlanParams:
    return PlanParams(
        goal_type=goal,
        start_date=start,
        race_date=race,
        target_time_s=target_s,
        days_per_week=5,
        long_run_day=race.weekday(),
        current_vdot=vdot,
        weekly_km_baseline=35.0,
        variant=variant,
    )


def _gen(goal, variant, race=None, start=None):
    if goal == "marathon":
        race, start = race or _MAR_RACE, start or _MAR_START
    else:
        race, start = race or _HALF_RACE, start or _HALF_START
    return HigdonPlan().generate(_params(goal, variant, race, start))


def _by_week(workouts):
    weeks: dict[int, list] = {}
    for w in workouts:
        weeks.setdefault(w.week_number, []).append(w)
    return weeks


def test_all_tiers_marathon_are_18_full_weeks() -> None:
    for v in _TIERS:
        ws = _gen("marathon", v)
        weeks = _by_week(ws)
        assert sorted(weeks) == list(range(1, _MARATHON_WEEKS + 1)), f"{v}: {sorted(weeks)}"
        assert all(len(r) == 7 for r in weeks.values()), f"{v}: every week has 7 rows"
        assert len(ws) == _MARATHON_WEEKS * 7, v


def test_all_tiers_half_are_12_full_weeks() -> None:
    for v in _TIERS:
        ws = _gen("half_marathon", v)
        weeks = _by_week(ws)
        assert sorted(weeks) == list(range(1, _HALF_WEEKS + 1)), f"{v}: {sorted(weeks)}"
        assert len(ws) == _HALF_WEEKS * 7, v


def test_race_lands_on_race_date_final_week() -> None:
    for goal, race, weeks_total in (
        ("marathon", _MAR_RACE, _MARATHON_WEEKS),
        ("half_marathon", _HALF_RACE, _HALF_WEEKS),
    ):
        for v in _TIERS:
            ws = _gen(goal, v)
            race_rows = [w for w in ws if w.planned_date == race]
            assert len(race_rows) == 1, f"{goal}/{v}: one race row"
            r = race_rows[0]
            assert r.workout_type == "race", f"{goal}/{v}"
            assert r.week_number == weeks_total, f"{goal}/{v}: race in final week"
            assert ws[-1].planned_date == race, f"{goal}/{v}: plan ends on race day"


def test_only_allowed_workout_types() -> None:
    for goal in ("marathon", "half_marathon"):
        for v in _TIERS:
            used = {w.workout_type for w in _gen(goal, v)}
            assert not (used - _ALLOWED_TYPES), f"{goal}/{v}: illegal {used - _ALLOWED_TYPES}"


def test_paces_are_vdot_zone_values() -> None:
    """Every prescribed pace is a VDOT zone pace — the engine never invents a
    pace outside the Daniels table (race pace excepted; it comes from goal time)."""
    zone_values = set(_paces_for_vdot(49.0).values())
    for goal in ("marathon", "half_marathon"):
        for v in _TIERS:
            for w in _gen(goal, v):
                if w.target_pace_s_per_km is None or w.workout_type == "race":
                    continue
                assert w.target_pace_s_per_km in zone_values, (
                    f"{goal}/{v} {w.title}: {w.target_pace_s_per_km} not in zones"
                )


def test_novice_1_is_pure_easy_running() -> None:
    """The beginner plan: only easy runs, one long run, cross-training, rest —
    no tempo/intervals anywhere."""
    for goal in ("marathon", "half_marathon"):
        types = {w.workout_type for w in _gen(goal, "novice_1")}
        assert "tempo" not in types, f"{goal}: novice_1 has tempo"
        assert "intervals" not in types, f"{goal}: novice_1 has intervals"
        assert {"easy", "long", "cross", "rest"} <= types, f"{goal}: {types}"


def test_run_days_climb_with_tier() -> None:
    """Novice ~4, Intermediate ~5, Advanced ~6 running days per week (measured on
    a representative mid-plan week)."""
    def run_days(v):
        wk = [w for w in _gen("marathon", v) if w.week_number == 8]
        return sum(1 for w in wk if w.workout_type not in ("rest", "cross"))
    assert run_days("novice_1") == 4
    assert run_days("intermediate_1") == 5
    assert run_days("advanced_1") == 6
    assert run_days("advanced_2") == 6


def test_marathon_peak_long_run_is_32km() -> None:
    """The signature 20-miler: every tier's biggest long run hits the 32 km cap."""
    for v in _TIERS:
        longs = [w.target_distance_km or 0 for w in _gen("marathon", v) if w.workout_type == "long"]
        assert max(longs) == _PEAK_KM, f"{v}: peak long {max(longs)} != {_PEAK_KM}"


def test_advanced_has_more_20milers_than_novice() -> None:
    """Novice runs up to the peak once; Advanced flattens the top onto three
    20-milers."""
    def count_peak(v):
        return sum(
            1 for w in _gen("marathon", v)
            if w.workout_type == "long" and (w.target_distance_km or 0) == _PEAK_KM
        )
    novice, advanced = count_peak("novice_1"), count_peak("advanced_2")
    assert novice == 1, novice
    assert advanced >= 3, advanced
    assert advanced > novice


def test_half_ladder_is_never_flattened() -> None:
    """flatten_top is a marathon concept (the two/three 20-milers) — Higdon's
    half schedules peak exactly once, for every tier."""
    from runsphera.plans.higdon import _HALF_LONG_KM
    half_peak = max(_HALF_LONG_KM)
    for v in _TIERS:
        longs = [w.target_distance_km or 0 for w in _gen("half_marathon", v) if w.workout_type == "long"]
        n_peak = sum(1 for km in longs if km == half_peak)
        assert n_peak == 1, f"{v}: {n_peak} peak long runs in the half plan ({longs})"
        # The step-back rhythm survives: the ladder is used as authored.
        assert longs == _HALF_LONG_KM, f"{v}: half ladder altered: {longs}"


def test_hill_repeats_distance_matches_structure() -> None:
    """The headline distance is derived from the structure (WU + reps + 90 s
    jog-backs at E pace + CD) so the card, weekly totals, and the pushed
    workout agree — the plan-engine distance↔structure contract."""
    paces = _paces_for_vdot(49.0)
    hills = [w for w in _gen("marathon", "advanced_1") if w.title.startswith("Hill repeats")]
    assert hills, "expected hill sessions in advanced_1"
    for w in hills:
        reps = w.workout_structure["steps"][1]["iterations"]
        implied = 4.0 + reps * (0.4 + round(90 / paces["E"], 2))
        assert abs(w.target_distance_km - implied) < 0.1, (
            f"{w.title}: headline {w.target_distance_km} vs structure-implied {implied:.1f}"
        )


def test_weekday_volumes_taper_last_two_weeks() -> None:
    """The race-week 0.6× cut applies only to the final week; the week before
    gets the 0.8× taper — matching the two taper-badged weeks."""
    from runsphera.plans.higdon import _weekday_km
    assert _weekday_km(10, 18, 18) == 6.0   # race week
    assert _weekday_km(10, 17, 18) == 8.0   # taper week
    assert _weekday_km(10, 16, 18) == 10.0  # last full week — no cut yet


def test_registry_variants_match_engine_tiers() -> None:
    """The registry's variant list and the engine's _TIERS are the same six
    tiers, in the same order, with the same labels — a typo in either would
    otherwise ship a picker whose choices raise at generation time. The
    attached day offsets must match the tier templates (the form mirrors
    them into the day pickers) and their counts must match the tier copy
    (Novice 4, Intermediate 5, Advanced 6 run days)."""
    from runsphera.plans import get_methodology_info
    from runsphera.plans.higdon import tier_day_offsets
    info = get_methodology_info("higdon")
    assert [v[0] for v in info.variants] == list(_TIERS.keys())
    assert {v[0]: v[1] for v in info.variants} == {
        k: t.label for k, t in _TIERS.items()
    }
    for vid, _label, _desc, offsets in info.variants:
        assert offsets == tier_day_offsets(vid), vid
    days_per_week = {v[0]: len(v[3]) for v in info.variants}
    assert days_per_week == {
        "novice_1": 4, "novice_2": 4,
        "intermediate_1": 5, "intermediate_2": 5,
        "advanced_1": 6, "advanced_2": 6,
    }, days_per_week


def test_unknown_variant_raises() -> None:
    """Unknown tier values fail loud — a silent Novice 1 fallback would let a
    plan generate a different tier than the label stored on it."""
    _raises(
        lambda: HigdonPlan().generate(_params("marathon", "garbage", _MAR_RACE, _MAR_START)),
        "unknown higdon experience tier",
    )


def test_marathon_pace_runs_use_M_pace() -> None:
    paces = _paces_for_vdot(49.0)
    mp_runs = [w for w in _gen("marathon", "advanced_1") if w.title.startswith("Marathon-pace run")]
    assert mp_runs, "expected marathon-pace runs in advanced_1"
    assert all(w.workout_type == "tempo" and w.target_pace_s_per_km == paces["M"] for w in mp_runs)


def test_half_pace_runs_use_T_pace() -> None:
    """Half-marathon goal pace ≈ threshold, so pace runs must sit at T, not M."""
    paces = _paces_for_vdot(49.0)
    pace_runs = [w for w in _gen("half_marathon", "intermediate_1") if w.title.startswith("Half-pace run")]
    assert pace_runs, "expected half-pace runs"
    assert all(w.workout_type == "tempo" and w.target_pace_s_per_km == paces["T"] for w in pace_runs)


def test_hills_and_speed_use_I_pace_intervals() -> None:
    paces = _paces_for_vdot(49.0)
    hills = [w for w in _gen("marathon", "advanced_1") if w.title.startswith("Hill repeats")]
    speed = [w for w in _gen("marathon", "advanced_2") if w.title.startswith("Speed")]
    assert hills and speed, "expected hills (adv_1) and speed (adv_2)"
    for w in hills + speed:
        assert w.workout_type == "intervals", w.title
        assert w.target_pace_s_per_km == paces["I"], w.title


def test_mp_long_runs_carry_E_M_structure() -> None:
    """Marathon-pace-finish long runs carry the two-step zone-tagged structure
    so the M finish reaches the watch and survives recalibration."""
    paces = _paces_for_vdot(49.0)
    mp_longs = [
        w for w in _gen("marathon", "advanced_2")
        if w.workout_type == "long" and "@ goal pace" in w.title
    ]
    assert mp_longs, "expected MP-finish long runs"
    for w in mp_longs:
        steps = (w.workout_structure or {}).get("steps", [])
        assert [s.get("zone") for s in steps] == ["E", "M"], f"{w.title}: {steps}"
        assert steps[1]["pace_s_per_km"] == paces["M"]


def test_half_long_runs_have_no_mp_finish() -> None:
    """Half plans keep long runs plain — goal-pace work lives in the pace run,
    not the long run (avoids the marathon-pace vs half-pace zone mismatch)."""
    for v in _TIERS:
        mp_longs = [w for w in _gen("half_marathon", v) if "@ goal pace" in w.title]
        assert not mp_longs, f"{v}: half long run should not carry an MP finish"


def test_taper_is_final_two_weeks() -> None:
    for goal, total in (("marathon", _MARATHON_WEEKS), ("half_marathon", _HALF_WEEKS)):
        weeks = _by_week(_gen(goal, "intermediate_1"))
        assert weeks[total][0].week_phase == "taper", goal
        assert weeks[total - 1][0].week_phase == "taper", goal
        # Week 1 opens in base.
        assert weeks[1][0].week_phase == "base", goal


def test_peak_phase_contains_the_biggest_long_run() -> None:
    ws = _gen("marathon", "novice_1")
    peak_week = max(
        (w for w in ws if w.workout_type == "long"),
        key=lambda w: (w.target_distance_km or 0),
    )
    assert peak_week.week_phase == "peak", peak_week.week_number


def test_cross_training_has_no_pace_or_structure() -> None:
    cross = [w for w in _gen("marathon", "novice_1") if w.workout_type == "cross"]
    assert cross, "novice_1 should schedule cross-training"
    for w in cross:
        assert w.target_pace_s_per_km is None and w.workout_structure is None


def test_null_variant_defaults_to_novice_1() -> None:
    default = HigdonPlan().generate(_params("marathon", None, _MAR_RACE, _MAR_START))
    novice = _gen("marathon", "novice_1")
    assert [w.title for w in default] == [w.title for w in novice]


def test_short_window_compresses_instead_of_backdating() -> None:
    eng = HigdonPlan()
    assert eng.total_weeks("marathon", _MAR_RACE, _MAR_START_15WK) == 15
    ws = eng.generate(_params("marathon", "novice_1", _MAR_RACE, _MAR_START_15WK))
    weeks = _by_week(ws)
    assert sorted(weeks) == list(range(1, 16)), sorted(weeks)
    assert min(w.planned_date for w in ws) >= _MAR_START_15WK, "back-dated before start"
    # The race and the 32 km peak still land (peak anchors stay tied to race).
    assert [w for w in ws if w.planned_date == _MAR_RACE][0].workout_type == "race"
    assert max((w.target_distance_km or 0) for w in ws if w.workout_type == "long") == _PEAK_KM


def test_too_short_window_raises() -> None:
    _raises(
        lambda: HigdonPlan().generate(
            _params("marathon", "novice_1", _MAR_RACE, date(2026, 9, 7))
        ),
        "at least 12 weeks",
    )


def test_requires_supported_goal_and_race_date() -> None:
    eng = HigdonPlan()
    bad_goal = _params("10k", "novice_1", _MAR_RACE, _MAR_START)
    _raises(lambda: eng.generate(bad_goal), "half marathon and the marathon")

    no_race = _params("marathon", "novice_1", _MAR_RACE, _MAR_START)
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
    test_all_tiers_marathon_are_18_full_weeks,
    test_all_tiers_half_are_12_full_weeks,
    test_race_lands_on_race_date_final_week,
    test_only_allowed_workout_types,
    test_paces_are_vdot_zone_values,
    test_novice_1_is_pure_easy_running,
    test_run_days_climb_with_tier,
    test_marathon_peak_long_run_is_32km,
    test_advanced_has_more_20milers_than_novice,
    test_half_ladder_is_never_flattened,
    test_hill_repeats_distance_matches_structure,
    test_weekday_volumes_taper_last_two_weeks,
    test_registry_variants_match_engine_tiers,
    test_unknown_variant_raises,
    test_marathon_pace_runs_use_M_pace,
    test_half_pace_runs_use_T_pace,
    test_hills_and_speed_use_I_pace_intervals,
    test_mp_long_runs_carry_E_M_structure,
    test_half_long_runs_have_no_mp_finish,
    test_taper_is_final_two_weeks,
    test_peak_phase_contains_the_biggest_long_run,
    test_cross_training_has_no_pace_or_structure,
    test_null_variant_defaults_to_novice_1,
    test_short_window_compresses_instead_of_backdating,
    test_too_short_window_raises,
    test_requires_supported_goal_and_race_date,
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
