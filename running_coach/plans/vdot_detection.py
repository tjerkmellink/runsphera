"""Auto-detect VDOT-implying efforts and suggest a plan recalibration.

The pitch: a runner who blazes a 5k tempo or a parkrun is telling us
something about their current fitness — back-derive a VDOT from the
performance, compare to the plan's `vdot_at_start`, surface a banner
when the gap is big enough to matter. One-click apply triggers the
existing `update_plan_vdot` + `recalibrate_paces` flow that already
ships per-workout pace rewrites + Garmin re-pushes.

Detection heuristic (intentionally conservative — better to miss
a few real efforts than to nag with false positives):

1. **Activity is a running activity.**
2. **Distance matches a standard race distance** (5k / 10k / 15k /
   half-marathon / marathon) within a small ± tolerance per distance.
3. **High-effort signal** — either (a) ≥ 60% of the activity time spent
   in HR Zone 4 or 5, or (b) the activity name contains a race keyword
   ("race", "wedstrijd", "parkrun", "time trial", "tt", "tempo").
4. **Not dismissed previously** (per-activity dismiss state).
5. **Implied VDOT is ≥ 1.0 ABOVE the plan's vdot_at_start.** A
   negative delta from a "high-HR but slow-pace" run (heat,
   fatigue, recovery) isn't a credible fitness-decline signal off
   a single activity, and auto-suggesting a VDOT *cut* would feel
   wrong. Manual downgrade via the existing plan-settings UI
   remains available.

Only one suggestion at a time: the most recent qualifying activity.
The runner sees one nudge, not a queue.
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from typing import Any

from . import service as plan_service


# Standard race distances + ± tolerance in km. Slightly generous on
# the upper bound to catch GPS-drift overshoot on shorter distances.
_RACE_DISTANCES: tuple[tuple[str, float, float], ...] = (
    # (label,        target_km,  tolerance_km)
    ("5K",           5.0,        0.25),
    ("10K",         10.0,        0.40),
    ("15K",         15.0,        0.50),
    ("Half",        21.0975,     0.60),
    ("Marathon",    42.195,      0.80),
)

# Keywords in activity name that strongly suggest a race effort.
# Both English and Dutch (the app supports both UI languages).
_RACE_KEYWORDS = (
    "race", "racing", "parkrun", "time trial", " tt ",
    "wedstrijd", "wedstr.", "5k", "10k", "halve", "marathon",
)

# Fraction of activity time in Z4+ that flags a "racing-hard" effort
# even when the name doesn't say "race". Calibrated for amateurs:
# easy / steady runs sit mostly in Z2-Z3, race efforts spike into Z4+.
_HIGH_HR_FRACTION_MIN = 0.60

# Minimum gap between the implied VDOT and the plan's current VDOT
# to be worth surfacing. Below this, the suggestion is noise.
_MIN_VDOT_DELTA = 1.0

# How far back to scan. Matches the post-marathon recovery window —
# anything older is stale enough that we shouldn't be re-calibrating
# off it now.
_SCAN_DAYS = 28


def _match_distance(distance_m: float | None) -> str | None:
    """Map a raw activity distance to a canonical race label when it
    falls within tolerance; otherwise None."""
    if not distance_m:
        return None
    km = distance_m / 1000.0
    for label, target, tol in _RACE_DISTANCES:
        if abs(km - target) <= tol:
            return label
    return None


def _has_race_keyword(name: str | None) -> bool:
    if not name:
        return False
    n = name.lower()
    return any(kw in n for kw in _RACE_KEYWORDS)


def _high_hr_fraction(activity: dict) -> float:
    """Fraction of time spent in Z4 + Z5 over the activity duration.
    Returns 0.0 when HR-zone data is missing."""
    duration_s = activity.get("duration_s") or 0
    z4 = activity.get("hr_zone_4_s") or 0
    z5 = activity.get("hr_zone_5_s") or 0
    if duration_s <= 0:
        return 0.0
    return (z4 + z5) / duration_s


def _is_race_effort(activity: dict) -> bool:
    """A racing-hard signal — HR mostly in Z4+, OR the name explicitly
    says race. Either alone is enough; both makes it bulletproof."""
    return (
        _high_hr_fraction(activity) >= _HIGH_HR_FRACTION_MIN
        or _has_race_keyword(activity.get("activity_name"))
    )


def detect_vdot_suggestion(conn: sqlite3.Connection) -> dict[str, Any] | None:
    """Scan recent activities for a race-pace effort that implies a
    meaningfully different VDOT than the plan's current calibration.

    Returns a suggestion payload `{activity_id, name, date, distance_label,
    distance_km, duration_s, implied_vdot, current_vdot, delta}` or None
    when there's nothing worth surfacing.
    """
    plan = plan_service.get_active_plan(conn)
    if not plan:
        return None
    # Effort-based plans (Foppen, Couch to 5K) carry no VDOT paces —
    # recalibration would refuse anyway, so never surface the banner.
    try:
        plan_service._require_vdot_paces(plan.get("methodology"))
    except ValueError:
        return None
    current_vdot = plan.get("vdot_at_start")
    if not current_vdot or current_vdot <= 0:
        return None

    since_iso = (date.today() - timedelta(days=_SCAN_DAYS)).isoformat()
    # Pull running activities in the window, newest first; we'll early-exit
    # on the first qualifying one for the "one suggestion at a time" UX.
    rows = conn.execute(
        """SELECT activity_id, activity_name, start_time_local,
                  distance_m, duration_s, avg_hr,
                  hr_zone_1_s, hr_zone_2_s, hr_zone_3_s,
                  hr_zone_4_s, hr_zone_5_s,
                  vdot_suggestion_dismissed_at,
                  vdot_suggestion_applied_at
           FROM activities
           WHERE activity_type = 'running'
             AND date(start_time_local) >= ?
           ORDER BY start_time_gmt DESC""",
        (since_iso,),
    ).fetchall()

    for row in rows:
        activity = dict(row)
        # Skip dismissed / already-applied suggestions
        if activity["vdot_suggestion_dismissed_at"] or activity["vdot_suggestion_applied_at"]:
            continue
        label = _match_distance(activity["distance_m"])
        if not label:
            continue
        if not _is_race_effort(activity):
            continue
        try:
            implied = plan_service.estimate_vdot_from_race(
                distance_m=float(activity["distance_m"]),
                time_s=float(activity["duration_s"] or 0),
            )
        except ValueError:
            continue
        delta = implied - float(current_vdot)
        # Only surface fitness-improvement signals — see the module
        # docstring (rule #5) for the rationale on excluding negative
        # deltas from auto-suggest.
        if delta < _MIN_VDOT_DELTA:
            continue
        return {
            "activity_id":     activity["activity_id"],
            "name":            activity["activity_name"],
            "date":            (activity["start_time_local"] or "")[:10],
            "distance_label":  label,
            "distance_km":     round(activity["distance_m"] / 1000.0, 2),
            "duration_s":      int(activity["duration_s"] or 0),
            "avg_hr":          int(activity["avg_hr"] or 0) if activity.get("avg_hr") else None,
            "implied_vdot":    implied,
            "current_vdot":    round(float(current_vdot), 1),
            "delta":           round(delta, 1),
            "plan_id":         plan["id"],
        }
    return None


def mark_dismissed(conn: sqlite3.Connection, activity_id: int) -> None:
    """Record that the runner dismissed the suggestion for this activity
    so we don't keep nagging on the next dashboard render."""
    conn.execute(
        "UPDATE activities SET vdot_suggestion_dismissed_at = datetime('now') "
        "WHERE activity_id = ?",
        (activity_id,),
    )
    conn.commit()


def mark_applied(conn: sqlite3.Connection, activity_id: int) -> None:
    """Record that the runner applied this suggestion. Same effect as
    dismissed for the detector — we never re-suggest the same activity."""
    conn.execute(
        "UPDATE activities SET vdot_suggestion_applied_at = datetime('now') "
        "WHERE activity_id = ?",
        (activity_id,),
    )
    conn.commit()
