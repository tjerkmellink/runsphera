"""Tests for runsphera/plans/narrative.py — the coach-voice walkthrough
rendered in the plan-workout modal.

The renderer is derived-at-display, so the invariants that matter are:

1. It reads the same numbers the watch will run (structure, not prose).
2. It never invents a pace on an effort-based plan (C25K / Foppen contract —
   see `MethodologyInfo.uses_vdot_paces=False`).
3. It never *misstates* a session it can't model — taper strides carry R pace
   on what is really an easy run, so they must fall back to the shorthand
   instead of prescribing 4 km at R pace.
4. Every workout gets at least one paragraph, so the template can render
   unconditionally.

Run with:
    .venv/Scripts/python.exe tests/test_workout_narrative.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runsphera.plans.daniels import (  # noqa: E402
    _interval_structure,
    _tempo_structure,
)
from runsphera.plans.narrative import narrate  # noqa: E402


# VDOT 43 paces — the same fixture the description-refresh tests use.
PACES = {"E": 383, "M": 323, "T": 299, "I": 277, "R": 259}


def _row(**over):
    base = {
        "workout_type": "easy",
        "title": "Easy 8 km",
        "description": "Conversational aerobic, 6:23/km.",
        "target_distance_km": 8.0,
        "target_pace_s_per_km": PACES["E"],
        "target_duration_s": None,
        "structure_parsed": None,
    }
    base.update(over)
    return base


# ── the motivating example: a Daniels interval session ───────────────────

def test_interval_session_reads_as_prose() -> None:
    """6×1000 m @ I pace — the shape the feature was requested for."""
    w = _row(
        workout_type="intervals",
        title="Intervals 6×1000 m",
        description="WU 2 km easy, 6×1000 m @ I pace (4:37/km) w/ 2:00 jog, CD 2 km.",
        target_pace_s_per_km=277,
        structure_parsed=_interval_structure(6, 1000, 120, 277),
    )
    paras = narrate(w)
    assert len(paras) == 4, f"want warm-up/main/cool-down/why, got {len(paras)}: {paras}"

    warmup, main, cooldown, why = paras
    assert "2 km" in warmup and "warm-up" in warmup, warmup
    assert "6 repetitions" in main, main
    assert "1000 m" in main, main
    assert "interval (I)" in main and "4:37/km" in main, main
    assert "2 minutes" in main, "recovery jog should be described: " + main
    assert "2 km" in cooldown and "cool-down" in cooldown, cooldown
    assert "VO₂max" in why, why


def test_interval_pace_follows_the_structure_not_the_description() -> None:
    """After a recalibration the structure holds the new pace. The prose must
    read *that*, never the (possibly stale) shorthand string."""
    w = _row(
        workout_type="intervals",
        title="Intervals 5×1000 m",
        description="WU 2 km easy, 5×1000 m @ I pace (4:11/km) w/ 2:00 jog, CD 2 km.",
        target_pace_s_per_km=277,
        structure_parsed=_interval_structure(5, 1000, 120, 277),
    )
    joined = " ".join(narrate(w))
    assert "4:37/km" in joined, joined
    assert "4:11" not in joined, "stale description pace leaked into the prose"


# ── other paced shapes ───────────────────────────────────────────────────

def test_tempo_is_one_continuous_block() -> None:
    w = _row(
        workout_type="tempo",
        title="Tempo 10 km",
        description="Easy 2 km, 6 km @ T pace (4:59/km), easy 2 km.",
        target_pace_s_per_km=PACES["T"],
        structure_parsed=_tempo_structure(10.0, PACES["T"]),
    )
    paras = narrate(w)
    assert len(paras) == 4, paras
    assert "6 km" in paras[1] and "threshold (T)" in paras[1], paras[1]
    assert "4:59/km" in paras[1], paras[1]
    assert "lactate" in paras[3], paras[3]


def test_marathon_pace_long_run_describes_both_segments() -> None:
    """The peak marathon long run is easy → M pace. Both halves, both paces,
    and a purpose paragraph that knows this is a race rehearsal."""
    w = _row(
        workout_type="long",
        title="Long 30 km incl. 8 km @ M pace",
        description="First 22 km easy (6:23/km), last 8 km @ M pace (5:23/km).",
        target_distance_km=30.0,
        target_pace_s_per_km=PACES["E"],
        structure_parsed={"steps": [
            {"type": "active", "zone": "E", "end": {"distance_m": 22000},
             "pace_s_per_km": PACES["E"]},
            {"type": "active", "zone": "M", "end": {"distance_m": 8000},
             "pace_s_per_km": PACES["M"]},
        ]},
    )
    paras = narrate(w)
    main = paras[0]  # no warm-up step on this shape
    assert "22 km" in main and "8 km" in main, main
    assert "easy (E)" in main and "marathon (M)" in main, main
    assert "6:23/km" in main and "5:23/km" in main, main
    assert "tired" in paras[-1], "should use the M-finish purpose: " + paras[-1]


def test_plain_easy_run_without_structure() -> None:
    paras = narrate(_row())
    assert len(paras) == 2, paras
    assert "8 km" in paras[0] and "6:23/km" in paras[0], paras[0]
    assert "conversational" in paras[0].lower(), paras[0]


def test_rest_day() -> None:
    paras = narrate(_row(workout_type="rest", title="Rest", description="Full rest."))
    assert len(paras) == 1 and "Rest is when" in paras[0], paras


# ── the "don't misstate it" guard ────────────────────────────────────────

def test_taper_strides_fall_back_to_the_shorthand() -> None:
    """Strides are an *easy* run with 4–6 fast bursts, but the row carries R
    pace and no structure. Narrating "run 4 km at R pace" would be flatly
    wrong, so the shorthand must survive instead."""
    shorthand = "Easy 4–5 km with 4–6×100 m strides at R pace (4:19/km). Stay sharp, not sore."
    w = _row(
        workout_type="intervals",
        title="Strides 4–6×100 m",
        description=shorthand,
        target_distance_km=4.0,
        target_pace_s_per_km=PACES["R"],
        structure_parsed=None,
    )
    paras = narrate(w)
    assert paras[0] == shorthand, paras
    assert "economy" in paras[-1], "R-zone purpose should still be appended: " + paras[-1]


# ── paceless engines: C25K / Foppen ──────────────────────────────────────

def test_c25k_runwalk_repeats_stay_paceless() -> None:
    """Time-based run/walk repeats: durations and effort only. A single '/km'
    anywhere here would break the C25K paceless contract."""
    w = _row(
        workout_type="intervals",
        title="Run/walk 8×1:00",
        description="Brisk 5:00 walk, 8× (1:00 run / 1:30 walk), 5:00 walk.",
        target_distance_km=None,
        target_pace_s_per_km=None,
        structure_parsed={"steps": [
            {"type": "warmup", "end": {"duration_s": 300}},
            {"type": "repeat", "iterations": 8, "steps": [
                {"type": "active", "end": {"duration_s": 60}},
                {"type": "recovery", "end": {"duration_s": 90}},
            ]},
            {"type": "cooldown", "end": {"duration_s": 300}},
        ]},
    )
    paras = narrate(w)
    joined = " ".join(paras)
    assert "/km" not in joined, "invented a pace on a paceless plan: " + joined
    assert "8 repetitions" in paras[1], paras[1]
    assert "1 minute" in paras[1], paras[1]
    # Sub-two-minute odd durations read as whole seconds, not "1:30".
    assert "90 seconds" in paras[1], paras[1]
    assert "5 minutes" in paras[0], paras[0]


def test_c25k_ladder_is_read_out_in_order() -> None:
    """Uneven hand-built weeks alternate blocks with no repeat wrapper — the
    sequence is the workout, so list it rather than force a reps shape."""
    w = _row(
        workout_type="intervals",
        title="Run/walk ladder",
        description="5:00 walk, 5:00 run, 3:00 walk, 8:00 run, 5:00 walk.",
        target_distance_km=None,
        target_pace_s_per_km=None,
        structure_parsed={"steps": [
            {"type": "warmup", "end": {"duration_s": 300}},
            {"type": "active", "end": {"duration_s": 300}},
            {"type": "recovery", "end": {"duration_s": 180}},
            {"type": "active", "end": {"duration_s": 480}},
            {"type": "cooldown", "end": {"duration_s": 300}},
        ]},
    )
    joined = " ".join(narrate(w))
    assert "/km" not in joined, joined
    assert "run 5 minutes" in joined and "walk 3 minutes" in joined, joined
    assert "run 8 minutes" in joined, joined


def test_foppen_effort_intervals_have_no_pace() -> None:
    w = _row(
        workout_type="intervals",
        title="INT 6×3:00",
        description="WU 15:00 RD, 6×3:00 INT w/ 2:00 RD, CD 10:00 RD.",
        target_distance_km=None,
        target_pace_s_per_km=None,
        structure_parsed={"steps": [
            {"type": "warmup", "end": {"duration_s": 900}},
            {"type": "repeat", "iterations": 6, "steps": [
                {"type": "active", "end": {"duration_s": 180}},
                {"type": "recovery", "end": {"duration_s": 120}},
            ]},
            {"type": "cooldown", "end": {"duration_s": 600}},
        ]},
    )
    joined = " ".join(narrate(w))
    assert "/km" not in joined, joined
    assert "6 repetitions" in joined and "3 minutes" in joined, joined
    # Effort language, and deliberately no intensity claim — the same shape
    # covers a Foppen INT block and a beginner's C25K run/walk.
    assert "an effort you can hold" in joined, joined


# ── the engine's own note ────────────────────────────────────────────────

def test_authored_note_survives_when_the_structure_cant_hold_it() -> None:
    """Higdon's hill repeats are "8×400 m at I pace" structurally — only the
    engine's own words say *uphill*. Dropping that would change the session."""
    note = ("WU 2 km, then 8×400 m uphill hard at ~5K effort (I, 4:28/km) with an "
            "easy jog back down to recover, CD 2 km. Builds strength and running economy.")
    w = _row(
        workout_type="intervals",
        title="Hill repeats 8×400 m",
        description=note,
        target_pace_s_per_km=268,
        structure_parsed=_interval_structure(8, 400, 90, 268),
    )
    paras = narrate(w)
    assert note in paras, paras
    assert "8 repetitions" in " ".join(paras), paras


def test_terse_shorthand_is_not_repeated_after_the_walkthrough() -> None:
    """Daniels shorthand is a spec line, not prose — the walkthrough replaces
    it rather than printing both."""
    shorthand = "WU 2 km easy, 6×1000 m @ I pace (4:37/km) w/ 2:00 jog, CD 2 km."
    w = _row(
        workout_type="intervals",
        title="Intervals 6×1000 m",
        description=shorthand,
        target_pace_s_per_km=277,
        structure_parsed=_interval_structure(6, 1000, 120, 277),
    )
    assert shorthand not in narrate(w)


def test_single_block_session_lets_the_authored_note_lead() -> None:
    """One continuous run has nothing to decompose. When the engine already
    described it well, the generic "40 minutes at a steady effort" is dropped
    rather than stacked on top."""
    note = ("Forty minutes easy. Conversational pace, small light steps. Maintenance "
            "run — supports recovery and lays the base for the rest of the week.")
    w = _row(
        workout_type="easy",
        title="RD 40 min",
        description=note,
        target_distance_km=None,
        target_pace_s_per_km=None,
        target_duration_s=2400,
        structure_parsed={"steps": [{"type": "active", "end": {"duration_s": 2400}}]},
    )
    paras = narrate(w)
    assert paras[0] == note, paras
    assert not any("steady effort" in p for p in paras), paras


def test_multi_paragraph_note_keeps_its_blocks() -> None:
    """Foppen appends a blank-line-separated weekly challenge — it must stay a
    paragraph of its own, not get glued onto the sentence before it."""
    w = _row(
        workout_type="easy",
        title="RD 40 min",
        description="Forty minutes easy, conversational pace throughout the whole run.\n\n"
                    "Weekly challenge: run one session in the shape of the digit 7.",
        target_distance_km=None,
        target_pace_s_per_km=None,
        target_duration_s=2400,
        structure_parsed={"steps": [{"type": "active", "end": {"duration_s": 2400}}]},
    )
    paras = narrate(w)
    assert any(p.startswith("Weekly challenge:") for p in paras), paras


def test_race_day_does_not_talk_over_the_race_briefing() -> None:
    """A race row's distance is the event, not a prescription. Narrating
    "15 km at a steady effort" over Foppen's course briefing would be noise."""
    briefing = ("Course: the first 7 km climb most of the elevation gain; the last "
                "stretch is mostly downhill — if you've paced well, lift the tempo there.")
    w = _row(
        workout_type="race",
        title="🏁 RACE — NN Zevenheuvelenloop 15 km",
        description=briefing,
        target_distance_km=15.0,
        target_pace_s_per_km=None,
        structure_parsed={"steps": [{"type": "active", "end": {"distance_m": 15000}}]},
    )
    paras = narrate(w)
    assert paras[0] == briefing, paras
    assert not any("steady effort" in p for p in paras), paras
    assert "Race day" in paras[-1], paras


def test_paceless_repeats_get_the_effort_purpose_not_the_vo2max_one() -> None:
    """A beginner's 8×1-minute run/walk is not VO₂max work, even though it
    shares the `intervals` type with one."""
    w = _row(
        workout_type="intervals",
        title="Run/walk 8×1:00",
        description="Run/walk repeats.",
        target_distance_km=None,
        target_pace_s_per_km=None,
        structure_parsed={"steps": [
            {"type": "repeat", "iterations": 8, "steps": [
                {"type": "active", "end": {"duration_s": 60}},
                {"type": "recovery", "end": {"duration_s": 90}},
            ]},
        ]},
    )
    why = narrate(w)[-1]
    assert "VO₂max" not in why, why
    assert "recovery in between" in why, why


# ── universal invariants ─────────────────────────────────────────────────

def test_every_workout_type_yields_at_least_one_paragraph() -> None:
    for wtype in ("easy", "tempo", "intervals", "long", "recovery", "rest", "cross", "race"):
        paras = narrate(_row(workout_type=wtype, title=wtype.capitalize()))
        assert paras and all(p.strip() for p in paras), f"{wtype}: {paras}"


def test_dutch_locale_translates() -> None:
    w = _row(
        workout_type="intervals",
        title="Intervals 6×1000 m",
        description="WU 2 km easy, 6×1000 m @ I pace (4:37/km) w/ 2:00 jog, CD 2 km.",
        target_pace_s_per_km=277,
        structure_parsed=_interval_structure(6, 1000, 120, 277),
    )
    nl = narrate(w, locale="nl")
    en = narrate(w, locale="en")
    assert len(nl) == len(en) == 4, (nl, en)
    for i, (n, e) in enumerate(zip(nl, en)):
        assert n != e, f"paragraph {i} is untranslated: {n}"
    joined = " ".join(nl)
    # Numbers must survive translation intact.
    assert "4:37/km" in joined and "6" in joined and "1000 m" in joined, joined


TESTS = [
    test_interval_session_reads_as_prose,
    test_interval_pace_follows_the_structure_not_the_description,
    test_tempo_is_one_continuous_block,
    test_marathon_pace_long_run_describes_both_segments,
    test_plain_easy_run_without_structure,
    test_rest_day,
    test_taper_strides_fall_back_to_the_shorthand,
    test_c25k_runwalk_repeats_stay_paceless,
    test_c25k_ladder_is_read_out_in_order,
    test_foppen_effort_intervals_have_no_pace,
    test_authored_note_survives_when_the_structure_cant_hold_it,
    test_terse_shorthand_is_not_repeated_after_the_walkthrough,
    test_single_block_session_lets_the_authored_note_lead,
    test_multi_paragraph_note_keeps_its_blocks,
    test_race_day_does_not_talk_over_the_race_briefing,
    test_paceless_repeats_get_the_effort_purpose_not_the_vo2max_one,
    test_every_workout_type_yields_at_least_one_paragraph,
    test_dutch_locale_translates,
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
