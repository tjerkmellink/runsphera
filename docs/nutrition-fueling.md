# Nutrition & Fueling (Fuel tab)

> Turns your training load into daily calorie, carbohydrate and hydration targets — plus around-the-run fuelling on long days. Rules-based, computed locally, works with or without Garmin.

## Purpose

The app coaches *training* but, until this feature, said nothing about *fuelling* — and you can't train for (let alone finish) a marathon without it. We already capture the energy side from Garmin (`activities.calories`, `daily_metrics.total_kcal/active_kcal/bmr_kcal`) but had nothing that turns burn into "what and how much to eat and drink today."

Fuel closes that loop: it personalises mainstream sports-nutrition rules to the runner's body and the day's planned workout, so a long-run day prescribes more carbs and fluid than a rest day, and runs over ~75 minutes get explicit before/during/after fuelling guidance.

**Phase 1** delivered the numbers + fuelling timing. **Phase 2** (shipped) assembles those targets into **concrete Dutch dishes with scaled portions** for breakfast / lunch / dinner / snack, respecting the diet preference.

## How it works (user view)

- **Settings → Body profile card** (`/settings#fuel`): enter weight (required), height, birth year, sex, and an optional diet preference. If Garmin is connected, an **Import** button pre-fills weight/height/sex/birth year from your Garmin profile + latest weigh-in; you can still edit before saving.
- **Fuel tab** (`/fuel`): the daily view —
  - **Energy & macros**: a kcal target (BMR × daily-life factor + the run) split into carbs / protein / fat, with the carb band (g/kg) for the day type.
  - **Meals**: four concrete Dutch dishes (breakfast / lunch / dinner / snack) with per-ingredient grams scaled to the day's carb target, plus per-meal macros. Dishes rotate by date for variety and respect the diet preference (vegan / vegetarian / omnivore). A footer reconciles the meals' carbs against the daily target.
  - **Fuel the run** (only for efforts > ~75 min): before / during / after carbs, gel cadence, and fluid per hour.
  - **Hydration today**: baseline + run replacement + warm-day bump.
  - **Carb load by day**: a 7-bar sparkline of the active plan's current week, so carb periodisation (and race-week loading) is visible at a glance.
  - A date stepper walks through other days.
- **Dashboard tile** ("② Today · Fuel"): a compact glance — energy, carbs, hydration, gel cadence — linking into the Fuel tab.

If no body profile is set, both surfaces show an empty state linking to Settings.

## How it works (implementation)

- **Modules**:
  - `runsphera/nutrition/engine.py` — pure, deterministic rules (no I/O): `bmr()`, `run_kcal()`, `daily_targets()`, `fuel_the_run()`, `hydration()`. All thresholds are named constants at the top.
  - `runsphera/nutrition/service.py` — gathers DB inputs (profile, the day's workout + matched-activity calories, Garmin daily metrics, weather) and calls the engine; `fuel_for_date()` (now also assembles meals) and `weekly_fuel_strip()`.
  - `runsphera/nutrition/food_library.py` — hand-authored curated Dutch dish templates (per-100 g macros, diet tag, one carb anchor each). Pure data; validated at import.
  - `runsphera/nutrition/meal_plan.py` — pure rules: split the daily carb pool across slots, pick a diet-appropriate dish per slot (date-rotated), scale to the slot's carb target (clamped). Named constants for shares/seeds/clamp.
  - `runsphera/settings.py` — `get_body_profile()` / `set_body_profile()` (range-validated; weight required).
  - `runsphera/garmin.py` — `fetch_profile()` reads Garmin's `get_userprofile_settings()` + `get_body_composition()` tolerantly.
- **Templates**: `web/templates/fuel.html` (tab), the Body-profile card in `settings.html`, the Fuel tile in `index.html`, the nav link in `base.html`.
- **Routes**: `GET /fuel`, `POST /settings/body-profile`, `POST /settings/body-profile/import-garmin`.
- **DB**: new `app_settings` columns — `weight_kg`, `height_cm`, `birth_year`, `sex`, `diet_pref`, `body_profile_updated_at`.
- **External services**: Garmin (optional pre-fill only); Open-Meteo weather (reused via `weather.current_weather`). No external nutrition API — the food data is local (see licensing note).

**Food data & NEVO licensing**: the dish table in `food_library.py` is hand-authored. We deliberately do **not** embed RIVM's NEVO (Nederlands Voedingsstoffenbestand) dataset: it's CC-BY 4.0 but distribution is gated behind terms-acceptance and a per-user dataset request. Nutrient *values* are facts (not copyrightable), so we author our own modest per-100 g table, cross-checked against public sources (NEVO-online, USDA FoodData Central). This keeps the app offline, license-clean, and rules-first.

**Data flow**: body profile + active-plan workout (+ Garmin metrics/weather when present) → engine computes energy/macros/hydration/fuelling → service shapes dicts → templates render. No caching: the computation is cheap and inputs change rarely. Saving the profile invalidates the daily coach cache.

**Garmin-optional degradation**: BMR prefers the Mifflin-St Jeor formula (needs height + birth year + sex) and falls back to Garmin's measured `bmr_kcal`; with neither, carbs/protein still personalise by weight but no kcal target shows. The run's calories prefer the matched activity's measured value and fall back to the ~1 kcal/kg/km estimate from the planned distance.

## Configuration

- **Body profile** — `/settings#fuel`, stored in `app_settings` (single-row, local SQLite). Weight is the only required field.
- **Engine constants** — `nutrition/engine.py`: activity factor, carb periodisation bands per workout type, protein g/kg, fluid rates, heat threshold, the 75-min "fuel the run" cutoff, etc. Edit there to retune; values are sourced from mainstream endurance guidance (ACSM / IOC consensus / Daniels).
- **Meal-assembly constants** — `nutrition/meal_plan.py`: per-slot carb shares (breakfast 30% · lunch 35% · dinner 30% · snack 5%), rotation seeds, and the 0.5–2.0× portion-scale clamp.
- **Diet preference** — `app_settings.diet_pref` (omnivore default); filters which dishes are eligible.
- **Dish library** — extend `nutrition/food_library.py`; keep ≥2 vegan + ≥2 vegetarian per slot (import-time validation enforces one carb anchor per dish).

## Known limitations

- **No measured sweat/hydration** — fluid is estimated from duration × an intensity rate + a temperature bump; real sweat rate varies a lot between people.
- **Meals are examples, not a closed total** — portions are clamped to realistic sizes (0.5–2.0× a base serving), so on very high-carb days the four meals deliberately under-cover the target; the footer says to top up with extra snacks. Macros follow the carb-anchored scaling, so protein/fat aren't independently optimised.
- **Curated food list, not NEVO** — a modest hand-authored dish set (see licensing note below), so it won't cover every food or brand.
- **Weather only applies to today** — the day strip computes other days without a heat bump (no historical/forecast weather wired in).
- **Single goal direction** — assumes fuelling to support training (no explicit cut/bulk surplus/deficit selector yet).
- **Garmin payload variance** — `fetch_profile()` is best-effort; some accounts return partial data, in which case the user fills the rest by hand.

## Verification

1. **No Garmin / manual**: open `/settings#fuel`, enter weight (e.g. 72), height 178, birth year 1990, sex male, save. Open `/fuel` — energy + macro card renders, hydration shows, and (on a long-run day) the "Fuel the run" block appears. Dashboard shows the "② Today · Fuel" tile.
2. **With Garmin**: click Import, confirm weight/height/sex/birth year pre-fill; save.
3. **Measured override**: on a day whose run is matched to a synced activity, confirm the energy line shows the "✓" measured marker.
4. **Meals**: with a profile set, `/fuel` shows four dishes with per-ingredient grams + macros. Switch `diet_pref` to vegan in Settings → dishes change to vegan; flip language to nl → Dutch dish + slot names. On a long-run day, the footer notes the during-run carbs are excluded from the meal pool.
5. **Edge**: clear the profile (fresh DB) → `/fuel` shows the empty state linking to Settings. No active plan → rest-day/maintenance targets, no "Fuel the run" block.
6. **Unit tests** (plain-assert scripts; no pytest dependency):
   - `tests/test_nutrition_engine.py` — BMR matches Mifflin-St Jeor; carb g/kg in-band per workout type; energy falls back to `run_kcal()` without Garmin.
   - `tests/test_meal_plan.py` — vegan never leaks animal dishes; during-run carbs excluded from the pool; assembled carbs track the pool; deterministic per date but rotates across days; scale clamps; locale picks Dutch names.

## Future improvements

1. **Swap alternatives** — a one-line "or swap for…" per meal, and/or a re-roll button to pick a different dish for a slot.
2. **Smarter assembly** — optimise protein/fat alongside carbs (not just carb-anchored scaling); add a second snack on very high-carb days so meals cover more of the target.
3. **Grow the dish library** — more variety, regional/seasonal options, brand items (AH/Jumbo).
4. **Goal direction** — maintain / lose / gain selector that shifts the energy target by a surplus/deficit.
5. **Weight tracking over time** — chart weight (Garmin `get_body_composition`) rather than a single static value.
6. **LLM layer** (optional) — explain the day's fuelling/meals in the coach voice, grounded in the computed numbers.

---

*Last updated: 2026-06-28 (Phase 2 — concrete meals)*
