"""Test for _refresh_description_paces — the regex helper that keeps the
description string in sync with the workout's numeric pace target after a
recalibration.

The bug this guards against: on 2026-05-27 the user's planned tempo workout
showed `Target pace: 5:00/km` (correct after recalibrate) but the description
string still said `@ T pace (4:11/km)` (stale from before the VDOT change).
The LLM coach saw both, averaged them, and prescribed `4:20/km`. The fix
rewrites the embedded pace numbers in the description text whenever paces
change.

Run with:
    .venv/Scripts/python.exe tests/test_description_refresh.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runsphera.plans.service import (  # noqa: E402
    _derive_title,
    _refresh_description_paces,
    _zone_for_workout,
)


# VDOT 43 paces (a mid-range fixture) — used as ground truth in
# these tests. Sourced from runsphera/plans/daniels.py at 2026-05-29.
PACES_43 = {"E": 383, "M": 323, "T": 299, "I": 277, "R": 259}
# Pre-bugfix VDOT-50 paces (what stale descriptions tend to carry).
PACES_50 = {"E": 350, "M": 290, "T": 270, "I": 250, "R": 232}


def test_zone_labelled_tempo() -> None:
    """`T pace (4:11/km)` should rewrite to the new T pace."""
    src = "Easy 1.5 km, 3 km @ T pace (4:11/km), easy 1.5 km."
    got = _refresh_description_paces(src, PACES_43)
    assert "T pace (4:59/km)" in got, got
    assert "4:11/km" not in got, got


def test_zone_labelled_marathon() -> None:
    """`M pace (4:50/km)` should rewrite to the new M pace."""
    src = "First half easy (5:50/km), last 6 km @ M pace (4:50/km)."
    got = _refresh_description_paces(src, PACES_43)
    assert "M pace (5:23/km)" in got, got
    assert "(6:23/km)" in got, got  # parened-unlabelled treated as E
    assert "4:50/km" not in got and "5:50/km" not in got, got


def test_zone_labelled_intervals_and_repetition() -> None:
    """I pace and R pace each rewrite to their own zone."""
    src = "WU 2 km, 6×800 m @ I pace (4:10/km) w/ 90 s jog, CD 2 km."
    got = _refresh_description_paces(src, PACES_43)
    assert "I pace (4:37/km)" in got, got

    src = "Easy 5 km with 4–6×100 m strides at R pace (3:52/km). Stay sharp."
    got = _refresh_description_paces(src, PACES_43)
    assert "R pace (4:19/km)" in got, got


def test_tilde_prefixed_zone_label() -> None:
    """`~T pace (X:XX/km)` (used in the engine's peak-half template)."""
    src = "Easy 8 km then 5 km @ ~T pace (4:30/km). Cooldown 1 km."
    got = _refresh_description_paces(src, PACES_43)
    assert "T pace (4:59/km)" in got, got
    assert "4:30/km" not in got, got


def test_bare_standalone_is_easy() -> None:
    """A standalone `X:XX/km` (no parens, no zone) refers to E pace."""
    src = "Conversational aerobic, 5:50/km."
    got = _refresh_description_paces(src, PACES_43)
    assert got == "Conversational aerobic, 6:23/km."


def test_tilde_prefixed_bare_is_easy() -> None:
    """`~5:50/km` — bare with tilde prefix — also treats as E."""
    src = "Conversational pace, ~5:50/km. Steady aerobic."
    got = _refresh_description_paces(src, PACES_43)
    assert "~6:23/km" in got, got


def test_already_current_is_noop() -> None:
    """Description with current paces in it produces no changes."""
    src = "Easy 1.5 km, 3 km @ T pace (4:59/km), easy 1.5 km."
    got = _refresh_description_paces(src, PACES_43)
    assert got == src


def test_empty_and_none() -> None:
    """Empty / None inputs pass through cleanly."""
    assert _refresh_description_paces("", PACES_43) == ""
    assert _refresh_description_paces(None, PACES_43) is None


def test_mixed_paces_in_one_string() -> None:
    """Multiple zone labels in one description all rewrite independently."""
    src = "WU 2 km, 4×1.5 km @ T pace (4:30/km) w/ 1:00 jog, CD 2 km."
    got = _refresh_description_paces(src, PACES_43)
    assert "T pace (4:59/km)" in got, got
    # The "1:00 jog" duration must NOT be rewritten — it's not a pace.
    assert "1:00 jog" in got, got


def test_duration_strings_not_touched() -> None:
    """`90 s`, `1:00 jog`, `2:00 jog` — durations are not paces (no /km)."""
    src = "6×800 m @ I pace (4:10/km) w/ 90 s jog, 5×1000 m @ I pace (4:10/km) w/ 2:00 jog."
    got = _refresh_description_paces(src, PACES_43)
    assert "90 s jog" in got, got
    assert "2:00 jog" in got, got
    # Both paces should have flipped to current I pace.
    assert got.count("I pace (4:37/km)") == 2, got


def test_actually_heals_the_user_bug() -> None:
    """End-to-end: the exact description string from the 2026-05-27 bug
    report, recalibrated against the VDOT-43 fixture paces."""
    src = "Easy 1.5 km, 3 km @ T pace (4:11/km), easy 1.5 km."
    got = _refresh_description_paces(src, PACES_43)
    assert got == "Easy 1.5 km, 3 km @ T pace (4:59/km), easy 1.5 km."


def test_pfitzinger_zone_comma_form() -> None:
    """Pfitzinger's `(Z, X:XX/km)` idiom rewrites against the labelled zone —
    NOT against E, which used to corrupt every LT/VO₂max/MP description."""
    src = "A sustained block at lactate-threshold pace (T, 4:30/km) — comfortably hard."
    got = _refresh_description_paces(src, PACES_43)
    assert "(T, 4:59/km)" in got, got

    src = "Endurance 15 km easy (5:50/km), then 14 km at marathon pace (M, 4:50/km)."
    got = _refresh_description_paces(src, PACES_43)
    assert "(M, 5:23/km)" in got, got
    assert "(6:23/km)" in got, got  # the unlabelled easy paren stays E

    src = "WU 2 km, 6×1000 m at VO₂max pace (I, 4:10/km) with 2:00 jog recovery, CD 2 km."
    got = _refresh_description_paces(src, PACES_43)
    assert "(I, 4:37/km)" in got, got
    assert "2:00 jog" in got, got


def test_zone_for_workout_pfitzinger_vocabulary() -> None:
    """Races are never rezoned (goal/tune-up paces aren't zone paces), and the
    Pfitzinger race-week dress rehearsal maps to M like Daniels' MP tempos."""
    assert _zone_for_workout({"workout_type": "race", "title": "Tune-up race ~15 km"}) is None
    assert _zone_for_workout({"workout_type": "race", "title": "🏁 Race day — Marathon 42.2 km"}) is None
    assert _zone_for_workout({"workout_type": "tempo", "title": "Race-pace tune 7 km"}) == "M"
    assert _zone_for_workout({"workout_type": "tempo", "title": "Marathon-pace 12 km"}) == "M"
    assert _zone_for_workout({"workout_type": "tempo", "title": "Lactate threshold 11 km"}) == "T"
    assert _zone_for_workout({"workout_type": "intervals", "title": "VO₂max 6×1000 m"}) == "I"
    assert _zone_for_workout({"workout_type": "intervals", "title": "Strides 6×100 m"}) == "R"
    assert _zone_for_workout({"workout_type": "long", "title": "Medium-long 21 km"}) == "E"
    assert _zone_for_workout({"workout_type": "rest", "title": "Rest"}) is None


def test_zone_for_workout_higdon_vocabulary() -> None:
    """Higdon titles must rezone correctly: marathon-pace runs → M, half-pace
    runs and tempos → T, hills/speed → I, cross → None, easy/long → E."""
    assert _zone_for_workout({"workout_type": "tempo", "title": "Marathon-pace run 12 km"}) == "M"
    assert _zone_for_workout({"workout_type": "tempo", "title": "Half-pace run 10 km"}) == "T"
    assert _zone_for_workout({"workout_type": "tempo", "title": "Tempo run 8 km"}) == "T"
    assert _zone_for_workout({"workout_type": "intervals", "title": "Hill repeats 8×400 m"}) == "I"
    assert _zone_for_workout({"workout_type": "intervals", "title": "Speed 6×800 m"}) == "I"
    assert _zone_for_workout({"workout_type": "cross", "title": "Cross-training"}) is None
    assert _zone_for_workout({"workout_type": "easy", "title": "Easy run 6 km"}) == "E"
    assert _zone_for_workout({"workout_type": "long", "title": "Long run 32 km"}) == "E"


def test_higdon_descriptions_refresh_zone_correctly() -> None:
    """The Higdon idioms — goal-pace `(M, …)`, hills `(I, …)`, and the plain
    parenthesised easy pace — each rewrite against the right zone."""
    src = "Warm up, then settle into marathon goal pace (M, 4:55/km), and cool down."
    assert "(M, 5:23/km)" in _refresh_description_paces(src, PACES_43)

    src = "WU 2 km, then 8×400 m uphill hard at ~5K effort (I, 4:10/km) with jog back, CD 2 km."
    got = _refresh_description_paces(src, PACES_43)
    assert "(I, 4:37/km)" in got, got

    src = "12 km easy (5:50/km), then 4 km at marathon goal pace (M, 4:55/km)."
    got = _refresh_description_paces(src, PACES_43)
    assert "(M, 5:23/km)" in got and "(6:23/km)" in got, got


def test_derive_title_preserves_tempo_vocabulary() -> None:
    """Editing a tempo workout must keep its pace vocabulary: the recalibrator
    zones tempo rows off title tokens ('Marathon-pace' / 'Race-pace' → M, else
    T), so re-deriving a generic 'Tempo N km' would silently flip an M-pace
    session to threshold pace on the next recalibrate."""
    # Same-type edits pass the old title through — vocabulary survives.
    assert _derive_title("tempo", 14, None, current_title="Marathon-pace run 12 km") \
        == "Marathon-pace run 14 km"
    assert _derive_title("tempo", 9, None, current_title="Race-pace tune 7 km") \
        == "Race-pace tune 9 km"
    assert _derive_title("tempo", 12, None, current_title="Lactate threshold 11 km") \
        == "Lactate threshold 12 km"
    assert _derive_title("tempo", 9, None, current_title="Half-pace run 10 km") \
        == "Half-pace run 9 km"
    # Zone is preserved end-to-end.
    assert _zone_for_workout({
        "workout_type": "tempo",
        "title": _derive_title("tempo", 14, None, current_title="Marathon-pace run 12 km"),
    }) == "M"
    # No current title (type changed, or legacy caller) → canonical fallback.
    assert _derive_title("tempo", 8, None) == "Tempo 8 km"
    # A title without the 'N km' shape falls back too.
    assert _derive_title("tempo", 8, None, current_title="Fartlek session") == "Tempo 8 km"


def test_require_vdot_paces_guard() -> None:
    """Effort-based methodologies refuse pace recalibration; pace-based and
    unknown/legacy ids pass through (the historical behaviour)."""
    from runsphera.plans.service import _require_vdot_paces

    for ok in ("daniels", "higdon", "pfitzinger", "some_legacy_id", None, ""):
        _require_vdot_paces(ok)  # must not raise
    for effort_based in ("foppen_7heuvelen", "c25k"):
        try:
            _require_vdot_paces(effort_based)
        except ValueError as exc:
            assert "effort-based" in str(exc)
        else:
            raise AssertionError(f"{effort_based} should refuse recalibration")


# ──────────────────────────────────────────────────────────────────────────

TESTS = [
    test_zone_labelled_tempo,
    test_zone_labelled_marathon,
    test_zone_labelled_intervals_and_repetition,
    test_tilde_prefixed_zone_label,
    test_bare_standalone_is_easy,
    test_tilde_prefixed_bare_is_easy,
    test_already_current_is_noop,
    test_empty_and_none,
    test_mixed_paces_in_one_string,
    test_duration_strings_not_touched,
    test_actually_heals_the_user_bug,
    test_pfitzinger_zone_comma_form,
    test_zone_for_workout_pfitzinger_vocabulary,
    test_zone_for_workout_higdon_vocabulary,
    test_higdon_descriptions_refresh_zone_correctly,
    test_derive_title_preserves_tempo_vocabulary,
    test_require_vdot_paces_guard,
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
