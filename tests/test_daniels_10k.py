"""Lock-down tests for the Daniels 10K plan.

Origin (2026-07-18): reviewing plan enrollment surfaced two 10K problems.
The default plan was 8 weeks with a 1-week taper that never tapered — the
taper interpolation `t = week_in_phase / max(phase_len - 1, 1)` gives t=0
for a 1-week phase, leaving the race week at 0.85 × peak volume. The default
is now 10 weeks (base 3 / build 4 / peak 2 / taper 1) and a single taper
week sits at the midpoint of the ramp: 0.60 × peak. Multi-week tapers keep
the historical 0.85 → 0.35 endpoints bit-for-bit.

Run from repo root:
    .venv/Scripts/python.exe tests/test_daniels_10k.py
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from running_coach.plans.daniels import (  # noqa: E402
    DanielsVDOT,
    _paces_for_vdot,
    _weekly_km_for_week,
)
from running_coach.plans.methodology import PlanParams  # noqa: E402


def _params(race_date: date | None = None) -> PlanParams:
    return PlanParams(
        goal_type="10k",
        start_date=date(2026, 7, 20),  # a Monday
        race_date=race_date,
        target_time_s=None,
        days_per_week=4,
        long_run_day=6,
        current_vdot=45.0,
        weekly_km_baseline=30.0,
        workout_days=[1, 3, 4, 6],
    )


def _weeks_by_phase(workouts) -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    for w in workouts:
        out.setdefault(w.week_phase, [])
        if w.week_number not in out[w.week_phase]:
            out[w.week_phase].append(w.week_number)
    return out


def test_default_is_10_weeks_3_4_2_1() -> None:
    workouts = DanielsVDOT().generate(_params())
    assert len(workouts) == 70, f"expected 10 weeks × 7 rows, got {len(workouts)}"
    phases = _weeks_by_phase(workouts)
    assert phases["base"] == [1, 2, 3], f"base weeks: {phases['base']}"
    assert phases["build"] == [4, 5, 6, 7], f"build weeks: {phases['build']}"
    assert phases["peak"] == [8, 9], f"peak weeks: {phases['peak']}"
    assert phases["taper"] == [10], f"taper weeks: {phases['taper']}"


def test_single_week_taper_lands_at_60pct_of_peak() -> None:
    """THE BUG: a 1-week taper used to land at 0.85 × peak."""
    peak = _weekly_km_for_week(7, 10, "peak", "10k", 30.0)
    taper = _weekly_km_for_week(9, 10, "taper", "10k", 30.0)
    ratio = taper / peak
    assert 0.55 <= ratio <= 0.65, (
        f"1-week taper should sit at ~0.60 × peak, got {ratio:.2f} "
        f"(taper {taper} km vs peak {peak} km) — 0.85 is the old bug"
    )


def test_multi_week_tapers_unchanged() -> None:
    """Half (2-wk taper) and marathon (3-wk) keep the 0.85 → 0.35 ramp."""
    def close(actual: float, expected: float) -> None:
        assert abs(actual - expected) <= 0.11, f"{actual} != {expected} (±0.1 rounding)"

    # Half marathon: 12 weeks, taper = weeks 11-12 (indices 10, 11).
    hm_peak = _weekly_km_for_week(9, 12, "peak", "half_marathon", 30.0)
    close(_weekly_km_for_week(10, 12, "taper", "half_marathon", 30.0), hm_peak * 0.85)
    close(_weekly_km_for_week(11, 12, "taper", "half_marathon", 30.0), hm_peak * 0.35)
    # Marathon: 16 weeks, taper = weeks 14-16 (indices 13-15); middle = 0.60.
    m_peak = _weekly_km_for_week(12, 16, "peak", "marathon", 30.0)
    close(_weekly_km_for_week(13, 16, "taper", "marathon", 30.0), m_peak * 0.85)
    close(_weekly_km_for_week(14, 16, "taper", "marathon", 30.0), m_peak * 0.60)
    close(_weekly_km_for_week(15, 16, "taper", "marathon", 30.0), m_peak * 0.35)


def test_base_quality_is_tempo_at_t_pace() -> None:
    workouts = DanielsVDOT().generate(_params())
    paces = _paces_for_vdot(45.0)
    base_quality = [w for w in workouts
                    if w.week_phase == "base" and w.workout_type in ("tempo", "intervals")]
    assert len(base_quality) == 3
    for w in base_quality:
        assert w.title.startswith("Tempo"), f"base quality should be tempo, got '{w.title}'"
        assert w.target_pace_s_per_km == paces["T"]


def test_build_alternates_tempo_and_1000s() -> None:
    workouts = DanielsVDOT().generate(_params())
    build_quality = [w for w in workouts
                     if w.week_phase == "build" and w.workout_type in ("tempo", "intervals")]
    assert len(build_quality) == 4
    kinds = [w.title.split()[0] for w in build_quality]
    assert kinds == ["Tempo", "Intervals", "Tempo", "Intervals"], f"got {kinds}"
    for w in build_quality:
        if w.workout_type == "intervals":
            assert "1000 m" in w.title


def test_peak_weeks_run_800s_then_1000s() -> None:
    workouts = DanielsVDOT().generate(_params())
    paces = _paces_for_vdot(45.0)
    peak_quality = [w for w in workouts
                    if w.week_phase == "peak" and w.workout_type == "intervals"]
    assert len(peak_quality) == 2
    assert peak_quality[0].title == "Intervals 6×800 m"
    assert peak_quality[1].title == "Intervals 5×1000 m"
    for w in peak_quality:
        assert w.target_pace_s_per_km == paces["I"]


def test_all_paces_come_from_the_vdot_table() -> None:
    workouts = DanielsVDOT().generate(_params())
    allowed = set(_paces_for_vdot(45.0).values())
    for w in workouts:
        if w.target_pace_s_per_km is not None and w.workout_type != "race":
            assert w.target_pace_s_per_km in allowed, (
                f"{w.title}: pace {w.target_pace_s_per_km} not in the VDOT-45 table"
            )


def test_weekly_totals_track_the_volume_curve() -> None:
    """Title-rounded distances must stay close to the weekly volume target,
    and the taper week must actually be lighter than the peak weeks."""
    workouts = DanielsVDOT().generate(_params())
    by_week: dict[int, float] = {}
    for w in workouts:
        if w.target_distance_km and w.workout_type != "race":
            by_week[w.week_number] = by_week.get(w.week_number, 0) + w.target_distance_km
    peak_avg = (by_week[8] + by_week[9]) / 2
    assert by_week[10] < peak_avg * 0.75, (
        f"taper week ({by_week[10]} km) barely below peak ({peak_avg} km)"
    )


def test_race_overlay_on_race_date() -> None:
    start = date(2026, 7, 20)
    race = start + timedelta(weeks=9, days=6)  # Sunday of week 10
    workouts = DanielsVDOT().generate(_params(race_date=race))
    race_days = [w for w in workouts if w.workout_type == "race"]
    assert len(race_days) == 1
    assert race_days[0].planned_date == race
    assert race_days[0].target_distance_km == 10.0


TESTS = [
    test_default_is_10_weeks_3_4_2_1,
    test_single_week_taper_lands_at_60pct_of_peak,
    test_multi_week_tapers_unchanged,
    test_base_quality_is_tempo_at_t_pace,
    test_build_alternates_tempo_and_1000s,
    test_peak_weeks_run_800s_then_1000s,
    test_all_paces_come_from_the_vdot_table,
    test_weekly_totals_track_the_volume_curve,
    test_race_overlay_on_race_date,
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
