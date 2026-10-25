"""Race-readiness score for the A-race countdown card.

Blends five signals into a 0-100 number telling the runner whether
their build-up is on track. Visible on the dashboard countdown card
when an active plan has a linked race; hidden in the first 14 days
of a plan (not enough data to score honestly) and in the recap phase.

Each component caps at its own ceiling; the total is the sum:

  plan adherence       (0-40)  — % of recent quality sessions completed
  recent quality work  (0-20)  — at least 1 quality session / wk for 3 wks
  VDOT trend           (0-15)  — improving / flat / declining over 4 wks
  ACWR sweet spot      (0-15)  — in the 0.8-1.5 corridor (full points)
  long-run base        (0-10)  — longest recent long-run, judged against
                                 what the plan asked for lately AND what
                                 the race itself demands (see below)

The math is intentionally simple — every component is a linear or
piecewise-linear interpolation off a single source-of-truth table
already in the DB (`plan_workouts`, `activities`, `training_status`).
No re-implementation of plan logic; we're just SUMMARIZING.

Every component helper returns a small dict — `pts`, its `max`, the raw
numbers behind it, and `estimated` (True when the DB couldn't answer and
we fell back to half points). That dict is what the "where does this
number come from?" panel on the countdown card renders, so the score and
its explanation can never drift apart.
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from typing import Any


# Workout types that count as "quality" — the work that actually
# stresses the system. Easy runs maintain volume; quality drives
# adaptation. Race-readiness is mostly about quality adherence.
_QUALITY_TYPES = ("tempo", "intervals", "long", "race")

# How far back each component looks.
_ADHERENCE_WEEKS = 4
_QUALITY_WEEKS  = 3
_VDOT_WEEKS     = 4
_LONGRUN_WEEKS  = 6

# Per-component ceilings. Single source of truth: the scorer interpolates
# against them and the breakdown panel prints them as the "/ 40" denominator,
# so re-weighting a component never leaves the explainer lying.
_MAX_ADHERENCE = 40.0
_MAX_QUALITY   = 20.0
_MAX_VDOT      = 15.0
_MAX_ACWR      = 15.0
_MAX_LONGRUN   = 10.0

# Quality sessions in the recency window that earn full marks.
_QUALITY_TARGET = 3

# Long-run ramps start at this fraction of their target: at or below it the
# component scores 0, at the target it scores full marks, linear between.
# 60 % of a marathon's 30 km long run is 18 km — far enough short that the
# runner is genuinely not there yet, so the distinction between 12 km and
# 16 km isn't worth points.
_LONGRUN_FLOOR_FRACTION = 0.6

# Score bands → headline verdict shown next to the bar.
_BAND_THRESHOLDS = (
    (75, "on_track"),
    (55, "building"),
    (0,  "behind"),
)

# Minimum plan age before we score (otherwise nothing meaningful to
# measure — runner will see a "?" badge instead).
_MIN_PLAN_AGE_DAYS = 14


def _band_for(score: int) -> str:
    for threshold, label in _BAND_THRESHOLDS:
        if score >= threshold:
            return label
    return "behind"


def _adherence_pts(
    conn: sqlite3.Connection, plan_id: int, today: date
) -> dict[str, Any]:
    """0-40 points. % of due quality workouts in the last 4 weeks that
    have a matched activity attached. Carries `done` / `due` so the
    breakdown panel can say "8 of 10 sessions done"."""
    cutoff = (today - timedelta(weeks=_ADHERENCE_WEEKS)).isoformat()
    today_iso = today.isoformat()
    placeholders = ",".join("?" * len(_QUALITY_TYPES))
    row = conn.execute(
        f"""SELECT
              SUM(CASE WHEN actual_activity_id IS NOT NULL THEN 1 ELSE 0 END) AS done,
              COUNT(*) AS due
            FROM plan_workouts
            WHERE plan_id = ?
              AND planned_date >= ?
              AND planned_date <  ?
              AND workout_type IN ({placeholders})""",
        (plan_id, cutoff, today_iso, *_QUALITY_TYPES),
    ).fetchone()
    done = int(row["done"] or 0)
    due  = int(row["due"]  or 0)
    if due == 0:
        # No quality work scheduled in window — neutral score, lean lower
        # since we can't verify the runner is on top of things.
        return {"pts": _MAX_ADHERENCE / 2, "max": _MAX_ADHERENCE,
                "done": done, "due": due, "weeks": _ADHERENCE_WEEKS,
                "estimated": True}
    return {"pts": (done / due) * _MAX_ADHERENCE, "max": _MAX_ADHERENCE,
            "done": done, "due": due, "weeks": _ADHERENCE_WEEKS,
            "estimated": False}


def _quality_recency_pts(
    conn: sqlite3.Connection, today: date
) -> dict[str, Any]:
    """0-20 points. Did the runner DO quality work recently? Counts
    completed quality activities (not just planned) in the last 3
    weeks. Target: 3 quality sessions = full points."""
    cutoff = (today - timedelta(weeks=_QUALITY_WEEKS)).isoformat()
    placeholders = ",".join("?" * len(_QUALITY_TYPES))
    row = conn.execute(
        f"""SELECT COUNT(DISTINCT pw.id) AS n
            FROM plan_workouts pw
            WHERE pw.actual_activity_id IS NOT NULL
              AND pw.planned_date >= ?
              AND pw.workout_type IN ({placeholders})""",
        (cutoff, *_QUALITY_TYPES),
    ).fetchone()
    n = int(row["n"] or 0)
    return {"pts": min(n / float(_QUALITY_TARGET), 1.0) * _MAX_QUALITY,
            "max": _MAX_QUALITY, "n": n, "target": _QUALITY_TARGET,
            "weeks": _QUALITY_WEEKS, "estimated": False}


def _vdot_trend_pts(conn: sqlite3.Connection, today: date) -> dict[str, Any]:
    """0-15 points. Compare today's VDOT vs 4 weeks ago. +1 VDOT or
    more → full points. 0 → neutral (10). -2 or worse → 0."""
    today_iso = today.isoformat()
    past  = (today - timedelta(weeks=_VDOT_WEEKS)).isoformat()
    row_now = conn.execute(
        "SELECT vo2max_precise FROM training_status WHERE vo2max_precise IS NOT NULL "
        "AND calendar_date <= ? ORDER BY calendar_date DESC LIMIT 1", (today_iso,),
    ).fetchone()
    row_past = conn.execute(
        "SELECT vo2max_precise FROM training_status WHERE vo2max_precise IS NOT NULL "
        "AND calendar_date <= ? ORDER BY calendar_date DESC LIMIT 1", (past,),
    ).fetchone()
    if not row_now or not row_past:
        # Half points when we don't have history yet.
        return {"pts": _MAX_VDOT / 2, "max": _MAX_VDOT, "delta": None,
                "weeks": _VDOT_WEEKS, "estimated": True}
    delta = float(row_now["vo2max_precise"]) - float(row_past["vo2max_precise"])
    if delta >= 1.0:
        pts = 15.0
    elif delta >= 0.0:
        # 0 → 10, +1 → 15 (linear)
        pts = 10.0 + 5.0 * delta
    elif delta >= -2.0:
        # 0 → 10, -2 → 0 (linear)
        pts = max(0.0, 10.0 + 5.0 * delta)
    else:
        pts = 0.0
    return {"pts": pts, "max": _MAX_VDOT, "delta": delta,
            "weeks": _VDOT_WEEKS, "estimated": False}


def _acwr_band_pts(conn: sqlite3.Connection) -> dict[str, Any]:
    """0-15 points. Today's ACWR ratio:
      0.8 ≤ ratio ≤ 1.5 → full points (sweet spot)
      below 0.8         → linear down to 0 at ratio=0
      above 1.5         → linear down to 0 at ratio=2.5
    """
    row = conn.execute(
        "SELECT acwr_ratio FROM training_status WHERE acwr_ratio IS NOT NULL "
        "ORDER BY calendar_date DESC LIMIT 1"
    ).fetchone()
    if not row or row["acwr_ratio"] is None:
        # Half points without data.
        return {"pts": _MAX_ACWR / 2, "max": _MAX_ACWR, "ratio": None,
                "estimated": True}
    ratio = float(row["acwr_ratio"])
    if 0.8 <= ratio <= 1.5:
        pts = 15.0
    elif ratio < 0.8:
        pts = max(0.0, 15.0 * (ratio / 0.8))
    else:  # ratio > 1.5
        pts = max(0.0, 15.0 * (1.0 - (ratio - 1.5) / 1.0))
    return {"pts": pts, "max": _MAX_ACWR, "ratio": ratio, "estimated": False}


def _longrun_ramp(longest_km: float, target_km: float) -> float:
    """0-10 points on a linear ramp from `_LONGRUN_FLOOR_FRACTION` of the
    target (0 pts) up to the target itself (full pts)."""
    if target_km <= 0:
        return 0.0
    floor_km = _LONGRUN_FLOOR_FRACTION * target_km
    if longest_km >= target_km:
        return _MAX_LONGRUN
    if longest_km <= floor_km:
        return 0.0
    return _MAX_LONGRUN * (longest_km - floor_km) / (target_km - floor_km)


def _plan_progress(
    conn: sqlite3.Connection, plan_id: int, today: date, race_day: date
) -> float:
    """How far through the plan we are, 0.0 at the first workout → 1.0 on
    race day. Falls back to 1.0 (judge purely on race-day terms) when the
    plan has no workouts or the dates don't make sense."""
    row = conn.execute(
        "SELECT MIN(planned_date) AS first FROM plan_workouts WHERE plan_id = ?",
        (plan_id,),
    ).fetchone()
    try:
        start = date.fromisoformat((row["first"] or "")[:10])
    except (ValueError, TypeError):
        return 1.0
    span = (race_day - start).days
    if span <= 0:
        return 1.0
    return max(0.0, min(1.0, (today - start).days / span))


def _longrun_base_pts(
    conn: sqlite3.Connection,
    race_distance_km: float | None,
    plan_id: int,
    today: date,
    race_day: date,
) -> dict[str, Any]:
    """0-10 points for the long-run base, blending two questions whose
    relative weight shifts across the plan:

      plan-relative — "did you run what the plan asked for lately?"
      absolute      — "is that enough for the race itself?"

    Weighted by plan progress, so week 3 isn't marked down for not having
    run week 19's long run, while race week is judged on race terms. The
    absolute targets:

      5k  / 10k / 15k → longest ≥ race distance  = full points
      half marathon  → longest ≥ 18 km           = full points
      marathon       → longest ≥ 30 km           = full points

    Keeping the absolute half matters: a plan that peaks well below the
    race-day benchmark (Daniels caps the long run at ~25 % of weekly
    volume, so marathon plans often top out around 24 km) would otherwise
    score full marks for a base that can't actually carry the runner
    through 42 km. That gap is exactly what this component exists to show.
    """
    if not race_distance_km or race_distance_km <= 0:
        # No race target → neutral half-points.
        return {"pts": _MAX_LONGRUN / 2, "max": _MAX_LONGRUN,
                "longest_km": 0.0, "target_km": None, "asked_km": None,
                "floor_km": None, "progress": None,
                "weeks": _LONGRUN_WEEKS, "estimated": True}
    target_km = (
        30.0 if race_distance_km >= 35.0
        else 18.0 if race_distance_km >= 18.0
        else race_distance_km
    )
    cutoff = (today - timedelta(weeks=_LONGRUN_WEEKS)).isoformat()
    today_iso = today.isoformat()
    row = conn.execute(
        """SELECT MAX(distance_m) / 1000.0 AS longest_km
           FROM activities
           WHERE activity_type = 'running'
             AND date(start_time_local) >= ?""",
        (cutoff,),
    ).fetchone()
    longest_km = float(row["longest_km"] or 0.0)

    # What the plan itself asked for over the same window — and only what
    # has already come due, so a long run scheduled for Sunday doesn't
    # count against the runner on Friday.
    row = conn.execute(
        """SELECT MAX(target_distance_km) AS asked_km
           FROM plan_workouts
           WHERE plan_id = ?
             AND planned_date >= ?
             AND planned_date <= ?""",
        (plan_id, cutoff, today_iso),
    ).fetchone()
    asked_km = float(row["asked_km"]) if row and row["asked_km"] else 0.0

    pts_absolute = _longrun_ramp(longest_km, target_km)
    if asked_km <= 0:
        # Nothing distance-based has come due lately — nothing to be
        # relative to, so judge on race terms alone.
        return {"pts": pts_absolute, "max": _MAX_LONGRUN,
                "longest_km": longest_km, "target_km": target_km,
                "asked_km": None,
                "floor_km": _LONGRUN_FLOOR_FRACTION * target_km,
                "progress": None, "weeks": _LONGRUN_WEEKS,
                "estimated": False}

    progress = _plan_progress(conn, plan_id, today, race_day)
    pts_relative = _longrun_ramp(longest_km, asked_km)
    pts = (1.0 - progress) * pts_relative + progress * pts_absolute
    return {"pts": pts, "max": _MAX_LONGRUN, "longest_km": longest_km,
            "target_km": target_km, "asked_km": asked_km,
            "floor_km": _LONGRUN_FLOOR_FRACTION * target_km,
            "progress": progress, "weeks": _LONGRUN_WEEKS,
            "estimated": False}


def race_readiness(
    conn: sqlite3.Connection,
    plan: dict,
    race: dict | None,
    today: date | None = None,
) -> dict[str, Any] | None:
    """Top-level scorer. Returns the dashboard payload or None when
    there's not enough signal to render anything honest:

      - plan has no race_date (stay-fit plan)
      - plan is younger than _MIN_PLAN_AGE_DAYS
      - race already happened more than 2 days ago (recap window over)

    `today` defaults to the real date; tests pass a fixed one so the
    windows and the plan-progress weighting are reproducible.
    """
    if not plan or not plan.get("race_date"):
        return None
    try:
        race_day = date.fromisoformat(plan["race_date"])
        plan_created = date.fromisoformat((plan.get("created_at") or "")[:10])
    except (ValueError, TypeError):
        return None
    today = today or date.today()
    if (today - plan_created).days < _MIN_PLAN_AGE_DAYS:
        return None
    if (today - race_day).days > 2:
        return None  # race is in the past

    race_distance_km = (race or {}).get("chosen_distance_km")

    components = {
        "adherence":    _adherence_pts(conn, plan["id"], today),
        "quality":      _quality_recency_pts(conn, today),
        "vdot_trend":   _vdot_trend_pts(conn, today),
        "acwr":         _acwr_band_pts(conn),
        "longrun_base": _longrun_base_pts(
            conn, race_distance_km, plan["id"], today, race_day),
    }
    total = sum(c["pts"] for c in components.values())
    score = max(0, min(100, int(round(total))))

    # Round for display only — the total above uses full precision so the
    # printed components can never add up to something else than the score
    # by more than the rounding of the score itself.
    for c in components.values():
        c["pts"] = round(c["pts"], 1)
        for key in ("delta", "longest_km", "target_km", "asked_km", "floor_km"):
            if c.get(key) is not None:
                c[key] = round(c[key], 1)
        for key in ("ratio", "progress"):
            if c.get(key) is not None:
                c[key] = round(c[key], 2)

    return {
        "score": score,
        "band":  _band_for(score),
        # Band cut-offs, so the explainer panel prints the same numbers the
        # verdict label was picked with.
        "thresholds": {label: threshold for threshold, label in _BAND_THRESHOLDS},
        "components": components,
    }
