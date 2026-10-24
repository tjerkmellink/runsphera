"""Tests for the strength push payload builder.

The payload is what determines whether Garmin Connect accepts our
workout *and* whether the Fenix-class watches will sync it. Three
quirks live in `garmin_push.build_payload` that were each found by
diffing our payload against Garmin's pre-made workouts:

1. ``sportType`` per session category (cardio_training / hiit / mobility,
   never strength_training for pure bodyweight).
2. Per-step ``description`` must be None, top-level ``workoutProvider``
   must be non-null. (See the in-file comments for the rationale.)
3. Multi-round blocks emit a ``RepeatGroupDTO`` so the watch shows
   "Round N of M" UX instead of flat step numbering. Single-round
   blocks emit flat exercises (no point wrapping a one-shot pass).

This file guards (1) and (3) directly. (2) is also asserted as a
side-check.

Run with:
    .venv/Scripts/python.exe tests/test_strength_push_payload.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from running_coach.strength.garmin_push import build_payload  # noqa: E402


# ── Test fixtures ─────────────────────────────────────────────────

def _session(category: str, blocks: list[dict]) -> dict:
    """Minimal hydrated session dict that build_payload expects."""
    return {
        "session_id":      1,
        "plan_id":         1,
        "planned_date":    "2030-01-06",
        "title":           "Test session",
        "category":        category,
        "duration_min_lo": 20,
        "duration_min_hi": 25,
        "notes":           None,
        "structure":       {"blocks": blocks},
    }


def _ex(category: str, exercise: str, **kwargs) -> dict:
    return {"category": category, "exercise": exercise, **kwargs}


# ── Sport-type routing ───────────────────────────────────────────

def test_sport_type_recovery_is_yoga():
    # `mobility` (id 11) uploads + animates but the Fenix rejects it on
    # sync ("incompatible device", probed 2026-06-16). `yoga` (id 7) —
    # the sport type Garmin's own syncable pose/move workouts use — syncs.
    p = build_payload(_session("recovery", []))
    assert p["sportType"]["sportTypeKey"] == "yoga", p["sportType"]
    assert p["subSportType"] == "GENERIC", p["subSportType"]


def test_sport_type_plyo_is_hiit():
    p = build_payload(_session("plyo", []))
    assert p["sportType"]["sportTypeKey"] == "hiit", p["sportType"]


def test_sport_type_default_is_cardio_training():
    """Every other category — core+hamstrings, full_body, hip_stability,
    core, etc. — must NOT be `strength_training` (Fenix 7 won't sync)."""
    for cat in ["core+hamstrings", "full_body", "hip_stability", "core", "anything_else"]:
        p = build_payload(_session(cat, []))
        assert p["sportType"]["sportTypeKey"] == "cardio_training", \
            f"{cat} → {p['sportType']}"


# ── Top-level validator hygiene ──────────────────────────────────

def test_workoutProvider_is_set():
    """Non-null workoutProvider is required by the Fenix validator
    for non-running sport types."""
    p = build_payload(_session("core+hamstrings", [{"name": "x", "rounds": 1, "exercises": []}]))
    assert p["workoutProvider"] is not None, p


# ── Round flattening: single-round blocks stay flat ──────────────

def test_single_round_block_is_flat():
    """A block with rounds=1 should emit its exercises directly into
    the segment, no RepeatGroupDTO wrap."""
    blocks = [{
        "name":   "Warm-up",
        "rounds": 1,
        "rest_between_rounds_s": 0,
        "exercises": [
            _ex("plank", "plank", duration_s=30),
            _ex("plank", "side_plank", duration_s=30, per_side=True),
        ],
    }]
    p = build_payload(_session("core", blocks))
    steps = p["workoutSegments"][0]["workoutSteps"]
    # 1 plank + 2 side_plank-per-side = 3 flat ExecutableSteps.
    assert all(s["type"] == "ExecutableStepDTO" for s in steps), [s["type"] for s in steps]
    assert len(steps) == 3, f"expected 3 flat steps, got {len(steps)}"


# ── Round flattening: multi-round blocks wrap in RepeatGroup ─────

def test_multi_round_block_is_repeat_group():
    """A block with rounds>1 should emit one RepeatGroupDTO with the
    exercises ONCE inside, plus a final rest step in the group when
    rest_between_rounds_s > 0."""
    blocks = [{
        "name":   "Strength",
        "rounds": 3,
        "rest_between_rounds_s": 90,
        "exercises": [
            _ex("squat", "body_weight_wall_squat", reps=12),
            _ex("plyo", "body_weight_jump_squat", reps=10),
        ],
    }]
    p = build_payload(_session("core+hamstrings", blocks))
    steps = p["workoutSegments"][0]["workoutSteps"]

    assert len(steps) == 1, f"expected 1 top-level step (the group), got {len(steps)}"
    g = steps[0]
    assert g["type"] == "RepeatGroupDTO", g["type"]
    assert g["numberOfIterations"] == 3
    assert g["endConditionValue"] == 3.0
    assert g["endCondition"]["conditionTypeKey"] == "iterations"
    assert g["skipLastRestStep"] is True
    assert g["smartRepeat"] is False

    inner = g["workoutSteps"]
    # 2 exercises (no per_side) + 1 rest = 3 inner steps, NOT 3 rounds × ...
    assert len(inner) == 3, f"expected exercises emitted once + 1 rest, got {len(inner)}"
    assert inner[0]["category"] == "SQUAT"
    assert inner[1]["category"] == "PLYO"
    assert inner[2]["stepType"]["stepTypeKey"] == "rest"


def test_repeat_group_childStepId_increments_per_block():
    """Multiple multi-round blocks each get their own ``childStepId``
    so the watch can distinguish them. Inner steps inherit the
    parent group's id."""
    blocks = [
        {
            "name": "Block A", "rounds": 2, "rest_between_rounds_s": 60,
            "exercises": [_ex("plank", "plank", duration_s=30)],
        },
        {
            "name": "Block B", "rounds": 2, "rest_between_rounds_s": 60,
            "exercises": [_ex("squat", "body_weight_wall_squat", reps=10)],
        },
    ]
    p = build_payload(_session("core", blocks))
    g1, g2 = p["workoutSegments"][0]["workoutSteps"]
    assert g1["childStepId"] == 1
    assert g2["childStepId"] == 2
    for st in g1["workoutSteps"]:
        assert st["childStepId"] == 1, f"block-1 inner step had childStepId={st['childStepId']}"
    for st in g2["workoutSteps"]:
        assert st["childStepId"] == 2, f"block-2 inner step had childStepId={st['childStepId']}"


def test_repeat_group_no_rest_step_when_zero():
    """A block with rest_between_rounds_s=0 should not emit a rest
    step inside its group."""
    blocks = [{
        "name": "x", "rounds": 2, "rest_between_rounds_s": 0,
        "exercises": [_ex("plank", "plank", duration_s=30)],
    }]
    p = build_payload(_session("core", blocks))
    inner = p["workoutSegments"][0]["workoutSteps"][0]["workoutSteps"]
    assert all(s["stepType"]["stepTypeKey"] != "rest" for s in inner), inner


# ── Per-side emission ────────────────────────────────────────────

def test_per_side_emits_twice_inside_repeat_group():
    """A per-side exercise inside a multi-round block emits two
    consecutive inner steps (first side / second side), and the
    rounds loop happens around the whole pair."""
    blocks = [{
        "name": "x", "rounds": 2, "rest_between_rounds_s": 30,
        "exercises": [_ex("plank", "side_plank", duration_s=40, per_side=True)],
    }]
    p = build_payload(_session("core", blocks))
    inner = p["workoutSegments"][0]["workoutSteps"][0]["workoutSteps"]
    # 2 per-side emissions + 1 rest = 3 inner steps.
    assert len(inner) == 3, f"expected 3, got {len(inner)}"
    assert inner[0]["category"] == "PLANK"
    assert inner[1]["category"] == "PLANK"   # same exercise, second side
    assert inner[2]["stepType"]["stepTypeKey"] == "rest"


# ── stepOrder is flat across groups + inner steps ────────────────

def test_step_order_flat_numbering():
    """Garmin numbers every step (group AND inner) sequentially in
    one flat range. Verify we don't accidentally restart per block."""
    blocks = [
        {
            "name": "A", "rounds": 2, "rest_between_rounds_s": 30,
            "exercises": [
                _ex("plank", "plank", duration_s=30),
                _ex("plank", "side_plank", duration_s=30),
            ],
        },
        {
            "name": "B", "rounds": 1, "rest_between_rounds_s": 0,
            "exercises": [_ex("squat", "body_weight_wall_squat", reps=10)],
        },
    ]
    p = build_payload(_session("core", blocks))
    steps = p["workoutSegments"][0]["workoutSteps"]
    # Block A is a RepeatGroup: stepOrder 1, inner 2/3/4 (rest)
    # Block B is flat: stepOrder 5
    g = steps[0]
    assert g["stepOrder"] == 1
    inner = g["workoutSteps"]
    assert [s["stepOrder"] for s in inner] == [2, 3, 4]
    assert steps[1]["stepOrder"] == 5


# ── Per-step Fenix-validator hygiene ─────────────────────────────

def test_inner_step_description_is_none():
    """All step descriptions must be None — see comment in
    `_make_exercise_step` for why."""
    blocks = [{
        "name": "x", "rounds": 2, "rest_between_rounds_s": 30,
        "exercises": [_ex("plank", "plank", duration_s=30)],
    }]
    p = build_payload(_session("core", blocks))
    for s in p["workoutSegments"][0]["workoutSteps"][0]["workoutSteps"]:
        assert s["description"] is None, s


# ──────────────────────────────────────────────────────────────────

TESTS = [
    test_sport_type_recovery_is_yoga,
    test_sport_type_plyo_is_hiit,
    test_sport_type_default_is_cardio_training,
    test_workoutProvider_is_set,
    test_single_round_block_is_flat,
    test_multi_round_block_is_repeat_group,
    test_repeat_group_childStepId_increments_per_block,
    test_repeat_group_no_rest_step_when_zero,
    test_per_side_emits_twice_inside_repeat_group,
    test_step_order_flat_numbering,
    test_inner_step_description_is_none,
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
