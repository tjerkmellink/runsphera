"""Lock-down tests for the Fuel nutrition engine.

The engine is the rules-first core: BMR, daily energy + macros, hydration
and around-the-run fuelling, all deterministic. These tests pin the
formulas (Mifflin-St Jeor, carb periodisation, the ~1 kcal/kg/km running
cost) and the Garmin-optional degradation path so they can't drift.

Run from the repo root:
    .venv/Scripts/python.exe -m pytest tests/test_nutrition_engine.py
    .venv/Scripts/python.exe tests/test_nutrition_engine.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make `running_coach` importable when running this script directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from running_coach.nutrition import engine  # noqa: E402


# A known runner used across cases. Age is computed against a fixed
# ref_year so the test doesn't drift as real calendar years pass.
PROFILE = {"weight_kg": 72.0, "height_cm": 178.0, "birth_year": 1990, "sex": "male"}
REF_YEAR = 2025  # → age 35


def test_bmr_matches_mifflin_st_jeor_male() -> None:
    # 10*72 + 6.25*178 - 5*35 + 5 = 720 + 1112.5 - 175 + 5 = 1662.5
    assert engine.bmr(PROFILE, ref_year=REF_YEAR) == 1662.5


def test_bmr_matches_mifflin_st_jeor_female() -> None:
    fem = {**PROFILE, "sex": "female"}
    # ...same base, female constant -161: 1662.5 - 5 - 161 = 1496.5
    assert engine.bmr(fem, ref_year=REF_YEAR) == 1496.5


def test_bmr_none_when_inputs_missing() -> None:
    assert engine.bmr({"weight_kg": 72.0}) is None
    assert engine.bmr({**PROFILE, "sex": None}) is None


def test_run_kcal_is_one_per_kg_per_km() -> None:
    # 18 km * 72 kg * 1.0 = 1296
    assert engine.run_kcal(18.0, 72.0) == 1296.0
    assert engine.run_kcal(None, 72.0) == 0.0


def test_carbs_periodise_by_workout_type() -> None:
    """Carb g/kg band must rise with training load and the headline grams
    must fall inside band × weight."""
    weight = PROFILE["weight_kg"]
    for wtype, (lo, hi) in engine.CARB_G_PER_KG_BY_TYPE.items():
        t = engine.daily_targets(PROFILE, workout={"workout_type": wtype}, ref_year=REF_YEAR)
        assert t["carbs_g_per_kg_lo"] == lo and t["carbs_g_per_kg_hi"] == hi
        # headline grams within [lo*weight, hi*weight] (allow rounding to 5)
        assert lo * weight - 5 <= t["carbs_g"] <= hi * weight + 5, wtype
    # ordering: a long day prescribes more carbs than a rest day
    rest = engine.daily_targets(PROFILE, workout={"workout_type": "rest"}, ref_year=REF_YEAR)
    long = engine.daily_targets(PROFILE, workout={"workout_type": "long"}, ref_year=REF_YEAR)
    assert long["carbs_g"] > rest["carbs_g"]


def test_protein_is_1_6_per_kg() -> None:
    t = engine.daily_targets(PROFILE, workout={"workout_type": "easy"}, ref_year=REF_YEAR)
    # 1.6 * 72 = 115.2 → rounds to nearest 5 = 115
    assert t["protein_g"] == 115
    assert t["protein_g_per_kg"] == 1.6


def test_energy_uses_formula_bmr_and_estimated_run() -> None:
    workout = {"workout_type": "long", "target_distance_km": 18.0}
    t = engine.daily_targets(PROFILE, workout=workout, ref_year=REF_YEAR)
    # daily life = round(1662.5 * 1.3)=2161 → rounded to 10 = 2160
    # run = 18*72 = 1296 → 1300; energy = 2160+1300 region, rounded to 10
    assert t["bmr_source"] == "formula"
    assert t["run_kcal_measured"] is False
    assert t["run_kcal"] == 1300  # 1296 rounded to nearest 10
    assert t["energy_kcal"] is not None and t["energy_kcal"] > t["daily_life_kcal"]


def test_energy_prefers_measured_run_kcal() -> None:
    workout = {"workout_type": "long", "target_distance_km": 18.0}
    t = engine.daily_targets(
        PROFILE, workout=workout, measured_run_kcal=950, ref_year=REF_YEAR
    )
    assert t["run_kcal_measured"] is True
    assert t["run_kcal"] == 950


def test_energy_falls_back_to_garmin_bmr_without_formula() -> None:
    """No height/age/sex → BMR formula impossible → use Garmin's bmr_kcal."""
    sparse = {"weight_kg": 72.0}
    t = engine.daily_targets(
        sparse, workout={"workout_type": "easy", "target_distance_km": 8.0},
        garmin_bmr_kcal=1700,
    )
    assert t["bmr_source"] == "garmin"
    assert t["energy_kcal"] is not None
    # carbs/protein still personalise by weight even without BMR inputs
    assert t["carbs_g"] > 0 and t["protein_g"] > 0


def test_energy_none_when_no_bmr_available() -> None:
    sparse = {"weight_kg": 72.0}
    t = engine.daily_targets(sparse, workout={"workout_type": "easy"})
    assert t["bmr_source"] is None
    assert t["energy_kcal"] is None
    # but macros that only need weight are still present
    assert t["carbs_g"] > 0 and t["protein_g"] > 0 and t["fat_g"] > 0


def test_fuel_the_run_only_for_long_efforts() -> None:
    # 40-min easy run → no intra-run fuelling
    short = engine.fuel_the_run(PROFILE, {"workout_type": "easy", "target_duration_s": 40 * 60})
    assert short is None
    # 110-min long run → fuelling block with high-carb band + gel cadence
    long = engine.fuel_the_run(PROFILE, {"workout_type": "long", "target_duration_s": 110 * 60})
    assert long is not None
    assert (long["during_carb_per_hr_lo"], long["during_carb_per_hr_hi"]) == engine.CARB_PER_HR_HIGH
    assert long["gel_interval_min"] > 0
    # rest day never fuels
    assert engine.fuel_the_run(PROFILE, {"workout_type": "rest"}) is None


def test_fuel_the_run_estimates_duration_from_distance() -> None:
    # No target_duration_s but 20 km → ~120 min at default pace → fuels
    out = engine.fuel_the_run(PROFILE, {"workout_type": "long", "target_distance_km": 20.0})
    assert out is not None and out["minutes"] >= engine.FUEL_THE_RUN_MIN_MINUTES


def test_hydration_baseline_plus_run_plus_heat() -> None:
    # Rest day, no weather: baseline only = 35 * 72 = 2520 → rounds to 2500
    rest = engine.hydration(PROFILE, workout={"workout_type": "rest"})
    assert rest["run_ml"] == 0 and rest["heat_ml"] == 0
    assert rest["baseline_ml"] == 2500

    # Long run + warm day adds run + heat
    hot = engine.hydration(
        PROFILE,
        workout={"workout_type": "long", "target_duration_s": 90 * 60},
        weather={"current_temp_c": 28},
    )
    assert hot["run_ml"] > 0
    assert hot["heat_ml"] > 0  # 28 > 18 threshold
    assert hot["total_l"] > rest["total_l"]


# ── plain-assert runner (mirrors the other test modules) ────────────────
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
