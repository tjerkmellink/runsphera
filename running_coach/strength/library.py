"""Canonical bodyweight strength + core + mobility sessions for the
rest-day rotation. Every exercise references Garmin's FIT exercise
catalog directly via a ``(category, exercise)`` pair — that means each
session pushed to the watch carries proper animations, localized
labels, and an auto-generated muscle-group diagram in the Garmin
Connect summary.

## Exercise shape

Each exercise dict carries:

- ``category``    — FIT exercise category enum (lowercase snake_case).
- ``exercise``    — FIT exercise name enum within that category.
- ``duration_s``  — seconds, OR…
- ``reps``        — rep count.
- ``per_side``    — True when the exercise needs both sides. The push
  layer emits two consecutive watch steps so the runner gets a clean
  "first side / second side" beat.
- ``superset_id`` — optional letter that pairs consecutive exercises as
  a superset (rendered side-by-side in the modal). No effect on the
  watch payload — the watch executes them in stepOrder.
- ``description`` — hand-written one-sentence form cue for the modal.

Exercise *labels* in the modal come from title-casing the FIT enum
directly (`single_leg_hip_raise` → `Single leg hip raise`). We
deliberately do not override them — keeping the in-app label, the
Garmin Connect list, and the Fenix watch screen all showing the same
name avoids the "app says X, watch says Y" confusion.

## Block shape

- ``name`` — display title.
- ``rounds`` — how many times the block repeats.
- ``rest_between_rounds_s`` — rest in seconds between rounds.
- ``exercises`` — ordered list of exercise dicts.

## Animation guarantee

Every exercise here is validated against
``garmin_catalog.is_animated()`` at module-import time (see the
``_validate_library`` call at the bottom). That function answers
"will this pair render with animation + info popup in Garmin
Connect?" — built from an empirical sweep, not the FIT catalog. The
distinction matters: many FIT-valid enums (every ``warm_up/stretch_*``,
most plyo / hip_stability variants, every specialized squat) accept
the payload but show "Er is een fout opgetreden" when tapped in the
app. The validator means you can't accidentally ship a broken one.

## Adding new exercises

If you reach for a `(category, exercise)` pair that isn't in the
allowlist, the import will fail with a clear error. To add it:
push a probe workout containing the candidate, walk it in the Garmin
Connect app, and if the popup renders, append to
``KNOWN_ANIMATED`` in ``garmin_catalog.py``. Use ``pose/*`` and
``move/*`` freely — those whole categories are default-animated.
See ``docs/strength-sessions.md`` for the probe procedure.
"""
from __future__ import annotations

from . import garmin_catalog


# ── 1. Core & Hamstrings ──────────────────────────────────────────────
# The original session — proven to push and animate cleanly. Glute
# activation + diagonal core + plank superset.
CORE_HAMSTRINGS = {
    "slug":            "core_hamstrings",
    "title":           "Core & Hamstrings",
    "category":        "core+hamstrings",
    "duration_min_lo": 20,
    "duration_min_hi": 25,
    "notes":           (
        "Easy paced. Hold each position; don't rush. Quality over speed — "
        "two clean rounds beat three sloppy ones."
    ),
    "blocks": [
        {
            "name": "Warm-up",
            "rounds": 2,
            "rest_between_rounds_s": 60,
            "exercises": [
                {
                    "category": "hip_raise", "exercise": "single_leg_hip_raise",
                    "duration_s": 30,
                    "description": "Bridge up on one leg with the other extended. Drive through the planted heel and squeeze the glute. Hips stay level — don't dip on the free side. Alternate sides as you go.",
                },
                {
                    "category": "core", "exercise": "bicycle",
                    "duration_s": 30, "per_side": True,
                    "description": "Lie on your back, knees lifted, hands behind head. Bring opposite elbow toward opposite knee, alternating. Slow and controlled.",
                },
                {
                    "category": "hip_stability", "exercise": "external_hip_raise",
                    "duration_s": 30, "per_side": True,
                    "description": "Lie on your side, knees bent and stacked. Keep feet together and open the top knee like a clam. Don't roll the hips back.",
                },
                {
                    "category": "cardio", "exercise": "jumping_jacks",
                    "duration_s": 30,
                    "description": "Feet together, arms at sides. Jump feet wide while arms come overhead, jump back. Light bouncy landings — get the heart rate up.",
                },
            ],
        },
        {
            "name": "Strength block",
            "rounds": 3,
            "rest_between_rounds_s": 90,
            "exercises": [
                {
                    "category": "squat", "exercise": "squat",
                    "reps": 12, "superset_id": "A",
                    "description": "Feet shoulder-width, sit back and down until thighs are parallel, drive up through the heels. Knees track over toes; chest tall.",
                },
                {
                    "category": "plyo", "exercise": "body_weight_jump_squat",
                    "reps": 10, "superset_id": "A",
                    "description": "Sink to a quarter squat, explode up jumping off both feet, land soft into the next rep. Bouncy, not heavy.",
                },
            ],
        },
        {
            "name": "Core finisher",
            "rounds": 2,
            "rest_between_rounds_s": 60,
            "exercises": [
                {
                    "category": "plank", "exercise": "side_plank",
                    "duration_s": 40, "per_side": True, "superset_id": "B",
                    "description": "On one elbow, body straight from ankles to shoulder. Hips up, don't sag. Squeeze the side closer to the floor.",
                },
                {
                    "category": "plank", "exercise": "plank",
                    "duration_s": 60, "superset_id": "B",
                    "description": "Forearms down, body straight from heels to shoulders. Brace the core — no hip sag, no piking up. Breathe steady.",
                },
            ],
        },
    ],
}


# ── 2. Full-Body Strength ─────────────────────────────────────────────
# Longer session — full-body compound bodyweight. Push / legs / hips /
# core. ~30-40 min. Rebuilt from the animated allowlist.
FULL_BODY_STRENGTH = {
    "slug":            "full_body_strength",
    "title":           "Full-Body Strength",
    "category":        "full_body",
    "duration_min_lo": 30,
    "duration_min_hi": 40,
    "notes":           (
        "Bigger session — schedule on a day off running, not before a "
        "quality run. Reset between rounds; the rest is part of the work."
    ),
    "blocks": [
        {
            "name": "Warm-up",
            "rounds": 2,
            "rest_between_rounds_s": 40,
            "exercises": [
                {
                    "category": "cardio", "exercise": "jumping_jacks",
                    "duration_s": 30,
                    "description": "Feet together, arms at sides. Jump feet wide while arms come overhead, jump back. Light, bouncy.",
                },
                {
                    "category": "lunge", "exercise": "walking_lunge",
                    "duration_s": 30,
                    "description": "Step forward into a lunge, back knee just off the floor, drive up off the front heel into the next step. Long strides.",
                },
                {
                    "category": "pose", "exercise": "warrior_one",
                    "duration_s": 30, "per_side": True,
                    "description": "Front knee bent over ankle, back leg straight, both arms reaching overhead. Hips squared toward the front. Open chest.",
                },
                {
                    "category": "plank", "exercise": "mountain_climber",
                    "duration_s": 30,
                    "description": "Plank position; drive one knee toward the chest then back, alternating with a controlled tempo.",
                },
            ],
        },
        {
            "name": "Push + squat",
            "rounds": 3,
            "rest_between_rounds_s": 90,
            "exercises": [
                {
                    "category": "push_up", "exercise": "push_up",
                    "reps": 10, "superset_id": "A",
                    "description": "Hands shoulder-width, body straight from heels to head, lower until elbows reach 90°, press back up. Drop to knees if needed.",
                },
                {
                    "category": "squat", "exercise": "squat",
                    "reps": 12, "superset_id": "A",
                    "description": "Feet shoulder-width, sit back and down until thighs are parallel, drive up through the heels. Knees track over toes.",
                },
            ],
        },
        {
            "name": "Lunge + hip raise",
            "rounds": 3,
            "rest_between_rounds_s": 90,
            "exercises": [
                {
                    "category": "lunge", "exercise": "walking_lunge",
                    "reps": 8, "per_side": True, "superset_id": "B",
                    "description": "Step forward into a long lunge, back knee just off the floor, drive up off the front heel. Alternate sides as you walk.",
                },
                {
                    "category": "hip_raise", "exercise": "single_leg_hip_raise",
                    "reps": 8, "per_side": True, "superset_id": "B",
                    "description": "Bridge up on one leg with the other extended. Drive through the planted heel and squeeze the glute hard at the top.",
                },
            ],
        },
        {
            "name": "Finisher",
            "rounds": 2,
            "rest_between_rounds_s": 60,
            "exercises": [
                {
                    "category": "total_body", "exercise": "burpee",
                    "reps": 8, "superset_id": "C",
                    "description": "Squat down, hands to floor, kick legs back to plank, kick back in, stand and jump. Smooth tempo, soft landings.",
                },
                {
                    "category": "plank", "exercise": "plank",
                    "duration_s": 45, "superset_id": "C",
                    "description": "Forearms down, body straight from heels to shoulders. Brace the core — no hip sag, no piking up. Breathe steady.",
                },
            ],
        },
    ],
}


# ── 3. Hip & Glute Stability ──────────────────────────────────────────
# Injury-prevention focused. Single-leg work, lateral hip stability,
# slow controlled bridges.
HIP_GLUTE_STABILITY = {
    "slug":            "hip_glute_stability",
    "title":           "Hip & Glute Stability",
    "category":        "hip_stability",
    "duration_min_lo": 20,
    "duration_min_hi": 25,
    "notes":           (
        "All about clean alignment — knee tracking over toes, hips level, "
        "no twisting. If something hurts in a way you can't breathe past, stop."
    ),
    "blocks": [
        {
            "name": "Activation",
            "rounds": 2,
            "rest_between_rounds_s": 45,
            "exercises": [
                {
                    "category": "hip_stability", "exercise": "external_hip_raise",
                    "reps": 15, "per_side": True,
                    "description": "Lie on your side, knees bent and stacked. Keep feet together and open the top knee like a clam. Don't roll the hips back.",
                },
                {
                    "category": "hip_raise", "exercise": "hip_raise",
                    "reps": 15,
                    "description": "Lie on your back, knees bent, feet flat. Drive through the heels to lift the hips into a straight line from knee to shoulder. Squeeze the glutes at the top.",
                },
                {
                    "category": "hip_raise", "exercise": "single_leg_hip_raise",
                    "reps": 10, "per_side": True,
                    "description": "Bridge up on one leg with the other extended. Drive through the planted heel, squeeze the glute. Hips stay level — don't dip on the free side.",
                },
            ],
        },
        {
            "name": "Single-leg control",
            "rounds": 3,
            "rest_between_rounds_s": 60,
            "exercises": [
                {
                    "category": "lunge", "exercise": "runners_lunge_to_balance",
                    "reps": 8, "per_side": True, "superset_id": "A",
                    "description": "From a runner's lunge with the back knee off the floor, drive through the front heel to stand on the front leg while the back knee rises to a high-knee balance. Hold a beat, return down. Strong glute + single-leg balance.",
                },
                {
                    "category": "pose", "exercise": "warrior_two",
                    "duration_s": 25, "per_side": True, "superset_id": "A",
                    "description": "Front knee bent over ankle, back leg straight and turned out, arms parallel to the floor in a T. Hold the line — glute medius gets loud.",
                },
            ],
        },
        {
            "name": "Anti-rotation finisher",
            "rounds": 2,
            "rest_between_rounds_s": 60,
            "exercises": [
                {
                    "category": "plank", "exercise": "side_plank",
                    "duration_s": 25, "per_side": True, "superset_id": "B",
                    "description": "Body straight from ankles to shoulder, hips lifted, free arm to the ceiling. Hold the line; squeeze the side closer to the floor.",
                },
                {
                    "category": "pose", "exercise": "bridge",
                    "duration_s": 30, "superset_id": "B",
                    "description": "Lie on your back, knees bent, lift hips up into a bridge and hold. Shoulder blades pressed into the floor; squeeze the glutes.",
                },
            ],
        },
    ],
}


# ── 4. Plyometric Power ───────────────────────────────────────────────
# Short, sharp. Power + reactivity for the running stride. Rebuilt
# around the four bouncy moves that animate (jumping_jacks, squat_jacks,
# body_weight_jump_squat, burpee) plus mountain_climber as fast-core.
PLYO_POWER = {
    "slug":            "plyo_power",
    "title":           "Plyometric Power",
    "category":        "plyo",
    "duration_min_lo": 15,
    "duration_min_hi": 20,
    "notes":           (
        "Bouncy, not heavy — pretend the ground is hot. Quality reps, "
        "long rest. Don't do this on tired legs (skip after a hard run)."
    ),
    "blocks": [
        {
            "name": "Activation",
            "rounds": 2,
            "rest_between_rounds_s": 30,
            "exercises": [
                {
                    "category": "cardio", "exercise": "jumping_jacks",
                    "duration_s": 30,
                    "description": "Feet together, arms at sides. Jump feet wide while arms come overhead, jump back. Light bouncy landings.",
                },
                {
                    "category": "plank", "exercise": "mountain_climber",
                    "duration_s": 30,
                    "description": "Plank position; drive one knee toward the chest then back, alternating quickly. Active, controlled tempo.",
                },
                {
                    "category": "pose", "exercise": "warrior_one",
                    "duration_s": 20, "per_side": True,
                    "description": "Front knee bent over ankle, back leg straight, arms overhead. A controlled pause before the bouncy work.",
                },
            ],
        },
        {
            "name": "Bounds",
            "rounds": 3,
            "rest_between_rounds_s": 90,
            "exercises": [
                {
                    "category": "cardio", "exercise": "squat_jacks",
                    "reps": 15, "superset_id": "A",
                    "description": "Squat down, then jump feet apart and stand up; jump back together as you squat. Combines the squat with the jack pattern.",
                },
                {
                    "category": "plyo", "exercise": "body_weight_jump_squat",
                    "reps": 10, "superset_id": "A",
                    "description": "Sink to a quarter squat, explode up jumping off both feet, land soft into the next rep. Bouncy, not heavy — minimal ground time.",
                },
            ],
        },
        {
            "name": "Power finisher",
            "rounds": 2,
            "rest_between_rounds_s": 90,
            "exercises": [
                {
                    "category": "total_body", "exercise": "burpee",
                    "reps": 8, "superset_id": "B",
                    "description": "Squat down, hands to floor, kick legs back to plank, kick back in, stand and jump. Full-body explosive.",
                },
                {
                    "category": "squat", "exercise": "squat",
                    "reps": 12, "superset_id": "B",
                    "description": "Feet shoulder-width, sit back and down until thighs are parallel, drive up through the heels. Active rest from the explosive work.",
                },
            ],
        },
    ],
}


# ── 5. Recovery & Mobility ────────────────────────────────────────────
# Gentle yoga flow — auto-assigned the day after any quality / long
# session. Rebuilt from `pose/*` and `move/*` entirely; the old warm_up
# stretches all turned out to be FIT-valid but unanimated.
RECOVERY_MOBILITY = {
    "slug":            "recovery_mobility",
    "title":           "Recovery & Mobility",
    "category":        "recovery",
    "duration_min_lo": 15,
    "duration_min_hi": 20,
    "notes":           (
        "Slow down. This is the version of strength training your legs "
        "will thank you for tomorrow. Skip anything that pulls on a tight spot."
    ),
    "blocks": [
        {
            "name": "Settle in",
            "rounds": 1,
            "rest_between_rounds_s": 0,
            "exercises": [
                {
                    "category": "pose", "exercise": "easy_seated",
                    "duration_s": 45,
                    "description": "Sit cross-legged with the spine tall. Soften the shoulders, eyes closed, slow breath in and out through the nose. Arrive in the body.",
                },
                {
                    "category": "pose", "exercise": "cat",
                    "duration_s": 30,
                    "description": "On hands and knees, exhale and round the spine to the ceiling, tuck the chin. Move slowly with the breath.",
                },
                {
                    "category": "pose", "exercise": "cow",
                    "duration_s": 30,
                    "description": "On hands and knees, inhale and drop the belly, lift the chest and tailbone, soft gaze up. The pair with cat — slow and rhythmic.",
                },
                {
                    "category": "pose", "exercise": "sphinx",
                    "duration_s": 30,
                    "description": "Lie on your front, forearms down with elbows under the shoulders, gently lift the chest. A soft back-bend to undo the cat rounding. Shoulders relaxed away from the ears.",
                },
            ],
        },
        {
            "name": "Hip openers",
            "rounds": 1,
            "rest_between_rounds_s": 30,
            "exercises": [
                {
                    "category": "pose", "exercise": "low_lunge",
                    "duration_s": 45, "per_side": True,
                    "description": "Step one foot forward into a lunge, drop the back knee to the floor, sink the hips down and forward. Opens the hip flexor of the back leg.",
                },
                {
                    "category": "pose", "exercise": "runners_lunge",
                    "duration_s": 45, "per_side": True,
                    "description": "Front foot flat with knee over ankle, back leg long with the knee off the floor. Hands frame the front foot. Strong hip opener.",
                },
                {
                    "category": "pose", "exercise": "one_legged_pigeon",
                    "duration_s": 45, "per_side": True,
                    "description": "From all fours, bring one knee forward toward that wrist, slide the back leg long. Square the hips and fold forward over the front shin. Deep glute / hip rotator stretch.",
                },
                {
                    "category": "pose", "exercise": "bound_angle",
                    "duration_s": 45,
                    "description": "Sit tall, bring the soles of the feet together and let the knees fall open. Hold the feet and lengthen the spine; fold forward a touch if it feels good. Opens the inner thighs and groin.",
                },
            ],
        },
        {
            "name": "Lengthen",
            "rounds": 1,
            "rest_between_rounds_s": 30,
            "exercises": [
                {
                    "category": "pose", "exercise": "downward_facing_dog",
                    "duration_s": 45,
                    "description": "Hands and feet on the floor, hips lifted into an inverted V. Press the chest toward the thighs, heels reaching down. Length through the spine.",
                },
                {
                    "category": "move", "exercise": "forward_fold",
                    "duration_s": 45,
                    "description": "Stand tall, hinge from the hips, soften the knees and let the head hang heavy. Hold whatever depth feels good. Hamstrings + low back release.",
                },
                {
                    "category": "pose", "exercise": "seated_long_leg_forward_bend",
                    "duration_s": 45,
                    "description": "Sit with both legs extended, flex the feet, hinge from the hips and walk the hands toward the toes. Lead with the chest, not the chin. Deep hamstring + calf lengthener.",
                },
                {
                    "category": "move", "exercise": "hamstring_stretch",
                    "duration_s": 30, "per_side": True,
                    "description": "Lie on your back, lift one leg toward the ceiling with the other heel rooted into the floor. Hold behind the thigh; flex the lifted foot. Long slow breath.",
                },
                {
                    "category": "move", "exercise": "piriformis_stretch",
                    "duration_s": 30, "per_side": True,
                    "description": "Lie on your back, cross one ankle over the opposite thigh into a figure-4, then draw that thigh toward the chest. Targets the deep glute / piriformis that tightens up from running.",
                },
            ],
        },
        {
            "name": "Decompress",
            "rounds": 1,
            "rest_between_rounds_s": 0,
            "exercises": [
                {
                    "category": "pose", "exercise": "reclined_hand_to_foot",
                    "duration_s": 30, "per_side": True,
                    "description": "Lie on your back and float one leg toward the ceiling, holding behind the thigh or calf with the other leg long on the floor. Ease the leg closer with each exhale. Gentle supine hamstring.",
                },
                {
                    "category": "pose", "exercise": "supine_spinal_twist",
                    "duration_s": 45, "per_side": True,
                    "description": "Lie on your back, hug one knee in and let it fall across the body to the opposite side. Open arms wide; turn the head the other way. Stays gentle.",
                },
                {
                    "category": "pose", "exercise": "thread_the_needle",
                    "duration_s": 30, "per_side": True,
                    "description": "From all fours, slide one arm under the body, shoulder + cheek resting on the floor. Opposite hand stays planted or reaches overhead. Upper-back release.",
                },
                {
                    "category": "pose", "exercise": "childs",
                    "duration_s": 60,
                    "description": "Knees wide, big toes touching, sit back onto the heels and walk the hands forward. Forehead to the floor. Stay and breathe.",
                },
                {
                    "category": "pose", "exercise": "corpse",
                    "duration_s": 60,
                    "description": "Lie flat on your back, legs relaxed and arms by your sides, palms up. Let everything go heavy and breathe naturally. The reward for the work — don't skip it.",
                },
            ],
        },
    ],
}


# ── 6. Anti-Rotation Core ─────────────────────────────────────────────
# Pure rotational stability for the running stride. Plank-heavy + slow
# control. Rebuilt to drop the broken dead_bug / bird-dog / knee-twist
# enums.
ANTI_ROTATION_CORE = {
    "slug":            "anti_rotation_core",
    "title":           "Anti-Rotation Core",
    "category":        "core",
    "duration_min_lo": 18,
    "duration_min_hi": 22,
    "notes":           (
        "Plank-heavy. Goal is staying square under load — the core's job "
        "in running is to resist twisting, not produce it. Slow and quiet."
    ),
    "blocks": [
        {
            "name": "Activation",
            "rounds": 2,
            "rest_between_rounds_s": 45,
            "exercises": [
                {
                    "category": "pose", "exercise": "all_fours",
                    "duration_s": 30,
                    "description": "Hands under shoulders, knees under hips, neutral spine, eyes down. Slight engagement through the belly. Reset the alignment.",
                },
                {
                    "category": "hip_raise", "exercise": "hip_raise",
                    "reps": 12,
                    "description": "Lie on your back, knees bent, feet flat. Drive through the heels to lift the hips into a straight line from knee to shoulder. Squeeze the glutes at the top.",
                },
            ],
        },
        {
            "name": "Plank circuit",
            "rounds": 3,
            "rest_between_rounds_s": 60,
            "exercises": [
                {
                    "category": "plank", "exercise": "plank",
                    "duration_s": 45, "superset_id": "A",
                    "description": "Forearms down, body straight from heels to shoulders. Brace the core — no hip sag, no piking up. Breathe steady.",
                },
                {
                    "category": "plank", "exercise": "side_plank",
                    "duration_s": 30, "per_side": True, "superset_id": "A",
                    "description": "On one elbow, body straight from ankles to shoulder. Hips up, don't sag. Squeeze the side closer to the floor.",
                },
            ],
        },
        {
            "name": "Slow control",
            "rounds": 2,
            "rest_between_rounds_s": 60,
            "exercises": [
                {
                    "category": "plank", "exercise": "plank_with_oblique_crunch",
                    "reps": 10, "per_side": True, "superset_id": "B",
                    "description": "Plank position; bring one knee toward the same-side elbow, slowly return, alternate sides. Resist the urge to twist the hips — obliques do the work.",
                },
                {
                    "category": "core", "exercise": "bicycle",
                    "reps": 15, "per_side": True, "superset_id": "B",
                    "description": "Lie on your back, knees lifted, hands behind head. Bring opposite elbow toward opposite knee, alternating. Slow and controlled.",
                },
            ],
        },
        {
            "name": "Finisher",
            "rounds": 2,
            "rest_between_rounds_s": 30,
            "exercises": [
                {
                    "category": "sit_up", "exercise": "sit_up",
                    "reps": 12, "superset_id": "C",
                    "description": "Lie on your back, knees bent, feet flat. Curl up bringing the chest toward the knees; lower slowly with control. Hands behind the head or crossed on chest.",
                },
                {
                    "category": "crunch", "exercise": "crunch",
                    "reps": 15, "superset_id": "C",
                    "description": "Lie on your back, knees bent. Curl only the shoulders off the floor — lower back stays planted. Slow up, slower down.",
                },
            ],
        },
    ],
}


# Ordered list — the scheduler walks it in this order on rotation.
# Recovery & Mobility is excluded from the default rotation; the
# scheduler pulls it in after any quality / long session as the
# "easy day after hard day" override.
LIBRARY: list[dict] = [
    CORE_HAMSTRINGS,
    FULL_BODY_STRENGTH,
    HIP_GLUTE_STABILITY,
    PLYO_POWER,
    ANTI_ROTATION_CORE,
    RECOVERY_MOBILITY,
]


RECOVERY_SLUG = "recovery_mobility"
ROTATION_SLUGS: list[str] = [w["slug"] for w in LIBRARY if w["slug"] != RECOVERY_SLUG]


# ── Import-time animation guard ──────────────────────────────────────
# Validates that every exercise in every session references an enum
# Garmin Connect knows how to animate. Raises on miss so we can't
# silently ship a session with broken "Er is een fout opgetreden"
# steps — that's the regression class that bit us before the empirical
# allowlist existed.

def _validate_library() -> None:
    errors: list[str] = []
    for session in LIBRARY:
        for block in session["blocks"]:
            for ex in block["exercises"]:
                c, e = ex["category"], ex["exercise"]
                if not garmin_catalog.is_animated(c, e):
                    errors.append(
                        f"{session['slug']} / {block['name']!r} → "
                        f"({c!r}, {e!r}) is not in the known-animated set"
                    )
    if errors:
        raise RuntimeError(
            "strength.library: broken exercise references "
            f"({len(errors)}):\n  " + "\n  ".join(errors) +
            "\n\nAdd the pair to garmin_catalog.KNOWN_ANIMATED after "
            "verifying it animates in Garmin Connect (see "
            "docs/strength-sessions.md → 'Animation probe procedure')."
        )


_validate_library()
