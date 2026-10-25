"""Lock-down test for the Jack Daniels VDOT pace table.

Asserts a handful of reference points against the canonical Daniels chart
(Daniels' Running Formula 4th ed. Table 5.2 / runsmartproject.com calculator)
so the table can't silently drift again.

Background: this catches the historical bug where M/T/I/R paces were 15-30
sec/km too FAST — a "tempo" at VDOT 50 was 4:08/km when Daniels actually
says 4:30/km. The bug effectively pushed every prescribed tempo into VO2max
territory.

Run from the repo root:
    .venv/Scripts/python.exe tests/test_daniels_paces.py

No external dependencies (just plain `assert` + a small runner) so this
works against a fresh checkout.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make `runsphera` importable when running this script directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runsphera.plans.daniels import _VDOT_PACES, _paces_for_vdot  # noqa: E402


# ──────────────────────────────────────────────────────────────────────────
# Reference table — canonical Daniels VDOT chart, lower bound for E pace.
# Values in seconds per km. Tolerance below ±3 s/km is acceptable since
# different printings/calculators round slightly differently; outside that
# we treat it as a real drift and fail.
# ──────────────────────────────────────────────────────────────────────────
TOLERANCE_S_PER_KM = 3

_CANONICAL_PACES: dict[int, dict[str, int]] = {
    # E values use the marathon blueprint's "easy = 1 min slower than M" rule
    # (M + 60 s/km), the *everyday easy / long-run* pace. This is the slower
    # end of Daniels' E range — faster E (warm-up jog) isn't a prescribed
    # workout target in this engine.
    # Lower-end VDOT — new / recovering runner
    30: {"E": 474, "M": 414, "T": 384, "I": 355, "R": 328},
    # Common amateur range
    40: {"E": 399, "M": 339, "T": 313, "I": 290, "R": 270},
    # Solid amateur ~3:30 marathon territory
    50: {"E": 350, "M": 290, "T": 270, "I": 250, "R": 232},
    # Strong sub-3 marathoner
    60: {"E": 313, "M": 253, "T": 236, "I": 218, "R": 202},
    # Elite
    70: {"E": 286, "M": 226, "T": 210, "I": 193, "R": 179},
}


def _fmt(secs: int) -> str:
    m, s = divmod(secs, 60)
    return f"{m}:{s:02d}/km"


def assert_close(actual: int, expected: int, label: str) -> None:
    diff = abs(actual - expected)
    if diff > TOLERANCE_S_PER_KM:
        raise AssertionError(
            f"{label}: got {_fmt(actual)} ({actual}s), "
            f"expected {_fmt(expected)} ({expected}s) — off by {diff}s/km"
        )


def test_table_matches_canonical() -> None:
    """Every entry in `_VDOT_PACES` for the reference VDOTs must match."""
    for vdot, paces in _CANONICAL_PACES.items():
        for zone, expected in paces.items():
            actual = _VDOT_PACES[vdot][zone]
            assert_close(actual, expected, f"VDOT {vdot} {zone}")


def test_monotone_within_vdot() -> None:
    """Within a single VDOT, paces must monotonically decrease E > M > T > I > R."""
    for vdot, paces in _VDOT_PACES.items():
        seq = [paces["E"], paces["M"], paces["T"], paces["I"], paces["R"]]
        for i in range(len(seq) - 1):
            assert seq[i] > seq[i + 1], (
                f"VDOT {vdot}: pace ordering broken at index {i} "
                f"({seq[i]} not > {seq[i + 1]})"
            )


def test_monotone_across_vdot() -> None:
    """Paces must get faster (smaller s/km) as VDOT rises, in every zone."""
    vdots = sorted(_VDOT_PACES.keys())
    for zone in ("E", "M", "T", "I", "R"):
        for i in range(len(vdots) - 1):
            lo, hi = vdots[i], vdots[i + 1]
            assert _VDOT_PACES[lo][zone] > _VDOT_PACES[hi][zone], (
                f"{zone}: VDOT {lo} pace {_VDOT_PACES[lo][zone]} not slower "
                f"than VDOT {hi} pace {_VDOT_PACES[hi][zone]}"
            )


def test_interpolation_at_known_vdots() -> None:
    """`_paces_for_vdot(N)` for a table key N must return the table row."""
    for vdot, paces in _VDOT_PACES.items():
        out = _paces_for_vdot(float(vdot))
        for zone, expected in paces.items():
            assert out[zone] == expected, (
                f"interpolation at VDOT {vdot} {zone}: "
                f"got {out[zone]}, expected {expected}"
            )


def test_interpolation_clamps_outside_range() -> None:
    """VDOT outside [30, 70] should clamp to the nearest endpoint."""
    assert _paces_for_vdot(20.0) == _paces_for_vdot(30.0)
    assert _paces_for_vdot(80.0) == _paces_for_vdot(70.0)


def test_vdot_49_t_pace_is_around_4_30() -> None:
    """Regression for the original bug report: VDOT 49 tempo should be
    canonical Daniels T pace (~4:30-4:34/km), not pushed into interval
    territory (~4:11/km). Allow some slack for the linear interpolation."""
    paces = _paces_for_vdot(49.0)
    t = paces["T"]
    assert 268 <= t <= 280, (
        f"VDOT 49 T pace = {_fmt(t)} ({t}s) — expected ~4:30/km (270s) ± a few "
        f"seconds. If this fails the pace table has drifted."
    )


def test_e_is_everyday_easy_not_warmup_jog() -> None:
    """Regression for the 2026-05-29 bug: easy pace was 5:21/km for VDOT 49
    (Daniels' E_lower, intended for warm-up/cool-down jogs), but the engine
    uses it for every easy / long workout. Result: prescribed easies were
    1+ minute faster than the blueprint's "easy = 1-2 min slower than M".

    The fix sets E = M + ~60 sec/km, i.e. exactly the slower-end of the
    blueprint's range. Asserts the gap is in 55-75 s/km across all VDOTs."""
    for vdot, paces in _VDOT_PACES.items():
        gap = paces["E"] - paces["M"]
        assert 55 <= gap <= 75, (
            f"VDOT {vdot}: E-M gap = {gap}s. Expected 55-75s (~1 min slower "
            f"than marathon pace, the blueprint's 'sustainable easy' rule)."
        )


def test_vdot_49_e_is_sustainable() -> None:
    """Regression: VDOT 49 conversational easy should be ~5:50-6:00/km, not
    the old 5:21/km which was the warmup-jog speed not the everyday pace."""
    paces = _paces_for_vdot(49.0)
    e = paces["E"]
    assert 345 <= e <= 365, (
        f"VDOT 49 E pace = {_fmt(e)} ({e}s). Expected 5:45-6:05/km (345-365s)."
    )


# ──────────────────────────────────────────────────────────────────────────

TESTS = [
    test_table_matches_canonical,
    test_monotone_within_vdot,
    test_monotone_across_vdot,
    test_interpolation_at_known_vdots,
    test_interpolation_clamps_outside_range,
    test_vdot_49_t_pace_is_around_4_30,
    test_e_is_everyday_easy_not_warmup_jog,
    test_vdot_49_e_is_sustainable,
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
