"""Garmin's exercise catalog — the FIT enum table + our empirical
animation allowlist.

Two distinct sources of truth here:

1. **FIT-SDK catalog** (`categories`, `exercises_in`, `is_known`,
   `to_api_value`) — the Garmin watch firmware's full exercise
   vocabulary. ~50 categories, hundreds of named exercises. Every
   `(category, exercise)` pair the SDK knows is a valid step in a
   pushed workout — the watch will fire the step timer and accept the
   payload.

2. **Empirical animated allowlist** (`KNOWN_ANIMATED`,
   `OPEN_CATEGORIES`, `KNOWN_EMPTY`, `is_animated`) — the subset that
   actually renders **with an animation + info popup** in Garmin
   Connect. A FIT-valid enum that's not in this allowlist will
   show "Er is een fout opgetreden" when the runner taps it in the app
   (the workout still runs on the watch, but the Connect UX is broken).

These are not the same set! Garmin's exercise-info database has narrower
coverage than the FIT catalog and there's no programmatic way to ask
("does this enum animate?"). The allowlist below was built empirically
across 5 probe workouts on 2026-05-31 — see `docs/strength-sessions.md`
for the full discovery story and the probe procedure to extend it.

**For library authors:** use `is_animated(c, e)` to check that an
exercise will look good in the runner's app. `library.py` validates
every `(category, exercise)` pair at import time against this function
— a typo or unverified enum raises immediately, preventing silent
regressions like the ones we shipped before this allowlist existed.
"""
from __future__ import annotations

from functools import lru_cache


# ── FIT-SDK enum catalog ─────────────────────────────────────────────

@lru_cache(maxsize=1)
def _profile_types() -> dict:
    """Lazy import so the FIT SDK only loads when actually queried."""
    from garmin_fit_sdk import profile
    return profile.Profile["types"]


@lru_cache(maxsize=1)
def categories() -> list[str]:
    """All ~50 exercise categories Garmin's watches understand.
    Lowercase snake_case; pass through `to_api_value` to UPPERCASE for
    Garmin's REST payloads."""
    return list(_profile_types()["exercise_category"].values())


def exercises_in(category: str) -> list[str]:
    """All canonical exercise names for one category — includes variants
    (``weighted_*``, ``banded_*``, etc.) when relevant. Filter with
    `bodyweight_exercises_in` when you only want equipment-free moves."""
    cat = category.lower()
    table = _profile_types().get(f"{cat}_exercise_name")
    return list(table.values()) if table else []


def bodyweight_exercises_in(category: str) -> list[str]:
    """All exercises in `category` that don't reference loaded equipment."""
    _LOADED = (
        "weighted", "barbell", "dumbbell", "cable", "machine",
        "kettlebell", "band", "banded", "swiss_ball", "bosu",
        "plate", "medicine_ball", "smith", "trap_bar",
    )
    return [
        ex for ex in exercises_in(category)
        if not any(token in ex for token in _LOADED)
    ]


def is_known(category: str, exercise_name: str) -> bool:
    """True if `(category, exercise_name)` is a real FIT enum entry —
    i.e. the watch will accept it as a payload step. This is NOT the
    same as `is_animated()` — many FIT-valid enums don't have animation
    entries in Garmin Connect's exercise-info DB."""
    return exercise_name.lower() in exercises_in(category)


def to_api_value(name: str) -> str:
    """Garmin's REST API uses UPPERCASE snake_case for category +
    exerciseName fields (e.g. ``PLANK_WITH_ARM_RAISE``). The FIT SDK
    stores them lowercase."""
    return name.upper()


# ── Empirical animation allowlist ────────────────────────────────────
#
# The (category, exercise) pairs that render WITH animation + info
# popup in Garmin Connect. Anything outside this set + outside
# OPEN_CATEGORIES will render the broken "Er is een fout opgetreden"
# popup when the runner taps it in the app.
#
# Built empirically — there is no API to ask Garmin. To extend, see
# `docs/strength-sessions.md` → "Animation probe procedure".

# Explicit pairs (the 18 "basic gym move" enums that animate).
KNOWN_ANIMATED: frozenset[tuple[str, str]] = frozenset({
    # Squats
    ("squat",          "squat"),
    # Planks
    ("plank",          "plank"),
    ("plank",          "side_plank"),
    ("plank",          "mountain_climber"),
    ("plank",          "plank_with_oblique_crunch"),
    # Lunges (only these three of ~70 lunge variants animate)
    ("lunge",          "lunge"),
    ("lunge",          "walking_lunge"),
    ("lunge",          "runners_lunge_to_balance"),
    # Push / pull / sit
    ("push_up",        "push_up"),
    ("sit_up",         "sit_up"),
    ("pull_up",        "pull_up"),
    # Core / crunch
    ("crunch",         "crunch"),
    ("crunch",         "bicycle_crunch"),
    ("core",           "bicycle"),
    # Hip raise / hip stability
    ("hip_raise",      "hip_raise"),
    ("hip_raise",      "single_leg_hip_raise"),
    ("hip_stability",  "external_hip_raise"),
    # Cardio / plyo / total body
    ("cardio",         "jumping_jacks"),
    ("cardio",         "squat_jacks"),
    ("plyo",           "body_weight_jump_squat"),
    ("total_body",     "burpee"),
})

# Whole-category passes. Garmin's stock yoga / pilates workouts cover
# these categories thoroughly — every enum we tested animated cleanly.
# Treated as default-animated unless explicitly listed in KNOWN_EMPTY.
OPEN_CATEGORIES: frozenset[str] = frozenset({
    "pose",   # yoga poses — 24/25 tested working, 116 total in FIT-SDK
    "move",   # pilates / mobility moves — 3/3 tested working
})

# Edge cases inside OPEN_CATEGORIES — Garmin has the record but no
# animation file (the modal renders empty instead of erroring).
KNOWN_EMPTY: frozenset[tuple[str, str]] = frozenset({
    ("pose", "seated_cat_cow"),  # use pose/cat + pose/cow separately
})


def is_animated(category: str, exercise_name: str) -> bool:
    """True if the (category, exercise) pair will render with animation +
    info popup in Garmin Connect (and the watch firmware). This is the
    function `library.py` validates against at import time to guarantee
    we never silently regress.

    Returns False for:
    - Pairs not in `KNOWN_ANIMATED` and not in an `OPEN_CATEGORIES`
    - Pairs explicitly listed in `KNOWN_EMPTY` (record exists, no anim)

    Note: this only checks animation availability. The pair might
    still be FIT-invalid (use `is_known()` to check that)."""
    pair = (category.lower(), exercise_name.lower())
    if pair in KNOWN_EMPTY:
        return False
    if pair in KNOWN_ANIMATED:
        return True
    return category.lower() in OPEN_CATEGORIES
