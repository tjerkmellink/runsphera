"""Tests for runsphera.execution_score — composite execution score
shown as a corner ring on completed plan-workout cards.

The scoring math is the bit that needs guarding: tolerance bands per
workout type, asymmetric over/under penalties on easy-vs-tempo, and
the weighted combine. The compute() integration is exercised through
synthetic activity dicts so we don't hit the DB.

Run with:
    .venv/Scripts/python.exe tests/test_execution_score.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runsphera.execution_score import (  # noqa: E402
    _color_for, _distance_score, _hr_score, _pace_score, compute,
)


def _close(actual: float, expected: float, label: str, tol: float = 1.0) -> None:
    if abs(actual - expected) > tol:
        raise AssertionError(f"{label}: got {actual}, expected ~{expected} (±{tol})")


# ── Pace score ─────────────────────────────────────────────────────

def test_pace_tempo_on_target() -> None:
    """Active block at target = 100."""
    s = _pace_score(actual_s=300, target_s=300, workout_type="tempo")
    _close(s, 100, "tempo on target")


def test_pace_tempo_within_tight_band() -> None:
    """±5s on a tempo target stays at 100 (Daniels' window)."""
    assert _pace_score(305, 300, "tempo") == 100, "tempo +5s should be 100"
    assert _pace_score(295, 300, "tempo") == 100, "tempo -5s should be 100"


def test_pace_tempo_falloff_to_zero() -> None:
    """25 s/km off = 0; halfway is ~50."""
    _close(_pace_score(325, 300, "tempo"), 0, "tempo +25s")
    _close(_pace_score(275, 300, "tempo"), 0, "tempo -25s")
    _close(_pace_score(315, 300, "tempo"), 50, "tempo +15s", tol=2)


def test_pace_easy_slower_than_target_is_fine() -> None:
    """30s slower than easy target = still easy. Wide `over` tolerance
    (60s) means no penalty. On tempo the same +30s diff would be zero."""
    assert _pace_score(330, 300, "easy") == 100, "easy +30s should be 100"
    _close(_pace_score(330, 300, "tempo"), 0, "tempo +30s", tol=2)


def test_pace_easy_faster_than_target_is_penalized() -> None:
    """Easy run TOO FAST = "you didn't actually recover" — narrow `under`
    band. -20s is the tight edge; -50s mid-falloff; -75s ≈ zero."""
    assert _pace_score(280, 300, "easy") == 100, "easy -20s should be 100"
    s50 = _pace_score(250, 300, "easy")  # 50s faster
    assert 30 < s50 < 70, f"easy -50s mid-falloff, got {s50}"
    _close(_pace_score(225, 300, "easy"), 0, "easy -75s (out of band)", tol=2)


def test_pace_unknown_inputs_return_none() -> None:
    assert _pace_score(None, 300, "tempo") is None
    assert _pace_score(300, None, "tempo") is None
    assert _pace_score(300, 300, "rest") is None  # no tolerance entry


# ── Distance score ────────────────────────────────────────────────

def test_distance_dead_on() -> None:
    assert _distance_score(10.0, 10.0) == 100


def test_distance_within_tolerance() -> None:
    """0.95–1.10 ratio is a flat 100."""
    assert _distance_score(9.5, 10.0) == 100, "95% completion"
    assert _distance_score(11.0, 10.0) == 100, "110% (long-run-runs-long)"


def test_distance_sharp_undershoot_penalty() -> None:
    """Under 95% completion drops sharply; 50% completion = 0."""
    _close(_distance_score(7.0, 10.0), 44, "70% complete", tol=2)
    _close(_distance_score(5.0, 10.0), 0, "50% complete")


def test_distance_overshoot_penalty() -> None:
    """Over 110% — linear falloff to zero at 150%. Burning reserves on
    one session has a real cost for the rest of the week."""
    _close(_distance_score(12.0, 10.0), 75, "120%", tol=2)
    _close(_distance_score(13.0, 10.0), 50, "130%", tol=2)
    _close(_distance_score(15.0, 10.0), 0,  "150%")


def test_distance_missing_target_returns_none() -> None:
    assert _distance_score(10.0, None) is None
    assert _distance_score(10.0, 0) is None


# ── HR score ───────────────────────────────────────────────────────

def test_hr_easy_mostly_aerobic_scores_high() -> None:
    """Easy run mostly in Z1+Z2+Z3 — high score."""
    activity = {
        "hr_zone_1_s": 600, "hr_zone_2_s": 1800, "hr_zone_3_s": 1200,
        "hr_zone_4_s": 0,   "hr_zone_5_s": 0,
    }
    s = _hr_score(activity, "easy")
    assert s == 100, f"all aerobic easy should be 100, got {s}"


def test_hr_easy_with_threshold_drift_loses_points() -> None:
    """Easy that drifts into Z4 for 30% of the run scores ~70."""
    activity = {
        "hr_zone_1_s": 0, "hr_zone_2_s": 700, "hr_zone_3_s": 0,
        "hr_zone_4_s": 300, "hr_zone_5_s": 0,
    }
    s = _hr_score(activity, "easy")
    _close(s, 70, "easy with Z4 drift")


def test_hr_tempo_in_threshold_zone() -> None:
    """Tempo mostly in Z3+Z4 — high HR score."""
    activity = {
        "hr_zone_1_s": 100, "hr_zone_2_s": 100, "hr_zone_3_s": 400,
        "hr_zone_4_s": 400, "hr_zone_5_s": 0,
    }
    s = _hr_score(activity, "tempo")
    _close(s, 80, "tempo Z3+Z4")


def test_hr_no_zone_data_returns_none() -> None:
    activity = {f"hr_zone_{i}_s": 0 for i in range(1, 6)}
    assert _hr_score(activity, "easy") is None
    activity = {f"hr_zone_{i}_s": None for i in range(1, 6)}
    assert _hr_score(activity, "easy") is None


# ── Color thresholds ──────────────────────────────────────────────

def test_color_thresholds() -> None:
    assert _color_for(100) == "green"
    assert _color_for(85)  == "green"
    assert _color_for(84)  == "amber"
    assert _color_for(60)  == "amber"
    assert _color_for(59)  == "red"
    assert _color_for(0)   == "red"


# ── compute() integration ──────────────────────────────────────────

class _StubConn:
    """Minimal stand-in for sqlite3.Connection. compute() only uses the
    conn to call laps.active_block_summary, which fails-soft to None
    when no laps exist for the given activity_id. For tempo workouts
    without laps we fall through to total-run avg pace."""
    def execute(self, *_, **__):  # pragma: no cover — never reached
        class _Row:
            def fetchall(self): return []
            def fetchone(self): return None
        return _Row()


def test_compute_perfect_tempo() -> None:
    """Tempo on target distance, on target pace, mostly aerobic HR."""
    conn = _StubConn()
    planned = {
        "workout_type": "tempo",
        "target_distance_km": 6.0,
        "target_pace_s_per_km": 300,
    }
    activity = {
        "activity_id": 1,
        "distance_m": 6000,
        "duration_s": 1800,  # exactly 5:00/km
        "avg_hr": 170,
        "hr_zone_1_s": 0, "hr_zone_2_s": 0, "hr_zone_3_s": 1000,
        "hr_zone_4_s": 800, "hr_zone_5_s": 0,
    }
    es = compute(conn, planned, activity)
    assert es is not None
    assert es["score"] >= 90, f"perfect tempo should be 90+, got {es['score']}"
    assert es["color"] == "green"


def test_compute_short_easy() -> None:
    """Easy run that cut short halfway through — distance dominates the
    penalty even if pace + HR are fine."""
    conn = _StubConn()
    planned = {
        "workout_type": "easy",
        "target_distance_km": 10.0,
        "target_pace_s_per_km": 380,
    }
    activity = {
        "activity_id": 2,
        "distance_m": 5000,           # half-done
        "duration_s": 1900,           # 6:20/km — on target
        "avg_hr": 140,
        "hr_zone_1_s": 200, "hr_zone_2_s": 1500, "hr_zone_3_s": 200,
        "hr_zone_4_s": 0, "hr_zone_5_s": 0,
    }
    es = compute(conn, planned, activity)
    assert es is not None
    assert es["score"] < 60, f"half-done easy should be red, got {es['score']}"
    assert es["color"] == "red"


def test_compute_rest_returns_none() -> None:
    conn = _StubConn()
    assert compute(conn, {"workout_type": "rest"}, {}) is None
    assert compute(conn, {"workout_type": "cross"}, {}) is None


def test_compute_no_activity_returns_none() -> None:
    conn = _StubConn()
    planned = {"workout_type": "easy", "target_distance_km": 10.0, "target_pace_s_per_km": 380}
    assert compute(conn, planned, None) is None


def test_compute_missing_target_returns_none() -> None:
    """No pace AND no distance to score against → can't compute."""
    conn = _StubConn()
    planned = {"workout_type": "easy", "target_distance_km": None, "target_pace_s_per_km": None}
    activity = {"activity_id": 3, "distance_m": 5000, "duration_s": 1900, "avg_hr": 140}
    assert compute(conn, planned, activity) is None


# ──────────────────────────────────────────────────────────────────

TESTS = [
    test_pace_tempo_on_target,
    test_pace_tempo_within_tight_band,
    test_pace_tempo_falloff_to_zero,
    test_pace_easy_slower_than_target_is_fine,
    test_pace_easy_faster_than_target_is_penalized,
    test_pace_unknown_inputs_return_none,
    test_distance_dead_on,
    test_distance_within_tolerance,
    test_distance_sharp_undershoot_penalty,
    test_distance_overshoot_penalty,
    test_distance_missing_target_returns_none,
    test_hr_easy_mostly_aerobic_scores_high,
    test_hr_easy_with_threshold_drift_loses_points,
    test_hr_tempo_in_threshold_zone,
    test_hr_no_zone_data_returns_none,
    test_color_thresholds,
    test_compute_perfect_tempo,
    test_compute_short_easy,
    test_compute_rest_returns_none,
    test_compute_no_activity_returns_none,
    test_compute_missing_target_returns_none,
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
