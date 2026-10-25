"""Fuel service — assembles the inputs the nutrition engine needs from the
DB (body profile, the day's workout, weather, Garmin day metrics) and
returns ready-to-render dicts for the Fuel tab + dashboard tile.

Kept thin: all the actual nutrition *rules* live in `engine`; this module
only does data-gathering and shaping.
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from . import engine, meal_plan
from .. import settings as app_settings
from .. import weather as weather_service
from ..plans import service as plan_service


def _workout_for_date(conn: sqlite3.Connection, day_iso: str) -> dict | None:
    """The active plan's workout on `day_iso`, with the matched activity's
    calories when the run's been synced (so the energy target can use the
    measured burn instead of the estimate)."""
    row = conn.execute(
        """SELECT pw.*, a.calories AS actual_calories
           FROM plan_workouts pw
           JOIN plans p ON p.id = pw.plan_id
           LEFT JOIN activities a ON a.activity_id = pw.actual_activity_id
           WHERE p.status = 'active' AND pw.planned_date = ?
           ORDER BY pw.day_of_week LIMIT 1""",
        (day_iso,),
    ).fetchone()
    return dict(row) if row else None


def _garmin_day(conn: sqlite3.Connection, day_iso: str) -> dict | None:
    row = conn.execute(
        "SELECT bmr_kcal, active_kcal, total_kcal FROM daily_metrics "
        "WHERE calendar_date = ?",
        (day_iso,),
    ).fetchone()
    return dict(row) if row else None


def fuel_for_date(conn: sqlite3.Connection, day: date | None = None) -> dict | None:
    """Full fuel picture for a date: energy + macros, hydration, and the
    around-the-run block. Returns None when no body profile is set yet —
    callers render an empty state pointing at Settings.
    """
    profile = app_settings.get_body_profile(conn)
    if not profile:
        return None

    day = day or date.today()
    day_iso = day.isoformat()
    is_today = day == date.today()

    workout = _workout_for_date(conn, day_iso)
    garmin_day = _garmin_day(conn, day_iso)
    # Weather only meaningfully applies to today (the cache is "now").
    weather = weather_service.current_weather(conn) if is_today else None

    measured_run_kcal = workout.get("actual_calories") if workout else None
    garmin_bmr = garmin_day.get("bmr_kcal") if garmin_day else None

    targets = engine.daily_targets(
        profile,
        workout=workout,
        measured_run_kcal=measured_run_kcal,
        garmin_bmr_kcal=garmin_bmr,
    )
    hydration = engine.hydration(profile, workout=workout, weather=weather)
    fuel_run = engine.fuel_the_run(profile, workout)

    meals = meal_plan.build_day_meals(
        targets,
        fuel_run,
        diet_pref=profile.get("diet_pref"),
        day_ordinal=day.toordinal(),
        locale=app_settings.get_language(conn),
    )

    return {
        "date": day_iso,
        "is_today": is_today,
        "profile": profile,
        "workout": workout,
        "targets": targets,
        "hydration": hydration,
        "fuel_run": fuel_run,
        "meals": meals,
        "weather": weather,
    }


def fuel_day_strip(
    conn: sqlite3.Connection,
    profile: dict,
    start_day: date,
    *,
    selected_iso: str,
    ndays: int = 7,
) -> list[dict]:
    """A rolling `ndays`-day selector starting at `start_day` (today by
    default), each day carrying its workout + day-type so the Fuel tab can
    render a full-width strip. `selected_iso` marks which day is open."""
    today_iso = date.today().isoformat()
    out = []
    for i in range(ndays):
        d = start_day + timedelta(days=i)
        iso = d.isoformat()
        workout = _workout_for_date(conn, iso)
        targets = engine.daily_targets(profile, workout=workout)
        out.append({
            "date": iso,
            "weekday": d.weekday(),          # 0=Mon … 6=Sun
            "day_num": d.day,
            "workout_type": (workout or {}).get("workout_type") or "rest",
            "day_type": targets["day_type"],
            "day_type_label": targets["day_type_label"],
            "distance_km": (workout or {}).get("target_distance_km"),
            "carbs_g": targets["carbs_g"],
            "is_today": iso == today_iso,
            "is_selected": iso == selected_iso,
        })
    return out


def weekly_fuel_strip(conn: sqlite3.Connection, profile: dict, ref_day: date) -> dict | None:
    """The active plan's week containing `ref_day`, as a 7-bar carb-load
    sparkline. Each bar's height is the day's carb target relative to the
    week's max. Returns None when there's no active plan."""
    plan = plan_service.get_active_plan(conn)
    if not plan:
        return None
    weeks = plan_service.get_plan_weeks(conn, plan["id"])
    if not weeks:
        return None

    ref_iso = ref_day.isoformat()
    # Pick the week whose dates bracket ref_day; else the latest week that
    # has already started; else the first week.
    chosen = None
    for w in weeks:
        dates = [x["planned_date"] for x in w["workouts"]]
        if dates and min(dates) <= ref_iso <= max(dates):
            chosen = w
            break
    if chosen is None:
        started = [w for w in weeks if w["week_start"] <= ref_iso]
        chosen = started[-1] if started else weeks[0]

    bars = []
    max_carbs = 1
    for wk in chosen["workouts"]:
        t = engine.daily_targets(profile, workout=wk)
        carbs = t["carbs_g"] or 0
        max_carbs = max(max_carbs, carbs)
        bars.append({
            "day_of_week": wk["day_of_week"],
            "planned_date": wk["planned_date"],
            "workout_type": wk["workout_type"],
            "carbs_g": carbs,
            "is_today": wk["planned_date"] == date.today().isoformat(),
        })
    bars.sort(key=lambda b: b["day_of_week"])
    for b in bars:
        b["height_pct"] = int(round(100 * b["carbs_g"] / max_carbs)) if max_carbs else 0

    return {
        "plan_title": plan.get("title"),
        "week_number": chosen["week_number"],
        "week_phase": chosen["week_phase"],
        "total_weeks": len(weeks),
        "bars": bars,
    }
