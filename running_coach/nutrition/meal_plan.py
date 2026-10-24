"""Deterministic meal assembler — turns daily macro targets into concrete
Dutch dishes with scaled portions. Pure rules, no I/O (mirrors `engine`).

Approach: split the day's carbohydrate target across four meal slots by
fixed shares, pick a dish per slot from `food_library` (filtered by diet,
rotated by date for variety), then scale the whole dish to that slot's
carb target. Carbs lead because they're what training actually periodises;
protein/fat follow from the chosen dishes.

All shares, seeds and clamp bounds are named constants below — auditable,
reproducible, offline.
"""
from __future__ import annotations

from . import food_library

# Diet permissiveness: a dish is allowed when it's at least as permissive as
# the user's preference (vegan dish is fine for everyone; omnivore only for
# omnivores).
DIET_RANK = {"vegan": 0, "vegetarian": 1, "omnivore": 2}
DEFAULT_DIET = "omnivore"

# Order shown + share of the day's (post-run-fuel) carbohydrate pool.
SLOT_ORDER = ("breakfast", "lunch", "dinner", "snack")
SLOT_SHARE = {"breakfast": 0.30, "lunch": 0.35, "dinner": 0.30, "snack": 0.05}
# Per-slot offset so the four slots don't all rotate in lockstep day to day.
SLOT_SEED = {"breakfast": 0, "lunch": 1, "dinner": 2, "snack": 3}

# Keep scaled portions sane even when a slot target is far from a dish's
# base size (a 5 g-carb snack target shouldn't shrink a dish to crumbs, nor
# a huge target triple it).
SCALE_MIN = 0.5
SCALE_MAX = 2.0


def diet_ok(dish: dict, user_pref: str | None) -> bool:
    pref = user_pref if user_pref in DIET_RANK else DEFAULT_DIET
    return DIET_RANK[dish["diet"]] <= DIET_RANK[pref]


def _round5(x: float) -> int:
    return int(round(x / 5.0) * 5)


def _base_carbs(dish: dict) -> float:
    return sum(i["base_g"] / 100.0 * i["carb"] for i in dish["ingredients"])


def candidates_for(slot: str, diet_pref: str | None) -> list[dict]:
    return [
        t for t in food_library.MEAL_TEMPLATES
        if t["slot"] == slot and diet_ok(t, diet_pref)
    ]


def pick_dish(slot: str, diet_pref: str | None, day_ordinal: int) -> dict | None:
    cands = candidates_for(slot, diet_pref)
    if not cands:
        return None
    idx = (day_ordinal + SLOT_SEED.get(slot, 0)) % len(cands)
    return cands[idx]


def scale_dish(dish: dict, target_carb: float, locale: str = "en") -> dict:
    """Scale the whole dish to `target_carb` grams of carbohydrate, clamped,
    and emit ingredient portions + the resulting macros."""
    base = _base_carbs(dish)
    factor = target_carb / base if base else 1.0
    factor = max(SCALE_MIN, min(SCALE_MAX, factor))

    name_key = "name_nl" if locale == "nl" else "name_en"
    ingredients, carbs, protein, fat = [], 0.0, 0.0, 0.0
    for ing in dish["ingredients"]:
        grams = _round5(ing["base_g"] * factor)
        carbs += grams / 100.0 * ing["carb"]
        protein += grams / 100.0 * ing["protein"]
        fat += grams / 100.0 * ing["fat"]
        ingredients.append({"name": ing[name_key], "grams": grams})
    return {
        "slug": dish["slug"],
        "name": dish[name_key],
        "diet": dish["diet"],
        "ingredients": ingredients,
        "carbs_g": round(carbs),
        "protein_g": round(protein),
        "fat_g": round(fat),
    }


def build_day_meals(
    targets: dict,
    fuel_run: dict | None = None,
    *,
    diet_pref: str | None = None,
    day_ordinal: int,
    locale: str = "en",
) -> dict:
    """Assemble the day's four meals to cover the carbohydrate target.

    On run days the during-run carbs (gels/drink) are already part of the
    daily carb target *and* shown separately in the "fuel the run" block,
    so they're subtracted from the meal pool here to avoid double-counting.
    """
    daily_carbs = targets.get("carbs_g") or 0
    during = (fuel_run or {}).get("during_total_carb_g") or 0
    pool = max(0, daily_carbs - during)

    meals = []
    tot_c = tot_p = tot_f = 0
    for slot in SLOT_ORDER:
        dish = pick_dish(slot, diet_pref, day_ordinal)
        if not dish:
            continue
        m = scale_dish(dish, pool * SLOT_SHARE[slot], locale)
        m["slot"] = slot
        meals.append(m)
        tot_c += m["carbs_g"]
        tot_p += m["protein_g"]
        tot_f += m["fat_g"]

    return {
        "meals": meals,
        "assembled": {"carbs_g": tot_c, "protein_g": tot_p, "fat_g": tot_f},
        "target_carbs_g": daily_carbs,
        "pool_carbs_g": round(pool),
        "during_run_carbs_g": round(during),
    }
