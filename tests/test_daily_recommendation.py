"""Tests for runsphera.plans.coach.daily_recommendation — the readiness /
ACWR rules engine behind the dashboard headline.

The case worth guarding hardest is DONE: once today's session is matched to an
activity, readiness and ACWR describe what that session *cost*, so they must
not drive a swap suggestion. Leaving them wired up produced "swap today's
quality session for an easy run" on a run already in the log — which the LLM
layer could only reconcile by relocating the run to yesterday.

The three DB reads are monkeypatched, so `conn` is never touched.

Run with:
    .venv/Scripts/python.exe tests/test_daily_recommendation.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runsphera.plans import coach as plan_coach  # noqa: E402


def _rec(workout: dict | None, readiness: dict | None, status: dict | None) -> dict | None:
    """Run daily_recommendation with the DB reads stubbed out."""
    orig = (
        plan_coach.plan_service.todays_workout,
        plan_coach._latest_readiness,
        plan_coach._latest_training_status,
    )
    plan_coach.plan_service.todays_workout = lambda conn: workout
    plan_coach._latest_readiness = lambda conn: readiness
    plan_coach._latest_training_status = lambda conn: status
    try:
        return plan_coach.daily_recommendation(None)
    finally:
        (
            plan_coach.plan_service.todays_workout,
            plan_coach._latest_readiness,
            plan_coach._latest_training_status,
        ) = orig


# Post-interval-session state: readiness tanked, acute load spiked. Exactly the
# shape that used to trigger an EASY swap on an already-completed workout.
_SPENT = {"score": 37, "level": "LOW"}
_SPIKED = {"acwr_ratio": 1.30, "acwr_status": "OPTIMAL"}
_FRESH = {"score": 86, "level": "HIGH"}
_STEADY = {"acwr_ratio": 0.95, "acwr_status": "OPTIMAL"}

_PLANNED = {"workout_type": "intervals", "actual_activity_id": None}
_LOGGED = {"workout_type": "intervals", "actual_activity_id": 23787468074}


# ── DONE: the session is already in the log ────────────────────────

def test_completed_workout_is_done_not_easy() -> None:
    rec = _rec(_LOGGED, _SPENT, _SPIKED)
    assert rec["status"] == "done", f"expected done, got {rec['status']}"


def test_completed_workout_never_suggests_a_swap() -> None:
    """The whole point: no prescription for a run that already happened."""
    rec = _rec(_LOGGED, _SPENT, _SPIKED)
    assert rec["suggestion"] is None, f"got a swap suggestion: {rec['suggestion']}"


def test_completed_workout_still_reports_state() -> None:
    """DONE is not silence — the post-session numbers still reach the coach."""
    rec = _rec(_LOGGED, _SPENT, _SPIKED)
    joined = "; ".join(rec["reasons"])
    assert "37" in joined, f"readiness missing from reasons: {joined}"
    assert "1.30" in joined, f"ACWR missing from reasons: {joined}"
    assert rec["signals"]["readiness"] == 37, "signals should carry the raw score"


def test_completed_headline_reads_as_past_tense() -> None:
    """Plural workout types must not produce 'today's intervals is logged'."""
    rec = _rec(_LOGGED, _SPENT, _SPIKED)
    assert "intervals session is logged" in rec["headline"], rec["headline"]


def test_completed_workout_when_well_recovered_is_still_done() -> None:
    """Completion wins over a green readiness signal — no GO on a done day."""
    rec = _rec(_LOGGED, _FRESH, _STEADY)
    assert rec["status"] == "done", f"expected done, got {rec['status']}"


# ── The prescriptive statuses still work ───────────────────────────

def test_unrun_workout_with_low_readiness_still_says_easy() -> None:
    """Same signals, nothing logged yet — the swap advice must survive."""
    rec = _rec(_PLANNED, _SPENT, _SPIKED)
    assert rec["status"] == "easy", f"expected easy, got {rec['status']}"
    assert rec["suggestion"], "an unrun quality session should still get a swap"


def test_unrun_workout_when_fresh_says_go() -> None:
    rec = _rec(_PLANNED, _FRESH, _STEADY)
    assert rec["status"] == "go", f"expected go, got {rec['status']}"
    assert rec["suggestion"] is None, "GO carries no swap suggestion"
    assert len(rec["reasons"]) == 2, f"GO should report both signals: {rec['reasons']}"


def test_rest_day_is_unaffected() -> None:
    rec = _rec({"workout_type": "rest", "actual_activity_id": None}, _SPENT, _SPIKED)
    assert rec["status"] == "rest", f"expected rest, got {rec['status']}"


def test_no_workout_today_returns_none() -> None:
    assert _rec(None, _FRESH, _STEADY) is None, "no planned workout → no recommendation"


def test_missing_signals_do_not_crash() -> None:
    """Garmin-less runners have neither readiness nor training status."""
    rec = _rec(_PLANNED, None, None)
    assert rec["status"] == "go", f"no signals should not penalize: {rec['status']}"
    assert rec["reasons"] == [], f"nothing to report: {rec['reasons']}"


TESTS = [
    test_completed_workout_is_done_not_easy,
    test_completed_workout_never_suggests_a_swap,
    test_completed_workout_still_reports_state,
    test_completed_headline_reads_as_past_tense,
    test_completed_workout_when_well_recovered_is_still_done,
    test_unrun_workout_with_low_readiness_still_says_easy,
    test_unrun_workout_when_fresh_says_go,
    test_rest_day_is_unaffected,
    test_no_workout_today_returns_none,
    test_missing_signals_do_not_crash,
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
