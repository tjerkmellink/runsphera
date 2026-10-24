"""Lock-down tests for the Fuel meal assembler (Phase 2).

Pins the rules that matter: diet filtering never leaks animal products to a
vegan, the during-run carbs are excluded from the meal pool, assembled
carbs track the target, picks are deterministic per date but rotate across
days, and portion scaling stays within its clamp.

Run from the repo root:
    .venv/Scripts/python.exe tests/test_meal_plan.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from running_coach.nutrition import meal_plan, food_library  # noqa: E402


TARGETS = {"carbs_g": 400, "protein_g": 115, "fat_g": 85}
DAY = 739000  # arbitrary fixed ordinal


def test_library_has_variety_per_slot() -> None:
    """Every slot must offer ≥2 vegan and ≥2 vegetarian options so each diet
    has day-to-day variety."""
    for slot in food_library.SLOTS:
        vegan = meal_plan.candidates_for(slot, "vegan")
        veg = meal_plan.candidates_for(slot, "vegetarian")
        assert len(vegan) >= 2, f"{slot}: only {len(vegan)} vegan options"
        assert len(veg) >= 4, f"{slot}: only {len(veg)} vegetarian-or-better options"


def test_vegan_never_leaks_animal_dishes() -> None:
    plan = meal_plan.build_day_meals(TARGETS, diet_pref="vegan", day_ordinal=DAY)
    assert plan["meals"], "expected meals"
    for m in plan["meals"]:
        assert m["diet"] == "vegan", f"{m['slug']} is {m['diet']}, not vegan"


def test_vegetarian_excludes_omnivore() -> None:
    for day in range(DAY, DAY + 14):
        plan = meal_plan.build_day_meals(TARGETS, diet_pref="vegetarian", day_ordinal=day)
        for m in plan["meals"]:
            assert m["diet"] in ("vegan", "vegetarian"), m["slug"]


def test_omnivore_default_when_unset() -> None:
    # diet_pref=None → omnivore → all slots filled
    plan = meal_plan.build_day_meals(TARGETS, diet_pref=None, day_ordinal=DAY)
    assert len(plan["meals"]) == len(meal_plan.SLOT_ORDER)


def test_during_run_carbs_excluded_from_pool() -> None:
    fuel_run = {"during_total_carb_g": 60}
    plan = meal_plan.build_day_meals(TARGETS, fuel_run, diet_pref="omnivore", day_ordinal=DAY)
    assert plan["target_carbs_g"] == 400
    assert plan["during_run_carbs_g"] == 60
    assert plan["pool_carbs_g"] == 340  # 400 − 60


def test_assembled_carbs_track_pool() -> None:
    targets = {"carbs_g": 250}
    plan = meal_plan.build_day_meals(targets, diet_pref="omnivore", day_ordinal=DAY)
    pool = plan["pool_carbs_g"]
    assembled = plan["assembled"]["carbs_g"]
    assert abs(assembled - pool) <= 0.2 * pool, f"assembled {assembled} vs pool {pool}"


def test_deterministic_same_day() -> None:
    a = meal_plan.build_day_meals(TARGETS, diet_pref="omnivore", day_ordinal=DAY)
    b = meal_plan.build_day_meals(TARGETS, diet_pref="omnivore", day_ordinal=DAY)
    assert [m["slug"] for m in a["meals"]] == [m["slug"] for m in b["meals"]]


def test_rotates_across_days() -> None:
    """Breakfast shouldn't be identical every day over a week."""
    slugs = []
    for day in range(DAY, DAY + 7):
        plan = meal_plan.build_day_meals(TARGETS, diet_pref="omnivore", day_ordinal=day)
        bf = next(m["slug"] for m in plan["meals"] if m["slot"] == "breakfast")
        slugs.append(bf)
    assert len(set(slugs)) > 1, "breakfast never rotates"


def test_scale_clamps() -> None:
    dish = food_library.MEAL_TEMPLATES[0]
    base = meal_plan._base_carbs(dish)
    # Absurdly high target → factor clamps at SCALE_MAX
    hi = meal_plan.scale_dish(dish, base * 100, locale="en")
    cap = sum(
        meal_plan._round5(i["base_g"] * meal_plan.SCALE_MAX) / 100.0 * i["carb"]
        for i in dish["ingredients"]
    )
    assert hi["carbs_g"] == round(cap)
    # Near-zero target → factor clamps at SCALE_MIN (dish doesn't vanish)
    lo = meal_plan.scale_dish(dish, 1, locale="en")
    assert lo["carbs_g"] > 0


def test_locale_picks_dutch_names() -> None:
    en = meal_plan.build_day_meals(TARGETS, diet_pref="omnivore", day_ordinal=DAY, locale="en")
    nl = meal_plan.build_day_meals(TARGETS, diet_pref="omnivore", day_ordinal=DAY, locale="nl")
    en_names = [m["name"] for m in en["meals"]]
    nl_names = [m["name"] for m in nl["meals"]]
    # same dishes (same slugs), but the displayed names differ by locale
    assert [m["slug"] for m in en["meals"]] == [m["slug"] for m in nl["meals"]]
    assert en_names != nl_names


def _run() -> int:
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ok   {fn.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {fn.__name__}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run())
