"""Assemble the runner-context dicts that `prompts.py` consumes.

Two builders, one per cache layer:
  - build_profile_context(conn): slowly-changing (name, VDOT, plan, last 7 days,
    last 5 diary entries). Cacheable per session.
  - build_request_context(conn, recommendation, todays_workout): today's specific
    state (planned workout, readiness, ACWR, rules decision). Per-request.

The profile builder caps lists tight on purpose — prompt caching only helps if
the block is byte-identical across calls within a session, and a 50-row diary
list would blow the cache budget every time a new entry lands.
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from typing import Any

from .. import diary, settings, weather as weather_service
from ..analytics import fmt_pace
from ..plans import service as plan_service
from ..plans.methodology import GOAL_LABELS


def _current_vdot(conn: sqlite3.Connection) -> float | None:
    row = conn.execute(
        "SELECT vo2max_precise FROM training_status "
        "WHERE vo2max_precise IS NOT NULL ORDER BY calendar_date DESC LIMIT 1"
    ).fetchone()
    if row:
        return float(row["vo2max_precise"])
    # Garmin-less runners: fall back to the manually-entered baseline
    # (race-result-derived VDOT) so the coach still knows their level.
    from .. import settings as app_settings
    manual = app_settings.get_fitness_baseline(conn)["vdot"]
    return float(manual) if manual else None


def _weekly_km_baseline(conn: sqlite3.Connection) -> float | None:
    """Mean weekly running km over the last 4 complete weeks. None if no runs."""
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    window_start = (monday - timedelta(weeks=4)).isoformat()
    window_end = monday.isoformat()
    row = conn.execute(
        """SELECT COALESCE(SUM(distance_m), 0) / 1000.0 / 4.0 AS avg_km,
                  COUNT(*) AS n
           FROM activities
           WHERE activity_type = 'running'
             AND date(start_time_local) >= ?
             AND date(start_time_local) <  ?""",
        (window_start, window_end),
    ).fetchone()
    if not row or not row["n"]:
        return None
    return float(row["avg_km"] or 0)


def _recent_runs_for_llm(conn: sqlite3.Connection, days: int = 7) -> list[dict[str, Any]]:
    """Last N days of runs with the fields prompts.profile_block expects."""
    since = (date.today() - timedelta(days=days)).isoformat()
    rows = conn.execute(
        """SELECT activity_id, activity_name, start_time_local,
                  distance_m, duration_s, avg_hr, garmin_feel, garmin_rpe
           FROM activities
           WHERE activity_type = 'running'
             AND date(start_time_local) >= ?
           ORDER BY start_time_gmt DESC""",
        (since,),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        km = (r["distance_m"] or 0) / 1000.0
        dur_s = r["duration_s"] or 0
        pace = (dur_s / 60.0) / km if km > 0 else None
        out.append({
            "date": r["start_time_local"][:10],
            "name": r["activity_name"] or "",
            "km": km,
            "pace": fmt_pace(pace) if pace else None,
            "avg_hr": r["avg_hr"],
            "garmin_feel_label": diary.garmin_feel_label(r["garmin_feel"]),
            "garmin_rpe_label": diary.garmin_rpe_label(r["garmin_rpe"]),
        })
    return out


def _diary_link_descriptor(entry: dict) -> str | None:
    """Short string describing what a diary entry is linked to."""
    if entry.get("linked_workout_title"):
        return entry["linked_workout_title"]
    name = entry.get("linked_activity_name")
    start = entry.get("linked_activity_start")
    if name and start:
        return f"{name} ({start[:10]})"
    if name:
        return name
    return None


def _recent_diary_for_llm(conn: sqlite3.Connection, n: int = 5) -> list[dict[str, Any]]:
    entries = diary.list_entries(conn, limit=n)
    out: list[dict[str, Any]] = []
    for e in entries:
        out.append({
            "entry_date": e["entry_date"],
            "mood_label": diary.mood_label(e.get("mood")),
            "linked": _diary_link_descriptor(e),
            "body": e["body"],
        })
    return out


def _days_to_race(plan: dict | None) -> int | None:
    if not plan or not plan.get("race_date"):
        return None
    try:
        race = datetime.strptime(plan["race_date"][:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None
    return (race - date.today()).days


def _decorate_plan(plan: dict | None) -> dict | None:
    """Add human-readable labels onto the raw plan row."""
    if not plan:
        return None
    return {
        "title": plan.get("title"),
        "goal_label": GOAL_LABELS.get(plan.get("goal_type", ""), plan.get("goal_type")),
        "methodology_name": plan_service._methodology_label(plan["methodology"]),
        "race_date": plan.get("race_date"),
    }


def _latest_readiness(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        "SELECT score, level, feedback_short FROM training_readiness "
        "ORDER BY timestamp DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def _latest_training_status(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        "SELECT acwr_ratio, acwr_status FROM training_status "
        "ORDER BY calendar_date DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def build_profile_context(conn: sqlite3.Connection) -> dict[str, Any]:
    """Kwargs for prompts.profile_block(). Stable across the day — cacheable."""
    plan = plan_service.get_active_plan(conn)
    baseline = _weekly_km_baseline(conn)
    # Body / wellbeing block — active issues + recent resolved + 90-day
    # heatmap top zones, pre-rendered to a single string for direct splice
    # into the cached prompt. Returns None on a clean bill of health so we
    # don't burn tokens on "no issues". Gated on the Settings opt-out
    # toggle (default ON): when off, the body block never reaches the LLM
    # even when issues exist.
    try:
        if settings.get_include_body_in_llm(conn):
            from .. import body as body_service
            body_block = body_service.context_for_llm(conn)
        else:
            body_block = None
    except Exception:  # noqa: BLE001 — never break the coach over an optional extra
        body_block = None
    return {
        "first_name": settings.garmin_first_name(conn),
        "about_you": settings.get_about_you(conn),
        "vdot": _current_vdot(conn),
        "baseline_km": baseline,
        "plan": _decorate_plan(plan),
        "days_to_race": _days_to_race(plan),
        "recent_runs": _recent_runs_for_llm(conn),
        "recent_diary": _recent_diary_for_llm(conn),
        "body_block": body_block,
    }


def build_request_context(
    conn: sqlite3.Connection,
    recommendation: dict[str, Any] | None,
    todays_workout: dict[str, Any] | None,
) -> dict[str, Any]:
    """Kwargs for prompts.request_block(). Per-request — not cached.

    When today's workout has already been matched to a completed activity,
    pull the actual stats so the coach can comment on the run that
    just happened rather than prescribing one that's done."""
    completed_today: dict | None = None
    completed_segments: list[dict] | None = None
    completed_active_block: dict | None = None
    if todays_workout and todays_workout.get("actual_activity_id"):
        aid = todays_workout["actual_activity_id"]
        row = conn.execute(
            "SELECT distance_m, duration_s, avg_hr, max_hr, training_load, "
            "       activity_name, start_time_local, "
            "       hr_zone_1_s, hr_zone_2_s, hr_zone_3_s, hr_zone_4_s, hr_zone_5_s "
            "FROM activities WHERE activity_id = ?",
            (aid,),
        ).fetchone()
        if row:
            completed_today = dict(row)
            # Same lap segmentation we feed into the per-activity reaction —
            # lets the daily coach line judge the active block against target
            # pace instead of warmup-dragged total-run average.
            from .. import laps as laps_module
            completed_segments = laps_module.group_segments(laps_module.get_laps(conn, aid))
            completed_active_block = laps_module.active_block_summary(conn, aid)

    # Optional strength session scheduled today (rest-day bodyweight work).
    # Lets the coach acknowledge it ("strength day — keep the legs fresh") and
    # react once it's done. None when no plan / strength off / plain rest day.
    todays_strength: dict | None = None
    try:
        from ..strength import service as _strength_service
        todays_strength = _strength_service.todays_strength_session(conn)
    except Exception:  # noqa: BLE001 — never break the coach over an optional extra
        todays_strength = None

    return {
        "today_iso": date.today().isoformat(),
        "todays_workout": todays_workout,
        "todays_strength": todays_strength,
        "completed_today": completed_today,
        "completed_segments": completed_segments,
        "completed_active_block": completed_active_block,
        "recommendation": recommendation,
        "readiness": _latest_readiness(conn),
        "training_status": _latest_training_status(conn),
        "weather": weather_service.current_weather(conn),
    }


def target_recap_week(today: date | None = None) -> tuple[date, date, str]:
    """Pick the most-recently-COMPLETED Mon–Sun week as of `today`.

    Returns (mon, sun, week_key). Today's in-progress day is never part of
    the recap window — so on Sunday the recap still covers the previous
    Mon–Sun. Simple rule, no time-of-day fiddling.
    """
    today = today or date.today()
    # weekday(): Mon=0..Sun=6. Days back to the most-recent past Sunday.
    last_sun = today - timedelta(days=today.weekday() + 1)
    last_mon = last_sun - timedelta(days=6)
    iso_year, iso_week, _ = last_mon.isocalendar()
    return last_mon, last_sun, f"{iso_year}-W{iso_week:02d}"


def build_weekly_recap_context(
    conn: sqlite3.Connection,
    today: date | None = None,
) -> dict[str, Any] | None:
    """Kwargs for prompts.weekly_recap_request_block(). Pulls the full picture
    of the most-recently-completed Mon–Sun week, plus a peek at the upcoming
    week for forward setup. Returns None when there's nothing to talk about
    (no active plan, no runs, no diary in the window)."""
    mon, sun, week_key = target_recap_week(today)
    next_mon = sun + timedelta(days=1)
    next_sun = next_mon + timedelta(days=6)
    week_label = f"Mon {mon.strftime('%d %b')} – Sun {sun.strftime('%d %b %Y')}"

    # Planned workouts inside the window.
    planned = conn.execute(
        """SELECT pw.planned_date, pw.workout_type, pw.title,
                  pw.target_distance_km, pw.target_pace_s_per_km,
                  pw.actual_activity_id, pw.id AS pw_id
           FROM plan_workouts pw
           JOIN plans p ON p.id = pw.plan_id
           WHERE p.status = 'active'
             AND pw.planned_date >= ? AND pw.planned_date <= ?
           ORDER BY pw.planned_date""",
        (mon.isoformat(), sun.isoformat()),
    ).fetchall()
    planned_list = [dict(r) for r in planned]

    # Adherence counts (matches conventions in plan_service.week_adherence).
    qual_planned = sum(1 for p in planned_list if p["workout_type"] not in ("rest", "cross"))
    done = sum(
        1 for p in planned_list
        if p["workout_type"] not in ("rest", "cross") and p["actual_activity_id"]
    )
    missed = sum(
        1 for p in planned_list
        if p["workout_type"] not in ("rest", "cross")
        and not p["actual_activity_id"]
        and p["planned_date"] < date.today().isoformat()
    )
    adherence = {"planned": qual_planned, "done": done, "missed": missed}

    # Actual completed running activities in the window.
    actuals = conn.execute(
        """SELECT a.activity_id, a.activity_name, a.start_time_local,
                  a.distance_m, a.duration_s, a.avg_hr, a.training_load,
                  a.aerobic_te, a.anaerobic_te, a.elevation_gain_m,
                  pw.title AS matched_plan_title
           FROM activities a
           LEFT JOIN plan_workouts pw ON pw.actual_activity_id = a.activity_id
           WHERE a.activity_type = 'running'
             AND date(a.start_time_local) >= ? AND date(a.start_time_local) <= ?
           ORDER BY a.start_time_gmt""",
        (mon.isoformat(), sun.isoformat()),
    ).fetchall()
    actual_list = [dict(r) for r in actuals]

    weekly_total_km = sum((a.get("distance_m") or 0) for a in actual_list) / 1000.0
    weekly_total_duration_s = sum((a.get("duration_s") or 0) for a in actual_list)
    weekly_total_tl = sum((a.get("training_load") or 0) for a in actual_list) or None

    # Standout effort: highest training load (with distance as tiebreaker).
    standout = None
    if actual_list:
        standout = max(
            actual_list,
            key=lambda a: (a.get("training_load") or 0, a.get("distance_m") or 0),
        )

    # Diary entries inside the window (any: freestanding, activity-linked, etc.).
    diary_rows = conn.execute(
        """SELECT de.*,
                  a.activity_name        AS linked_activity_name,
                  pw.title               AS linked_workout_title
           FROM diary_entries de
           LEFT JOIN activities a    ON a.activity_id = de.activity_id
           LEFT JOIN plan_workouts pw ON pw.id = de.plan_workout_id
           WHERE de.entry_date >= ? AND de.entry_date <= ?
           ORDER BY de.entry_date""",
        (mon.isoformat(), sun.isoformat()),
    ).fetchall()
    diary_list: list[dict] = []
    for r in diary_rows:
        d = dict(r)
        d["mood_label"] = diary.mood_label(d.get("mood"))
        linked = d.get("linked_workout_title") or d.get("linked_activity_name")
        d["linked"] = linked
        diary_list.append(d)

    # End-of-week training status — pick the row whose calendar_date is on or
    # before the Sunday, latest first.
    ts_row = conn.execute(
        "SELECT acwr_ratio, acwr_status FROM training_status "
        "WHERE calendar_date <= ? ORDER BY calendar_date DESC LIMIT 1",
        (sun.isoformat(),),
    ).fetchone()
    end_ts = dict(ts_row) if ts_row else None

    # Next week's plan (forward setup).
    next_planned = conn.execute(
        """SELECT pw.planned_date, pw.workout_type, pw.title,
                  pw.target_distance_km
           FROM plan_workouts pw
           JOIN plans p ON p.id = pw.plan_id
           WHERE p.status = 'active'
             AND pw.planned_date >= ? AND pw.planned_date <= ?
           ORDER BY pw.planned_date""",
        (next_mon.isoformat(), next_sun.isoformat()),
    ).fetchall()
    next_planned_list = [dict(r) for r in next_planned]

    # Nothing to talk about: no plan in the window AND no activities AND no diary.
    if not planned_list and not actual_list and not diary_list:
        return None

    return {
        "week_label": week_label,
        "week_start_iso": mon.isoformat(),
        "week_end_iso": sun.isoformat(),
        "planned_workouts": planned_list,
        "actual_activities": actual_list,
        "adherence": adherence,
        "diary_entries": diary_list,
        "weekly_total_km": weekly_total_km,
        "weekly_total_duration_s": weekly_total_duration_s,
        "weekly_total_training_load": weekly_total_tl,
        "standout_run": standout,
        "end_of_week_training_status": end_ts,
        "next_week_planned": next_planned_list,
    }


def build_run_reaction_context(
    conn: sqlite3.Connection,
    activity_id: int,
) -> dict[str, Any] | None:
    """Kwargs for prompts.run_reaction_request_block(). Per-activity — not cached.

    Returns None when the activity doesn't exist."""
    row = conn.execute(
        "SELECT * FROM activities WHERE activity_id = ?", (activity_id,)
    ).fetchone()
    if not row:
        return None
    activity = dict(row)

    # Matched planned workout (if the activity-matcher tied it to one).
    planned = conn.execute(
        "SELECT * FROM plan_workouts WHERE actual_activity_id = ? LIMIT 1",
        (activity_id,),
    ).fetchone()
    planned_dict = dict(planned) if planned else None

    # Diary entry tied to this specific activity.
    diary_row = conn.execute(
        "SELECT * FROM diary_entries WHERE activity_id = ? ORDER BY updated_at DESC LIMIT 1",
        (activity_id,),
    ).fetchone()
    diary_dict: dict | None = None
    if diary_row:
        d = dict(diary_row)
        d["mood_label"] = diary.mood_label(d.get("mood"))
        diary_dict = d

    # Lap segmentation — pulled from activity_laps if present. For structured
    # workouts (tempo / intervals) this yields a separate stat block for the
    # warmup, active, cooldown phases so the LLM can judge the active block
    # against the target pace instead of the warmup-dragged total average.
    from .. import laps as laps_module
    segments = laps_module.group_segments(laps_module.get_laps(conn, activity_id))
    active_block = laps_module.active_block_summary(conn, activity_id)

    return {
        "activity": activity,
        "planned_workout": planned_dict,
        "diary": diary_dict,
        "feel_label": diary.garmin_feel_label(activity.get("garmin_feel")),
        "rpe_label":  diary.garmin_rpe_label(activity.get("garmin_rpe")),
        "segments": segments,
        "active_block": active_block,
    }
