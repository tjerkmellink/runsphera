"""Test for the Daniels VDOT-from-race calculator (Tier 2b feature).

The formula has well-known reference points: VDOT 50 = HM 1:31:35, VDOT 40 =
HM 2:00:00, VDOT 60 = HM 1:20-ish. We assert the estimator lands close to
those — within 1 VDOT point of the published Daniels chart, which accounts
for rounding and the formula's modest error margin in the amateur range.

Run with:
    .venv/Scripts/python.exe tests/test_vdot_estimator.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from running_coach.plans.service import estimate_vdot_from_race  # noqa: E402


def _assert_close(actual: float, expected: float, label: str, tol: float = 1.0) -> None:
    if abs(actual - expected) > tol:
        raise AssertionError(
            f"{label}: got VDOT {actual}, expected ~{expected} (±{tol})"
        )


def test_hm_1_55_lands_around_vdot_40() -> None:
    """The bug-report case: HM 1:55:00 should give VDOT ~39-40, NOT 49 as
    Garmin's HR-based estimate suggested."""
    vdot = estimate_vdot_from_race(21097.5, 115 * 60)
    _assert_close(vdot, 38.5, "HM 1:55", tol=1.5)
    assert vdot < 45, (
        f"HM 1:55 → VDOT {vdot}. Should be well below 45; if it isn't, the "
        f"calibration is off."
    )


def test_hm_1_31_35_is_vdot_50() -> None:
    """Reference: Daniels' chart shows VDOT 50 ≈ HM 1:31:35."""
    vdot = estimate_vdot_from_race(21097.5, 91 * 60 + 35)
    _assert_close(vdot, 50.0, "HM 1:31:35")


def test_5k_19_57_is_vdot_50() -> None:
    """Reference: VDOT 50 ≈ 5K in 19:57."""
    vdot = estimate_vdot_from_race(5000, 19 * 60 + 57)
    _assert_close(vdot, 50.0, "5K 19:57", tol=1.5)


def test_marathon_3_10_49_is_vdot_50() -> None:
    """Reference: VDOT 50 ≈ marathon in 3:10:49."""
    vdot = estimate_vdot_from_race(42195, 3 * 3600 + 10 * 60 + 49)
    _assert_close(vdot, 50.0, "Marathon 3:10:49", tol=1.5)


def test_marathon_3_43_is_vdot_40() -> None:
    """Reference: Daniels' chart shows VDOT 40 ≈ 3:43:23 marathon
    (4:00:00 actually corresponds to ~VDOT 38, NOT 40 as one might assume —
    common amateur intuition trap)."""
    vdot = estimate_vdot_from_race(42195, 3 * 3600 + 43 * 60 + 23)
    _assert_close(vdot, 40.0, "Marathon 3:43:23", tol=1.5)


def test_invalid_inputs_raise() -> None:
    """Zero or negative distance/time must raise."""
    for d, t in [(0, 60), (-1, 60), (5000, 0), (5000, -1)]:
        try:
            estimate_vdot_from_race(d, t)
        except ValueError:
            continue
        raise AssertionError(f"d={d}, t={t} should have raised ValueError")


# ──────────────────────────────────────────────────────────────────────────

TESTS = [
    test_hm_1_55_lands_around_vdot_40,
    test_hm_1_31_35_is_vdot_50,
    test_5k_19_57_is_vdot_50,
    test_marathon_3_10_49_is_vdot_50,
    test_marathon_3_43_is_vdot_40,
    test_invalid_inputs_raise,
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
