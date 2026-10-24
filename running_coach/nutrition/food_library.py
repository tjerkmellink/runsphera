"""Curated Dutch meal templates for the Fuel meal assembler.

This is **hand-authored reference data**, deliberately NOT the NEVO dataset.
NEVO (RIVM's Nederlands Voedingsstoffenbestand) is CC-BY 4.0 but gated
behind terms-acceptance and a per-user dataset request, so we don't embed
it. Nutrient *values* are facts (not copyrightable); the per-100 g figures
below are authored by us and cross-checked against public sources
(NEVO-online / USDA FoodData Central) and rounded to sensible precision.
They're estimates for everyday foods, not a clinical food table.

## Shape

Each template is a dish assignable to one meal slot:

- ``slug``    — stable id.
- ``slot``    — ``breakfast`` | ``lunch`` | ``dinner`` | ``snack``.
- ``diet``    — the MOST PERMISSIVE diet the dish satisfies:
  ``vegan`` (no animal products), ``vegetarian`` (dairy/egg, no meat/fish),
  or ``omnivore`` (meat/fish). A vegan dish is valid for vegetarians and
  omnivores too — see ``meal_plan.diet_ok``.
- ``name_en`` / ``name_nl`` — display names (picked by UI locale).
- ``ingredients`` — list of components. Macros are **per 100 g**. Exactly
  one ingredient is the carb ``anchor`` — the assembler scales the whole
  dish to hit a meal's carb target, anchored on that item.

## Adding a dish

Append here. Keep ≥2 vegan and ≥2 vegetarian options per slot so every
diet has day-to-day variety. The ``_validate`` call at import time enforces
one-anchor-per-dish and valid enums, so a typo fails fast.
"""
from __future__ import annotations

SLOTS = ("breakfast", "lunch", "dinner", "snack")
DIETS = ("vegan", "vegetarian", "omnivore")


def _ing(name_en, name_nl, base_g, carb, protein, fat, anchor=False):
    return {
        "name_en": name_en, "name_nl": name_nl, "base_g": base_g,
        "carb": carb, "protein": protein, "fat": fat, "anchor": anchor,
    }


# ── Meal templates ──────────────────────────────────────────────────────
MEAL_TEMPLATES: list[dict] = [
    # ===== BREAKFAST =====
    {"slug": "havermout_kwark_banaan", "slot": "breakfast", "diet": "vegetarian",
     "name_en": "Oatmeal with quark & banana", "name_nl": "Havermout met kwark en banaan",
     "ingredients": [
         _ing("Rolled oats", "Havermout", 60, 60, 13, 7, anchor=True),
         _ing("Low-fat quark", "Magere kwark", 150, 4, 11, 0),
         _ing("Banana", "Banaan", 120, 20, 1, 0),
     ]},
    {"slug": "brood_ei_pindakaas", "slot": "breakfast", "diet": "vegetarian",
     "name_en": "Whole-grain bread, egg & peanut butter", "name_nl": "Volkorenbrood met ei en pindakaas",
     "ingredients": [
         _ing("Whole-grain bread", "Volkorenbrood", 90, 41, 9, 3, anchor=True),
         _ing("Egg", "Ei", 60, 1, 13, 11),
         _ing("Peanut butter", "Pindakaas", 20, 12, 25, 50),
     ]},
    {"slug": "overnight_oats_soja", "slot": "breakfast", "diet": "vegan",
     "name_en": "Overnight oats with soy yogurt", "name_nl": "Overnight oats met sojayoghurt",
     "ingredients": [
         _ing("Rolled oats", "Havermout", 60, 60, 13, 7, anchor=True),
         _ing("Soy yogurt", "Sojayoghurt", 150, 5, 4, 2),
         _ing("Banana", "Banaan", 100, 20, 1, 0),
     ]},
    {"slug": "muesli_havermelk_appel", "slot": "breakfast", "diet": "vegan",
     "name_en": "Muesli with oat milk & apple", "name_nl": "Muesli met havermelk en appel",
     "ingredients": [
         _ing("Muesli", "Muesli", 70, 60, 10, 8, anchor=True),
         _ing("Oat milk", "Havermelk", 200, 7, 1, 2),
         _ing("Apple", "Appel", 120, 14, 0, 0),
     ]},
    {"slug": "skyr_muesli_bes", "slot": "breakfast", "diet": "vegetarian",
     "name_en": "Skyr with muesli & berries", "name_nl": "Skyr met muesli en bessen",
     "ingredients": [
         _ing("Muesli", "Muesli", 60, 60, 10, 8, anchor=True),
         _ing("Skyr", "Skyr", 150, 4, 11, 0),
         _ing("Blueberries", "Bosbessen", 80, 12, 1, 0),
     ]},
    {"slug": "omelet_brood_kaas", "slot": "breakfast", "diet": "vegetarian",
     "name_en": "Omelette with bread & cheese", "name_nl": "Omelet met brood en kaas",
     "ingredients": [
         _ing("Whole-grain bread", "Volkorenbrood", 80, 41, 9, 3, anchor=True),
         _ing("Egg", "Ei", 100, 1, 13, 11),
         _ing("Cheese 30+", "Kaas 30+", 30, 0, 25, 23),
     ]},

    # ===== LUNCH =====
    {"slug": "brood_kipfilet_avocado", "slot": "lunch", "diet": "omnivore",
     "name_en": "Bread with chicken & avocado", "name_nl": "Brood met kipfilet en avocado",
     "ingredients": [
         _ing("Whole-grain bread", "Volkorenbrood", 110, 41, 9, 3, anchor=True),
         _ing("Chicken breast", "Kipfilet", 80, 0, 31, 4),
         _ing("Avocado", "Avocado", 60, 9, 2, 15),
     ]},
    {"slug": "couscous_kikkererwten", "slot": "lunch", "diet": "vegan",
     "name_en": "Couscous with chickpeas & spinach", "name_nl": "Couscous met kikkererwten en spinazie",
     "ingredients": [
         _ing("Couscous (cooked)", "Couscous (gekookt)", 200, 23, 4, 0, anchor=True),
         _ing("Chickpeas", "Kikkererwten", 120, 27, 9, 3),
         _ing("Spinach", "Spinazie", 80, 1, 3, 0),
     ]},
    {"slug": "wrap_hummus_groente", "slot": "lunch", "diet": "vegan",
     "name_en": "Wrap with hummus & veg", "name_nl": "Wrap met hummus en groente",
     "ingredients": [
         _ing("Tortilla wrap", "Tortillawrap", 100, 50, 8, 7, anchor=True),
         _ing("Hummus", "Hummus", 60, 14, 8, 17),
         _ing("Bell pepper", "Paprika", 80, 6, 1, 0),
     ]},
    {"slug": "brood_tonijn_ei", "slot": "lunch", "diet": "omnivore",
     "name_en": "Bread with tuna & egg", "name_nl": "Brood met tonijn en ei",
     "ingredients": [
         _ing("Whole-grain bread", "Volkorenbrood", 110, 41, 9, 3, anchor=True),
         _ing("Tuna", "Tonijn", 80, 0, 26, 1),
         _ing("Egg", "Ei", 50, 1, 13, 11),
     ]},
    {"slug": "linzensalade_brood", "slot": "lunch", "diet": "vegan",
     "name_en": "Lentil salad with bread", "name_nl": "Linzensalade met brood",
     "ingredients": [
         _ing("Whole-grain bread", "Volkorenbrood", 90, 41, 9, 3, anchor=True),
         _ing("Lentils (cooked)", "Linzen (gekookt)", 150, 20, 9, 0),
         _ing("Tomato", "Tomaat", 100, 4, 1, 0),
     ]},
    {"slug": "pasta_pesto_kaas", "slot": "lunch", "diet": "vegetarian",
     "name_en": "Pasta with pesto & cheese", "name_nl": "Pasta met pesto en kaas",
     "ingredients": [
         _ing("Whole-grain pasta (cooked)", "Volkorenpasta (gekookt)", 180, 30, 5, 2, anchor=True),
         _ing("Pesto", "Pesto", 25, 6, 3, 45),
         _ing("Cheese 30+", "Kaas 30+", 25, 0, 25, 23),
     ]},

    # ===== DINNER =====
    {"slug": "rijst_kip_groente", "slot": "dinner", "diet": "omnivore",
     "name_en": "Brown rice with chicken & broccoli", "name_nl": "Zilvliesrijst met kip en broccoli",
     "ingredients": [
         _ing("Brown rice (cooked)", "Zilvliesrijst (gekookt)", 220, 25, 3, 1, anchor=True),
         _ing("Chicken breast", "Kipfilet", 120, 0, 31, 4),
         _ing("Broccoli", "Broccoli", 150, 4, 3, 0),
     ]},
    {"slug": "pasta_zalm_spinazie", "slot": "dinner", "diet": "omnivore",
     "name_en": "Pasta with salmon & spinach", "name_nl": "Pasta met zalm en spinazie",
     "ingredients": [
         _ing("Whole-grain pasta (cooked)", "Volkorenpasta (gekookt)", 220, 30, 5, 2, anchor=True),
         _ing("Salmon", "Zalm", 120, 0, 20, 13),
         _ing("Spinach", "Spinazie", 100, 1, 3, 0),
     ]},
    {"slug": "aardappel_tofu_boontjes", "slot": "dinner", "diet": "vegan",
     "name_en": "Potatoes with tofu & green beans", "name_nl": "Aardappel met tofu en sperziebonen",
     "ingredients": [
         _ing("Potato (cooked)", "Aardappel (gekookt)", 300, 17, 2, 0, anchor=True),
         _ing("Tofu", "Tofu", 150, 2, 12, 7),
         _ing("Green beans", "Sperziebonen", 150, 5, 2, 0),
     ]},
    {"slug": "zoete_aardappel_kikkererwten", "slot": "dinner", "diet": "vegan",
     "name_en": "Sweet potato & chickpea curry", "name_nl": "Zoete aardappel-kikkererwtencurry",
     "ingredients": [
         _ing("Sweet potato (cooked)", "Zoete aardappel (gekookt)", 250, 20, 2, 0, anchor=True),
         _ing("Chickpeas", "Kikkererwten", 150, 27, 9, 3),
         _ing("Spinach", "Spinazie", 100, 1, 3, 0),
     ]},
    {"slug": "pasta_tomatensaus_kaas", "slot": "dinner", "diet": "vegetarian",
     "name_en": "Pasta with tomato sauce & cheese", "name_nl": "Pasta met tomatensaus en kaas",
     "ingredients": [
         _ing("Whole-grain pasta (cooked)", "Volkorenpasta (gekookt)", 220, 30, 5, 2, anchor=True),
         _ing("Tomato sauce", "Tomatensaus", 150, 6, 2, 2),
         _ing("Cheese 30+", "Kaas 30+", 40, 0, 25, 23),
     ]},
    {"slug": "rijst_tempeh_roerbak", "slot": "dinner", "diet": "vegan",
     "name_en": "Rice with tempeh stir-fry", "name_nl": "Rijst met tempeh-roerbak",
     "ingredients": [
         _ing("Brown rice (cooked)", "Zilvliesrijst (gekookt)", 220, 25, 3, 1, anchor=True),
         _ing("Tempeh", "Tempeh", 120, 9, 19, 11),
         _ing("Stir-fry veg", "Roerbakgroente", 150, 5, 2, 0),
     ]},
    {"slug": "aardappel_ei_groente", "slot": "dinner", "diet": "vegetarian",
     "name_en": "Potatoes with egg & vegetables", "name_nl": "Aardappel met ei en groente",
     "ingredients": [
         _ing("Potato (cooked)", "Aardappel (gekookt)", 300, 17, 2, 0, anchor=True),
         _ing("Egg", "Ei", 120, 1, 13, 11),
         _ing("Green vegetables", "Groene groente", 150, 4, 3, 0),
     ]},

    # ===== SNACK =====
    {"slug": "banaan_pindakaas", "slot": "snack", "diet": "vegan",
     "name_en": "Banana with peanut butter", "name_nl": "Banaan met pindakaas",
     "ingredients": [
         _ing("Banana", "Banaan", 120, 20, 1, 0, anchor=True),
         _ing("Peanut butter", "Pindakaas", 20, 12, 25, 50),
     ]},
    {"slug": "rijstwafels_pindakaas", "slot": "snack", "diet": "vegan",
     "name_en": "Rice cakes with peanut butter", "name_nl": "Rijstwafels met pindakaas",
     "ingredients": [
         _ing("Rice cakes", "Rijstwafels", 30, 81, 8, 3, anchor=True),
         _ing("Peanut butter", "Pindakaas", 20, 12, 25, 50),
     ]},
    {"slug": "kwark_rozijnen", "slot": "snack", "diet": "vegetarian",
     "name_en": "Quark with raisins", "name_nl": "Kwark met rozijnen",
     "ingredients": [
         _ing("Raisins", "Rozijnen", 40, 79, 3, 0, anchor=True),
         _ing("Low-fat quark", "Magere kwark", 150, 4, 11, 0),
     ]},
    {"slug": "appel_noten", "slot": "snack", "diet": "vegan",
     "name_en": "Apple with mixed nuts", "name_nl": "Appel met gemengde noten",
     "ingredients": [
         _ing("Apple", "Appel", 150, 14, 0, 0, anchor=True),
         _ing("Mixed nuts", "Gemengde noten", 30, 16, 20, 54),
     ]},
    {"slug": "yoghurt_granola", "slot": "snack", "diet": "vegetarian",
     "name_en": "Greek yogurt with granola", "name_nl": "Griekse yoghurt met granola",
     "ingredients": [
         _ing("Granola", "Granola", 40, 64, 9, 14, anchor=True),
         _ing("Greek yogurt", "Griekse yoghurt", 150, 4, 10, 5),
     ]},
    {"slug": "dadels_noten", "slot": "snack", "diet": "vegan",
     "name_en": "Dates with nuts", "name_nl": "Dadels met noten",
     "ingredients": [
         _ing("Dates", "Dadels", 50, 75, 2, 0, anchor=True),
         _ing("Mixed nuts", "Gemengde noten", 25, 16, 20, 54),
     ]},
]


def _validate() -> None:
    """Fail fast at import on a malformed template (one anchor, valid enums)."""
    seen_slugs = set()
    for t in MEAL_TEMPLATES:
        slug = t.get("slug")
        if not slug or slug in seen_slugs:
            raise ValueError(f"food_library: missing/duplicate slug {slug!r}")
        seen_slugs.add(slug)
        if t["slot"] not in SLOTS:
            raise ValueError(f"food_library: {slug} bad slot {t['slot']!r}")
        if t["diet"] not in DIETS:
            raise ValueError(f"food_library: {slug} bad diet {t['diet']!r}")
        anchors = [i for i in t["ingredients"] if i.get("anchor")]
        if len(anchors) != 1:
            raise ValueError(f"food_library: {slug} needs exactly one anchor, got {len(anchors)}")


_validate()
