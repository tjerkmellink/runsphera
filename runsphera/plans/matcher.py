"""Match completed Garmin activities to planned workouts.

Two-tier strategy:

1. **High-confidence (pushed workouts)** — for any plan_workouts row with a
   garmin_workout_id, look for an activity with the same name on the planned
   date (±1 day tolerance for tz edge cases). When a workout is pushed to
   Garmin and the user runs it, the resulting activity comes back with the
   workout name attached, so this is essentially exact match.

2. **Heuristic fallback** — for free runs (no matching pushed workout), match
   by date + activity_type=running + distance proximity (±25%). Pick the
   closest distance match if multiple activities qualify.

Idempotent: re-running over already-matched rows is a no-op.
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

# Date tolerance for matching planned vs actual.
_DATE_TOLERANCE_DAYS = 1
# Distance proximity threshold for heuristic match (±25%).
_DISTANCE_TOLERANCE = 0.25
# Workout types where we only consider 'running' activities.
_RUN_TYPES = frozenset({"easy", "long", "recovery", "tempo", "intervals", "race"})


def _date_window(d: str) -> tuple[str, str]:
    """ISO date string -> inclusive lower/upper bounds with ±1 day tolerance."""
    dt = date.fromisoformat(d)
    return (
        (dt - timedelta(days=_DATE_TOLERANCE_DAYS)).isoformat(),
        (dt + timedelta(days=_DATE_TOLERANCE_DAYS)).isoformat(),
    )


def _find_activities_in_window(
    conn: sqlite3.Connection,
    iso_date: str,
    activity_type_filter: str | None = "running",
    exclude_ids: set[int] | None = None,
) -> list[sqlite3.Row]:
    lo, hi = _date_window(iso_date)
    sql = (
        "SELECT activity_id, activity_name, activity_type, start_time_local, "
        "       distance_m, duration_s, avg_hr "
        "FROM activities "
        "WHERE date(start_time_local) BETWEEN ? AND ?"
    )
    params: list = [lo, hi]
    if activity_type_filter:
        sql += " AND activity_type = ?"
        params.append(activity_type_filter)
    rows = conn.execute(sql, params).fetchall()
    if exclude_ids:
        rows = [r for r in rows if r["activity_id"] not in exclude_ids]
    return rows


def _name_match_score(workout_name: str, activity_name: str) -> int:
    """0 = no match, 100 = exact, 50 = substring. Case-insensitive."""
    if not activity_name:
        return 0
    a = activity_name.strip().lower()
    w = workout_name.strip().lower()
    if a == w:
        return 100
    if w in a or a in w:
        return 50
    return 0


def _heuristic_score(planned_km: float, actual_m: float) -> float:
    """Inverse distance score. 1.0 = identical, decreases as they diverge."""
    if not planned_km or not actual_m:
        return 0.0
    planned_m = planned_km * 1000.0
    diff_ratio = abs(actual_m - planned_m) / planned_m
    if diff_ratio > _DISTANCE_TOLERANCE:
        return 0.0
    return 1.0 - diff_ratio  # 1.0 .. 0.75


def match_plan_workouts(
    conn: sqlite3.Connection,
    plan_id: int | None = None,
    today: date | None = None,
) -> dict[str, int]:
    """Run the matcher over plan_workouts. If plan_id is None, runs over all plans.

    Returns counts: {"matched_exact", "matched_heuristic", "skipped_future",
                     "already_matched", "unmatched_past"}.
    """
    today = today or date.today()
    today_iso = today.isoformat()

    # Find all candidate plan_workouts to consider: planned_date on or before today.
    # When scanning all plans, restrict to ACTIVE plans only — inactive plans'
    # workouts must not compete with the active plan for newly-synced activities.
    # (A specific plan_id override, e.g. from a manual re-match, ignores status.)
    sql = (
        "SELECT pw.id, pw.plan_id, pw.planned_date, pw.workout_type, pw.title, "
        "       pw.target_distance_km, pw.garmin_workout_id, pw.actual_activity_id "
        "FROM plan_workouts pw "
        "JOIN plans p ON p.id = pw.plan_id "
        "WHERE pw.planned_date <= ? "
        "  AND pw.workout_type NOT IN ('rest', 'cross')"
    )
    params: list = [today_iso]
    if plan_id is not None:
        sql += " AND pw.plan_id = ?"
        params.append(plan_id)
    else:
        sql += " AND p.status = 'active'"
    sql += " ORDER BY pw.planned_date"
    rows = conn.execute(sql, params).fetchall()

    counts = {
        "matched_exact": 0,
        "matched_heuristic": 0,
        "skipped_future": 0,
        "already_matched": 0,
        "unmatched_past": 0,
    }

    # Track which activities have been consumed by an exact match so we don't
    # double-link them via the heuristic pass.
    consumed: set[int] = set(
        r["actual_activity_id"]
        for r in conn.execute("SELECT actual_activity_id FROM plan_workouts WHERE actual_activity_id IS NOT NULL")
        if r["actual_activity_id"] is not None
    )

    # Pass 1: exact-name match for pushed workouts.
    for pw in rows:
        if pw["actual_activity_id"]:
            counts["already_matched"] += 1
            continue
        if not pw["garmin_workout_id"]:
            continue  # heuristic pass will handle

        candidates = _find_activities_in_window(conn, pw["planned_date"], "running", consumed)
        best: tuple[int, sqlite3.Row] | None = None
        for cand in candidates:
            score = _name_match_score(pw["title"], cand["activity_name"])
            if score > 0 and (best is None or score > best[0]):
                best = (score, cand)
        if best:
            conn.execute(
                "UPDATE plan_workouts SET actual_activity_id = ?, matched_at = datetime('now') WHERE id = ?",
                (best[1]["activity_id"], pw["id"]),
            )
            consumed.add(best[1]["activity_id"])
            counts["matched_exact"] += 1

    # Pass 2: heuristic match for the rest (un-pushed planned workouts).
    active_filter = (
        f" AND pw.plan_id = {int(plan_id)}" if plan_id is not None
        else " AND p.status = 'active'"
    )
    rows = conn.execute(
        "SELECT pw.id, pw.plan_id, pw.planned_date, pw.workout_type, pw.title, "
        "       pw.target_distance_km, pw.actual_activity_id, pw.garmin_workout_id "
        "FROM plan_workouts pw "
        "JOIN plans p ON p.id = pw.plan_id "
        "WHERE pw.planned_date <= ? "
        "  AND pw.workout_type NOT IN ('rest', 'cross') "
        "  AND pw.actual_activity_id IS NULL"
        + active_filter
        + " ORDER BY pw.planned_date",
        (today_iso,),
    ).fetchall()
    for pw in rows:
        # Only match running workouts to running activities.
        if pw["workout_type"] not in _RUN_TYPES:
            counts["unmatched_past"] += 1
            continue

        candidates = _find_activities_in_window(conn, pw["planned_date"], "running", consumed)
        if not candidates:
            counts["unmatched_past"] += 1
            continue

        best: tuple[float, sqlite3.Row] | None = None
        for cand in candidates:
            sc = _heuristic_score(pw["target_distance_km"] or 0.0, cand["distance_m"] or 0.0)
            if sc > 0 and (best is None or sc > best[0]):
                best = (sc, cand)
        if best:
            conn.execute(
                "UPDATE plan_workouts SET actual_activity_id = ?, matched_at = datetime('now') WHERE id = ?",
                (best[1]["activity_id"], pw["id"]),
            )
            consumed.add(best[1]["activity_id"])
            counts["matched_heuristic"] += 1
        else:
            counts["unmatched_past"] += 1

    conn.commit()
    return counts


