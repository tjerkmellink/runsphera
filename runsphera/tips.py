"""Daily supplementary-activity tips.

Rules-driven for v1 — picks one concrete bonus activity calibrated to today's
state: planned workout intensity, yesterday's intensity, and (if a plan is
running) the coach's readiness signal. No LLM in this version; tips are
structured cards, not voiced lines.

Decision flow:
  1. Today has a planned workout → tip is the right complement to that workout.
  2. No workout today but yesterday was hard/long → active recovery walk.
  3. Otherwise → a quiet-day bonus (core + mobility).

Pure functions over the SQLite handle. No writes.
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from typing import Any

from .plans import service as plan_service

# Categories drive both the swatch color and the label on the tip card.
CATEGORY_LABELS = {
    "mobility": "Mobility",
    "core":     "Core",
    "strength": "Strength",
    "walk":     "Walk",
    "strides":  "Strides",
    "stretch":  "Stretch",
    "off":      "Off",
}

_HARD_TYPES = frozenset({"tempo", "intervals", "race"})
_MODERATE_TYPES = frozenset({"long"})


def _yesterdays_planned(conn: sqlite3.Connection, today: date) -> dict | None:
    y = (today - timedelta(days=1)).isoformat()
    row = conn.execute(
        """SELECT pw.workout_type, pw.title
           FROM plan_workouts pw
           JOIN plans p ON p.id = pw.plan_id
           WHERE p.status = 'active' AND pw.planned_date = ?""",
        (y,),
    ).fetchone()
    return dict(row) if row else None


def _yesterdays_run(conn: sqlite3.Connection, today: date) -> dict | None:
    y = (today - timedelta(days=1)).isoformat()
    row = conn.execute(
        """SELECT activity_id, distance_m, duration_s, training_load
           FROM activities
           WHERE activity_type = 'running' AND date(start_time_local) = ?
           ORDER BY start_time_gmt DESC LIMIT 1""",
        (y,),
    ).fetchone()
    return dict(row) if row else None


def _was_hard_yesterday(yest_planned: dict | None, yest_run: dict | None) -> bool:
    if yest_planned and yest_planned.get("workout_type") in _HARD_TYPES | _MODERATE_TYPES:
        return True
    # No plan info — fall back to a load threshold. Garmin training_load above
    # ~100 generally indicates a quality session for amateur runners.
    if yest_run and (yest_run.get("training_load") or 0) >= 100:
        return True
    # Long runs also count even without high TL — duration > 1h15 is "long-ish".
    if yest_run and (yest_run.get("duration_s") or 0) >= 75 * 60:
        return True
    return False


def daily_tip(
    conn: sqlite3.Connection,
    today: date | None = None,
) -> dict[str, Any] | None:
    """Return today's supplementary-activity tip, or None to render nothing."""
    today = today or date.today()
    todays_workout = plan_service.todays_workout(conn)
    wtype = (todays_workout or {}).get("workout_type")

    if wtype in _HARD_TYPES:
        return {
            "category": "strides",
            "title": "Bookend your quality session",
            "duration_min": 15,
            "body": (
                "Before: 8–10 min easy jog + 4 × 20s strides at near-mile pace. "
                "After: 5 min easy cool-down jog + a few minutes rolling quads and calves."
            ),
            "rationale": (
                "Today's " + wtype + " is the hard session of the week — "
                "a proper warm-up gets more out of it, and the cool-down speeds tomorrow's legs."
            ),
        }

    if wtype in _MODERATE_TYPES:
        return {
            "category": "mobility",
            "title": "Post-long-run reset",
            "duration_min": 10,
            "body": (
                "Once you're showered and fed: 10 min focused on hips, hamstrings, calves. "
                "Hydrate and get protein within 30 min."
            ),
            "rationale": (
                "Long runs stiffen the posterior chain. A short mobility flow now keeps "
                "tomorrow's easy run actually easy."
            ),
        }

    if wtype == "easy":
        return {
            "category": "strides",
            "title": "Optional strides",
            "duration_min": 5,
            "body": (
                "After today's easy run: 4 × 15–20s strides at near-mile pace, "
                "full recovery walking between. Skip them if the legs feel flat."
            ),
            "rationale": (
                "Strides preserve neuromuscular sharpness without adding meaningful "
                "fatigue — a small bonus on top of an easy day."
            ),
        }

    if wtype == "recovery":
        return {
            "category": "mobility",
            "title": "Light mobility",
            "duration_min": 10,
            "body": (
                "Short flow — hip openers, ankle rocks, thoracic rotations. "
                "Skip the foam roller today."
            ),
            "rationale": "Recovery day means recovery — promote blood flow, don't add stress.",
        }

    if wtype == "cross":
        return {
            "category": "core",
            "title": "Pair with runner core",
            "duration_min": 15,
            "body": (
                "Tack on 15 min of runner-specific core — planks, side planks, "
                "dead bugs, single-leg glute bridges (3 rounds, 30–45s each)."
            ),
            "rationale": (
                "Cross-training days are a low-cost slot for strength work — "
                "the next day's run isn't a key session."
            ),
        }

    # --- No workout today (rest day in plan, gap day, or pre-plan-start) ---
    yest_planned = _yesterdays_planned(conn, today)
    yest_run = _yesterdays_run(conn, today)

    if _was_hard_yesterday(yest_planned, yest_run):
        descriptor = (
            yest_planned["workout_type"] if yest_planned else "harder effort"
        )
        return {
            "category": "walk",
            "title": "Active recovery walk",
            "duration_min": 30,
            "body": (
                "Easy 30 min walk, outside if you can, no headphones. "
                "Let the legs flush without adding load."
            ),
            "rationale": (
                f"Yesterday was a {descriptor}. A walk keeps blood moving "
                "without stacking another running stimulus on top."
            ),
        }

    # Quiet day — quiet days are the natural slot for the non-running fitness work.
    return {
        "category": "core",
        "title": "Bonus core + mobility",
        "duration_min": 20,
        "body": (
            "10 min runner core (planks, glute bridges, dead bugs) "
            "+ 10 min hip mobility flow. No equipment needed."
        ),
        "rationale": (
            "Quiet days are when the injury-prevention work happens — "
            "small habits, large compound effect."
        ),
    }
