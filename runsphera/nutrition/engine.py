"""Deterministic sports-nutrition rules — the rules-first core of Fuel.

Pure functions, no I/O. Everything keys off a body profile
(`{weight_kg, height_cm, birth_year, sex, ...}`) and the day's workout.
The feature must work with *zero* Garmin data, so each function degrades
gracefully: measured values (Garmin) are preferred when passed in, but we
always have a defensible estimate from the profile + the planned workout.

All thresholds live as named constants below so the prescriptions are
auditable. Sources are summarised in docs/nutrition-fueling.md; in short
they follow mainstream endurance guidance (ACSM / IOC consensus / Daniels):

  - BMR: Mifflin-St Jeor (1990).
  - Carbohydrate periodisation by training load: ~3–10 g/kg/day.
  - Protein for endurance athletes: ~1.4–1.8 g/kg/day.
  - Running energy cost: ~1 kcal per kg per km.
  - During-exercise carbs: 30–60 g/hr, up to ~90 g/hr for long/race efforts.
  - Fluid: ~35 ml/kg/day baseline + 400–800 ml/hr of running.
"""
from __future__ import annotations

from datetime import date

# ── Energy ──────────────────────────────────────────────────────────────
# Multiplier on BMR for non-exercise daily life (work, chores, NEAT). The
# run itself is added on top explicitly, so this stays at the "lightly
# active" end to avoid double-counting exercise.
NON_EXERCISE_ACTIVITY_FACTOR = 1.3
# Running's gross energy cost is famously close to 1 kcal per kg of body
# mass per km, near-independent of pace. The fallback when there's no
# measured (Garmin) calorie figure for the run.
RUN_KCAL_PER_KG_KM = 1.0

# ── Macros ──────────────────────────────────────────────────────────────
KCAL_PER_G_CARB = 4
KCAL_PER_G_PROTEIN = 4
KCAL_PER_G_FAT = 9
PROTEIN_G_PER_KG = 1.6          # mid of the 1.4–1.8 endurance range
FAT_FLOOR_G_PER_KG = 0.8        # don't drop fat below this for hormones/health

# Carbohydrate periodisation: grams per kg of body mass per day, as a
# (low, high) band keyed off the day's workout type. Higher load → more
# carbs. The headline number uses the band midpoint; the band is shown so
# the runner can flex within it.
CARB_G_PER_KG_BY_TYPE: dict[str, tuple[float, float]] = {
    "rest":      (3.0, 5.0),
    "cross":     (4.0, 6.0),
    "easy":      (5.0, 7.0),
    "tempo":     (6.0, 8.0),
    "intervals": (6.0, 8.0),
    "long":      (7.0, 10.0),
    "race":      (7.0, 10.0),
}
CARB_G_PER_KG_DEFAULT = (4.0, 6.0)   # maintenance when there's no plan

# Human-readable label per day type, for the macro card.
DAY_TYPE_LABEL: dict[str, str] = {
    "rest":      "rest / low-carb day",
    "cross":     "cross-training day",
    "easy":      "easy day",
    "tempo":     "quality day",
    "intervals": "quality day",
    "long":      "long-run / high-carb day",
    "race":      "race day",
}

# ── Around-the-run fuelling ─────────────────────────────────────────────
# Below this planned duration, no intra-run carbs are needed — glycogen
# covers it. Above it, the "fuel the run" block appears.
FUEL_THE_RUN_MIN_MINUTES = 75
CARB_PER_HR_STANDARD = (30, 60)   # g/hr for easy/moderate efforts > 75 min
CARB_PER_HR_HIGH = (60, 90)       # g/hr for long-run / race efforts
GEL_CARB_G = 25                   # a typical energy gel ≈ 25 g carbs
PRE_RUN_CARB_G_PER_KG = (1.0, 3.0)  # 2–3 h before a long/hard effort
POST_RUN_PROTEIN_G = (25, 30)       # recovery protein within 30–60 min
POST_RUN_CARB_G_PER_KG = 1.0        # recovery carbs alongside it

# ── Hydration ───────────────────────────────────────────────────────────
BASELINE_FLUID_ML_PER_KG = 35       # daily baseline, no exercise
# Sweat replacement per hour of running, by intensity. Real sweat rate
# varies hugely between people — these are defensible mid estimates.
RUN_FLUID_ML_PER_HR: dict[str, int] = {
    "easy":      500,
    "cross":     500,
    "tempo":     650,
    "intervals": 650,
    "long":      600,
    "race":      700,
}
RUN_FLUID_ML_PER_HR_DEFAULT = 550
# Warm-weather bump: above this temp, add this many ml per °C over it.
HEAT_THRESHOLD_C = 18
HEAT_FLUID_ML_PER_DEGREE = 40
# Default easy pace (s/km) used to estimate a run's duration when the plan
# row carries a distance but no target duration.
DEFAULT_PACE_S_PER_KM = 360


def _round_to(value: float, step: int) -> int:
    """Round to the nearest `step` — keeps headline numbers from looking
    falsely precise (2,847 kcal → 2,850)."""
    return int(round(value / step) * step)


def age_from_birth_year(birth_year: int | None, ref_year: int | None = None) -> int | None:
    if birth_year is None:
        return None
    ref_year = ref_year or date.today().year
    return ref_year - birth_year


def bmr(profile: dict, ref_year: int | None = None) -> float | None:
    """Basal metabolic rate via Mifflin-St Jeor. Needs weight, height,
    age and sex; returns None if any are missing (the service then falls
    back to Garmin's measured `bmr_kcal`)."""
    weight = profile.get("weight_kg")
    height = profile.get("height_cm")
    sex = profile.get("sex")
    age = age_from_birth_year(profile.get("birth_year"), ref_year)
    if not weight or not height or age is None or sex not in ("male", "female"):
        return None
    base = 10 * weight + 6.25 * height - 5 * age
    return base + (5 if sex == "male" else -161)


def run_minutes(workout: dict | None) -> float:
    """Best estimate of a run's duration in minutes: the planned duration
    if present, else distance × a default easy pace."""
    if not workout:
        return 0.0
    secs = workout.get("target_duration_s")
    if secs:
        return secs / 60.0
    km = workout.get("target_distance_km")
    if km:
        return (km * DEFAULT_PACE_S_PER_KM) / 60.0
    return 0.0


def run_kcal(distance_km: float | None, weight_kg: float) -> float:
    """Estimated running energy cost (~1 kcal/kg/km). Fallback only — a
    measured Garmin value is preferred when available."""
    if not distance_km:
        return 0.0
    return distance_km * weight_kg * RUN_KCAL_PER_KG_KM


def _day_type(workout: dict | None) -> str:
    if not workout:
        return "rest"
    wt = (workout.get("workout_type") or "rest").lower()
    return wt if wt in CARB_G_PER_KG_BY_TYPE else "rest"


def daily_targets(
    profile: dict,
    *,
    workout: dict | None = None,
    measured_run_kcal: float | None = None,
    garmin_bmr_kcal: float | None = None,
    ref_year: int | None = None,
) -> dict:
    """Daily energy + macro targets.

    energy = BMR × non-exercise factor + the run's calories, where the run
    figure prefers `measured_run_kcal` (Garmin) and falls back to the
    ~1 kcal/kg/km estimate from the planned distance. BMR prefers the
    Mifflin-St Jeor formula and falls back to Garmin's `bmr_kcal`.
    """
    weight = profile["weight_kg"]
    day_type = _day_type(workout)

    bmr_formula = bmr(profile, ref_year)
    if bmr_formula is not None:
        bmr_kcal, bmr_source = bmr_formula, "formula"
    elif garmin_bmr_kcal:
        bmr_kcal, bmr_source = float(garmin_bmr_kcal), "garmin"
    else:
        bmr_kcal, bmr_source = None, None

    daily_life_kcal = bmr_kcal * NON_EXERCISE_ACTIVITY_FACTOR if bmr_kcal else None

    if measured_run_kcal is not None:
        rk = float(measured_run_kcal)
    else:
        rk = run_kcal(workout.get("target_distance_km") if workout else None, weight)

    energy_kcal = (daily_life_kcal + rk) if daily_life_kcal is not None else None

    # Carbs by periodisation. Headline = band midpoint × weight.
    lo_pk, hi_pk = CARB_G_PER_KG_BY_TYPE.get(day_type, CARB_G_PER_KG_DEFAULT)
    carbs_g = ((lo_pk + hi_pk) / 2) * weight

    protein_g = PROTEIN_G_PER_KG * weight

    # Fat fills the energy gap after carbs + protein, but never below the
    # health floor. Only computable when we have an energy target.
    if energy_kcal is not None:
        gap_kcal = energy_kcal - (carbs_g * KCAL_PER_G_CARB + protein_g * KCAL_PER_G_PROTEIN)
        fat_g = max(gap_kcal / KCAL_PER_G_FAT, FAT_FLOOR_G_PER_KG * weight)
    else:
        fat_g = FAT_FLOOR_G_PER_KG * weight

    return {
        "weight_kg": weight,
        "day_type": day_type,
        "day_type_label": DAY_TYPE_LABEL.get(day_type, "maintenance"),
        "bmr_kcal": _round_to(bmr_kcal, 10) if bmr_kcal else None,
        "bmr_source": bmr_source,
        "daily_life_kcal": _round_to(daily_life_kcal, 10) if daily_life_kcal else None,
        "run_kcal": _round_to(rk, 10) if rk else 0,
        "run_kcal_measured": measured_run_kcal is not None,
        "energy_kcal": _round_to(energy_kcal, 10) if energy_kcal else None,
        "carbs_g": _round_to(carbs_g, 5),
        "carbs_g_per_kg_lo": lo_pk,
        "carbs_g_per_kg_hi": hi_pk,
        "protein_g": _round_to(protein_g, 5),
        "protein_g_per_kg": PROTEIN_G_PER_KG,
        "fat_g": _round_to(fat_g, 5),
        "fat_g_per_kg": round(fat_g / weight, 1),
    }


def fuel_the_run(profile: dict, workout: dict | None) -> dict | None:
    """Around-the-run fuelling for efforts long enough to need it
    (> ~75 min). Returns None for shorter runs / rest days."""
    if not workout or _day_type(workout) in ("rest", "cross"):
        return None
    minutes = run_minutes(workout)
    if minutes < FUEL_THE_RUN_MIN_MINUTES:
        return None

    weight = profile["weight_kg"]
    hours = minutes / 60.0
    day_type = _day_type(workout)
    hi_effort = day_type in ("long", "race")
    carb_lo, carb_hi = CARB_PER_HR_HIGH if hi_effort else CARB_PER_HR_STANDARD

    # Gel cadence from the band midpoint: at X g/hr and 25 g/gel, that's
    # X/25 gels per hour → 60/(X/25) minutes between gels.
    carb_mid = (carb_lo + carb_hi) / 2
    gel_interval_min = int(round(60 / (carb_mid / GEL_CARB_G)))

    pre_lo, pre_hi = PRE_RUN_CARB_G_PER_KG
    return {
        "minutes": int(round(minutes)),
        "before_carb_g_lo": _round_to(pre_lo * weight, 5),
        "before_carb_g_hi": _round_to(pre_hi * weight, 5),
        "during_carb_per_hr_lo": carb_lo,
        "during_carb_per_hr_hi": carb_hi,
        "during_total_carb_g": _round_to(carb_mid * hours, 5),
        "gel_interval_min": gel_interval_min,
        "during_fluid_ml_per_hr_lo": 400,
        "during_fluid_ml_per_hr_hi": 600 if not hi_effort else 750,
        "after_carb_g": _round_to(POST_RUN_CARB_G_PER_KG * weight, 5),
        "after_protein_g_lo": POST_RUN_PROTEIN_G[0],
        "after_protein_g_hi": POST_RUN_PROTEIN_G[1],
    }


def hydration(
    profile: dict,
    *,
    workout: dict | None = None,
    weather: dict | None = None,
) -> dict:
    """Daily fluid target: baseline by body mass + sweat replacement for
    the run + a warm-weather bump."""
    weight = profile["weight_kg"]
    baseline_ml = BASELINE_FLUID_ML_PER_KG * weight

    minutes = run_minutes(workout)
    day_type = _day_type(workout)
    rate = RUN_FLUID_ML_PER_HR.get(day_type, RUN_FLUID_ML_PER_HR_DEFAULT)
    run_ml = (minutes / 60.0) * rate

    heat_ml = 0.0
    temp_c = None
    if weather:
        temp_c = weather.get("current_temp_c")
        if temp_c is None:
            temp_c = weather.get("feels_like_c")
    if temp_c is not None and temp_c > HEAT_THRESHOLD_C:
        heat_ml = (temp_c - HEAT_THRESHOLD_C) * HEAT_FLUID_ML_PER_DEGREE

    total_ml = baseline_ml + run_ml + heat_ml
    return {
        "baseline_ml": _round_to(baseline_ml, 50),
        "run_ml": _round_to(run_ml, 50),
        "heat_ml": _round_to(heat_ml, 50),
        "total_ml": _round_to(total_ml, 50),
        "total_l": round(_round_to(total_ml, 50) / 1000, 1),
        "temp_c": temp_c,
    }
