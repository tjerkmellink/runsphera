"""Lock-down test for the phase allocator.

Asserts the canonical 4-8 / 6-10 / 3-4 / 2-3 ranges from the marathon
training blueprint (docs/grounding/), and the specific bug from 2026-05-28
where a 23-week marathon was getting 7+7+4+5 instead of 8+9+3+3.

Run from repo root:
    .venv/Scripts/python.exe tests/test_daniels_phases.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runsphera.plans.daniels import _phase_layout, _PHASE_SPEC  # noqa: E402


def _as_dict(layout: list[tuple[str, int]]) -> dict[str, int]:
    return {p: n for p, n in layout}


def test_default_lengths_unchanged() -> None:
    """At the spec length, the allocator returns _PHASE_SPEC verbatim."""
    for goal in ("5k", "10k", "15k", "half_marathon", "marathon", "stay_fit"):
        spec = _PHASE_SPEC[goal]
        total = sum(n for _, n in spec)
        if total == 0:
            continue
        assert _phase_layout(goal, total) == spec, (
            f"{goal}@{total}w: expected default spec, got {_phase_layout(goal, total)}"
        )


def test_marathon_23_weeks_caps_taper_and_peak() -> None:
    """The original bug report — 23-week marathon was 7+7+4+5; should be
    8+9+3+3 (taper stays at 3, peak stays at 3, extras go to base+build)."""
    layout = _as_dict(_phase_layout("marathon", 23))
    assert layout["peak"] <= 4, f"peak {layout['peak']} > 4-week cap"
    assert layout["taper"] <= 3, f"taper {layout['taper']} > 3-week cap (THE BUG)"
    assert sum(layout.values()) == 23
    # Specific expectation: peak/taper stay at spec, base+build absorb extras.
    assert layout == {"base": 8, "build": 9, "peak": 3, "taper": 3}, (
        f"23-week marathon: got {layout}"
    )


def test_marathon_long_plans_never_exceed_caps() -> None:
    """For any longer-than-default marathon plan, peak ≤ 4 and taper ≤ 3."""
    for weeks in (17, 20, 24, 30, 40):
        layout = _as_dict(_phase_layout("marathon", weeks))
        assert layout["peak"] <= 4, f"{weeks}w marathon: peak={layout['peak']}"
        assert layout["taper"] <= 3, f"{weeks}w marathon: taper={layout['taper']}"
        assert sum(layout.values()) == weeks, f"{weeks}w marathon: total mismatch"


def test_marathon_short_plans_preserve_peak_taper() -> None:
    """Plans shorter than default compress base/build, leaving peak/taper alone
    until the absolute end. Race-week sharpening matters even for short plans."""
    layout_14 = _as_dict(_phase_layout("marathon", 14))
    assert layout_14["peak"] >= 1 and layout_14["taper"] >= 1
    # 14 = 16 - 2; we drop 2 from base.
    assert layout_14 == {"base": 3, "build": 5, "peak": 3, "taper": 3}, (
        f"14-week marathon: got {layout_14}"
    )

    # Very short plan — taper still preserved as long as possible.
    layout_10 = _as_dict(_phase_layout("marathon", 10))
    assert sum(layout_10.values()) == 10
    assert layout_10["taper"] >= 1, "taper dropped below 1 even though deficit was absorbable elsewhere"


def test_half_marathon_extends_build_and_base() -> None:
    layout = _as_dict(_phase_layout("half_marathon", 16))
    assert sum(layout.values()) == 16
    # spec = 4+4+2+2 = 12; extras = 4 split build/base alternately starting w/ build
    assert layout == {"base": 6, "build": 6, "peak": 2, "taper": 2}, (
        f"16-week half: got {layout}"
    )


def test_10k_long_plan_caps() -> None:
    """10k spec is 3+4+2+1; a 13-week 10k should grow base/build only."""
    layout = _as_dict(_phase_layout("10k", 13))
    assert sum(layout.values()) == 13
    assert layout["peak"] == 2 and layout["taper"] == 1


def test_stay_fit_single_phase() -> None:
    """Stay-fit only has one phase ("maintain"). For any length the allocator
    returns a single maintain entry — the engine's per-week loop applies the
    rolling 4-week mileage cycle internally."""
    layout = _phase_layout("stay_fit", 20)
    assert len(layout) == 1 and layout[0][0] == "maintain"
    assert layout[0][1] == 20, f"stay_fit 20w: maintain={layout[0][1]}"
    # Default length still matches the spec.
    assert _phase_layout("stay_fit", 4) == _PHASE_SPEC["stay_fit"]


def test_growth_alternates_build_then_base() -> None:
    """Build should grow first (favours threshold + race-pace fitness density),
    then base, then alternate."""
    # 17-week marathon = 1 extra → build gets it.
    layout = _as_dict(_phase_layout("marathon", 17))
    spec = _as_dict(_PHASE_SPEC["marathon"])
    assert layout["build"] == spec["build"] + 1, f"build didn't grow first: {layout}"
    assert layout["base"] == spec["base"], f"base grew before build: {layout}"


# ──────────────────────────────────────────────────────────────────────────

TESTS = [
    test_default_lengths_unchanged,
    test_marathon_23_weeks_caps_taper_and_peak,
    test_marathon_long_plans_never_exceed_caps,
    test_marathon_short_plans_preserve_peak_taper,
    test_half_marathon_extends_build_and_base,
    test_10k_long_plan_caps,
    test_stay_fit_single_phase,
    test_growth_alternates_build_then_base,
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
